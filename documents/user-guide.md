# BankOps AI - user guide and test flows

Use this to try every feature, in a sensible order, with ready-made test data. All data is synthetic.

## 0. Start, stop and reset

```powershell
cd D:\Study\BankOps-AI
docker compose up -d                 # PostgreSQL + backend (http://localhost:8000, Swagger at /docs)
cd frontend
npm run dev                          # UI at http://localhost:5173
```

Reset the demo data (wipes everything you created, reloads 15 incidents):

```powershell
docker compose exec backend python -m app.ingestion reset --yes
docker compose exec backend python -m app.ingestion load datasets/synthetic
```

Ollama must be running for AI analysis (tray icon). Model: `qwen3:4b`, about 5-8 minutes per analysis.

## 1. How the pieces connect

```
Browser (React UI :5173) --/api--> FastAPI (:8000) --> services (rules) --> PostgreSQL (:5445)
                                         |
                                         +--> AI: fact base -> Ollama / Claude -> guardrails -> investigation
```

| UI screen | API calls | Backend code | Tables |
|---|---|---|---|
| Dashboard | `GET /analytics/incident-summary`, `GET /incidents?active_only`, `GET /ai/investigations?status=AWAITING_REVIEW` | `analytics_service`, `incident_repository` | incidents, incident_sla, investigation_reports |
| Incidents list + New incident | `GET /incidents` (filters), `GET /applications`, `GET /reference-data`, `POST /incidents` | `incident_service.create`, `classification.derive_priority`, `sla_service` | incidents, incident_sla, incident_events |
| Incident detail - workflow | `PATCH /incidents/{id}/assign`, `PATCH /incidents/{id}/status` | `incident_service`, `lifecycle` (state machine) | incidents, incident_events, incident_sla |
| Incident detail - timeline | `GET /incidents/{id}/timeline`, `POST /incidents/{id}/events` | `timeline.record_event` | incident_events |
| Incident detail - RCA / CAPA | `GET /incidents/{id}/rca`, `POST /root-causes/{id}/review`, `PATCH /actions/{id}` | `rca_service` | incident_root_causes, incident_actions |
| Analyse with AI / AI investigations | `POST /ai/incidents/{id}/analyze` (202), `GET /ai/investigations/{id}` (polled every 5 s) | `analysis_service.start/run`, `context`, `compact`, `ollama` / `llm`, `apply_guardrails` | investigation_reports, agent_executions, operational_events (read) |
| Review panel | `POST /ai/investigations/{id}/review` | `analysis_service.review` | investigation_reports, incident_root_causes, incident_actions, incident_events |

## 2. Users and what they may do ("Acting as" at the top)

| User | Role | Can | Cannot |
|---|---|---|---|
| `risk.viewer` | VIEWER | read everything | change anything (no buttons) |
| `a.patel` | ENGINEER | create, assign, change status, add notes, start AI, update actions | close incidents, confirm root causes, approve/reject AI |
| `incident.manager` | INCIDENT_MANAGER | everything an engineer can, plus close, confirm/reject root causes, approve/reject AI | - |

The API enforces these rules; the UI only hides buttons. Try an action with the wrong user to see the API refuse it.

## 3. Test data: what each active incident is for

| Incident | App | Starts as | Good for testing | Ask the AI | Right answer (check the AI against this) |
|---|---|---|---|---|---|
| INC-1007 P1 | PAY | INVESTIGATING | P1 rules, escalation, AI | Was release 2.4.1 the cause? | Yes: CHG-2041 cut the DB pool 100 -> 20; fraud-scoring call holds connections |
| INC-1008 P2 | REC | INVESTIGATING | cross-application cause | Is this caused by another application? | Yes: Payment API HTTP 500s broke the extract (INC-1007) |
| INC-1009 P3 | CUS | ASSIGNED | downstream impact | Why are statuses stale? | Payment API timeouts; Customer Services serves cached status |
| INC-1010 P4 | CUS | OPEN | assign, low priority, full lifecycle | - | (cosmetic field-label bug, no evidence) |
| INC-1011 P2 | CBS | OPEN, unassigned | assign -> investigate -> AI -> resolve | What is causing the balance enquiry timeouts? | CHG-2043 left index IX_TXN_ACCT_DATE unusable -> full table scans at the morning peak (not CHG-2038) |
| INC-1012 P3 | PAY | ASSIGNED | AI with a red herring | Was release 2.4.1 the cause? | No: CHG-2044 removed firewall rule FW-118 to the card-scheme gateway |
| INC-1013 P3 | RDW | INVESTIGATING | chain PAY -> REC -> RDW | Why is the dashboard stale? | Upstream reconciliation feed not delivered (INC-1008), not warehouse performance |
| INC-1014 P4 | REC | OPEN | small data issue, preventive action | Why are there rounding breaks? | HALF_UP vs HALF_EVEN rounding mismatch |
| INC-1015 P3 | CUS | ON HOLD | resume from hold | Is this our problem? | External PDF vendor degraded (VND-7781) |

