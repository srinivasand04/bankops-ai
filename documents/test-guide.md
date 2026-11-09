# Test guide: every feature, in one pass

About 45 minutes. Each step says what to do and what you should see. Run the local setup once, then
work down the list.

## 0. Start everything (PowerShell)

```powershell
cd D:\Study\BankOps-AI
docker compose up -d --build          # database + backend (rebuilds with the ML libraries the first time)
cd frontend
npm run dev                           # leave this window open
```

Open http://localhost:5173. The large dataset, the BPI subset and the trained models are already in
your local database. To rebuild them from scratch, run the three commands below from `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.ingestion load datasets\synthetic_large
.\.venv\Scripts\python.exe scripts\bpi2014_to_dataset.py; .\.venv\Scripts\python.exe -m app.ingestion load datasets\bpi2014
.\.venv\Scripts\python.exe -m app.ml train-all
```

Automated checks (optional, about 4 minutes):

```powershell
cd D:\Study\BankOps-AI\backend
.\.venv\Scripts\python.exe -m pytest -q          # expect: 211 passed
.\.venv\Scripts\python.exe scripts\smoke_test.py  # expect: every line PASS
```

## 1. Language (EN / FR)

| Do | Expect |
|---|---|
| Click **FR** at the top right | Every menu, heading, button, status ("En investigation"), date ("9 nov. 2026") switches to French |
| Reload the page | Still French (remembered) |
| Click **EN** | Back to English |

## 2. Users and roles

| Do | Expect |
|---|---|
| Look at **Acting as** | *Srinivasan Dhakshanamoorthy - Administrator* is selected; the others show as Engineer, Incident manager, Viewer |
| Menu **Users** → add *Julie Martin*, user name `j.martin`, role Engineer | She appears in the table and in the Acting-as list straight away |
| Change Julie's role to Incident manager | Saved; the picker shows her new role |
| Change **your own** role to Viewer | Refused: "You cannot remove your own administrator access" |
| Act as Julie → open **Users** | Read-only: no add form, no role selectors |
| Act as Srinivasan → **Deactivate** Julie | Status Inactive; she disappears from the picker |
| Act as **Viewer** → open any incident | Workflow card says viewers cannot change incidents |

## 3. Incidents and correlation

| Do | Expect |
|---|---|
| **Incidents** → filter PAY, P1, All incidents → open **INC-1007** | Detail page with Description, Change correlation & impact, RCA, CAPA, Timeline, Workflow, SLA, ML insights, AI analysis |
| Read **Change correlation & impact** | CHG-2041 deployed 30 min before impact; REC, CUS and CBS incidents within minutes |
| **New incident** → create a P2 on Payment Processing | New INC number; Workflow offers Assign; ML insights fills in within seconds |

## 4. ML insights and ML Lab

| Do | Expect |
|---|---|
| On INC-1008, read **ML insights** | SLA-breach risk (%), predicted resolution time, suggested category and team, pattern, 5 similar past incidents (same RECON batch job), each with an ML-PRED id |
| Menu **ML Lab** → **SLA breach** | 4 algorithms side by side (logistic regression, random forest, XGBoost, LightGBM), drivers, confusion matrix, calibration |
| Tab **Change risk** | Bias-vs-variance chart (train rises to ~1, test peaks at depth 3-4), readable tree rules |
| Tabs **Resolution time**, **Routing**, **Patterns**, **Volume forecast**, **Anomalies** | Each shows its comparison table and chart (residuals, confusion matrix and top words, elbow + silhouette and clusters, forecast per application, flagged metric hours) |
| Tab **Scored changes** | Latest changes with incident risk % and reasons (e.g. CHG-2041 HIGH: outside the change window, Tier 1, earlier failures) |
| As Incident manager press **Train all models** | Tabs show "…" while training (~1 min); the "used" model per task may stay the same |

## 5. AI analysis and the agent team

Locally the AI is qwen3:4b (slow: 10-20 minutes for an agent run). For speed, test on the live site
(Groq: about 25 seconds), or set `AI_PROVIDER=groq` and `GROQ_API_KEY` in `.env`.

| Do | Expect |
|---|---|
| On an incident, choose **Agent team** → **Run agent team** | Investigation page: flow Triage → Supervisor → chosen specialists → Root cause → Human review, each step with tools, findings, tokens and time |
| When finished, read the report | Hypotheses with confidence, cited facts (EV-, CHG-, ML-PRED- ids), recommended actions with "needs approval" on production changes, Guardrails card |
| Act as Engineer → try Approve | Refused - only an incident manager approves |
| Act as Incident manager → **Approve** | Hypotheses and CAPA actions are added to the incident, still unconfirmed |

## 6. Reports

| Do | Expect |
|---|---|
| Menu **Reports** (Management report tab) | Scorecard with RAG for all applications, SLA performance, trends, change risk, problem management on one page |
| Switch period to 365 days | All numbers recalculate |
| Tab **SLA performance** → **Download CSV** | A CSV of incidents breaching now opens in Excel |
| **Print / save as PDF** | Clean landscape document without menus (sample: [management-report-sample.pdf](management-report-sample.pdf)) |

## 7. Real data (BPI 2014)

| Do | Expect |
|---|---|
| **Incidents** → application filter → a `BPI-W000…` component, All incidents | 300 real Rabobank incidents from March 2014 in total (e.g. "Software incident on Desktop Application DTA000056") |
| Open one | Timeline shows the real assignment and reassignment history ("BPI activity: Reassignment (TEAM0004)") |

## 8. Architecture

| Do | Expect |
|---|---|
| Menu **Architecture** | The one-page architecture, including the agentic AI and free deployment sections |

## Things that are expected (not bugs)

- **Slow local AI:** qwen3:4b runs on the CPU. Use Groq for speed.
- **Reports and BPI:** reports cover the chosen period, and BPI incidents are from 2014, so they appear in the
  incident list but not in "last 90 days" reports.
- **Green applications:** an application with no incidents in the period shows Green in the scorecard.
- **Synthetic scores:** ML scores come from synthetic data with designed signal; real-world scores would be lower.
