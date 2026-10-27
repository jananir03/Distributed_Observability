
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import pika
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "observability")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "")
SLOW_THRESHOLD_MS = float(os.getenv("SLOW_SPAN_THRESHOLD_MS", "1000"))
COMPLETION_WAIT_SECONDS = int(
    os.getenv("TRACE_COMPLETION_WAIT_SECONDS", "30")
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None

    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


class Base(DeclarativeBase):
    pass


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    root_service: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="incomplete")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TraceSpan(Base):
    __tablename__ = "trace_spans"
    __table_args__ = (
        UniqueConstraint("trace_id", "span_id", name="uq_trace_span"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    span_id: Mapped[str] = mapped_column(String(32), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    service_name: Mapped[str] = mapped_column(String(100), index=True)
    operation_name: Mapped[str] = mapped_column(String(200))
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="UNSET")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def process_span(event: dict[str, Any]) -> None:
    trace_id = event.get("trace_id")
    span_id = event.get("span_id")

    if not trace_id or not span_id:
        raise ValueError("trace_id and span_id are required")

    start = parse_time(event.get("start_time") or event.get("timestamp"))
    end = parse_time(event.get("end_time"))

    duration = None
    if start and end:
        duration = max((end - start).total_seconds() * 1000, 0)

    status = str(event.get("status") or "UNSET").upper()
    if event.get("error_message") and status == "UNSET":
        status = "ERROR"
    if duration is not None and duration > SLOW_THRESHOLD_MS:
        if status == "UNSET":
            status = "SLOW"

    with SessionLocal.begin() as db:
        span = db.scalar(
            select(TraceSpan).where(
                TraceSpan.trace_id == trace_id,
                TraceSpan.span_id == span_id,
            )
        )

        if span is None:
            span = TraceSpan(
                trace_id=trace_id,
                span_id=span_id,
                service_name=event.get("service_name", "unknown"),
                operation_name=event.get("operation_name", "unknown"),
            )
            db.add(span)

        # Update an existing span on redelivery rather than inserting a duplicate.
        span.parent_span_id = event.get("parent_span_id")
        span.service_name = event.get("service_name", "unknown")
        span.operation_name = event.get("operation_name", "unknown")
        span.start_time = start
        span.end_time = end
        span.duration_ms = duration
        span.status = status
        span.error_message = event.get("error_message")
        span.updated_at = utcnow()

        trace = db.scalar(
            select(Trace).where(Trace.trace_id == trace_id)
        )
        if trace is None:
            trace = Trace(trace_id=trace_id, status="incomplete")
            db.add(trace)

        # Recompute the summary from persisted spans. Arrival order does not matter.
        db.flush()
        spans = list(
            db.scalars(
                select(TraceSpan).where(TraceSpan.trace_id == trace_id)
            )
        )

        starts = [s.start_time for s in spans if s.start_time]
        ends = [s.end_time for s in spans if s.end_time]

        trace.start_time = min(starts) if starts else None
        trace.end_time = max(ends) if ends else None
        trace.duration_ms = (
            max((trace.end_time - trace.start_time).total_seconds() * 1000, 0)
            if trace.start_time and trace.end_time
            else None
        )

        root = next(
            (s for s in spans if not s.parent_span_id),
            None,
        )
        trace.root_service = root.service_name if root else None

        if any(s.status == "ERROR" for s in spans):
            trace.status = "error"
        elif any(s.status == "SLOW" for s in spans):
            trace.status = "slow"
        elif all(s.start_time and s.end_time for s in spans):
            trace.status = "complete"
        else:
            trace.status = "incomplete"

        trace.last_seen_at = utcnow()

        # This is a quiet-period completion policy, not proof that no more spans exist.
        if trace.status != "incomplete":
            trace.completed_at = utcnow()
        else:
            trace.completed_at = None


def consume_traces(stop_event: threading.Event):
    while not stop_event.is_set():
        connection = None
        try:
            credentials = pika.PlainCredentials(
                RABBITMQ_USER, RABBITMQ_PASSWORD
            )
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    port=RABBITMQ_PORT,
                    credentials=credentials,
                    heartbeat=30,
                    connection_attempts=3,
                    retry_delay=2,
                )
            )
            channel = connection.channel()
            channel.queue_declare(queue="telemetry.traces", durable=True)
            channel.basic_qos(prefetch_count=10)

            def on_message(ch, method, properties, body):
                try:
                    event = json.loads(body)
                    process_span(event)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    logger.info(
                        "Processed span %s for trace %s",
                        event.get("span_id"),
                        event.get("trace_id"),
                    )
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    # Invalid messages are logged and acknowledged to avoid poison loops.
                    logger.error("Discarding invalid trace event: %s", exc)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    logger.exception("Trace processing failed; requeueing event")
                    ch.basic_nack(
                        delivery_tag=method.delivery_tag,
                        requeue=True,
                    )

            channel.basic_consume(
                queue="telemetry.traces",
                on_message_callback=on_message,
                auto_ack=False,
            )

            while (
                connection.is_open
                and channel.is_open
                and not stop_event.is_set()
            ):
                connection.process_data_events(time_limit=1)

        except Exception:
            logger.exception("Trace consumer connection failed; retrying")
            stop_event.wait(3)
        finally:
            if connection is not None and connection.is_open:
                connection.close()


stop_event = threading.Event()
consumer_thread = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer_thread
    Base.metadata.create_all(bind=engine)
    stop_event.clear()
    consumer_thread = threading.Thread(
        target=consume_traces,
        args=(stop_event,),
        daemon=True,
    )
    consumer_thread.start()
    logger.info("Trace Processing Service started")
    yield
    stop_event.set()
    if consumer_thread:
        consumer_thread.join(timeout=5)
    engine.dispose()


