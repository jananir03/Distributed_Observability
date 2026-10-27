
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
from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
)

from app.telemetry import emit_log, emit_metric


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVICE_NAME = os.getenv("SERVICE_NAME", "order-service")

DATABASE_URL = os.getenv("DATABASE_URL")
PAYMENT_URL = os.getenv(
    "PAYMENT_SERVICE_URL",
    "http://127.0.0.1:8008",
).rstrip("/")
NOTIFICATION_URL = os.getenv(
    "NOTIFICATION_SERVICE_URL",
    "http://127.0.0.1:8009",
).rstrip("/")

TIMEOUT = float(os.getenv("SERVICE_TIMEOUT_SECONDS", "5"))

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


# --------------------------------------------------
# Database Model
# --------------------------------------------------

class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    customer_id: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )
    recipient: Mapped[str] = mapped_column(String(255))
    item_name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)
    total_amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(30),
        index=True,
        default="pending",
    )
    payment_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    notification_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    notification_status: Mapped[str] = mapped_column(
        String(20),
        default="not_sent",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


# --------------------------------------------------
# Request and Response Schemas
# --------------------------------------------------

class OrderRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    recipient: str = Field(min_length=1, max_length=255)
    item_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1, le=1000)
    unit_price: float = Field(gt=0, le=1_000_000)
    simulate_payment_failure: bool = False


class OrderResponse(BaseModel):
    id: str
    customer_id: str
    recipient: str
    item_name: str
    quantity: int
    unit_price: float
    total_amount: float
    status: str
    payment_id: str | None
    notification_id: str | None
    notification_status: str
    created_at: datetime


# --------------------------------------------------
# Application Lifecycle
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    client = httpx.AsyncClient(timeout=TIMEOUT)
    HTTPXClientInstrumentor().instrument_client(client)

    app.state.http = client

    try:
        yield
    finally:
        await client.aclose()
        engine.dispose()


app = FastAPI(
    title="Order Service",
    version="1.0.0",
    lifespan=lifespan,
)

FastAPIInstrumentor.instrument_app(app)


# --------------------------------------------------
# Health Endpoints
# --------------------------------------------------

@app.get("/health", tags=["Health"])
def health():
    return {
        "service": SERVICE_NAME,
        "status": "healthy",
    }


@app.get("/ready", tags=["Health"])
async def ready(request: Request):
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc

    dependencies = {}

    for name, url in (
        ("payment_service", PAYMENT_URL),
        ("notification_service", NOTIFICATION_URL),
    ):
        try:
            response = await request.app.state.http.get(
                f"{url}/health"
            )
            dependencies[name] = {
                "reachable": response.is_success,
                "status_code": response.status_code,
            }
        except httpx.RequestError:
            dependencies[name] = {
                "reachable": False,
                "status_code": None,
            }

    is_ready = all(
        item["reachable"] for item in dependencies.values()
    )

    result = {
        "service": SERVICE_NAME,
        "ready": is_ready,
        "database": "ok",
        "dependencies": dependencies,
    }

    if not is_ready:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content=result,
        )

    return result


# --------------------------------------------------
# Create Order
# --------------------------------------------------

