
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

import pika
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "observability")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")


class Base(DeclarativeBase):
    pass


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(20), index=True)
    service_name: Mapped[str] = mapped_column(String(100), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    processing_status: Mapped[str] = mapped_column(
        String(30), default="accepted"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class EventType(str, Enum):
    LOG = "log"
    TRACE = "trace"
    METRIC = "metric"


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = Field(default_factory=lambda: str(uuid4()), max_length=100)
    event_type: EventType
    service_name: str = Field(min_length=1, max_length=100)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: str | None = Field(default=None, max_length=64)
    span_id: str | None = Field(default=None, max_length=32)
    parent_span_id: str | None = Field(default=None, max_length=32)
    correlation_id: str | None = Field(default=None, max_length=100)
    severity: str | None = Field(default=None, max_length=20)
    message: str | None = Field(default=None, max_length=10000)
    metric_name: str | None = Field(default=None, max_length=100)
    metric_value: float | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str | None = Field(default=None, max_length=30)
    operation_name: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_event(self):
        if self.event_type == EventType.LOG:
            if not self.message:
                raise ValueError("Log events require a message")
            if self.severity and self.severity.upper() not in {
                "INFO", "WARNING", "ERROR", "CRITICAL"
            }:
                raise ValueError("Unsupported log severity")

        elif self.event_type == EventType.TRACE:
            if not self.trace_id or not self.span_id:
                raise ValueError("Trace events require trace_id and span_id")
            if self.start_time and self.end_time:
                if self.end_time < self.start_time:
                    raise ValueError("end_time cannot precede start_time")

        elif self.event_type == EventType.METRIC:
            if not self.metric_name or self.metric_value is None:
                raise ValueError(
                    "Metric events require metric_name and metric_value"
                )

        return self


class BatchRequest(BaseModel):
    events: list[TelemetryEvent] = Field(min_length=1, max_length=200)


def publish_event(event: dict[str, Any]) -> None:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            credentials=credentials,
            connection_attempts=2,
            retry_delay=1,
            socket_timeout=3,
            blocked_connection_timeout=3,
        )
    )

    try:
        channel = connection.channel()
        channel.exchange_declare(
            exchange="telemetry.events",
            exchange_type="topic",
            durable=True,
        )

        event_type = event["event_type"]
        routing_key = f"telemetry.{event_type}s"

        channel.queue_declare(queue=routing_key, durable=True)
        channel.queue_bind(
            queue=routing_key,
            exchange="telemetry.events",
            routing_key=routing_key,
        )

        # Enable publisher confirmations.
        channel.confirm_delivery()

        # In Pika's confirmation mode, successful publishing may return None.
        # Negative acknowledgements and unroutable messages raise exceptions.
        channel.basic_publish(
            exchange="telemetry.events",
            routing_key=routing_key,
            body=json.dumps(event, default=str),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                message_id=event["event_id"],
            ),
            mandatory=True,
        )
    finally:
        connection.close()


def ingest_one(event: TelemetryEvent) -> dict[str, Any]:
    payload = event.model_dump(mode="json")

    with SessionLocal() as db:
        existing = db.scalar(
            select(IngestionEvent).where(
                IngestionEvent.event_id == event.event_id
            )
        )

        if existing:
            return {
                "event_id": event.event_id,
                "status": "duplicate",
            }

        record = IngestionEvent(
            event_id=event.event_id,
            event_type=event.event_type.value,
            service_name=event.service_name,
            trace_id=event.trace_id,
            processing_status="publishing",
        )
        db.add(record)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return {
                "event_id": event.event_id,
                "status": "duplicate",
            }
        except SQLAlchemyError as exc:
            db.rollback()
            logger.exception("Failed to save ingestion record")
            raise HTTPException(
                status_code=503,
                detail="Ingestion database is unavailable",
            ) from exc

    try:
        publish_event(payload)
    except Exception as exc:
        logger.exception(
            "RabbitMQ publish failed: %s", type(exc).__name__
        )

        with SessionLocal() as db:
            record = db.scalar(
                select(IngestionEvent).where(
                    IngestionEvent.event_id == event.event_id
                )
            )
            if record:
                record.processing_status = "publish_failed"
                record.error_message = type(exc).__name__
                db.commit()

        raise HTTPException(
            status_code=503,
            detail="Telemetry broker is temporarily unavailable",
        ) from exc

    with SessionLocal() as db:
        record = db.scalar(
            select(IngestionEvent).where(
                IngestionEvent.event_id == event.event_id
            )
        )
        if record:
            record.processing_status = "published"
            db.commit()

    return {
        "event_id": event.event_id,
        "status": "published",
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("Telemetry Ingestion Service started")
    yield
    engine.dispose()


app = FastAPI(
    title="Telemetry Ingestion Service",
    description="Validates telemetry and publishes events to RabbitMQ.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {
        "service": "telemetry-ingestion",
        "status": "healthy",
    }


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=credentials,
                connection_attempts=1,
                socket_timeout=2,
            )
        )
        connection.close()

        return {
            "status": "ready",
            "database": "ok",
            "rabbitmq": "ok",
        }
    except Exception as exc:
        logger.warning("Readiness check failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="A required dependency is unavailable",
        ) from exc


@app.post(
    "/api/v1/telemetry/logs",
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_log(event: TelemetryEvent):
    if event.event_type != EventType.LOG:
        raise HTTPException(422, "event_type must be log")
    return ingest_one(event)


@app.post(
    "/api/v1/telemetry/traces",
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_trace(event: TelemetryEvent):
    if event.event_type != EventType.TRACE:
        raise HTTPException(422, "event_type must be trace")
    return ingest_one(event)


@app.post(
    "/api/v1/telemetry/metrics",
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_metric(event: TelemetryEvent):
    if event.event_type != EventType.METRIC:
        raise HTTPException(422, "event_type must be metric")
    return ingest_one(event)


@app.post(
    "/api/v1/telemetry/batch",
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_batch(batch: BatchRequest):
    results = []

    for event in batch.events:
        try:
            results.append(ingest_one(event))
        except HTTPException as exc:
            results.append({
                "event_id": event.event_id,
                "status": "failed",
                "error": exc.detail,
            })

    return {
        "total": len(results),
        "published": sum(
            result["status"] == "published" for result in results
        ),
        "duplicates": sum(
            result["status"] == "duplicate" for result in results
        ),
        "failed": sum(
            result["status"] == "failed" for result in results
        ),
        "results": results,
    }
