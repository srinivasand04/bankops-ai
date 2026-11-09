# Implementation plan

Target: two-day MVP, prioritising a working end-to-end incident investigation workflow.

## Phase 1 - Foundation ✅
- Project structure, `.env.example`, `.gitignore`
- Docker Compose: PostgreSQL 17 + pgvector (host port 5445), backend service, Redis under the `future` profile
- FastAPI app, settings, logging, error handling, request IDs
- SQLAlchemy 2 models, Alembic initial migration (upgrade/downgrade verified, `alembic check` clean)

## Phase 2 - Incident Management ✅
- Incident CRUD, references `INC-1001…` from a PostgreSQL sequence
- Severity / priority / category classification (priority derived from severity × criticality)
- Lifecycle state machine with validation; every transition writes a timeline event
- Assignment, escalation, resolution (summary required), closure (manager only; P1 needs confirmed root cause), reopen (note required)
- SLA engine: demo targets, due dates, live state (ON_TRACK / AT_RISK / BREACHED / MET), breach events, escalation recommendation
- Root cause hypotheses with human-only confirmation, RCA document, CAPA actions, change correlation
- Synthetic environment: 5 applications, dependencies, 5 changes, 10 incidents incl. the main scenario

## Phase 3 - Incident Analytics ✅
- Summary, severity, category, application breakdowns, MTTR/MTTA, SLA compliance, daily trends, repeated incidents

## Phase 4 - Data ingestion + operational evidence ✅
- Standard JSON dataset format, Pydantic schemas, three-layer validation (schema, references, lifecycle dry-run)
- Loader with `data_source` tagging, source-scoped replace, reference-sequence handling; CLI `python -m app.ingestion`
- `operational_events` table + evidence APIs; synthetic metrics/logs/alerts for the payment scenario
- Old `app/seed` module replaced by `backend/datasets/synthetic`

## Phase 5 - Claude Integration ✅
- `anthropic` 2.3.0 SDK wrapper behind an `LlmClient` protocol; model, effort, timeout, retries, fallbacks from settings
- Fact base builder with citable evidence IDs; fixed (cacheable) system prompt
- `POST /api/ai/incidents/{id}/analyze`: structured output (`IncidentAnalysis`), guardrails, investigation report AWAITING_REVIEW
- Human review: approval records AI hypotheses (still HYPOTHESIS) and OPEN CAPA actions; rejection applies nothing
- 22 tests with a fake LLM and a mocked SDK client
- Free local provider: `OllamaLlm` (`AI_PROVIDER=ollama`, `qwen3:8b`), 11 tests with mocked HTTP

## Phase 6 - Frontend workflow UI ✅
- Moved before the agentic phase so the human-in-the-loop workflow can be seen end to end
- AI analysis runs in the background: `POST .../analyze` returns 202 with a RUNNING investigation; the page polls
  until it is ready; interrupted runs are marked FAILED at startup; one running analysis per incident
- Pages: dashboard, incident list + create form, incident detail (assign, status transitions, SLA, timeline notes,
  root-cause confirm/reject, CAPA), AI investigation centre (start, live progress, report, approve/reject)
- Demo user switcher (engineer / incident manager / viewer) to show role rules; React, TypeScript, Tailwind, react-router

## Phase 7 - Agentic AI (done)
- 7B UI: agent-team view on the investigation page (flow strip, each step's tools, findings, tokens, timing, live while running), IMPACT/RISK score cards, single-call vs agent-team choice when starting
- LangGraph state, supervisor with conditional routing, five specialist agents
- Tools over existing services: `get_incident_details`, `get_incident_timeline`, `get_application_health`,
  `get_application_dependencies`, `get_related_changes`, `get_recent_deployments`, `calculate_incident_impact`,
  `calculate_operational_risk`, `get_incident_history`, `create_investigation_report`
- Human review interrupt and approve/reject endpoint; `agent_executions` per step

## Phase 8 - Real data (BPI 2014) (done)
- Adapter `app/ingestion/bpi2014.py` + `scripts/bpi2014_to_dataset.py`: raw Rabobank CSVs → 300 incidents, 130 changes,
  6 applications, loaded through the normal 3-layer validation ([bpi2014.md](bpi2014.md))

## ML module (done)
- Phase 1: seeded large synthetic dataset generator ([synthetic-data.md](synthetic-data.md))
- Phases 2-5: features without leakage, time-based splits, model registry (joblib + `ml_model_runs`), 8 tasks,
  predictions as `ML-PRED` evidence for the AI, ML Lab and ML insights UI, pre-trained bundle for the hosted demo
  ([ml.md](ml.md))

## Management reports, users and languages (done)
- Reports tab: scorecard with RAG, SLA performance, trends, change risk, problem management; print / PDF and CSV
- Users and roles in the database with an admin screen; English / French across every screen

## Known limitations / backlog
- SLA clock does not pause while ON_HOLD
- Analytics SLA compliance evaluates in Python (fine for MVP volumes; move to SQL/materialised views at scale)
- Demo/API-key auth only; no SSO, no per-team data scoping
- `starlette.testclient` emits a deprecation warning about `httpx`; harmless for now
