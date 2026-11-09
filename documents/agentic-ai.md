# Multi-agent investigation (Phase 7)

A LangGraph team investigates one incident. It produces the same report as the single-call analysis
([ai-analysis.md](ai-analysis.md)), so the same guardrails and the same human review apply. The difference
is how the report is built: specialists gather evidence with their own tools, a supervisor decides
who works on the case, and a root cause agent combines their findings.

```
START → triage → supervisor ──(conditional: next planned specialist)──► change_release
                                                                      ├► dependency_impact
                                                                      └► operational_risk
        each specialist ──(next planned specialist, else)──► root_cause → human_review_gate → END
```

The graph ends at the human review gate: the investigation waits as `AWAITING_REVIEW` until an
incident manager approves or rejects it (`POST /api/ai/investigations/{id}/review`). The gate is a
database state, not an in-memory pause, so it survives restarts.

## The team

| Agent | Job | Tools (read-only) |
|---|---|---|
| Triage (always) | Symptoms, timing, severity, SLA and the signals that show them | `get_incident_details`, `get_incident_timeline`, `get_application_health` |
| Supervisor (always) | Reads triage and decides which specialists the incident needs | - |
| Change & release | Deployments and changes close to the start of impact | `get_related_changes`, `get_recent_deployments` |
| Dependency & impact | Blast radius: connected applications, their active incidents, business tier | `get_application_dependencies`, `calculate_incident_impact` |
| Operational risk | Change risk, recurrence, SLA exposure, history | `calculate_operational_risk`, `get_incident_history` |
| Root cause (always) | Ranked, cited hypotheses and recommended actions from the team's findings | `create_investigation_report` |

`GET /api/ai/agents` returns this catalogue.

### Calculations the agents can cite

- `IMPACT-<incident>`: tier + severity + 10 per connected application with an active incident within
  3 hours (max 30) + 10 if the resolution SLA is breached. Score 0-100, band LOW / MEDIUM / HIGH.
- `RISK-<incident>`: risk of a change in the 24 hours before impact (0-25) + recurrence on the same
  application over 90 days (3 per incident, max 25) + SLA position (0-15) + tier (8-30).

These are transparent heuristics for the demo, not a validated risk model. The ML phase will add
learned predictions.

## Guardrails

- Specialist findings keep only citations that exist in the fact base. A finding with no valid
  citation is dropped, and a note says so.
- The supervisor can only choose agents from the catalogue. Duplicates are removed.
- The root cause report goes through the same guardrails as the single-call analysis: citations
  are checked, uncited facts are demoted, confidence is clamped to 0-1, duplicate hypotheses are
  removed, and production changes are forced to need approval.
- Every tool is read-only, and a test checks that running all of them leaves the database unchanged.
  No agent can deploy, roll back, change configuration, close incidents, approve changes or modify
  transactions.

## Audit trail

Each node writes an `agent_executions` row when it starts and when it finishes. The row holds the
agent, its order, its status, the tools it called (with timing and result size), its output (the
finding, or the supervisor's plan and reasoning), tokens used and duration. The UI can poll
`GET /api/ai/investigations/{id}` to watch the team work.

## In the UI

- **Start:** the AI card on an incident and the AI investigation centre both offer *Single AI call* or
  *Agent team*. The agent option shows how many agent runs are left today.
- **Watch:** the investigation page shows the team as a flow (Triage → Supervisor → chosen specialists
  → Root cause → Human review), coloured by state. Specialists the supervisor skipped are listed.
  Each step shows the tools it called (with timings), its risk signal, cited findings, open questions,
  tokens and duration. The page refreshes every 5 seconds while the team works.
- **Scores:** cards for the IMPACT and RISK calculations show the score, band, components and formula.
- **Review:** below that come the usual report and the approve / reject panel.

## API

```
POST /api/ai/incidents/{id}/investigate          202 + RUNNING investigation, runs in the background
POST /api/ai/incidents/{id}/investigate?wait=true 201 + finished investigation (scripts, tests)
GET  /api/ai/agents                               the team and their tools
GET  /api/ai/status                               includes agent_daily_limit / agent_runs_left_today
```

The report adds these to the standard analysis fields: `mode: "multi_agent"`, `plan` (specialists and
the supervisor's reasoning), `agent_findings` and `calculations`.

## Cost and limits

A run makes 3-6 LLM calls (triage, supervisor, 0-3 specialists, root cause), compared with 1 for
`/analyze`. `AI_AGENT_DAILY_LIMIT` caps multi-agent runs per UTC day (10 on the hosted demo), and
they also count towards `AI_DAILY_LIMIT`. Small local models get the compact fact base and short
answer limits, as in the single-call analysis.

## PowerShell check

```powershell
$h = @{ "X-User-Name" = "a.patel"; "X-User-Role" = "ENGINEER" }
$inc = Invoke-RestMethod http://localhost:8000/api/incidents/by-reference/INC-1008 -Headers $h
$inv = Invoke-RestMethod -Method Post "http://localhost:8000/api/ai/incidents/$($inc.id)/investigate" -Headers $h
# poll until AWAITING_REVIEW, then look at each agent step
(Invoke-RestMethod "http://localhost:8000/api/ai/investigations/$($inv.id)" -Headers $h).executions |
  Select-Object step_order, agent_name, status, input_tokens, output_tokens
```