@app.post(
    "/api/v1/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Orders"],
)
async def create_order(payload: OrderRequest, request: Request):
    total = round(payload.quantity * payload.unit_price, 2)

    order = Order(
        id=str(uuid4()),
        customer_id=payload.customer_id,
        recipient=payload.recipient,
        item_name=payload.item_name,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        total_amount=total,
        status="pending",
        notification_status="not_sent",
    )

    # Save the order before contacting external services.
    try:
        with SessionLocal() as db:
            db.add(order)
            db.commit()
            db.refresh(order)

            # Detach safely while retaining the loaded values.
            db.expunge(order)

    except SQLAlchemyError as exc:
        logger.exception("Could not persist order")
        raise HTTPException(
            status_code=503,
            detail="Order storage unavailable",
        ) from exc

    await emit_log(
        request.app.state.http,
        SERVICE_NAME,
        f"Order {order.id} created",
        "INFO",
        {
            "order_id": order.id,
            "total_amount": total,
        },
    )

    await emit_metric(
        request.app.state.http,
        SERVICE_NAME,
        "orders_created_total",
        1,
        "count",
        {"status": "pending"},
    )

    # Process payment.
    try:
        payment_response = await request.app.state.http.post(
            f"{PAYMENT_URL}/api/v1/payments",
            json={
                "order_id": order.id,
                "amount": total,
                "simulate_failure": payload.simulate_payment_failure,
            },
        )

        if payment_response.status_code >= 400:
            order.status = "payment_failed"

            with SessionLocal() as db:
                managed_order = db.merge(order)
                db.commit()
                db.refresh(managed_order)
                db.expunge(managed_order)
                order = managed_order

            await emit_log(
                request.app.state.http,
                SERVICE_NAME,
                f"Payment failed for order {order.id}",
                "ERROR",
                {"order_id": order.id},
            )

            raise HTTPException(
                status_code=502,
                detail={
                    "message": (
                        "Payment failed; order retained for investigation"
                    ),
                    "order_id": order.id,
                },
            )

        payment = payment_response.json()

        order.payment_id = payment["id"]
        order.status = "paid"

    except HTTPException:
        raise

    except httpx.TimeoutException as exc:
        order.status = "payment_unknown"

        with SessionLocal() as db:
            managed_order = db.merge(order)
            db.commit()

        raise HTTPException(
            status_code=504,
            detail={
                "message": (
                    "Payment service timed out; verify payment status "
                    "before retrying"
                ),
                "order_id": order.id,
            },
        ) from exc

    except httpx.RequestError as exc:
        order.status = "payment_unknown"

        with SessionLocal() as db:
            managed_order = db.merge(order)
            db.commit()

        raise HTTPException(
            status_code=502,
            detail={
                "message": "Payment service unavailable",
                "order_id": order.id,
            },
        ) from exc

    except (KeyError, ValueError) as exc:
        logger.exception("Invalid payment response for order %s", order.id)

        order.status = "payment_unknown"

        with SessionLocal() as db:
            managed_order = db.merge(order)
            db.commit()

        raise HTTPException(
            status_code=502,
            detail={
                "message": "Payment service returned an invalid response",
                "order_id": order.id,
            },
        ) from exc

    # Persist the payment result.
    try:
        with SessionLocal() as db:
            managed_order = db.merge(order)
            db.commit()
            db.refresh(managed_order)

            # Return a detached, refreshed instance.
            db.expunge(managed_order)
            order = managed_order

    except SQLAlchemyError as exc:
        logger.exception(
            "Could not save payment result for order %s",
            order.id,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Could not save the payment result",
                "order_id": order.id,
            },
        ) from exc

    # Send order confirmation notification.
    try:
        notification_response = await request.app.state.http.post(
            f"{NOTIFICATION_URL}/api/v1/notifications",
            json={
                "order_id": order.id,
                "recipient": order.recipient,
                "message": (
                    f"Your order for {order.item_name} has been confirmed. "
                    f"Total: {order.total_amount:.2f}"
                ),
            },
        )

        if notification_response.is_success:
            notification = notification_response.json()
            order.notification_id = notification["id"]
            order.notification_status = notification["status"]
        else:
            order.notification_status = "failed"

            logger.warning(
                "Notification failed for order %s: HTTP %s",
                order.id,
                notification_response.status_code,
            )

    except (httpx.RequestError, KeyError, ValueError):
        order.notification_status = "failed"
        logger.exception(
            "Could not send notification for order %s",
            order.id,
        )

    # Persist notification status.
    try:
        with SessionLocal() as db:
            managed_order = db.merge(order)
            db.commit()
            db.refresh(managed_order)
            db.expunge(managed_order)
            order = managed_order

    except SQLAlchemyError as exc:
        logger.exception(
            "Could not save notification result for order %s",
            order.id,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Could not save notification result",
                "order_id": order.id,
            },
        ) from exc

    await emit_log(
        request.app.state.http,
        SERVICE_NAME,
        f"Order {order.id} status {order.status}",
        "INFO",
        {
            "order_id": order.id,
            "payment_id": order.payment_id,
        },
    )

    await emit_metric(
        request.app.state.http,
        SERVICE_NAME,
        "order_total_amount",
        total,
        "currency_unit",
        {"order_id": order.id},
    )

    return order


# --------------------------------------------------
# List Orders
# --------------------------------------------------

@app.get(
    "/api/v1/orders",
    response_model=list[OrderResponse],
    tags=["Orders"],
)
def list_orders(limit: int = 50, offset: int = 0):
    if not 1 <= limit <= 200 or offset < 0:
        raise HTTPException(
            status_code=422,
            detail="limit must be 1..200 and offset must be >= 0",
        )

    with SessionLocal() as db:
        return list(
            db.scalars(
                select(Order)
                .order_by(Order.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )


# --------------------------------------------------
# Get Order by ID
# --------------------------------------------------

@app.get(
    "/api/v1/orders/{order_id}",
    response_model=OrderResponse,
    tags=["Orders"],
)
def get_order(order_id: str):
    with SessionLocal() as db:
        order = db.get(Order, order_id)

        if not order:
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        return order