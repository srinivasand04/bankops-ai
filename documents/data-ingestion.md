# Data ingestion pipeline (Phase 4)

All data enters BankOps AI through one path, whatever its source:

```
 source data ──► adapter ──► standard JSON dataset ──► validate ──► load (one transaction) ──► PostgreSQL
 (synthetic,     (Phase 8     backend/datasets/<name>/   schema +     lifecycle replayed,
  BPI 2014,       for BPI)                               references   rows tagged data_source
  live feeds)
```

The API, analytics and (later) the AI agents never know where a record came from. Adding a source
means writing an adapter that produces the standard dataset; nothing else changes.

## Dataset format

A folder with `manifest.json` and one JSON list per record type. Schemas live in
[backend/app/ingestion/schemas.py](../backend/app/ingestion/schemas.py); unknown fields are rejected.

| File | Records | Notes |
|---|---|---|
| `manifest.json` | name, `data_source`, description, license, citation | `data_source` tags every row (e.g. `SYNTHETIC`, `BPI2014`) |
| `applications.json` | code, name, criticality, owner, health | upserted by `code` |
| `dependencies.json` | application → depends_on | |
| `changes.json` | change reference, application, type, risk, version, deployed_at | upserted by `change_reference` |
| `incidents.json` | incident + `history` steps, change links, root causes, CAPA actions, RCA | history replayed through the state machine |
| `operational_events.json` | metrics, logs, alerts, job runs, health checks | evidence for investigations |

Times are absolute ISO-8601 or relative (`{"minutes_ago": 65}`, `{"minutes_from_now": 1440}`) so the
demo data always looks current. History steps use `after_minutes` from the incident's creation:

```json
{"type": "assign", "after_minutes": 6, "team": "Payments Production Support", "engineer": "a.patel"}
{"type": "status", "after_minutes": 8, "status": "INVESTIGATING", "note": "Bridge call opened"}
{"type": "event",  "after_minutes": 12, "event_type": "EVIDENCE_ADDED", "description": "...", "actor": "a.patel"}
```

## Validation, in three layers

1. **Schema**: Pydantic types and enums, with every error reported by file, index and field.
2. **References**: application codes and change references must exist in the dataset; no duplicates.
3. **Lifecycle replay**: `validate` performs a full load inside a transaction that is rolled back,
   so an impossible history (e.g. OPEN → CLOSED) is caught before anything is written.

## Loading rules

- Each source is loaded once (`load` skips an existing source); `--replace` reloads it.
- Replace deletes that source's incidents and evidence only. Records from other sources stay,
  for example incidents created through the API (`MANUAL`).
- A code or change reference owned by another source is a conflict and aborts the load.
- Dataset references (e.g. `INC-1007`) are kept; the reference sequence is moved past them so
  API-created incidents continue at the next number.
- Records loaded from datasets are always `source = HUMAN`: datasets never inject AI output.

## Commands (from `backend/`, or `docker compose exec backend ...`)

```powershell
python -m app.ingestion validate datasets/synthetic
python -m app.ingestion load datasets/synthetic
python -m app.ingestion load datasets/synthetic --replace
python -m app.ingestion sources
python -m app.ingestion reset --yes      # development only: wipes every table
```

## Synthetic evidence (149 events, one scenario per application)

| Incident | Application | Cause in the evidence | Also included so the AI can rule things out |
|---|---|---|---|
| INC-1007 (P1) / INC-1008 / INC-1009 | PAY, then REC and CUS downstream | release 2.4.1 cut the DB pool from 100 to 20; fraud-scoring call holds connections | healthy Core Banking CPU and ledger latency |
| INC-1003 (P2) | CBS | CHG-2030 lowered the Oracle listener process limit (300 -> 150); ORA-12519 errors after failover | flat DB CPU; payment retries as the downstream symptom |
| INC-1004 (P2) | CUS | identity-provider key rotation; the SSO library from CHG-2035 caches keys for 24 h, so new tokens fail | healthy Payment and Core Banking metrics |
| INC-1006 (P3) | RDW | ETL_AGG_DAILY overlaps the liquidity report window; warehouse CPU at 95% | Core Banking healthy, reconciliation feed delivered on time; INC-1005 is the same pattern |

Each scenario has metrics, logs, alerts or job runs in the incident's time window, plus at least one
nearby change that is not the cause (for example CHG-2038 OS patching).
