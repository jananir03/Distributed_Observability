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


## Run the Backend

From the repository root:

``` powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
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

