# Architecture

## Style

A **modular monolith**: one deployable FastAPI service and one PostgreSQL database, organised so each
business module can be added (or later extracted) without touching the others.

```
React (Vite)  ──HTTP/JSON──►  FastAPI routers (api/routes)
                                   │  Pydantic schemas validate every request/response
                                   ▼
                              Services (business rules)      ◄── AI agents call the same services
                              lifecycle · sla · classification   via tools (Phase 5), as `ai:` actors
                              incident · rca · analytics
                                   │
                                   ▼
                              Repositories (SQLAlchemy queries)
                                   │
                                   ▼
                              PostgreSQL 17 (+ pgvector for later RAG)
```

### Layers

| Layer | Responsibility | Rule |
|---|---|---|
| `api/routes` | HTTP, auth dependencies, pagination, serialisation | No business logic |
| `schemas` | Input validation and response contracts | Enums restrict values; lengths bounded |
| `services` | Business rules, transactions, audit events | Every state change writes a timeline event |
| `repositories` | Query construction | Parameterised SQLAlchemy only |
| `models` | Tables, constraints, relationships | Schema changes only via Alembic |

Pure rule modules (`lifecycle.py`, `sla_service.py`, `classification.py`) have no I/O so they are unit
tested directly and reused by the seed loader and, later, by AI tools.

## Module map

| # | Module | Status | Foundation already present |
|---|---|---|---|
| 1 | Banking Application Operations | Foundation | `applications`, `application_dependencies`, health status |
| 2 | IT Incident Intelligence | **Implemented** | full |
| 3 | Operational Risk Management | Planned | — |
| 4 | Change & Release Risk | Foundation | `change_records` (simulated ITSM feed), incident correlation |
| 5 | IT Controls & Compliance | Planned | audit timeline, role model |
| 6 | Business Continuity & Resilience | Planned | business criticality tiers, dependency graph |

New modules get their own `models/<module>.py`, `services/`, `api/routes/` files and an Alembic
revision; cross-module reads go through services, not direct table access.

## Data ingestion

Every dataset enters through `app/ingestion`: adapter → standard JSON dataset → schema, reference
and lifecycle-replay validation → single-transaction load tagged with `data_source`. See
[data-ingestion.md](data-ingestion.md).

## Governance and AI separation

- Every record carries a `source` (`HUMAN`, `AI`, `SYSTEM`).
- AI actors use the reserved `ai:` user prefix (cannot be claimed through request headers).
- Services refuse, for `ai:` actors: closing incidents, confirming/rejecting root causes, approving RCAs.
- Root causes can only be *created* as `HYPOTHESIS`/`UNDER_REVIEW`; `CONFIRMED` requires the review
  endpoint and a database CHECK constraint enforces `confirmed_by`/`confirmed_at`.
- The RCA view always returns `confirmed_root_causes` and `hypotheses` as separate lists.

## Planned agentic layer (Phase 5)

LangGraph `StateGraph` with a supervisor routing conditionally to five specialists (Operations
Monitoring, Incident Investigation, Change Risk, Risk Assessment, Reporting), ending in a human-review
interrupt. Tools wrap the existing services/repositories so agents only see real data. Runs and steps
are persisted to `investigation_reports` and `agent_executions`.

## Cross-cutting

- **Configuration**: `pydantic-settings`, environment variables / `.env`; secrets never in code.
- **Errors**: domain exceptions mapped to `{"error": {"code", "message", "details"}}` with 404/409/422/403/401.
- **Logging**: method, path, status, latency and request ID only — no headers or bodies.
- **Time**: all timestamps are timezone-aware UTC.
