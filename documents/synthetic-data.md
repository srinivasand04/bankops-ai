# Large synthetic dataset (`SYNTHETIC_LARGE`)

Twelve months of banking IT history with **designed signal**, so the ML module has patterns to learn.
The small demo dataset (`datasets/synthetic`, main scenario CHG-2041 -> INC-1007) is unchanged.

```powershell
cd D:\Study\BankOps-AI\backend
.\.venv\Scripts\python.exe scripts\generate_synthetic.py --seed 42 --months 12 --scale 1.0 --end 2026-11-05
.\.venv\Scripts\python.exe -m app.ingestion validate datasets/synthetic_large
.\.venv\Scripts\python.exe -m app.ingestion load datasets/synthetic_large    # after the demo dataset
```

The folder is git-ignored (about 31 MB); the same arguments always regenerate identical files.

| Item | Default (seed 42, 12 months, scale 1.0) |
|---|---|
| Applications | 12 (5 demo + 7 new); dependency graph of 22 edges |
| Changes | 648 |
| Incidents | 4,000 (about 10 still open at `end`) |
| Operational events | 125,046 (about 114K metrics, 3.6K job runs, about 7K alerts/logs, 648 deployment logs) |
| Files | 31.5 MB of JSON; about 58 MB in PostgreSQL |
| Generate / validate / load | 7 s / 33 s / 29 s on the demo laptop |

The code is in `backend/app/synthetic/`: `catalog.py` (applications, dependencies, teams, recurring problems),
`vocabulary.py` (wording) and `generator.py` (rules; every number below is a named constant there).

## Applications

| Code | Name | Tier | Primary metric |
|---|---|---|---|
| PAY | Payment Processing | 1 | http_5xx_rate_pct (+ p95_latency_ms) |
| CBS | Core Banking | 1 | db_cpu_pct (+ ledger_posting_latency_ms) |
| CUS | Customer Services | 2 | api_error_rate_pct |
| REC | Transaction Reconciliation | 2 | unmatched_items |
| RDW | Reporting & Data Warehouse | 3 | dw_cpu_pct |
| CARDS | Cards Authorisation | 1 | auth_decline_rate_pct (+ auth_latency_ms) |
| OLB | Online Banking | 1 | login_success_rate_pct (drops when broken) |
| MOB | Mobile Banking | 1 | app_crash_rate_pct (+ gateway_latency_ms) |
| AML | AML Screening | 1 | screening_queue_depth |
| TRS | Treasury | 2 | market_data_lag_s |
| GL | General Ledger | 2 | gl_posting_backlog |
| BATCH | Batch Scheduler | 2 | jobs_failed_per_hour |

The manifest sets `reuse_applications: true`, so when the demo dataset is already loaded, its five
applications are referenced (not taken over) and its dependency edges are not duplicated.

## Signal rules

### Changes -> incidents (label `change_caused_incident`)

P(change causes an incident within 10 min - 6 h) = sigmoid(logit), with
`logit = -3.4 + 1.2·Friday + 1.0·outside window + 0.05·components (cap 40) + 0.7·Tier 1 + 0.8·Emergency - 0.6·Standard`.

- Change window: Mon-Thu 18:00-23:00 and Sat 08:00-14:00. 72% of changes respect it; 40% of the rest land on a Friday.
- Scope: `components_changed` = 1 + log-normal(1.0, 0.8), at most 60 (new column, migration 0003).
- The recorded `risk_level` is the true risk plus noise (people rate risk imperfectly).
- 35% of changes that caused an incident are recorded as ROLLED_BACK.
- **Label** = the change has a CONFIRMED link to an incident.
  **Noise**: 5% of caused incidents have no link recorded; 3% of incidents near a harmless change get a false
  CONFIRMED link; 30% of incidents near a harmless change get a RULED_OUT link.
- Measured: Friday changes 38.9% vs other days 7.6%; risky (Friday or out of window) 24.6% vs safe 6.0%.

### Severity

`score = tier (T1 +1.0, T2 +0.3, T3 -0.6) + category (infra/network/security +0.5, database +0.4, ...)
+ 0.8·change on the app in the last 24 h + 0.3·business hours + Normal(0, 0.8)`;
thresholds 2.75 / 1.75 / 0.45 give about 5% P1, 19% P2, 47% P3, 29% P4. Priority is derived by the loader.

### Response and resolution (MTTR)

- Detection: log-normal, median 6 min (x1.5 at night). Acknowledgement: response target x log-normal(median 0.45, sigma 0.75),
  x1.6 at night.
- Resolution time (from impact start) = resolution target x log-normal(median ratio P1 0.9 / P2 0.6 / P3 0.45 / P4 0.35,
  sigma 0.6) x1.35 infrastructure/network x1.3 night (22:00-06:00) x1.6 escalated.
  MTTR is therefore "longer for P1" *relative to its target*, so P1s breach most often.
- Escalation rate P1 35%, P2 15%, P3 5%, P4 1%; 3% of incidents are reopened; closure 0.5-3 days after resolution.
- SLA targets are the demonstration targets in `DEFAULT_SLA_TARGETS` (the same ones `sla_service` uses), so breach labels
  come from the real SLA engine at load time. Measured breach rate: P1 51%, P2 29%, P3 15%, P4 7%.

### Text (category / team routing, similarity, clustering)

- Each category has its own title and symptom templates filled with entities (ORA- codes, hosts, tables, jobs, partners).
- 12% of incidents use wording from a *confusable* category (for example DATABASE <-> PERFORMANCE).
- 5% of incidents have a wrong recorded category (label noise).
- Team routing: the owning team, but 55% of NETWORK / INFRASTRUCTURE / SECURITY / DATABASE incidents go to the specialist team.

### Recurring problems (clustering ground truth)

Twelve problems (PRB-001 ... PRB-012), each repeating 14-28 times a year on one application with the same wording.
75% of closed recurring and change-caused incidents carry a CONFIRMED root cause starting with the problem key
(for example `PRB-007: Undo retention too short ...`), so clusters can be compared with known causes.

### Metrics and anomalies (time series)

- Hourly primary metric per application; 4-hourly second metric for PAY, CBS, CARDS and MOB.
- `value = baseline x (1 + 0.35·sin(2π(hour-7)/24)) x 0.75 at weekends x (1 + 0.15·elapsed/total) + Normal(0, 5% of baseline)`.
- Anomalies: P1/P2 incidents (and half of the P3s) multiply the metric by 2.5-6 (OLB login success: x0.6-0.85) from
  **1-3 hours before** the incident starts until it is resolved. Anomalous points are logged at ERROR level.
- Daily job runs for batch applications; a BATCH_PROCESSING incident that day turns the run into `NOTOK`.

### Missing data

15% of incidents have no business impact, 20% no assigned engineer, 15% no alert or log evidence;
10% of changes have no implementer or approver.

## Tests

`backend/tests/test_synthetic_generator.py` checks determinism (same seed gives byte-identical files), validity through the real
reader and lifecycle replay (standalone and next to the demo dataset), and the signal: risky changes cause over 2x as many
incidents, caused incidents start within 6 h, Tier 1 has more P1/P2, MTTR ratios for P1 and infrastructure, recurring problems
repeat, anomalies precede more than 80% of P1/P2 incidents, and noise and missing fields are present.

## Limitations

The patterns were designed, so every model trained on this data will find them; scores are optimistic compared
with real operations data. The small sizes of rare classes (P1 on Tier 3 apps, for example) are realistic but make some
per-class metrics noisy.
