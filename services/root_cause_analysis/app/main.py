
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import DateTime, Integer, JSON, String, Float, Boolean, desc, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import create_engine

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("root_cause_analysis")

DATABASE_URL = os.getenv("DATABASE_URL")
TRACE_SERVICE_URL = os.getenv(
    "TRACE_SERVICE_URL", "http://127.0.0.1:8002"
).rstrip("/")
LOG_SERVICE_URL = os.getenv(
    "LOG_SERVICE_URL", "http://127.0.0.1:8003"
).rstrip("/")
METRICS_SERVICE_URL = os.getenv(
    "METRICS_SERVICE_URL", "http://127.0.0.1:8004"
).rstrip("/")
ANALYSIS_TIMEOUT_SECONDS = float(
    os.getenv("ANALYSIS_TIMEOUT_SECONDS", "10")
)
SLOW_SPAN_THRESHOLD_MS = float(
    os.getenv("SLOW_SPAN_THRESHOLD_MS", "1000")
)

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


class DiagnosticReport(Base):
    __tablename__ = "diagnostic_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    trace_id: Mapped[str] = mapped_column(
        String(150), unique=True, index=True
    )
    root_service: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )
    severity: Mapped[str] = mapped_column(String(30), default="INFO")
    probable_cause: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(String(1000))
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )




class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    service_name: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    metric_name: Mapped[str] = mapped_column(String(200), index=True)
    operator: Mapped[str] = mapped_column(String(10), default=">=")
    threshold: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(30), default="WARNING")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(500), index=True)
    active_dedupe_key: Mapped[str | None] = mapped_column(String(500), unique=True, nullable=True)
    service_name: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    metric_name: Mapped[str] = mapped_column(String(200), index=True)
    severity: Mapped[str] = mapped_column(String(30), default="WARNING")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    summary: Mapped[str] = mapped_column(String(1000))
    current_value: Mapped[float] = mapped_column(Float)
    threshold_value: Mapped[float] = mapped_column(Float)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


app = FastAPI(
    title="Root-Cause Analysis Service",
    description=(
        "Correlates traces, logs, and metrics to produce "
        "rule-based diagnostic reports."
    ),
    version="1.0.0",
)


