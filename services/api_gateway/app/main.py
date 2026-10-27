import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

TRACE_URL = os.getenv("TRACE_SERVICE_URL", "http://127.0.0.1:8002").rstrip("/")
LOG_URL = os.getenv("LOG_SERVICE_URL", "http://127.0.0.1:8003").rstrip("/")
METRICS_URL = os.getenv("METRICS_SERVICE_URL", "http://127.0.0.1:8004").rstrip("/")
ROOT_CAUSE_URL = os.getenv("ROOT_CAUSE_SERVICE_URL", "http://127.0.0.1:8005").rstrip("/")
QUERY_URL = os.getenv("OBSERVABILITY_QUERY_SERVICE_URL", "http://127.0.0.1:8006").rstrip("/")
ORDER_URL = os.getenv("ORDER_SERVICE_URL", "http://127.0.0.1:8007").rstrip("/")
PAYMENT_URL = os.getenv("PAYMENT_SERVICE_URL", "http://127.0.0.1:8008").rstrip("/")
NOTIFICATION_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://127.0.0.1:8009").rstrip("/")
TIMEOUT = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "10"))

SERVICE_URLS = {
    "trace_processing": TRACE_URL,
    "log_processing": LOG_URL,
    "metrics_aggregation": METRICS_URL,
    "root_cause_analysis": ROOT_CAUSE_URL,
    "observability_query": QUERY_URL,
    "order_service": ORDER_URL,
    "payment_service": PAYMENT_URL,
    "notification_service": NOTIFICATION_URL,
}

# These schemas mirror the business-service request/response models so the
# gateway Swagger UI documents JSON request bodies instead of generic query params.
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
    payment_id: str | None = None
    notification_id: str | None = None
    notification_status: str
    created_at: datetime


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
    app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    yield
    await app.state.http.aclose()


