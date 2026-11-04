# BankOps AI

**Banking Operational Risk & IT Incident Intelligence Platform**

BankOps AI helps banking technology teams identify, investigate, assess and mitigate technology-related
operational risk. It is a modular monolith (FastAPI + PostgreSQL + React) designed for six business
modules; **Module 2 - IT Incident Intelligence** is implemented first. Claude + LangGraph agents are
added in Phases 4-5.

> All data is **synthetic**. SLA targets are **demonstration values**, not universal banking
> requirements. The MVP's authentication is a demo/API-key scheme and is **not** production-grade security.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | Repo structure, Docker Compose, PostgreSQL 17 + pgvector, FastAPI, SQLAlchemy 2, Alembic | Done |
| 2 Incident Management | CRUD, classification, lifecycle state machine, timeline, SLA, RCA, CAPA, change correlation | Done |
| 3 Incident Analytics | Summary, severity/category/application breakdowns, MTTR/MTTA, SLA compliance, trends, repeated incidents | Done |
| 4 Data Ingestion + Evidence | Standard JSON datasets, 3-layer validation, loader CLI, `data_source` tagging, operational evidence (metrics/logs/alerts) | Done |
| 5 Claude Integration | Fact base with citable evidence IDs, one structured Claude call, guardrails, human review gate | Done |
| 6 Frontend workflow UI | Incident list + create form, incident detail (assign, status, timeline, RCA, CAPA), AI investigation centre with live progress and approve/reject, user switcher | Done |
| 7 Agentic AI | LangGraph supervisor + 5 specialist agents, tools, human review | Next |
| 8 Real data + wrap-up | BPI 2014 (Rabobank) adapter with a small subset, final tests, demo docs | Planned |

## Quick start (Windows, PowerShell, Docker Desktop)

```powershell
cd D:\Study\BankOps-AI
Copy-Item .env.example .env        # then edit POSTGRES_PASSWORD (and DATABASE_URLs to match)
docker compose up -d --build       # PostgreSQL + backend; migrations + synthetic seed run on start
```

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health: http://localhost:8000/api/health

PostgreSQL is published on host port **5445** (5432-5434 are commonly used by other local instances;
change `POSTGRES_HOST_PORT` in `.env` if needed).

### Frontend (dev server)

Pages: **Dashboard** (KPIs, AI review queue), **Incidents** (filters, *New incident* form, detail page
with assign / status buttons / timeline notes / root-cause confirm-reject / CAPA), **AI investigations**
(start an analysis, live progress, report, *Approve* / *Reject*). The *Acting as* selector switches
between demo users (engineer, incident manager, viewer) to show the role rules.

```powershell
cd frontend
npm install
npm run dev                         # http://localhost:5173 (proxies /api to :8000)
```

### Backend on the host (for development)

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
docker compose up -d db             # from the project root
alembic upgrade head
python -m app.ingestion load datasets/synthetic   # --replace to reload; see documents/data-ingestion.md
uvicorn app.main:app --reload --port 8000
```

### Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest              # 118 tests against the bankops_test database (AI mocked)
.\.venv\Scripts\python.exe scripts\smoke_test.py  # end-to-end HTTP workflow against a running backend
```

Tests run against a separate `bankops_test` database (created by `docker/postgres/init`), which is
migrated with Alembic at the start of the session and truncated between tests. The suite refuses to
run if `TEST_DATABASE_URL` does not point at a database ending in `_test`.

## AI analysis: Claude or a free local model

`AI_PROVIDER` in `.env` selects the model provider; everything else is identical.

- `AI_PROVIDER=ollama` (free): install [Ollama](https://ollama.com), run `ollama pull qwen3:8b`,
  then `docker compose up -d backend`. Slower on a laptop CPU (minutes per analysis).
- `AI_PROVIDER=anthropic`: set `ANTHROPIC_API_KEY`; model `claude-opus-5-5`, adaptive thinking,
  effort `high`.

If the provider is not ready, `POST /api/ai/incidents/{id}/analyze` returns 503 and records a FAILED
investigation; `GET /api/ai/status` says what is missing. See [documents/ai-analysis.md](documents/ai-analysis.md).

## Demo identity

With `AUTH_ENABLED=false` (default) requests may send `X-User-Name` / `X-User-Role`
(`VIEWER`, `ENGINEER`, `INCIDENT_MANAGER`, `ADMIN`); without them the caller is `demo.manager`
(INCIDENT_MANAGER). With `AUTH_ENABLED=true`, `X-API-Key` must match an entry in `API_KEYS`.

| Action | Minimum role |
|---|---|
| Read anything | VIEWER |
| Create/update incidents, add events, actions, hypotheses | ENGINEER |
| Close incidents, confirm/reject root causes, approve RCA | INCIDENT_MANAGER (never an `ai:` actor) |

## Synthetic environment

The dataset in `backend/datasets/synthetic/` is loaded through the ingestion pipeline. It has five
applications (Payment Processing, Core Banking, Customer Services, Transaction Reconciliation,
Reporting & Data Warehouse) with dependencies, five change records, 149 operational events
(metrics, logs, alerts, job runs) and ten incidents, including the
**main demo scenario**: Payment Processing release 2.4.1 (`CHG-2041`) deployed, HTTP 500s 30 minutes
later (`INC-1007`, P1), reconciliation batch failure (`INC-1008`, P2) and Customer Services status
delays (`INC-1009`, P3).

## Project structure

```
BankOps-AI/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, error handlers, request logging
│   │   ├── core/                settings, DB session, security, exceptions, logging
│   │   ├── models/              SQLAlchemy models (incidents, applications, changes, AI)
│   │   ├── schemas/             Pydantic request/response models
│   │   ├── repositories/        query layer
│   │   ├── services/            business rules: lifecycle, SLA, classification, RCA/CAPA, analytics
│   │   ├── api/routes/          FastAPI routers
│   │   ├── ai/                  context builder, Claude client, guardrails, prompts (agents/graph: Phase 6)
│   │   ├── ingestion/           dataset schemas, validation, loader, CLI
│   │   └── utils/
│   ├── datasets/synthetic/      standard JSON demo dataset
│   ├── alembic/                 migrations
│   ├── tests/                   pytest suite
│   ├── scripts/smoke_test.py
│   └── Dockerfile
├── frontend/                    React + TypeScript + Vite + Tailwind
├── documents/                   architecture, database, API, banking concepts, plan
├── docker/postgres/init/        creates bankops_test, enables pgvector
├── docker-compose.yml
└── .env.example
```

## Documentation

- [Architecture](documents/architecture.md)
- [Data ingestion pipeline](documents/data-ingestion.md)
- [AI incident analysis](documents/ai-analysis.md)
- [Database design](documents/database-design.md)
- [API documentation](documents/api-documentation.md)
- [Banking concepts](documents/banking-concepts.md)
- [Implementation plan](documents/implementation-plan.md)
