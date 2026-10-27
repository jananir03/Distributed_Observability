
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("observability_query")

TRACE_SERVICE_URL = os.getenv(
    "TRACE_SERVICE_URL", "http://127.0.0.1:8002"
).rstrip("/")
LOG_SERVICE_URL = os.getenv(
    "LOG_SERVICE_URL", "http://127.0.0.1:8003"
).rstrip("/")
METRICS_SERVICE_URL = os.getenv(
    "METRICS_SERVICE_URL", "http://127.0.0.1:8004"
).rstrip("/")
ROOT_CAUSE_SERVICE_URL = os.getenv(
    "ROOT_CAUSE_SERVICE_URL", "http://127.0.0.1:8005"
).rstrip("/")

QUERY_TIMEOUT_SECONDS = float(
    os.getenv("QUERY_TIMEOUT_SECONDS", "10")
)

app = FastAPI(
    title="Observability Query Service",
    description=(
        "Unified query APIs for traces, logs, metrics, "
        "and root-cause diagnostic reports."
    ),
    version="1.0.0",
)


def request_json(
    client: httpx.Client,
    service_name: str,
    url: str,
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "%s returned HTTP %s for %s",
            service_name,
            exc.response.status_code,
            url,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "A dependent service returned an error",
                "service": service_name,
                "upstream_status": exc.response.status_code,
            },
        ) from exc
    except httpx.RequestError as exc:
        logger.error("Cannot reach %s: %s", service_name, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "message": "A dependent service is unavailable",
                "service": service_name,
                "url": url,
            },
        ) from exc


@app.get("/health")
def health():
    return {
        "service": "observability_query",
        "status": "healthy",
    }


@app.get("/ready")
def ready():
    services = {
        "trace_processing": f"{TRACE_SERVICE_URL}/health",
        "log_processing": f"{LOG_SERVICE_URL}/health",
        "metrics_aggregation": f"{METRICS_SERVICE_URL}/health",
        "root_cause_analysis": f"{ROOT_CAUSE_SERVICE_URL}/health",
    }

    results = {}

    with httpx.Client(timeout=QUERY_TIMEOUT_SECONDS) as client:
        for name, url in services.items():
            try:
                response = client.get(url)
                results[name] = {
                    "reachable": response.is_success,
                    "status_code": response.status_code,
                }
            except httpx.RequestError:
                results[name] = {
                    "reachable": False,
                    "status_code": None,
                }

    ready = all(item["reachable"] for item in results.values())

    return {
        "service": "observability_query",
        "ready": ready,
        "dependencies": results,
    }


@app.get("/api/v1/observability/{trace_id}")
def get_observability_trace(trace_id: str):
    with httpx.Client(timeout=QUERY_TIMEOUT_SECONDS) as client:
        trace = request_json(
            client,
            "trace_processing",
            f"{TRACE_SERVICE_URL}/api/v1/traces/{trace_id}",
        )

        logs_result = request_json(
            client,
            "log_processing",
            f"{LOG_SERVICE_URL}/api/v1/logs",
            {"trace_id": trace_id, "limit": 200, "offset": 0},
        )

        metrics_result = request_json(
            client,
            "metrics_aggregation",
            f"{METRICS_SERVICE_URL}/api/v1/metrics",
            {"trace_id": trace_id, "limit": 200, "offset": 0},
        )

        report = None
        report_error = None

        try:
            report = request_json(
                client,
                "root_cause_analysis",
                f"{ROOT_CAUSE_SERVICE_URL}/api/v1/analysis/{trace_id}",
            )
        except HTTPException as exc:
            # A missing report is valid if analysis has not run yet.
            detail = exc.detail
            if (
                isinstance(detail, dict)
                and detail.get("upstream_status") == 404
            ):
                report = None
            else:
                report_error = detail

    return {
        "trace_id": trace_id,
        "trace": trace,
        "logs": logs_result.get("items", []),
        "log_count": logs_result.get("total", 0),
        "metrics": metrics_result.get("items", []),
        "metric_count": metrics_result.get("total", 0),
        "diagnostic_report": report,
        "diagnostic_report_error": report_error,
    }


@app.get("/api/v1/search")
def search_observability(
    trace_id: str | None = None,
    service_name: str | None = None,
    trace_status: str | None = None,
    level: str | None = None,
    metric_name: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    with httpx.Client(timeout=QUERY_TIMEOUT_SECONDS) as client:
        if trace_id:
            try:
                trace_data = request_json(
                    client,
                    "trace_processing",
                    f"{TRACE_SERVICE_URL}/api/v1/traces/{trace_id}",
                )
                traces = [trace_data]
            except HTTPException as exc:
                detail = exc.detail
                if (
                    isinstance(detail, dict)
                    and detail.get("upstream_status") == 404
                ):
                    traces = []
                else:
                    raise
        else:
            trace_params: dict[str, Any] = {
                "limit": limit,
                "offset": offset,
            }
            if service_name:
                trace_params["service_name"] = service_name
            if trace_status:
                trace_params["trace_status"] = trace_status

            trace_result = request_json(
                client,
                "trace_processing",
                f"{TRACE_SERVICE_URL}/api/v1/traces",
                trace_params,
            )
            traces = trace_result.get("items", [])

        log_params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        if trace_id:
            log_params["trace_id"] = trace_id
        if service_name:
            log_params["service_name"] = service_name
        if level:
            log_params["level"] = level

        logs_result = request_json(
            client,
            "log_processing",
            f"{LOG_SERVICE_URL}/api/v1/logs",
            log_params,
        )
        logs = logs_result.get("items", [])

        metric_params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        if trace_id:
            metric_params["trace_id"] = trace_id
        if service_name:
            metric_params["service_name"] = service_name
        if metric_name:
            metric_params["metric_name"] = metric_name

        metrics_result = request_json(
            client,
            "metrics_aggregation",
            f"{METRICS_SERVICE_URL}/api/v1/metrics",
            metric_params,
        )
        metrics = metrics_result.get("items", [])

        report_params: dict[str, Any] = {
            "limit": 200,
            "offset": 0,
        }
        if severity:
            report_params["severity"] = severity.upper()

        reports_result = request_json(
            client,
            "root_cause_analysis",
            f"{ROOT_CAUSE_SERVICE_URL}/api/v1/analysis",
            report_params,
        )
        reports = reports_result.get("items", [])

        # The reports list API doesn't support trace_id or service filters,
        # so apply those filters to the returned report records here.
        if trace_id:
            reports = [
                item for item in reports
                if item.get("trace_id") == trace_id
            ]

        if service_name:
            reports = [
                item for item in reports
                if item.get("root_service") == service_name
            ]

        return {
            "filters": {
                "trace_id": trace_id,
                "service_name": service_name,
                "trace_status": trace_status,
                "level": level,
                "metric_name": metric_name,
                "severity": severity,
            },
            "results": {
                "traces": traces,
                "logs": logs,
                "metrics": metrics,
                "diagnostic_reports": reports,
            },
            "counts": {
                "traces": len(traces),
                "logs": len(logs),
                "metrics": len(metrics),
                "diagnostic_reports": len(reports),
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
            },
        }
