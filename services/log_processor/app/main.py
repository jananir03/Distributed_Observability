
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import pika
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    desc,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("log_processor")

DATABASE_URL = os.getenv("DATABASE_URL")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "observability")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "DevRabbitPass_2026")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ProcessedLog(Base):
    __tablename__ = "processed_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    service_name: Mapped[str] = mapped_column(String(150), index=True)
    level: Mapped[str] = mapped_column(String(30), index=True)
    message: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(150), index=True, nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_event: Mapped[dict[str, Any]] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


app = FastAPI(
    title="Log Processing Service",
    description="Consumes telemetry logs from RabbitMQ and provides searchable log records.",
    version="1.0.0",
)

consumer_thread: threading.Thread | None = None
consumer_ready = threading.Event()
consumer_state = "starting"
stop_event = threading.Event()


def parse_timestamp(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def save_log(payload: dict[str, Any]) -> None:
    event_id = payload.get("event_id")
    if not event_id:
        raise ValueError("Log event is missing event_id")

    event_type = str(payload.get("event_type", "log")).lower()
    if event_type != "log":
        raise ValueError(f"Expected a log event, received: {event_type}")

    service_name = payload.get("service_name")
    message = payload.get("message")

    if not service_name or message is None:
        raise ValueError("Log event requires service_name and message")

    timestamp = (
        payload.get("timestamp")
        or payload.get("event_timestamp")
        or payload.get("time")
    )

    attributes = payload.get("attributes")
    if attributes is not None and not isinstance(attributes, dict):
        attributes = {"value": attributes}

    with SessionLocal() as session:
        existing = session.scalar(
            select(ProcessedLog).where(ProcessedLog.event_id == str(event_id))
        )
        if existing:
            logger.info("Duplicate log skipped: %s", event_id)
            return

        log_record = ProcessedLog(
            event_id=str(event_id),
            service_name=str(service_name),
            level=str(payload.get("level", payload.get("severity", "INFO"))).upper(),
            message=str(message),
            trace_id=payload.get("trace_id"),
            span_id=payload.get("span_id"),
            event_timestamp=parse_timestamp(timestamp),
            attributes=attributes,
            raw_event=payload,
        )
        session.add(log_record)

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            logger.info("Duplicate log skipped after concurrent insert: %s", event_id)


def rabbitmq_connection_parameters() -> pika.ConnectionParameters:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    return pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=30,
        connection_attempts=3,
        retry_delay=2,
    )


def consume_logs() -> None:
    global consumer_state

    while not stop_event.is_set():
        connection = None

        try:
            consumer_state = "connecting"
            connection = pika.BlockingConnection(rabbitmq_connection_parameters())
            channel = connection.channel()
            channel.exchange_declare(
                exchange="telemetry.events",
                exchange_type="topic",
                durable=True,
            )
            channel.queue_declare(queue="telemetry.logs", durable=True)
            channel.queue_bind(
                exchange="telemetry.events",
                queue="telemetry.logs",
                routing_key="telemetry.logs",
            )
            channel.basic_qos(prefetch_count=20)

            def handle_message(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("Message must be a JSON object")

                    save_log(payload)
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                    logger.error("Invalid log event; discarding message: %s", exc)
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                except Exception:
                    logger.exception("Log processing failed; message will be requeued")
                    ch.basic_nack(
                        delivery_tag=method.delivery_tag,
                        requeue=True,
                    )

            channel.basic_consume(
                queue="telemetry.logs",
                on_message_callback=handle_message,
                auto_ack=False,
            )

            consumer_state = "running"
            consumer_ready.set()
            logger.info("Consuming messages from telemetry.logs")

            channel.start_consuming()

        except Exception:
            consumer_state = "disconnected"
            consumer_ready.clear()
            if not stop_event.is_set():
                logger.exception("RabbitMQ consumer connection failed; retrying")
                time.sleep(3)

        finally:
            if connection and connection.is_open:
                try:
                    connection.close()
                except Exception:
                    logger.exception("Error closing RabbitMQ connection")


@app.on_event("startup")
def startup() -> None:
    global consumer_thread

    Base.metadata.create_all(bind=engine)

    # Run the RabbitMQ consumer in a separate thread so HTTP requests stay responsive.
    consumer_thread = threading.Thread(target=consume_logs, daemon=True)
    consumer_thread.start()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_event.set()


@app.get("/health")
def health():
    return {"service": "log_processor", "status": "healthy"}


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

        return {
            "service": "log_processor",
            "database": "connected",
            "rabbitmq_consumer": consumer_state,
            "ready": consumer_state == "running",
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.get("/api/v1/logs")
def list_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service_name: str | None = None,
    level: str | None = None,
    trace_id: str | None = None,
):
    with SessionLocal() as session:
        query = select(ProcessedLog)

        if service_name:
            query = query.where(ProcessedLog.service_name == service_name)
        if level:
            query = query.where(ProcessedLog.level == level.upper())
        if trace_id:
            query = query.where(ProcessedLog.trace_id == trace_id)

        total = len(session.scalars(query).all())
        records = session.scalars(
            query.order_by(desc(ProcessedLog.event_timestamp))
            .offset(offset)
            .limit(limit)
        ).all()

        return {
            "items": [
                {
                    "event_id": record.event_id,
                    "service_name": record.service_name,
                    "level": record.level,
                    "message": record.message,
                    "trace_id": record.trace_id,
                    "span_id": record.span_id,
                    "timestamp": record.event_timestamp.isoformat(),
                    "attributes": record.attributes,
                }
                for record in records
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@app.get("/api/v1/logs/{event_id}")
def get_log(event_id: str):
    with SessionLocal() as session:
        record = session.scalar(
            select(ProcessedLog).where(ProcessedLog.event_id == event_id)
        )

        if not record:
            raise HTTPException(status_code=404, detail="Log event not found")

        return {
            "event_id": record.event_id,
            "service_name": record.service_name,
            "level": record.level,
            "message": record.message,
            "trace_id": record.trace_id,
            "span_id": record.span_id,
            "timestamp": record.event_timestamp.isoformat(),
            "attributes": record.attributes,
            "raw_event": record.raw_event,
        }


@app.get("/api/v1/traces/{trace_id}/logs")
def list_trace_logs(
    trace_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Trace-correlated logs using the existing persisted log records."""
    with SessionLocal() as session:
        query = select(ProcessedLog).where(ProcessedLog.trace_id == trace_id)
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        records = session.scalars(
            query.order_by(desc(ProcessedLog.event_timestamp))
            .offset(offset).limit(limit)
        ).all()
        return {
            "trace_id": trace_id,
            "items": [{
                "event_id": r.event_id, "service_name": r.service_name,
                "level": r.level, "message": r.message, "trace_id": r.trace_id,
                "span_id": r.span_id, "timestamp": r.event_timestamp.isoformat(),
                "attributes": r.attributes,
            } for r in records],
            "total": total, "limit": limit, "offset": offset,
        }
