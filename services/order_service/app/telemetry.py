import logging
import os
from typing import Any
from uuid import uuid4

import httpx
from opentelemetry import trace

logger = logging.getLogger(__name__)
INGESTION_URL = os.getenv("TELEMETRY_INGESTION_URL", "http://127.0.0.1:8000").rstrip("/")


def trace_fields() -> dict[str, str | None]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {"trace_id": None, "span_id": None}
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
    }


async def send_event(client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> None:
    try:
        response = await client.post(f"{INGESTION_URL}{path}", json=payload)
        response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        # Business operations must remain available if observability is temporarily unavailable.
        logger.warning("Telemetry submission failed (%s)", type(exc).__name__)


async def emit_log(
    client: httpx.AsyncClient,
    service_name: str,
    message: str,
    severity: str = "INFO",
    attributes: dict[str, Any] | None = None,
) -> None:
    payload = {
        "event_id": str(uuid4()),
        "event_type": "log",
        "service_name": service_name,
        "severity": severity,
        "message": message,
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        **trace_fields(),
        "attributes": attributes or {},
    }
    await send_event(client, "/api/v1/telemetry/logs", payload)


async def emit_metric(
    client: httpx.AsyncClient,
    service_name: str,
    metric_name: str,
    value: float,
    unit: str = "count",
    attributes: dict[str, Any] | None = None,
) -> None:
    payload = {
        "event_id": str(uuid4()),
        "event_type": "metric",
        "service_name": service_name,
        "metric_name": metric_name,
        "metric_value": value,
        "metric_type": "gauge",
        "unit": unit,
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        **trace_fields(),
        "attributes": attributes or {},
    }
    await send_event(client, "/api/v1/telemetry/metrics", payload)
