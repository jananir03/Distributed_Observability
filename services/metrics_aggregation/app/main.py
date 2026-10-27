
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
    Float,
    Integer,
    String,
    create_engine,
    desc,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("metrics_aggregation")

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


class MetricRecord(Base):
    __tablename__ = "metric_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    service_name: Mapped[str] = mapped_column(String(150), index=True)
    metric_name: Mapped[str] = mapped_column(String(200), index=True)
    metric_type: Mapped[str] = mapped_column(String(50), default="gauge")
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_event: Mapped[dict[str, Any]] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


app = FastAPI(
    title="Metrics Aggregation Service",
    description=(
        "Consumes telemetry metrics from RabbitMQ, stores metric data, "
        "and provides metric queries and statistical aggregates."
    ),
    version="1.0.0",
)

consumer_state = "starting"
stop_event = threading.Event()


def parse_timestamp(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def save_metric(payload: dict[str, Any]) -> None:
    event_id = payload.get("event_id")
    service_name = payload.get("service_name")
    metric_name = payload.get("metric_name") or payload.get("name")
    metric_value = payload.get("value", payload.get("metric_value"))

    if not event_id:
        raise ValueError("Metric event requires event_id")

    event_type = str(payload.get("event_type", "metric")).lower()
    if event_type not in {"metric", "metrics"}:
        raise ValueError(f"Expected a metric event, received: {event_type}")

    if not service_name:
        raise ValueError("Metric event requires service_name")

    if not metric_name:
        raise ValueError("Metric event requires metric_name or name")

    if isinstance(metric_value, bool) or metric_value is None:
        raise ValueError("Metric event requires a numeric value")

    try:
        metric_value = float(metric_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Metric value must be numeric") from exc

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
            select(MetricRecord).where(
                MetricRecord.event_id == str(event_id)
            )
        )
        if existing:
            logger.info("Duplicate metric skipped: %s", event_id)
            return

        record = MetricRecord(
            event_id=str(event_id),
            service_name=str(service_name),
            metric_name=str(metric_name),
            metric_type=str(
                payload.get("metric_type", payload.get("type", "gauge"))
            ).lower(),
            value=metric_value,
            unit=payload.get("unit"),
            event_timestamp=parse_timestamp(timestamp),
            trace_id=payload.get("trace_id"),
            attributes=attributes,
            raw_event=payload,
        )

        session.add(record)

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            logger.info("Duplicate metric skipped after concurrent insert: %s", event_id)


def connection_parameters() -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=pika.PlainCredentials(
            RABBITMQ_USER,
            RABBITMQ_PASSWORD,
        ),
        heartbeat=60,
        blocked_connection_timeout=30,
        connection_attempts=3,
        retry_delay=2,
    )


def consume_metrics() -> None:
    global consumer_state

    while not stop_event.is_set():
        connection = None

        try:
            consumer_state = "connecting"
            connection = pika.BlockingConnection(connection_parameters())
            channel = connection.channel()

            channel.exchange_declare(
                exchange="telemetry.events",
                exchange_type="topic",
                durable=True,
            )
            channel.queue_declare(queue="telemetry.metrics", durable=True)
            channel.queue_bind(
                exchange="telemetry.events",
                queue="telemetry.metrics",
                routing_key="telemetry.metrics",
            )
            channel.basic_qos(prefetch_count=20)

            def handle_message(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))

                    if not isinstance(payload, dict):
                        raise ValueError("Message must be a JSON object")

                    save_metric(payload)
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                    logger.error("Invalid metric event; discarding message: %s", exc)
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                except Exception:
                    logger.exception("Metric processing failed; message requeued")
                    ch.basic_nack(
                        delivery_tag=method.delivery_tag,
                        requeue=True,
                    )

            channel.basic_consume(
                queue="telemetry.metrics",
                on_message_callback=handle_message,
                auto_ack=False,
            )

            consumer_state = "running"
            logger.info("Consuming messages from telemetry.metrics")
            channel.start_consuming()

        except Exception:
            consumer_state = "disconnected"
            if not stop_event.is_set():
                logger.exception("RabbitMQ consumer failed; retrying")
                time.sleep(3)

        finally:
            if connection and connection.is_open:
                try:
                    connection.close()
                except Exception:
                    logger.exception("Error closing RabbitMQ connection")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)

    thread = threading.Thread(target=consume_metrics, daemon=True)
    thread.start()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_event.set()


