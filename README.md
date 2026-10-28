# Distributed Observability & Root-Cause Analysis Platform

A microservices-based platform for collecting and analyzing application
telemetry, exploring traces and logs, monitoring metrics, mapping
service dependencies, diagnosing issues, and managing alerts.

## Features

-   **Telemetry ingestion** for application telemetry events.
-   **Distributed tracing** to retrieve and inspect trace data.
-   **Trace-correlated logs** to investigate activity using trace
    identifiers.
-   **Metrics monitoring** with summaries, time-series data, and latency
    percentiles.
-   **Service dependency mapping** to explore relationships between
    services.
-   **Root-cause diagnostics** to support issue investigation.
-   **Alert management** with threshold rules and duplicate-alert
    prevention.
-   **Business workflow services** for orders, payments, and
    notifications.
-   **Web dashboard** built with React.

## Technology Stack

-   **Backend:** Python 3.12, FastAPI, SQLAlchemy, Pydantic
-   **Frontend:** React, TypeScript, Vite, Material UI, Recharts
-   **Database:** MySQL 8.0
-   **Messaging:** RabbitMQ
-   **Containers:** Docker and Docker Compose

## Services and Ports

  Service                                        Default port
  ---------------------- ------------------------------------
  Telemetry Ingestion                                    8000
  API Gateway                                            8001
  Trace Processor                                        8002
  Log Processor                                          8003
  Metrics Aggregation                                    8004
  Root-Cause Analysis                                    8005
  Observability Query                                    8006
  Order Service                                          8007
  Payment Service                                        8008
  Notification Service                                   8009
  MySQL                                           3307 (host)
  RabbitMQ                 5672 (AMQP), 15672 (management UI)

The main API Gateway is available at `http://localhost:8001`. Backend
services communicate over the Docker Compose network using service
names.

## Prerequisites

-   Docker Desktop with Docker Compose
-   Node.js and npm (to run the frontend locally)
-   Git (optional)

## Configuration

1.  Create a local `.env` file using the project's environment
    example/template, if available.

2.  Set the required database URLs, credentials, RabbitMQ settings, and
    service configuration.

3.  Keep real credentials in `.env`; do not commit secrets.

4.  For business services running inside Docker, configure telemetry
    ingestion as:

    `TELEMETRY_INGESTION_URL=http://telemetry_ingestion:8000`

    A process running directly on the host may require a different
    address.

## Run the Backend

From the repository root:

``` powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Inspect logs when troubleshooting:

``` powershell
docker compose logs --tail=100 telemetry_ingestion
docker compose logs --tail=100 order_service
docker compose logs --tail=100 api_gateway
```

Open the API documentation:

-   Swagger UI: <http://localhost:8001/docs>
-   OpenAPI schema: <http://localhost:8001/openapi.json>

## Run the Frontend

Open a separate terminal:

``` powershell
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite. Configure the frontend API base URL
according to `frontend/src/services/api.ts` and your local environment.

To create a production build:

``` powershell
npm run build
```

## Suggested Verification Flow

1.  Confirm containers are running with `docker compose ps`.
2.  Open the API Gateway Swagger UI.
3.  Create an order with `POST /api/v1/orders`.
4.  Verify payment and notification records using their API endpoints.
5.  Query traces and inspect returned `trace_id` values.
6.  Inspect trace-correlated logs.
7.  Review metric summaries, time series, and latency percentiles.
8.  Check service dependencies and diagnostic results.
9.  Review alert rules and verify alert behavior.
10. Open the frontend and check the available dashboard views.

Use actual API responses when recording test results. A successful
business request does not by itself prove that telemetry was ingested or
a distributed trace was stored.

## Troubleshooting

-   **Telemetry connection errors:** Check `TELEMETRY_INGESTION_URL`,
    confirm the ingestion container is running, and inspect its logs.
-   **Database authentication errors:** Verify the database URL and
    credentials, and confirm required database-driver dependencies are
    installed.
-   **Missing traces or logs:** Confirm telemetry submission succeeds,
    trace identifiers are propagated, and processing services are
    running.
-   **Frontend API errors:** Confirm the backend is running and the
    frontend API base URL points to the correct gateway.
-   **Port conflicts:** Check whether configured host ports are already
    in use.

## Data and Security Notes

-   Never commit `.env` files, passwords, tokens, or other secrets.
-   Do not run `docker compose down -v` or remove Docker volumes unless
    you intentionally want to delete persistent data.
-   Review `docker-compose.yml` and environment example files before
    sharing the repository.

## Project Scope

The backend scope covers trace APIs, trace-correlated logs, metric
summaries and time series, service dependency mapping,
diagnostic/root-cause APIs, and persistent threshold-based alerts with
duplicate prevention. Actual behavior depends on each service's current
implementation and configuration.

## License

Add license and attribution information here if the project will be
distributed publicly.