app = FastAPI(
    title="Trace Processing Service",
    version="1.0.0",
    description="Consumes spans, reconstructs traces, and exposes trace queries.",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {"service": "trace-processor", "status": "healthy"}


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        logger.exception("Trace processor readiness check failed")
        raise HTTPException(503, "Database unavailable") from exc


@app.get("/api/v1/traces")
def list_traces(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service_name: str | None = None,
    trace_status: str | None = None,
):
    with SessionLocal() as db:
        query = select(Trace).order_by(Trace.last_seen_at.desc())
        if service_name:
            query = query.where(Trace.root_service == service_name)
        if trace_status:
            query = query.where(Trace.status == trace_status.lower())

        rows = list(db.scalars(query.offset(offset).limit(limit)))
        return {
            "items": [
                {
                    "trace_id": t.trace_id,
                    "root_service": t.root_service,
                    "start_time": t.start_time,
                    "end_time": t.end_time,
                    "duration_ms": t.duration_ms,
                    "status": t.status,
                    "completed_at": t.completed_at,
                }
                for t in rows
            ],
            "limit": limit,
            "offset": offset,
        }


@app.get("/api/v1/traces/{trace_id}")
def get_trace(trace_id: str):
    with SessionLocal() as db:
        trace = db.scalar(
            select(Trace).where(Trace.trace_id == trace_id)
        )
        if trace is None:
            raise HTTPException(404, "Trace not found")

        spans = list(
            db.scalars(
                select(TraceSpan)
                .where(TraceSpan.trace_id == trace_id)
                .order_by(TraceSpan.start_time.asc())
            )
        )

        span_ids = {s.span_id for s in spans}
        return {
            "trace_id": trace.trace_id,
            "root_service": trace.root_service,
            "start_time": trace.start_time,
            "end_time": trace.end_time,
            "duration_ms": trace.duration_ms,
            "status": trace.status,
            "completion_wait_seconds": COMPLETION_WAIT_SECONDS,
            "spans": [
                {
                    "span_id": s.span_id,
                    "parent_span_id": s.parent_span_id,
                    "parent_missing": bool(
                        s.parent_span_id and s.parent_span_id not in span_ids
                    ),
                    "service_name": s.service_name,
                    "operation_name": s.operation_name,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "duration_ms": s.duration_ms,
                    "status": s.status,
                    "error_message": s.error_message,
                }
                for s in spans
            ],
        }


@app.get("/api/v1/traces/{trace_id}/spans")
def list_trace_spans(trace_id: str):
    """Return the persisted spans for one trace, in deterministic time order."""
    with SessionLocal() as db:
        trace = db.scalar(select(Trace).where(Trace.trace_id == trace_id))
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        spans = list(db.scalars(
            select(TraceSpan).where(TraceSpan.trace_id == trace_id)
            .order_by(TraceSpan.start_time.asc(), TraceSpan.span_id.asc())
        ))
        return {
            "trace_id": trace_id,
            "total": len(spans),
            "items": [{
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "service_name": span.service_name,
                "operation_name": span.operation_name,
                "start_time": span.start_time,
                "end_time": span.end_time,
                "duration_ms": span.duration_ms,
                "status": span.status,
                "error_message": span.error_message,
            } for span in spans],
        }


@app.get("/api/v1/dependencies")
def list_dependencies(
    service_name: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
):
    """Infer caller -> callee edges from persisted parent/child spans."""
    with SessionLocal() as db:
        spans = list(db.scalars(
            select(TraceSpan).order_by(TraceSpan.trace_id, TraceSpan.start_time)
            .limit(limit)
        ))
        by_key = {(s.trace_id, s.span_id): s for s in spans}
        edges: dict[tuple[str, str], dict[str, Any]] = {}
        services = set()
        for child in spans:
            services.add(child.service_name)
            parent = by_key.get((child.trace_id, child.parent_span_id)) if child.parent_span_id else None
            if not parent:
                continue
            services.add(parent.service_name)
            if parent.service_name == child.service_name:
                continue
            key = (parent.service_name, child.service_name)
            if service_name and service_name not in key:
                continue
            edge = edges.setdefault(key, {
                "source": key[0], "target": key[1], "call_count": 0,
                "error_count": 0, "durations_ms": [],
            })
            edge["call_count"] += 1
            if str(child.status).upper() in {"ERROR", "FAILED", "FAILURE"}:
                edge["error_count"] += 1
            if child.duration_ms is not None:
                edge["durations_ms"].append(float(child.duration_ms))
        items = []
        for edge in edges.values():
            durations = edge.pop("durations_ms")
            edge["average_duration_ms"] = round(sum(durations) / len(durations), 3) if durations else None
            edge["error_rate"] = round(edge["error_count"] / edge["call_count"], 4) if edge["call_count"] else 0
            items.append(edge)
        return {"services": sorted(services), "dependencies": sorted(items, key=lambda x: (x["source"], x["target"])), "limit": limit}


@app.get("/api/v1/dependencies/{service_name}")
def get_service_dependencies(service_name: str):
    result = list_dependencies(service_name=service_name, limit=5000)
    incoming = [edge for edge in result["dependencies"] if edge["target"] == service_name]
    outgoing = [edge for edge in result["dependencies"] if edge["source"] == service_name]
    if service_name not in result["services"]:
        raise HTTPException(status_code=404, detail="Service dependency evidence not found")
    return {"service_name": service_name, "incoming": incoming, "outgoing": outgoing}