@app.get("/health")
def health():
    return {
        "service": "metrics_aggregation",
        "status": "healthy",
    }


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

        return {
            "service": "metrics_aggregation",
            "database": "connected",
            "rabbitmq_consumer": consumer_state,
            "ready": consumer_state == "running",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc


@app.get("/api/v1/metrics")
def list_metrics(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service_name: str | None = None,
    metric_name: str | None = None,
    trace_id: str | None = None,
):
    with SessionLocal() as session:
        query = select(MetricRecord)

        if service_name:
            query = query.where(MetricRecord.service_name == service_name)
        if metric_name:
            query = query.where(MetricRecord.metric_name == metric_name)
        if trace_id:
            query = query.where(MetricRecord.trace_id == trace_id)

        total = session.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        records = session.scalars(
            query.order_by(desc(MetricRecord.event_timestamp))
            .offset(offset)
            .limit(limit)
        ).all()

        return {
            "items": [
                {
                    "event_id": item.event_id,
                    "service_name": item.service_name,
                    "metric_name": item.metric_name,
                    "metric_type": item.metric_type,
                    "value": item.value,
                    "unit": item.unit,
                    "timestamp": item.event_timestamp.isoformat(),
                    "trace_id": item.trace_id,
                    "attributes": item.attributes,
                }
                for item in records
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@app.get("/api/v1/metrics/aggregate")
def aggregate_metrics(
    service_name: str | None = None,
    metric_name: str | None = None,
):
    with SessionLocal() as session:
        query = select(
            MetricRecord.service_name,
            MetricRecord.metric_name,
            func.count(MetricRecord.id).label("sample_count"),
            func.avg(MetricRecord.value).label("average"),
            func.min(MetricRecord.value).label("minimum"),
            func.max(MetricRecord.value).label("maximum"),
            func.sum(MetricRecord.value).label("total"),
        ).group_by(
            MetricRecord.service_name,
            MetricRecord.metric_name,
        )

        if service_name:
            query = query.where(MetricRecord.service_name == service_name)
        if metric_name:
            query = query.where(MetricRecord.metric_name == metric_name)

        rows = session.execute(query).all()

        return {
            "items": [
                {
                    "service_name": row.service_name,
                    "metric_name": row.metric_name,
                    "sample_count": row.sample_count,
                    "average": float(row.average) if row.average is not None else None,
                    "minimum": row.minimum,
                    "maximum": row.maximum,
                    "sum": row.total,
                }
                for row in rows
            ],
            "total_groups": len(rows),
        }



def _parse_query_time(value: str | None, parameter: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"{parameter} must be an ISO-8601 timestamp") from exc


def _metric_query(service_name: str | None, metric_name: str | None,
                  start_time: str | None, end_time: str | None):
    query = select(MetricRecord)
    if service_name:
        query = query.where(MetricRecord.service_name == service_name)
    if metric_name:
        query = query.where(MetricRecord.metric_name == metric_name)
    start = _parse_query_time(start_time, "start_time")
    end = _parse_query_time(end_time, "end_time")
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start_time must be <= end_time")
    if start:
        query = query.where(MetricRecord.event_timestamp >= start)
    if end:
        query = query.where(MetricRecord.event_timestamp <= end)
    return query


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return round(values[0], 4)
    position = (len(values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return round(values[lower] + (values[upper] - values[lower]) * fraction, 4)


@app.get("/api/v1/metrics/services")
def metrics_services():
    with SessionLocal() as session:
        rows = session.execute(
            select(MetricRecord.service_name, func.count(MetricRecord.id).label("sample_count"),
                   func.count(func.distinct(MetricRecord.metric_name)).label("metric_count"),
                   func.max(MetricRecord.event_timestamp).label("last_seen_at"))
            .group_by(MetricRecord.service_name)
            .order_by(MetricRecord.service_name)
        ).all()
        return {"items": [{
            "service_name": r.service_name, "sample_count": r.sample_count,
            "metric_count": r.metric_count,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
        } for r in rows], "total": len(rows)}


@app.get("/api/v1/metrics/summary")
def metrics_summary(
    service_name: str | None = None,
    metric_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
):
    query = _metric_query(service_name, metric_name, start_time, end_time)
    with SessionLocal() as session:
        records = session.scalars(query.order_by(MetricRecord.event_timestamp.asc())).all()
        grouped: dict[tuple[str, str], list[float]] = {}
        for row in records:
            grouped.setdefault((row.service_name, row.metric_name), []).append(float(row.value))
        return {"filters": {"service_name": service_name, "metric_name": metric_name,
                            "start_time": start_time, "end_time": end_time},
                "sample_count": len(records),
                "items": [{"service_name": key[0], "metric_name": key[1],
                           "sample_count": len(vals), "average": round(sum(vals)/len(vals), 4),
                           "minimum": min(vals), "maximum": max(vals), "sum": round(sum(vals), 4)}
                          for key, vals in sorted(grouped.items())]}


@app.get("/api/v1/metrics/timeseries")
def metrics_timeseries(
    service_name: str | None = None,
    metric_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
):
    query = _metric_query(service_name, metric_name, start_time, end_time)
    with SessionLocal() as session:
        rows = session.scalars(query.order_by(MetricRecord.event_timestamp.asc()).limit(limit)).all()
        return {"items": [{"timestamp": r.event_timestamp.isoformat(), "service_name": r.service_name,
                           "metric_name": r.metric_name, "value": r.value, "unit": r.unit,
                           "trace_id": r.trace_id} for r in rows],
                "total": len(rows), "limit": limit}


@app.get("/api/v1/metrics/latency")
def metrics_latency(
    service_name: str | None = None,
    metric_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
):
    query = _metric_query(service_name, metric_name, start_time, end_time)
    with SessionLocal() as session:
        rows = session.scalars(query.order_by(MetricRecord.event_timestamp.asc())).all()
        # Only use measurements whose metric name explicitly signals latency/duration.
        groups: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            if any(token in row.metric_name.lower() for token in ("latency", "duration", "response_time")):
                groups.setdefault((row.service_name, row.metric_name), []).append(float(row.value))
        return {"items": [{"service_name": key[0], "metric_name": key[1], "unit": next(
                                (r.unit for r in rows if r.service_name == key[0] and r.metric_name == key[1]), None),
                           "sample_count": len(values), "p50": _percentile(values, .50),
                           "p95": _percentile(values, .95), "p99": _percentile(values, .99),
                           "minimum": min(values), "maximum": max(values)}
                          for key, values in sorted(groups.items())],
                "note": "Percentiles are calculated from stored latency/duration/response_time samples only."}


@app.get("/api/v1/metrics/{event_id}")
def get_metric(event_id: str):
    with SessionLocal() as session:
        record = session.scalar(
            select(MetricRecord).where(MetricRecord.event_id == event_id)
        )

        if not record:
            raise HTTPException(status_code=404, detail="Metric not found")

        return {
            "event_id": record.event_id,
            "service_name": record.service_name,
            "metric_name": record.metric_name,
            "metric_type": record.metric_type,
            "value": record.value,
            "unit": record.unit,
            "timestamp": record.event_timestamp.isoformat(),
            "trace_id": record.trace_id,
            "attributes": record.attributes,
            "raw_event": record.raw_event,
        }