def fetch_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
) -> Any:
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def analyze_evidence(
    trace: dict[str, Any],
    logs: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    spans = trace.get("spans") or []
    trace_status = str(trace.get("status", "unknown")).lower()

    error_spans = [
        span for span in spans
        if str(span.get("status", "")).lower()
        in {"error", "failed", "failure"}
    ]

    slow_spans = [
        span for span in spans
        if isinstance(span.get("duration_ms"), (int, float))
        and span["duration_ms"] >= SLOW_SPAN_THRESHOLD_MS
    ]

    error_logs = [
        log for log in logs
        if str(log.get("level", "")).upper()
        in {"ERROR", "CRITICAL", "FATAL"}
    ]

    findings: list[dict[str, Any]] = []

    if error_spans:
        for span in error_spans:
            findings.append({
                "type": "span_error",
                "service_name": span.get("service_name"),
                "operation_name": span.get("operation_name"),
                "span_id": span.get("span_id"),
                "message": (
                    span.get("error_message")
                    or f"Span status is {span.get('status')}"
                ),
            })

    if error_logs:
        for log in error_logs:
            findings.append({
                "type": "error_log",
                "service_name": log.get("service_name"),
                "event_id": log.get("event_id"),
                "message": log.get("message"),
            })

    if slow_spans:
        for span in slow_spans:
            findings.append({
                "type": "slow_span",
                "service_name": span.get("service_name"),
                "operation_name": span.get("operation_name"),
                "duration_ms": span.get("duration_ms"),
                "threshold_ms": SLOW_SPAN_THRESHOLD_MS,
            })

    if not spans:
        findings.append({
            "type": "data_quality",
            "message": "The trace contains no spans to analyze.",
        })

    if error_spans:
        first = error_spans[0]
        cause = (
            f"Error reported by {first.get('service_name', 'unknown service')} "
            f"during {first.get('operation_name', 'an operation')}."
        )
        severity = "CRITICAL" if trace_status == "error" else "HIGH"
        summary = "The trace contains one or more failed spans."

    elif error_logs:
        first = error_logs[0]
        cause = (
            f"Error log found in {first.get('service_name', 'unknown service')}: "
            f"{str(first.get('message', 'No message'))[:250]}"
        )
        severity = "HIGH"
        summary = "The trace has correlated error logs."

    elif trace_status == "error":
        cause = (
            "The trace is marked as an error, but no span-level error "
            "details were found in the available evidence."
        )
        severity = "HIGH"
        summary = "The trace failed; more diagnostic evidence is needed."

    elif slow_spans:
        first = max(
            slow_spans,
            key=lambda span: span.get("duration_ms", 0),
        )
        cause = (
            f"Slow operation detected in "
            f"{first.get('service_name', 'unknown service')}: "
            f"{first.get('operation_name', 'unknown operation')}."
        )
        severity = "MEDIUM"
        summary = "One or more spans exceeded the configured duration threshold."

    elif trace_status == "slow":
        cause = (
            "The trace is marked slow, but no individual span exceeded "
            "the configured threshold. Inspect the complete trace timing."
        )
        severity = "MEDIUM"
        summary = "The trace is marked slow."

    else:
        cause = (
            "No clear failure or slow span was identified from the "
            "available trace and log evidence."
        )
        severity = "INFO"
        summary = "No obvious root cause was detected."

    return {
        "severity": severity,
        "probable_cause": cause,
        "summary": summary,
        "findings": findings,
        "evidence": {
            "trace_id": trace.get("trace_id"),
            "trace_status": trace_status,
            "span_count": len(spans),
            "error_span_count": len(error_spans),
            "slow_span_count": len(slow_spans),
            "correlated_log_count": len(logs),
            "error_log_count": len(error_logs),
            "metric_count": len(metrics),
            "metrics": metrics,
        },
    }


def report_to_dict(report: DiagnosticReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "trace_id": report.trace_id,
        "root_service": report.root_service,
        "severity": report.severity,
        "probable_cause": report.probable_cause,
        "summary": report.summary,
        "findings": report.findings,
        "evidence": report.evidence,
        "created_at": report.created_at.isoformat(),
    }


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {
        "service": "root_cause_analysis",
        "status": "healthy",
    }


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

        return {
            "service": "root_cause_analysis",
            "database": "connected",
            "ready": True,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc


@app.post("/api/v1/analysis/{trace_id}")
def analyze_trace(trace_id: str):
    try:
        with httpx.Client(timeout=ANALYSIS_TIMEOUT_SECONDS) as client:
            trace = fetch_json(
                client,
                f"{TRACE_SERVICE_URL}/api/v1/traces/{trace_id}",
            )

            log_result = fetch_json(
                client,
                f"{LOG_SERVICE_URL}/api/v1/logs",
                {"trace_id": trace_id, "limit": 200, "offset": 0},
            )
            logs = log_result.get("items", [])

            root_service = trace.get("root_service")
            metric_params: dict[str, Any] = {
                "limit": 200,
                "offset": 0,
                "trace_id": trace_id,
            }

            metric_result = fetch_json(
                client,
                f"{METRICS_SERVICE_URL}/api/v1/metrics",
                metric_params,
            )
            metrics = metric_result.get("items", [])

            # Metrics may not carry trace IDs. If none are correlated,
            # fetch metrics for the trace's root service as contextual evidence.
            if not metrics and root_service:
                metric_result = fetch_json(
                    client,
                    f"{METRICS_SERVICE_URL}/api/v1/metrics",
                    {
                        "service_name": root_service,
                        "limit": 200,
                        "offset": 0,
                    },
                )
                metrics = metric_result.get("items", [])

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Trace not found. Confirm that Trace Processing "
                    "has received this trace."
                ),
            ) from exc

        logger.exception("A dependency service returned an error")
        raise HTTPException(
            status_code=502,
            detail=(
                f"Dependency service returned HTTP "
                f"{exc.response.status_code}"
            ),
        ) from exc

    except httpx.RequestError as exc:
        logger.exception("Could not reach a dependency service")
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not reach a trace, log, or metrics service. "
                "Confirm that ports 8002, 8003, and 8004 are running."
            ),
        ) from exc

    if not isinstance(trace, dict):
        raise HTTPException(
            status_code=502,
            detail="Trace service returned an invalid response",
        )

    analysis = analyze_evidence(trace, logs, metrics)

    with SessionLocal() as session:
        report = session.scalar(
            select(DiagnosticReport).where(
                DiagnosticReport.trace_id == trace_id
            )
        )

        if report is None:
            report = DiagnosticReport(
                trace_id=trace_id,
                root_service=trace.get("root_service"),
                severity=analysis["severity"],
                probable_cause=analysis["probable_cause"],
                summary=analysis["summary"],
                findings=analysis["findings"],
                evidence=analysis["evidence"],
            )
            session.add(report)
        else:
            report.root_service = trace.get("root_service")
            report.severity = analysis["severity"]
            report.probable_cause = analysis["probable_cause"]
            report.summary = analysis["summary"]
            report.findings = analysis["findings"]
            report.evidence = analysis["evidence"]
            report.created_at = datetime.utcnow()

        session.commit()
        session.refresh(report)
        return report_to_dict(report)


