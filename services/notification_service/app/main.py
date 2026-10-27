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
from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import create_engine

from app.telemetry import emit_log, emit_metric

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
SERVICE_NAME = os.getenv("SERVICE_NAME", "notification-service")
DATABASE_URL = os.getenv("DATABASE_URL")
TIMEOUT = float(os.getenv("SERVICE_TIMEOUT_SECONDS", "5"))
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    recipient: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

class NotificationRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    recipient: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=2000)

class NotificationResponse(BaseModel):
    id: str
    order_id: str
    recipient: str
    message: str
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

app = FastAPI(title="Notification Service", version="1.0.0", lifespan=lifespan)
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

@app.post("/api/v1/notifications", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED, tags=["Notifications"])
async def create_notification(payload: NotificationRequest, request: Request):
    with SessionLocal() as db:
        # Repeated requests for the same order return the original notification.
        existing = db.scalar(
            select(Notification)
            .where(Notification.order_id == payload.order_id)
            .order_by(Notification.created_at.asc())
        )
        if existing:
            return existing

        notification = Notification(
            id=str(uuid4()), order_id=payload.order_id, recipient=payload.recipient,
            message=payload.message, status="sent",
        )
        db.add(notification)
        try:
            db.commit()
            db.refresh(notification)
        except SQLAlchemyError as exc:
            db.rollback()
            logger.exception("Could not persist notification")
            raise HTTPException(status_code=503, detail="Notification storage unavailable") from exc

    await emit_log(request.app.state.http, SERVICE_NAME, f"Notification simulated for order {payload.order_id}", "INFO", {"order_id": payload.order_id, "notification_id": notification.id})
    await emit_metric(request.app.state.http, SERVICE_NAME, "notifications_processed_total", 1, "count", {"status": notification.status})
    return notification

@app.get("/api/v1/notifications", response_model=list[NotificationResponse], tags=["Notifications"])
def list_notifications(limit: int = 50, request_offset: int = 0):
    if not 1 <= limit <= 200 or request_offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1..200 and request_offset must be >= 0")
    with SessionLocal() as db:
        return list(db.scalars(select(Notification).order_by(Notification.created_at.desc()).offset(request_offset).limit(limit)))

@app.get("/api/v1/notifications/{notification_id}", response_model=NotificationResponse, tags=["Notifications"])
def get_notification(notification_id: str):
    with SessionLocal() as db:
        notification = db.get(Notification, notification_id)
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        return notification
