# Obsidian

**Autonomous Earth Intelligence Platform.**

Obsidian is not a chatbot for satellite imagery. A user describes *what they want to know*; Obsidian determines *how to answer it*, plans the investigation transparently, executes it autonomously as a durable workflow, verifies the results, and returns evidence-backed, traceable conclusions.

The defining feature is the **Explainable Investigation Planner**: before any model runs, the system compiles a capability-based plan and exposes it to the user as an interactive investigation graph.

```
Natural Language Query
  → Intent Understanding
  → Location Resolution
  → Capability Planning
  → Workflow Compilation
  → Temporal Execution
  → Evidence Collection
  → Verification
  → Interactive Report
```

---

## Table of Contents

- [Current Status](#current-status)
- [Architecture Overview](#architecture-overview)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Core Principles](#core-principles)
- [Running the Stack](#running-the-stack)
- [Backend Standards (FastAPI)](#backend-standards-fastapi)
- [Workflow Standards (Temporal)](#workflow-standards-temporal)
- [Database Standards (Supabase + PostGIS)](#database-standards-supabase--postgis)
- [Frontend Standards (Next.js)](#frontend-standards-nextjs)
- [Cross-Cutting Standards](#cross-cutting-standards)

---

## Current Status

This README describes both what exists today and the product vision it is being built toward. The two are kept explicit so the gap is never hidden.

**Built today**
- `app_management_microservice` — the public FastAPI API: **Sign in with Google** (backend-issued JWT), user profiles, profile-picture storage, health/metrics.
- `workflow_microservice` — a clean Temporal worker scaffold (no workflows registered yet).
- The full **Supabase + PostGIS** schema (`database.context`): identity, projects, investigations, AOIs, datasets, capabilities, the investigation graph, imagery, artifacts/evidence, reports, timeline/outbox, monitors — seeded with capabilities, datasets, and templates.
- Docker Compose topology (dev / test / prod), Redis, Temporal cluster, and OpenTelemetry → Grafana observability.

**Not built yet (roadmap)**
- The investigation domain in code: the planner, AOI resolution, Earth-observation retrieval, analysis activities, and the `InvestigationWorkflow`. The database supports all of it; the routes/services/activities are still to come.
- The planner/reasoning LLM (will default to Claude).
- The Next.js frontend and PostHog analytics.

---

## Architecture Overview

Obsidian is a **monorepo** of independently deployable, **stateless** services that communicate only over the network (HTTP, Temporal task queues, Postgres). No service imports another service's source code.

```
                ┌─────────────────────────────────────────────┐
                │            frontend (Next.js) — planned       │
                │     Investigation graph · Map · Evidence UI   │
                └───────────────┬─────────────────────────────┘
                                │ HTTPS (REST) + SSE
                                ▼
                ┌─────────────────────────────────────────────┐
                │      app_management_microservice (FastAPI)    │
                │      routes → controllers → services          │
                │      Google auth · JWT · users · storage      │
                │      starts / queries Temporal workflows      │
                └──┬─────────┬──────────┬──────────┬───────────┘
                   │         │          │          │
         Temporal  │  Supabase│   Redis  │  Firebase│  Filebase (S3)
          client   │  Postgres│  cache / │  Google  │  object
                   │ + PostGIS│  streams │  verify  │  storage
                   ▼         ▼          ▼          ▼
        ┌───────────────────────────┐
        │   Temporal Server          │   durable orchestration
        └───────────────┬───────────┘
                        │ task queues
                        ▼
        ┌───────────────────────────┐
        │  workflow_microservice     │   Temporal worker (scaffold)
        │  workflows + activities    │   investigation orchestration
        └───────────────────────────┘
```

- **app_management_microservice** — FastAPI HTTP layer and the only public entrypoint. Authenticates requests, validates payloads, manages users/storage, and (in time) starts/queries Temporal workflows. Holds no long-lived state.
- **workflow_microservice** — Temporal worker that will host the investigation **workflows** (orchestration) and **activities** (capability implementations: AOI resolution, imagery retrieval, cloud filtering, segmentation, GIS analysis, evidence, reporting). Durable, retryable, replayable.
- **Temporal** — durable execution engine. Every investigation is a workflow; every pipeline stage is an activity.
- **Supabase (Postgres + PostGIS)** — system of record for users, investigations, geospatial AOIs, artifacts, and evidence.
- **Firebase Admin** — used *only* to verify a Google ID token once at sign-in; never a session authority.
- **Filebase (S3-compatible)** — object storage for profile pictures (and, later, imagery, masks, and exported reports).
- **Redis** — cache, JWT blocklist / refresh-token store, and the SSE event-outbox stream that drives incremental UI updates.

---

## Technology Stack

| Concern | Technology |
|---|---|
| API | FastAPI (Python 3.11+) |
| Workflows | Temporal (Python SDK) |
| Database | Supabase — Postgres + **PostGIS** |
| Authentication | Sign in with Google (Firebase Admin verifies the ID token) → backend-issued JWT access + refresh |
| Object storage | Filebase (S3-compatible, via presigned URLs) |
| Cache / streams | Redis |
| Observability | OpenTelemetry → Grafana Cloud (Loki · Tempo · Mimir) |
| Reverse proxy (prod) | Traefik |
| Containerization | Docker + Docker Compose |
| Frontend (planned) | Next.js (App Router) · TanStack Query · Zustand · PostHog |

---

## Repository Structure

```
Obsidian/
├── backend/
│   ├── app_management_microservice/    # FastAPI — the public API
│   │   ├── app/
│   │   │   ├── main.py                  # app factory; middleware + global error handler
│   │   │   ├── config/                  # ALL client/connection setup (see below)
│   │   │   ├── routes/                  # ENTRYPOINTS ONLY — auth & authorization
│   │   │   ├── controllers/             # request/response, validation, error handling
│   │   │   ├── services/                # BUSINESS LOGIC ONLY
│   │   │   ├── schemas/                 # pydantic request/response/DTO models
│   │   │   ├── core/                    # exceptions, global error handler, deps, responses
│   │   │   ├── utils/                   # structured logging, tracing, redaction
│   │   │   └── helpers/                 # pure, side-effect-free utilities
│   │   ├── database.context            # Supabase/PostGIS schema (DDL, source of truth)
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   ├── workflow_microservice/          # Temporal worker (orchestration scaffold)
│   │   ├── app/{config,workflows,routes,controllers,services,utils}
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   ├── grafana/dashboards/             # Grafana dashboards (imported manually)
│   ├── temporal/                       # Temporal dynamic config + TLS certs
│   ├── docker-compose.dev.yml          # local dev (hot reload, exposed ports)
│   ├── docker-compose.test.yml
│   ├── docker-compose.prod.yml         # Traefik-fronted production
│   └── .env.example                    # documented template for every variable
│
├── frontend/                           # Next.js app (planned)
├── feature_to_build.md                 # product vision / MVP definition
└── README.md
```

### `app/config/` — client setup (the only place clients are constructed)

```
config/
├── settings.py        # typed settings from env (pydantic-settings)
├── supabase.py        # Supabase (Postgres) client
├── temporal.py        # Temporal client
├── redis.py           # Redis client
├── firebase.py        # Firebase Admin (Google ID-token verification)
├── filebase.py        # Filebase S3 client (object storage)
└── observability.py   # OpenTelemetry SDK (traces/metrics/logs)
```

---

## Core Principles

These are non-negotiable and apply to every service.

1. **No cross-service code imports.** The frontend, `app_management`, and `workflow` services never import each other's source. They share data through contracts (REST payloads, workflow arguments), not packages. Contracts are duplicated and version-checked at the boundary.
2. **Everything is stateless.** No service holds session state, correctness-affecting in-memory caches, or sticky local state. All durable state lives in Supabase, Redis, or Temporal. Any replica can serve any request.
3. **Temporal owns all workflows.** Any multi-step, long-running, retryable, or scheduled process is a Temporal workflow — never an ad-hoc background task, cron loop, or in-process queue.
4. **Docker only.** Nothing is run with local language package managers. The stack runs via `docker compose`. If it does not run in Compose, it does not run.
5. **No inline narration comments.** Code is self-documenting through naming and structure. See [Comment policy](#comment-policy).
6. **Capability-based planning.** The planner reasons about *capabilities* (e.g. "Segment Objects"), never concrete models. The execution layer chooses the implementation (SAM2 / SAM3 / GeoSAM). Adding a model never changes the planner.
7. **Every artifact carries metadata.** Confidence, reason, source dataset, timestamp, processing method, and supporting evidence travel with every result. Nothing is a black box.

---

## Running the Stack

Everything runs in Docker via Compose. There is no supported "install packages and run locally" path.

```bash
cd backend
cp .env.example .env.dev      # fill in Supabase, Firebase, Filebase, Temporal, OTel values
docker compose -f docker-compose.dev.yml up --build
```

| Service | URL / Endpoint |
|---|---|
| API (app_management) | http://localhost:4000 |
| API docs (non-prod) | http://localhost:4000/docs |
| Temporal UI | http://localhost:8233 |
| Redis | localhost:6379 |
| Temporal gRPC | localhost:7233 |

The dev compose mounts the API source for hot reload. Production (`docker-compose.prod.yml`) fronts the API with Traefik (TLS) and exposes no service ports directly.

### Active API endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/google` | public | Sign in with Google → JWT access + refresh |
| POST | `/auth/refresh` | refresh token | Rotate the token pair |
| POST | `/auth/logout` | Bearer | Revoke refresh + blocklist access token |
| GET | `/users/me` | Bearer | Get own profile |
| PATCH | `/users/me` | Bearer | Update profile |
| DELETE | `/users/me` | Bearer | Delete account |
| POST | `/users/me/profile-pic/upload-url` | Bearer | Presigned Filebase upload URL |
| PUT | `/users/me/profile-pic` | Bearer | Confirm uploaded picture |
| POST | `/users/profile-pic/download-url` | Bearer | Presigned download URL |
| GET | `/health`, `/health/ready`, `/metrics` | public | Liveness, readiness, Prometheus metrics |

---

## Backend Standards (FastAPI)

The API is strictly layered. Each layer has one responsibility and may only call the layer directly beneath it.

### Layers

**`routes/` — entrypoints.** Define endpoints and wire dependencies. Responsible *only* for **authentication and authorization**: resolve the authenticated principal, check access, delegate to a controller. No validation logic, no business logic.

**`controllers/` — request/response orchestration.** Responsible for **input validation, response shaping, and error handling**. Parse and validate the request (pydantic schemas), call one or more services, map the result into a response envelope, and let exceptions propagate to the global handler. No business logic; never touch clients directly.

**`services/` — business logic only.** The only layer that contains domain logic. Services orchestrate Supabase, Redis, the Temporal client, Filebase, and Firebase (obtained from `config/`). Pure of HTTP concerns — they take and return domain objects/DTOs, not `Request`/`Response`.

**`config/` — client setup.** Every external client and connection is constructed here as a singleton proxy and initialized in the app lifespan. No layer instantiates clients inline.

### Rules

- **Strict downward flow:** `routes → controllers → services → config`. Never skip or invert layers.
- **Global error handling.** One global exception handler (registered in `main.py`) maps a typed exception hierarchy (`core/exceptions.py`) to a consistent error envelope with stable error codes. Controllers raise domain exceptions; they never build error responses by hand.
- **Validation at the edge.** All input is validated with pydantic schemas. Services trust their inputs.
- **Typed throughout.** Full type hints; pydantic models for every request, response, and DTO. No untyped `dict` crossing a layer boundary.
- **Stateless handlers.** No module-level mutable state. Anything durable goes to Supabase, Redis, or Temporal.
- **Workflows are started by contract.** The API triggers workflows via the Temporal client using stable workflow identifiers and JSON-serializable arguments — it does **not** import workflow code from the worker.
- **Authentication.** Sign in with Google only: the client obtains a Google ID token (Firebase SDK), `POST /auth/google` verifies it once via Firebase Admin, then the backend mints its own JWT access + refresh pair. Refresh tokens rotate; revocation is enforced via a Redis blocklist.
- **Tooling:** dependencies in `requirements.txt`; `ruff` + `mypy` in CI.

---

## Workflow Standards (Temporal)

Every investigation is a Temporal workflow. The investigation lifecycle and graph map directly onto workflow orchestration and activities.

- **Workflows are deterministic and I/O-free.** Workflow code only orchestrates: sequence activities, handle retries/timeouts, emit progress signals. No network calls, randomness, wall-clock reads, or direct DB/storage access in workflow code.
- **Activities do all the work.** Every side effect — AOI resolution, dataset selection, imagery retrieval, cloud filtering, segmentation, GIS analysis, evidence collection, report generation — is an activity. Activities are **idempotent** and **retryable**.
- **Capabilities, not models.** Activities implement capabilities; the concrete implementation (SAM2/SAM3/GeoSAM, dataset selection) is an execution-layer detail behind the capability interface. The workflow never references a model.
- **Progress is observable.** Workflows expose state via Temporal queries/signals and the Redis event outbox, so the API can stream incremental investigation-graph updates over SSE. Each graph node corresponds to an activity (or group) and is independently inspectable.
- **Artifacts are persisted, not passed around.** Large artifacts (scenes, masks, reports) go to object storage; workflows pass references and metadata, never blobs.
- **Confidence travels with results.** Every activity result carries confidence-layer metadata (confidence, reason, source dataset, timestamp, method, evidence refs).
- **Scheduled & monitored investigations** use Temporal Schedules — never external cron.
- **Stateless workers.** Workers hold no state between activities; everything needed is in workflow inputs or Supabase.

---

## Database Standards (Supabase + PostGIS)

- **DDL is the source of truth.** The full schema lives in `app_management_microservice/database.context` and runs top-to-bottom in the Supabase SQL editor (or as migration `0001`). Schema changes are made there, never by hand on a live database.
- **Geospatial-first.** Geometry is stored in **EPSG:4326** with PostGIS; AOIs, scene footprints, artifact/finding geometries are `geometry(...)` columns with GiST indexes. Original GeoJSON is retained alongside geometry for lossless frontend round-tripping.
- **Row Level Security is enabled** on every table. The API uses the Supabase service-role key and enforces per-user authorization in the service layer (the backend issues its own JWT, so `auth.uid()` policies do not apply); RLS denies direct anon/public access.
- **The API and worker are the only writers.** The frontend reads through the API.
- **No business logic in the database** beyond constraints, RLS, triggers, and integrity — domain logic lives in `services/` and Temporal activities.

---

## Frontend Standards (Next.js)

*Planned — not yet implemented.* When built, the frontend targets a production-grade, **agentic, incrementally-updating** experience: investigation-graph nodes appear and resolve live as the workflow progresses.

- **Server state → TanStack Query.** All API data goes through TanStack Query with a centralized `QueryClient`, structured query keys, and sensible defaults. No fetching into `useEffect` + local state.
- **Client/UI state → Zustand.** Ephemeral UI state (selected node, map view, panels) only. Server data is never copied into client stores.
- **Incremental updates.** Long-running investigations stream progress over **SSE**; incoming events patch the relevant query-cache entries so the graph updates node-by-node without refetching. Mutations use optimistic updates with rollback.
- **Auth.** The browser runs Google sign-in (Firebase SDK) to obtain an ID token, exchanges it at `POST /auth/google` for the backend JWT pair, and sends the access token as a Bearer header. No service-role keys ever reach the browser; only `NEXT_PUBLIC_*` values are exposed.
- **Analytics.** PostHog is the single analytics layer, with centrally-defined typed events. Respect consent before capturing.
- **Quality.** Feature-first structure; strict TypeScript (no `any`); ESLint + Prettier in CI. Types mirror API contracts but are maintained at the boundary, not imported from the backend.

---

## Cross-Cutting Standards

### Comment policy

- Code must be self-explanatory through naming and structure.
- **No narration comments** (`# loop over users`, `// set the value`). They are not accepted in review.
- Allowed: short comments explaining a non-obvious *why* (a workaround, an external constraint). Explanation of *how* belongs in docs.

### Configuration & secrets

- All configuration comes from environment variables, documented in `.env.example`. Real `.env.*` files are never committed.
- No secrets in source, images, or the frontend bundle. Clients are constructed only in each service's `config/`.

### Statelessness & scaling

- No service relies on local disk or in-process memory for correctness. Durable state is Supabase, Redis, or Temporal. Any service scales horizontally with no coordination.

### Observability

- Structured JSON logging (structlog) with a correlation/request id propagated across `api → Temporal → worker`.
- Telemetry via OpenTelemetry → Grafana Cloud (Loki/Tempo/Mimir). Investigation progress and confidence metadata are first-class, surfaced to the user — never hidden.

### Containerization

- Every service ships a `Dockerfile`; the stack is orchestrated by `docker compose`.
- The only supported execution path — local or deployed — is containers. No "works on my machine" package installs.
