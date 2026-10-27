import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, String, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import create_engine

from app.telemetry import emit_log, emit_metric

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
SERVICE_NAME = os.getenv("SERVICE_NAME", "payment-service")
DATABASE_URL = os.getenv("DATABASE_URL")
TIMEOUT = float(os.getenv("SERVICE_TIMEOUT_SECONDS", "5"))
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

class PaymentRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0, le=1_000_000)
    simulate_failure: bool = False

class PaymentResponse(BaseModel):
    id: str
    order_id: str
    amount: float
    status: str
    created_at: datetime

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    client = httpx.AsyncClient(timeout=TIMEOUT)
    HTTPXClientInstrumentor().instrument_client(client)
    app.state.http = client
    yield
    await client.aclose()
    engine.dispose()

app = FastAPI(title="Payment Service", version="1.0.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)

@app.get("/health", tags=["Health"])
def health():
    return {"service": SERVICE_NAME, "status": "healthy"}

@app.get("/ready", tags=["Health"])
def ready():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return {"service": SERVICE_NAME, "ready": True, "database": "ok"}
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

@app.post("/api/v1/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED, tags=["Payments"])
async def create_payment(payload: PaymentRequest, request: Request):
    with SessionLocal() as db:
        existing = db.scalar(select(Payment).where(Payment.order_id == payload.order_id))
        if existing:
            # Idempotent retry: preserve the original result, including failures.
            if existing.status == "failed":
                raise HTTPException(
                    status_code=402,
                    detail={"payment_id": existing.id, "status": "failed"},
                )
            return existing
        payment = Payment(
            id=str(uuid4()),
            order_id=payload.order_id,
            amount=payload.amount,
            status="failed" if payload.simulate_failure else "succeeded",
        )
        db.add(payment)
        try:
            db.commit()
            db.refresh(payment)
        except SQLAlchemyError as exc:
            db.rollback()
            logger.exception("Could not persist payment")
            raise HTTPException(status_code=503, detail="Payment storage unavailable") from exc

    await emit_log(
        request.app.state.http, SERVICE_NAME,
        f"Payment {payment.status} for order {payment.order_id}",
        "ERROR" if payment.status == "failed" else "INFO",
        {"order_id": payment.order_id, "payment_id": payment.id},
    )
    await emit_metric(request.app.state.http, SERVICE_NAME, "payments_processed_total", 1, "count", {"status": payment.status})

    if payment.status == "failed":
        raise HTTPException(status_code=402, detail={"payment_id": payment.id, "status": "failed"})
    return payment

@app.get("/api/v1/payments", response_model=list[PaymentResponse], tags=["Payments"])
def list_payments(limit: int = 50, request_offset: int = 0):
    if not 1 <= limit <= 200 or request_offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1..200 and request_offset must be >= 0")
    with SessionLocal() as db:
        return list(db.scalars(select(Payment).order_by(Payment.created_at.desc()).offset(request_offset).limit(limit)))

@app.get("/api/v1/payments/{payment_id}", response_model=PaymentResponse, tags=["Payments"])
def get_payment(payment_id: str):
    with SessionLocal() as db:
        payment = db.get(Payment, payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        return payment
