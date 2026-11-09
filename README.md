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
| 7 Agentic AI | LangGraph triage → supervisor → specialists → root cause, 10 read-only tools, per-step audit, human review gate | Done |
| 8 Real data | BPI 2014 (Rabobank) adapter: 300 real incidents and 130 changes through the same validation | Done |
| ML | Seeded large synthetic dataset; 8 ML tasks comparing 2-4 algorithms each on time-based splits; predictions as `ML-PRED` evidence for the AI; ML Lab | Done |
| Reports | 5 management reports across all applications, print to PDF, CSV | Done |
| Users & roles | Users stored in the database (role never trusted from the browser), admin screen, lock-out protection | Done |
| EN / FR | Every screen in English and French | Done |

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
The **EN / FR** switch in the header translates every screen; the choice is remembered in the
browser. Incident data and AI-written text stay in the language they were written in.

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
.\.venv\Scripts\python.exe -m pytest              # 209 tests against the bankops_test database (AI mocked)
.\.venv\Scripts\python.exe scripts\smoke_test.py  # end-to-end HTTP workflow against a running backend
```

Tests run against a separate `bankops_test` database (created by `docker/postgres/init`), which is
migrated with Alembic at the start of the session and truncated between tests. The suite refuses to
run if `TEST_DATABASE_URL` does not point at a database ending in `_test`.

## Management reports

The **Reports** tab covers every application for the last 30 / 90 / 180 / 365 days:

| Report | What management sees |
|---|---|
| Application scorecard | Each application's incidents, open / P1, SLA %, breaching now, MTTR / MTTA, changes and a RAG status |
| SLA performance | Response and resolution compliance by severity and application; incidents breaching now, most overdue first |
| Incident trends | Weekly or monthly volume by severity, resolutions, SLA breaches and MTTR |
| Change risk | Changes per application, failures / roll-backs, incidents linked to changes, change failure rate |
| Problem management | Recurring incidents (same application + category 3+ times) and reopened incidents |

*Management report* puts all five on one page: **Print / save as PDF** produces the pack
([sample](documents/management-report-sample.pdf)), and each report can be downloaded as CSV.
API: `GET /api/reports/{scorecard|sla|trends|change-risk|problems|management-pack}?days=90`.

## Large synthetic dataset (for the ML module)

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\generate_synthetic.py --seed 42 --months 12
.\.venv\Scripts\python.exe -m app.ingestion load datasets/synthetic_large
```

12 applications, 4,000 incidents, 648 changes, 125K events with designed signal - see
[documents/synthetic-data.md](documents/synthetic-data.md).

## Machine learning (ML Lab)

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.ml train-all       # 8 tasks, about 1 minute; needs the large dataset
.\.venv\Scripts\python.exe -m app.ml list            # active model and test metrics per task
```

SLA-breach and MTTR prediction, change-risk scoring, text routing, similar incidents (pgvector),
K-Means patterns, volume forecasting and metric anomalies. Each compares several algorithms
(linear / logistic regression, decision trees, random forests, gradient boosting, XGBoost / LightGBM,
Naive Bayes, SVM, KNN, K-Means, Holt-Winters) on a time-based split. Predictions appear on every
incident (*ML insights*) and in the AI fact base as `ML-PRED-<id>`; they never change an incident.
Results and limitations: [documents/ml.md](documents/ml.md).

## Real data: BPI Challenge 2014

```powershell
.\.venv\Scripts\python.exe scripts\bpi2014_to_dataset.py --raw ..\data\raw\bpi2014 --out datasets\bpi2014
.\.venv\Scripts\python.exe -m app.ingestion load datasets\bpi2014
```

300 real, anonymised Rabobank incidents (March 2014) with their activity history and 130 changes, on
6 service components - see [documents/bpi2014.md](documents/bpi2014.md).

## Deploy to the web (free tiers)

UI on Vercel, API (Docker) on Render, PostgreSQL on Neon, AI on Groq's free tier - step by step in
[documents/deployment.md](documents/deployment.md). [`render.yaml`](render.yaml) and
[`frontend/vercel.json`](frontend/vercel.json) hold the platform configuration.

## AI analysis: Claude or a free local model

`AI_PROVIDER` in `.env` selects the model provider (`anthropic`, `ollama` or `groq`); everything else is identical.

- `AI_PROVIDER=ollama` (free): install [Ollama](https://ollama.com), run `ollama pull qwen3:8b`,
  then `docker compose up -d backend`. Slower on a laptop CPU (minutes per analysis).
- `AI_PROVIDER=anthropic`: set `ANTHROPIC_API_KEY`; model `claude-opus-5-5`, adaptive thinking,
  effort `high`.

If the provider is not ready, `POST /api/ai/incidents/{id}/analyze` returns 503 and records a FAILED
investigation; `GET /api/ai/status` says what is missing. See [documents/ai-analysis.md](documents/ai-analysis.md).

## Users and roles

Users live in the database (`app_users`). Default users are created at startup: **Srinivasan
Dhakshanamoorthy (ADMIN)** plus one Engineer, one Incident manager and one Viewer. The **Users**
screen lets an administrator add people, change roles and deactivate them. There is always at least
one active admin, and an admin cannot remove their own access.

Demo mode (`AUTH_ENABLED=false`, no passwords): the browser names the user with `X-User-Name`. For a
stored user, the role always comes from the database (`X-User-Role` is ignored) and deactivated users
are refused. Names that are not stored (scripts, tests) use `X-User-Role` but can never be ADMIN.
With `AUTH_ENABLED=true`, `X-API-Key` must match an entry in `API_KEYS`. This is not production
authentication.

| Action | Minimum role |
|---|---|
| Read anything | VIEWER |
| Create/update incidents, add events, actions, hypotheses, run AI analyses | ENGINEER |
| Close incidents, confirm/reject root causes, approve AI findings, retrain ML models | INCIDENT_MANAGER (never an `ai:` actor) |
| Add users, change roles, deactivate users | ADMIN |

## Synthetic environment

The dataset in `backend/datasets/synthetic/` is loaded through the ingestion pipeline. It has five
applications (Payment Processing, Core Banking, Customer Services, Transaction Reconciliation,
Reporting & Data Warehouse) with dependencies, seven change records, 193 operational events
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

- [User guide and test flows](documents/user-guide.md)
- [Deployment (Vercel + Render + Neon + Groq)](documents/deployment.md)
- [Architecture](documents/architecture.md)
- [Data ingestion pipeline](documents/data-ingestion.md)
- [Large synthetic dataset for ML](documents/synthetic-data.md)
- [AI incident analysis](documents/ai-analysis.md)
- [Multi-agent investigation (LangGraph)](documents/agentic-ai.md)
- [Machine learning (ML Lab)](documents/ml.md)
- [Real data: BPI Challenge 2014](documents/bpi2014.md)
- [Test guide (every feature, step by step)](documents/test-guide.md)
- [Database design](documents/database-design.md)
- [API documentation](documents/api-documentation.md)
- [Banking concepts](documents/banking-concepts.md)
- [Implementation plan](documents/implementation-plan.md)