Resolved / closed history (INC-1001 to INC-1006) feeds the analytics and "similar incidents". INC-1003,
INC-1004 and INC-1006 also have evidence if you want to analyse past incidents.

## 4. Flows to try

### Flow A - create an incident (Incidents -> New incident), as `a.patel`

1. Application `REC`, severity `P2`, category `BATCH_PROCESSING`,
   title `Nostro reconciliation job stuck`, description `RECON_NOSTRO has been running 3 hours instead of 20 minutes`.
2. Leave team empty -> **Create incident**. You land on the new incident (next INC- number), status OPEN.
3. Check: priority was derived (P2 on a Tier 2 app = HIGH), the SLA shows 30 min response / 240 min resolution,
   and the timeline has a CREATED event.
4. Validation to try: title `abc` (too short), description shorter than 10 characters - the form or API refuses.

### Flow B - work the incident through its lifecycle

On any OPEN incident (INC-1010, INC-1011, INC-1014 or yours):

| Step | Do | What to notice |
|---|---|---|
| 1 | Assign: team `Core Banking Support`, engineer `a.patel` -> **Assign** | status OPEN -> ASSIGNED automatically; response SLA becomes MET |
| 2 | **INVESTIGATING** | only valid next steps are ever shown as buttons |
| 3 | (optional) **ESCALATED** or **ON HOLD** | escalation is a separate state; from ON HOLD you go back to ASSIGNED / INVESTIGATING |
| 4 | **RESOLVED** without a resolution summary | refused: summary is required |
| 5 | Type a summary, e.g. `Index rebuilt online; balance p95 back to 300 ms` -> **RESOLVED** | resolution SLA is MET or BREACHED |
| 6 | **CLOSED** as `a.patel` | the button is disabled: closing needs an incident manager |
| 7 | Switch to `incident.manager` -> **CLOSED** | for a P1 this is refused until a root cause is human-confirmed |
| 8 | **REOPENED** without a note -> refused; with a note -> reopen count increases | |

Every step appears on the timeline with who did it and whether it was HUMAN, AI or SYSTEM.

### Flow C - timeline notes

Add an *Investigation update*, *Evidence* or *Comment* (for example
`DB monitor: 250 full table scans per minute on ACCOUNT_TXN`). Notes are append-only audit records.

### Flow D - AI analysis (as `a.patel`)

1. Open INC-1011 -> type the question from the table above -> **Analyse with AI**.
2. You land on the investigation page: **RUNNING** with a timer; the page refreshes by itself.
3. When it is **AWAITING REVIEW**, read the report:
   - *Summary* answers your question in the first sentence.
   - *Hypotheses* are ranked with confidence; the evidence ids (EV-.., MS-.., CHG-..) point to real data.
   - *Confirmed facts* only contain cited statements; uncited claims are listed as removed.
   - *Recommended actions* that change production are tagged *needs approval*.
   - *Guardrails* lists anything the system corrected.
4. Compare the top hypothesis with the "Right answer" column. A small local model is right most of the time, but
   not always - that is the point of the next flow.
5. Only one analysis can run per incident; starting a second one is refused.
6. To see exactly what the model was given: `http://localhost:8000/api/ai/incidents/<id>/context`.

### Flow E - human review

1. As `a.patel`, press **Approve** -> refused ("requires role INCIDENT_MANAGER").
2. Switch to `incident.manager`, write notes (what you checked), then:
   - **Approve** if the top hypothesis matches the evidence -> its hypotheses and actions are added to the
     incident, still *unconfirmed*.
   - **Reject** if it is wrong (for example it blames CHG-2041 on INC-1012) -> nothing is added.
3. The investigation shows who reviewed it, when, and the notes.

### Flow F - confirm the root cause and finish CAPA

1. On the incident, *Root cause analysis* shows AI-sourced hypotheses. As `incident.manager`, **Confirm** the right
   one and **Reject** the others.
2. *CAPA*: **Start** and **Complete** actions; overdue actions are flagged.
3. Now a P1 can be closed (Flow B step 7).

### Flow G - dashboard, analytics and API

- Dashboard: KPI tiles, active incidents, AI awaiting review.
- Swagger, http://localhost:8000/docs: every endpoint, including analytics (`/api/analytics/mttr`,
  `/sla-compliance`, `/repeated-incidents`) and evidence (`/api/incidents/{id}/evidence`).

## 5. Suggested demo script (about 15 minutes plus AI time)

1. Dashboard -> explain the 5 applications and the open P1.
2. Create an incident (Flow A), assign and investigate it (Flow B 1-2).
3. Start AI on INC-1012 (the red-herring case) and, while it runs, show INC-1011's timeline and SLA.
4. Review INC-1012's analysis: if it blames release 2.4.1, **Reject** with the note "firewall rule FW-118 removed by
   CHG-2044"; if it finds CHG-2044, **Approve**.
5. Try approving as the engineer to show the role check.
6. Confirm the root cause and complete a CAPA action (Flow F).