@app.get("/api/v1/analysis")
def list_reports(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    severity: str | None = None,
):
    with SessionLocal() as session:
        query = select(DiagnosticReport)

        if severity:
            query = query.where(
                DiagnosticReport.severity == severity.upper()
            )

        reports = session.scalars(
            query.order_by(desc(DiagnosticReport.created_at))
            .offset(offset)
            .limit(limit)
        ).all()

        return {
            "items": [report_to_dict(item) for item in reports],
            "limit": limit,
            "offset": offset,
        }


@app.get("/api/v1/analysis/{trace_id}")
def get_report(trace_id: str):
    with SessionLocal() as session:
        report = session.scalar(
            select(DiagnosticReport).where(
                DiagnosticReport.trace_id == trace_id
            )
        )

        if report is None:
            raise HTTPException(
                status_code=404,
                detail="Diagnostic report not found",
            )

        return report_to_dict(report)


def _alert_rule_dict(rule: AlertRule) -> dict[str, Any]:
    return {"id": rule.id, "name": rule.name, "service_name": rule.service_name,
            "metric_name": rule.metric_name, "operator": rule.operator,
            "threshold": rule.threshold, "severity": rule.severity,
            "enabled": rule.enabled, "created_at": rule.created_at.isoformat(),
            "updated_at": rule.updated_at.isoformat()}


def _alert_dict(alert: Alert) -> dict[str, Any]:
    return {"id": alert.id, "rule_id": alert.rule_id, "fingerprint": alert.fingerprint,
            "service_name": alert.service_name, "metric_name": alert.metric_name,
            "severity": alert.severity, "status": alert.status, "summary": alert.summary,
            "current_value": alert.current_value, "threshold_value": alert.threshold_value,
            "occurrence_count": alert.occurrence_count,
            "first_seen_at": alert.first_seen_at.isoformat(),
            "last_seen_at": alert.last_seen_at.isoformat(),
            "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None}


@app.get("/api/v1/diagnostics")
def list_diagnostics(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    severity: str | None = None,
):
    return list_reports(limit=limit, offset=offset, severity=severity)


@app.get("/api/v1/diagnostics/{report_id}")
def get_diagnostic(report_id: int):
    with SessionLocal() as session:
        report = session.get(DiagnosticReport, report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Diagnostic report not found")
        return report_to_dict(report)


@app.post("/api/v1/diagnostics/analyze/{trace_id}")
def analyze_diagnostic(trace_id: str):
    return analyze_trace(trace_id)


@app.get("/api/v1/alerts/rules")
def list_alert_rules():
    with SessionLocal() as session:
        rules = session.scalars(select(AlertRule).order_by(AlertRule.id)).all()
        return {"items": [_alert_rule_dict(rule) for rule in rules], "total": len(rules)}


@app.post("/api/v1/alerts/rules", status_code=201)
def create_alert_rule(payload: dict[str, Any]):
    name = str(payload.get("name", "")).strip()
    metric_name = str(payload.get("metric_name", "")).strip()
    operator = str(payload.get("operator", ">=")).strip()
    severity = str(payload.get("severity", "WARNING")).upper()
    if not name or not metric_name:
        raise HTTPException(status_code=422, detail="name and metric_name are required")
    if operator not in {">", ">=", "<", "<=", "==", "!="}:
        raise HTTPException(status_code=422, detail="operator must be one of >, >=, <, <=, ==, !=")
    try:
        threshold = float(payload["threshold"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="threshold must be numeric") from exc
    if severity not in {"INFO", "WARNING", "HIGH", "CRITICAL"}:
        raise HTTPException(status_code=422, detail="Unsupported severity")
    with SessionLocal() as session:
        if session.scalar(select(AlertRule).where(AlertRule.name == name)):
            raise HTTPException(status_code=409, detail="An alert rule with this name already exists")
        rule = AlertRule(name=name, service_name=payload.get("service_name"),
                         metric_name=metric_name, operator=operator, threshold=threshold,
                         severity=severity, enabled=bool(payload.get("enabled", True)))
        session.add(rule)
        session.commit()
        session.refresh(rule)
        return _alert_rule_dict(rule)


@app.patch("/api/v1/alerts/rules/{rule_id}")
def update_alert_rule(rule_id: int, payload: dict[str, Any]):
    allowed = {"name", "service_name", "metric_name", "operator", "threshold", "severity", "enabled"}
    if not payload or set(payload) - allowed:
        raise HTTPException(status_code=422, detail="Provide one or more supported rule fields")
    with SessionLocal() as session:
        rule = session.get(AlertRule, rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")
        for key, value in payload.items():
            if key == "operator" and value not in {">", ">=", "<", "<=", "==", "!="}:
                raise HTTPException(status_code=422, detail="Unsupported operator")
            if key == "threshold":
                try: value = float(value)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=422, detail="threshold must be numeric") from exc
            if key == "severity":
                value = str(value).upper()
                if value not in {"INFO", "WARNING", "HIGH", "CRITICAL"}:
                    raise HTTPException(status_code=422, detail="Unsupported severity")
            setattr(rule, key, value)
        rule.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(rule)
        return _alert_rule_dict(rule)


def _threshold_met(value: float, operator: str, threshold: float) -> bool:
    return {">": value > threshold, ">=": value >= threshold, "<": value < threshold,
            "<=": value <= threshold, "==": value == threshold, "!=": value != threshold}[operator]


@app.post("/api/v1/alerts/evaluate")
def evaluate_alert_rules():
    """Evaluate enabled persisted rules against current stored metric samples."""
    with SessionLocal() as session:
        rules = session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))).all()
        evaluated = 0
        triggered = 0
        for rule in rules:
            params = {"metric_name": rule.metric_name, "limit": 200, "offset": 0}
            if rule.service_name:
                params["service_name"] = rule.service_name
            try:
                with httpx.Client(timeout=ANALYSIS_TIMEOUT_SECONDS) as client:
                    records = fetch_json(client, f"{METRICS_SERVICE_URL}/api/v1/metrics", params).get("items", [])
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.warning("Could not evaluate alert rule %s: %s", rule.id, type(exc).__name__)
                continue
            if not records:
                continue
            # When a rule is not service-specific, evaluate the latest sample
            # independently for each service rather than collapsing them together.
            latest_by_service = {}
            for record in records:
                latest_by_service.setdefault(record.get("service_name") or "unknown", record)
            for metric_service, latest in latest_by_service.items():
                evaluated += 1
                value = float(latest["value"])
                fingerprint = f"metric:{metric_service}:{rule.metric_name}:{rule.operator}:{rule.threshold}"
                active_key = fingerprint
                active = session.scalar(select(Alert).where(Alert.active_dedupe_key == active_key))
                if _threshold_met(value, rule.operator, float(rule.threshold)):
                    triggered += 1
                    summary = f"{rule.metric_name} for {metric_service} is {value}; threshold {rule.operator} {rule.threshold}"
                    if active:
                        active.current_value = value
                        active.last_seen_at = datetime.utcnow()
                        active.occurrence_count += 1
                        active.summary = summary
                    else:
                        active = Alert(rule_id=rule.id, fingerprint=fingerprint,
                                       active_dedupe_key=active_key, service_name=metric_service,
                                       metric_name=rule.metric_name, severity=rule.severity, status="active",
                                       summary=summary, current_value=value, threshold_value=float(rule.threshold))
                        session.add(active)
                elif active:
                    active.status = "resolved"
                    active.active_dedupe_key = None
                    active.resolved_at = datetime.utcnow()
                    active.last_seen_at = datetime.utcnow()
                session.flush()
        session.commit()
        return {"rules_evaluated": evaluated, "rules_triggered": triggered,
                "message": "Alert rules evaluated against the latest stored metric samples."}