app = FastAPI(
    title="Distributed Observability API Gateway",
    description=(
        "Unified entry point for business services, traces, logs, metrics, "
        "root-cause analysis, and observability queries."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Gateway Health"])
async def health() -> dict[str, str]:
    return {"service": "api_gateway", "status": "healthy"}


@app.get("/ready", tags=["Gateway Health"])
async def readiness(request: Request) -> Any:
    results: dict[str, Any] = {}
    for name, base_url in SERVICE_URLS.items():
        try:
            response = await request.app.state.http.get(f"{base_url}/health")
            results[name] = {
                "reachable": response.is_success,
                "status_code": response.status_code,
            }
        except httpx.RequestError:
            results[name] = {"reachable": False, "status_code": None}

    ready = all(item["reachable"] for item in results.values())
    result = {"service": "api_gateway", "ready": ready, "dependencies": results}
    if not ready:
        return JSONResponse(status_code=503, content=result)
    return result


async def forward_request(request: Request, base_url: str, path: str) -> Any:
    clean_path = path.strip("/")
    target_url = f"{base_url}/{clean_path}" if clean_path else f"{base_url}/"
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {
            "host", "content-length", "connection", "transfer-encoding"
        }
    }
    try:
        response = await request.app.state.http.request(
            method=request.method,
            url=target_url,
            params=list(request.query_params.multi_items()),
            content=body if body else None,
            headers=headers,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Downstream service timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Unable to connect to downstream service.") from exc

    content_type = response.headers.get("content-type", "application/json")
    try:
        content: Any = response.json() if "application/json" in content_type else {"detail": response.text}
    except ValueError:
        content = {"detail": response.text}

    return JSONResponse(
        status_code=response.status_code,
        content=content,
        headers={"X-Gateway": "api_gateway"},
    )


@app.get("/api/v1/traces/{trace_id}/logs", tags=["Trace-Correlated Logs"])
async def trace_correlated_logs(request: Request, trace_id: str):
    return await forward_request(request, LOG_URL, f"api/v1/traces/{trace_id}/logs")


@app.get("/api/v1/dependencies", tags=["Service Dependencies"])
@app.get("/api/v1/dependencies/{service_name}", tags=["Service Dependencies"])
async def dependency_routes(request: Request, service_name: str | None = None):
    target_path = "api/v1/dependencies" if not service_name else f"api/v1/dependencies/{service_name}"
    return await forward_request(request, TRACE_URL, target_path)


@app.api_route("/api/v1/diagnostics", methods=["GET"], tags=["Diagnostics"])
@app.api_route("/api/v1/diagnostics/{path:path}", methods=["GET", "POST"], tags=["Diagnostics"])
async def diagnostic_routes(request: Request, path: str = ""):
    target_path = "api/v1/diagnostics" + (f"/{path}" if path else "")
    return await forward_request(request, ROOT_CAUSE_URL, target_path)


@app.api_route("/api/v1/alerts", methods=["GET"], tags=["Alert Management"])
@app.api_route("/api/v1/alerts/{path:path}", methods=["GET", "POST", "PATCH"], tags=["Alert Management"])
async def alert_routes(request: Request, path: str = ""):
    target_path = "api/v1/alerts" + (f"/{path}" if path else "")
    return await forward_request(request, ROOT_CAUSE_URL, target_path)


@app.api_route("/api/v1/traces", methods=["GET"], tags=["Trace Processing"])
@app.api_route("/api/v1/traces/{path:path}", methods=["GET"], tags=["Trace Processing"])
async def trace_routes(request: Request, path: str = ""):
    target_path = "api/v1/traces" + (f"/{path}" if path else "")
    return await forward_request(request, TRACE_URL, target_path)


@app.api_route("/api/v1/logs", methods=["GET"], tags=["Log Processing"])
@app.api_route("/api/v1/logs/{path:path}", methods=["GET"], tags=["Log Processing"])
async def log_routes(request: Request, path: str = ""):
    target_path = "api/v1/logs" + (f"/{path}" if path else "")
    return await forward_request(request, LOG_URL, target_path)


@app.api_route("/api/v1/metrics", methods=["GET"], tags=["Metrics Aggregation"])
@app.api_route("/api/v1/metrics/{path:path}", methods=["GET"], tags=["Metrics Aggregation"])
async def metric_routes(request: Request, path: str = ""):
    target_path = "api/v1/metrics" + (f"/{path}" if path else "")
    return await forward_request(request, METRICS_URL, target_path)


@app.api_route("/api/v1/analysis", methods=["GET"], tags=["Root-Cause Analysis"])
@app.api_route("/api/v1/analysis/{path:path}", methods=["GET", "POST"], tags=["Root-Cause Analysis"])
async def analysis_routes(request: Request, path: str = ""):
    target_path = "api/v1/analysis" + (f"/{path}" if path else "")
    return await forward_request(request, ROOT_CAUSE_URL, target_path)


@app.api_route("/api/v1/observability/{path:path}", methods=["GET"], tags=["Observability Query"])
async def observability_routes(request: Request, path: str):
    return await forward_request(request, QUERY_URL, f"api/v1/observability/{path}")


@app.get("/api/v1/search", tags=["Observability Query"])
async def search_routes(request: Request):
    return await forward_request(request, QUERY_URL, "api/v1/search")


# Business endpoints are explicit so OpenAPI exposes proper requestBody schemas.
@app.post(
    "/api/v1/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Order Service"],
)
async def create_order(payload: OrderRequest, request: Request):
    return await forward_request(request, ORDER_URL, "api/v1/orders")


@app.get("/api/v1/orders", response_model=list[OrderResponse], tags=["Order Service"])
async def list_orders(request: Request):
    return await forward_request(request, ORDER_URL, "api/v1/orders")


@app.get("/api/v1/orders/{order_id}", response_model=OrderResponse, tags=["Order Service"])
async def get_order(request: Request, order_id: str):
    return await forward_request(request, ORDER_URL, f"api/v1/orders/{order_id}")


@app.post(
    "/api/v1/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Payment Service"],
)
async def create_payment(payload: PaymentRequest, request: Request):
    return await forward_request(request, PAYMENT_URL, "api/v1/payments")


@app.get("/api/v1/payments", response_model=list[PaymentResponse], tags=["Payment Service"])
async def list_payments(request: Request):
    return await forward_request(request, PAYMENT_URL, "api/v1/payments")


@app.get("/api/v1/payments/{payment_id}", response_model=PaymentResponse, tags=["Payment Service"])
async def get_payment(request: Request, payment_id: str):
    return await forward_request(request, PAYMENT_URL, f"api/v1/payments/{payment_id}")


@app.post(
    "/api/v1/notifications",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Notification Service"],
)
async def create_notification(payload: NotificationRequest, request: Request):
    return await forward_request(request, NOTIFICATION_URL, "api/v1/notifications")


@app.get("/api/v1/notifications", response_model=list[NotificationResponse], tags=["Notification Service"])
async def list_notifications(request: Request):
    return await forward_request(request, NOTIFICATION_URL, "api/v1/notifications")


@app.get(
    "/api/v1/notifications/{notification_id}",
    response_model=NotificationResponse,
    tags=["Notification Service"],
)
async def get_notification(request: Request, notification_id: str):
    return await forward_request(request, NOTIFICATION_URL, f"api/v1/notifications/{notification_id}")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["info"]["x-api-gateway"] = True
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
