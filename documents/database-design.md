# Database design

PostgreSQL 17 (image `pgvector/pgvector:pg17`). Schema managed by Alembic
(`backend/alembic/versions/0001_initial_incident_intelligence_schema.py`); `create_all` is never used.

Enumerations are stored as `VARCHAR(40)` with CHECK constraints (non-native enums) so adding a value
is a simple constraint migration. JSON columns use `JSONB`. All timestamps are `timestamptz`.

## Entity relationships

```
applications 1──* application_dependencies *──1 applications (depends_on)
applications 1──* change_records
applications 1──* incidents
incidents 1──1 incident_sla
incidents 1──* incident_events          (append-only audit timeline)
incidents 1──* incident_root_causes
incidents 1──1 incident_rca
incidents 1──* incident_actions          (CAPA)
incidents 1──* incident_related_changes *──1 change_records
incidents 1──* investigation_reports 1──* agent_executions   (Phase 5-6)
applications 1──* operational_events     (evidence: metrics, logs, alerts, job runs)
```

`applications`, `change_records`, `incidents` and `operational_events` carry `data_source`
(`MANUAL` default, `SYNTHETIC`, later `BPI2014`) and `external_id` (ID in the source system), with a
unique (`data_source`, `external_id`) constraint. Added in migration `0002`.

## Tables

### applications
`code` (unique), `name` (unique), `business_criticality` (TIER_1..3), `health_status`
(HEALTHY/DEGRADED/DOWN/UNKNOWN), `owner_team`, `technology_stack`, `is_active`, timestamps.

### application_dependencies
`application_id` → depends on `depends_on_id`; `dependency_type`; `is_critical`.
Unique pair; CHECK `application_id <> depends_on_id`.

### change_records
`change_reference` (unique, e.g. CHG-2041), `application_id`, `change_type`
(STANDARD/NORMAL/EMERGENCY), `status`, `risk_level`, `version`, `implementer`, `approver`,
`rollback_plan`, `components_changed` (change scope, migration 0003), `planned_start`, `deployed_at` (indexed). Simulated ITSM data for now.

### incidents
| Column | Notes |
|---|---|
| `reference_number` | unique; `INC-` + `incident_reference_seq` (starts 1001) |
| `title`, `description` | |
| `application_id` | FK, indexed |
| `severity` | P1..P4 — impact, drives SLA |
| `priority` | CRITICAL..LOW — work order, separate from severity |
| `category` | 11 categories, indexed |
| `status` | lifecycle state; composite index (`status`, `severity`) |
| `assigned_team` (indexed), `assigned_engineer` | |
| `business_impact`, `resolution_summary` | |
| `reopen_count`, `created_by` | |
| `started_at` | when business impact began (MTTR start) |
| `acknowledged_at` | first move out of OPEN (response SLA) |
| `resolved_at`, `closed_at` | |
| `created_at` (indexed), `updated_at` | |

### incident_events
Append-only timeline: `event_type`, `description`, `details` (JSONB), `source`, `created_by`,
`created_at`. Index (`incident_id`, `created_at`).

### incident_sla
One row per incident (unique `incident_id`). Snapshot of `severity`, `clock_started_at`,
`response_target_minutes`, `resolution_target_minutes`, `response_due_at`, `resolution_due_at`
(indexed), and outcome flags `response_breached` / `resolution_breached` (NULL = pending).
Recomputed when severity changes.

### incident_root_causes
`description`, `category`, `status` (HYPOTHESIS/UNDER_REVIEW/CONFIRMED/REJECTED), `source`,
`confidence` (CHECK 0..1), `supporting_evidence`, `missing_evidence` (JSONB lists),
`confirmed_by`, `confirmed_at`, `review_notes`.
CHECK: `status <> 'CONFIRMED' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)`.

### incident_rca
One per incident: `summary`, `confirmed_facts`, `contributing_factors`, `missing_evidence`,
`business_impact`, `status` (DRAFT/IN_REVIEW/APPROVED), `approved_by`, `approved_at`.
Added beyond the initial table list so the RCA narrative has a home separate from root-cause rows.

### incident_actions (CAPA)
`action_type` (CORRECTIVE/PREVENTIVE), `description`, `assigned_team`, `assigned_owner`, `due_date`,
`status` (OPEN/IN_PROGRESS/COMPLETED/CANCELLED), `completed_at`, `source`. Index (`status`, `due_date`).

### incident_related_changes
`incident_id`, `change_id`, `link_status` (SUSPECTED/CONFIRMED/RULED_OUT), `notes`, `source`,
`identified_by`. Unique (`incident_id`, `change_id`).

### operational_events
`application_id`, `event_type` (METRIC/LOG/ALERT/JOB_RUN/HEALTH_CHECK), `level`
(INFO/WARNING/ERROR/CRITICAL), `source_system`, `message`, `metric_name`, `metric_value`, `unit`,
`attributes` (JSONB), `occurred_at`. Index (`application_id`, `occurred_at`). Read-only evidence
for investigations.

### investigation_reports / agent_executions (Phase 4-5)
Investigation request, selected agents, structured report (JSONB), status
(PENDING → RUNNING → AWAITING_REVIEW → APPROVED/REJECTED, or FAILED), reviewer fields; per-agent
steps with tool calls, output, token counts and timings.

## Conventions

Constraint names follow a fixed naming convention (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`) so migrations are
deterministic. `alembic check` reports no drift between models and migrations.