@app.get("/api/v1/alerts")
def list_alerts(
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = None,
    service_name: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    with SessionLocal() as session:
        query = select(Alert)
        if status_filter:
            if status_filter not in {"active", "acknowledged", "resolved"}:
                raise HTTPException(status_code=422, detail="status must be active, acknowledged, or resolved")
            query = query.where(Alert.status == status_filter)
        if severity:
            query = query.where(Alert.severity == severity.upper())
        if service_name:
            query = query.where(Alert.service_name == service_name)
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        records = session.scalars(query.order_by(desc(Alert.last_seen_at)).offset(offset).limit(limit)).all()
        return {"items": [_alert_dict(a) for a in records], "total": total, "limit": limit, "offset": offset}


@app.get("/api/v1/alerts/{alert_id}")
def get_alert(alert_id: int):
    with SessionLocal() as session:
        alert = session.get(Alert, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        return _alert_dict(alert)


@app.patch("/api/v1/alerts/{alert_id}")
def update_alert(alert_id: int, payload: dict[str, Any]):
    if not payload or set(payload) - {"status"}:
        raise HTTPException(status_code=422, detail="Only status can be updated")
    status_value = payload.get("status")
    if status_value not in {"active", "acknowledged", "resolved"}:
        raise HTTPException(status_code=422, detail="status must be active, acknowledged, or resolved")
    with SessionLocal() as session:
        alert = session.get(Alert, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        alert.status = status_value
        if status_value == "resolved":
            alert.active_dedupe_key = None
            alert.resolved_at = datetime.utcnow()
        elif status_value in {"active", "acknowledged"} and alert.resolved_at:
            # Re-activating a resolved alert gets a fresh dedupe key only if available.
            alert.resolved_at = None
            alert.active_dedupe_key = alert.fingerprint
        session.commit()
        session.refresh(alert)
        return _alert_dict(alert)
