# API documentation

Interactive documentation: **http://localhost:8000/docs** (Swagger) and **/redoc**. This page summarises
conventions and endpoints; the OpenAPI schema at `/openapi.json` is authoritative.

## Conventions

- JSON only; timestamps ISO-8601 UTC. Naive input timestamps are treated as UTC.
- Identity: `X-User-Name` / `X-User-Role` (demo mode) or `X-API-Key` (`AUTH_ENABLED=true`).
- Pagination: `page` (≥1), `page_size` (1-100) → `{items, total, page, page_size, pages}`.
- Errors:

```json
{"error": {"code": "invalid_status_transition", "message": "Cannot move incident from OPEN to CLOSED",
           "details": {"current_status": "OPEN", "allowed": ["ASSIGNED", "ESCALATED"]}}}
```

| HTTP | code | When |
|---|---|---|
| 401 | `authentication_required` | missing/invalid API key, unknown role |
| 403 | `permission_denied` | role too low, AI actor attempting a human-only action |
| 404 | `not_found` | |
| 409 | `invalid_status_transition` | state machine violation |
| 422 | `validation_error` | schema validation (per-field errors in `details.errors`) |
| 422 | `business_rule_violation` | e.g. resolve without summary, close P1 without confirmed root cause |

## Incidents

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/api/incidents` | ENGINEER | priority derived if omitted; optional `assigned_team` assigns immediately |
| GET | `/api/incidents` | VIEWER | filters: `status`*, `severity`*, `priority`*, `category`*, `application_id`, `assigned_team`, `search`, `created_from`, `created_to`, `sla_breached`, `active_only`; `sort` (created_at, updated_at, started_at, severity, priority, status, reference_number), `order` (* = repeatable) |
| GET | `/api/incidents/{id}` | VIEWER | includes live SLA, `allowed_transitions`, counts |
| GET | `/api/incidents/by-reference/{ref}` | VIEWER | e.g. `INC-1007` |
| PUT | `/api/incidents/{id}` | ENGINEER | partial update of title, description, severity, priority, category, business_impact, started_at; `reason` recorded |
| PATCH | `/api/incidents/{id}/status` | ENGINEER (CLOSED: INCIDENT_MANAGER) | `{status, note?, resolution_summary?}` |
| PATCH | `/api/incidents/{id}/assign` | ENGINEER | `{assigned_team, assigned_engineer?, note?}`; OPEN/REOPENED → ASSIGNED |
| GET | `/api/incidents/{id}/sla` | VIEWER | response & resolution clocks, escalation status |

## Timeline

| Method | Path | Notes |
|---|---|---|
| GET | `/api/incidents/{id}/timeline` | chronological audit events |
| POST | `/api/incidents/{id}/events` | only `INVESTIGATION_UPDATE`, `EVIDENCE_ADDED`, `COMMENT`; others are system-generated |

## Root cause, RCA, CAPA, related changes

| Method | Path | Role |
|---|---|---|
| GET/POST | `/api/incidents/{id}/root-causes` | VIEWER / ENGINEER (created as HYPOTHESIS or UNDER_REVIEW only) |
| POST | `/api/root-causes/{id}/review` | INCIDENT_MANAGER, human only — `{decision: CONFIRM|REJECT, review_notes?}` |
| GET/PUT | `/api/incidents/{id}/rca` | composite RCA; `status: APPROVED` needs a confirmed root cause and a human manager |
| GET/POST | `/api/incidents/{id}/actions` | CAPA list / create |
| PATCH | `/api/actions/{id}` | update status/owner/due date; COMPLETED sets `completed_at` |
| GET/POST | `/api/incidents/{id}/related-changes` | link change records; returns minutes from deployment to incident start |

## Analytics

All accept `created_from`, `created_to`, `application_id` unless noted.

| Path | Returns |
|---|---|
| `/api/analytics/incident-summary` | totals, open, P1, SLA breaches, SLA compliance %, MTTR |
| `/api/analytics/severity-breakdown` | total/open per severity |
| `/api/analytics/category-breakdown` | total/open per category |
| `/api/analytics/application-incidents` | per application: total, open, P1, MTTR |
| `/api/analytics/mttr` | MTTR/MTTA overall and by severity, min/max |
| `/api/analytics/sla-compliance` | met/breached/pending + compliance % for response and resolution, by severity |
| `/api/analytics/trends?days=30` | daily created (by severity) and resolved counts |
| `/api/analytics/repeated-incidents?days=90&min_occurrences=2` | recurring application + category pairs |

## Applications and reference data

| Path | Returns |
|---|---|
| `GET /api/applications` | active applications |
| `GET /api/applications/{id}` | application with dependencies and dependents (blast radius) |
| `GET /api/changes?application_id=` | change records, newest deployment first |
| `GET /api/reference-data` | severity definitions + demo SLA targets, categories, priorities, transitions |
| `GET /api/health` | service and database health |

## Operational evidence and data sources

| Path | Returns |
|---|---|
| `GET /api/operational-events` | filters: `application_id`*, `event_type`*, `level`*, `metric_name`, `occurred_from`, `occurred_to`, `limit` |
| `GET /api/incidents/{id}/evidence` | evidence from `minutes_before` (default 120) the incident start until resolution/now; `include_related` adds dependencies and dependents |
| `GET /api/data-sources` | row counts per data source |

`GET /api/incidents` also accepts `data_source` (e.g. `SYNTHETIC`, `MANUAL`).

## AI analysis (Phase 5)

| Method | Path | Role |
|---|---|---|
| GET | `/api/ai/status` | VIEWER |
| GET | `/api/ai/incidents/{id}/context` | VIEWER - exact fact base sent to Claude |
| POST | `/api/ai/incidents/{id}/analyze` | ENGINEER - `{"focus": "..."}` optional; 201, or 503 `ai_unavailable` / 502 `ai_response_invalid` |
| GET | `/api/ai/incidents/{id}/investigations` | VIEWER |
| GET | `/api/ai/investigations/{id}` | VIEWER |
| POST | `/api/ai/investigations/{id}/review` | INCIDENT_MANAGER, human only |

Multi-agent `POST /api/ai/investigations` arrives in Phase 6. Details: [ai-analysis.md](ai-analysis.md).
