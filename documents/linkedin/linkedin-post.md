# LinkedIn post: BankOps AI

## Attachments (in this order)

| # | File | What it shows |
|---|---|---|
| 1 | `bankops-ai-architecture.gif` | The whole architecture: introduces the project |
| 2 | `3-dashboard-ai-guardrails.gif` | The real product: dashboard, MTTR / SLA KPIs, the AI investigation queue, the guardrails and the approval gate |
| 3 | `4-ai-root-cause-analysis.gif` | GenAI root cause: ranked hypotheses with confidence, cited evidence (EV- IDs), recommended actions, human approval |
| 4 | `2-incident-correlation.gif` | Banking use case: P1 payment outage linked to release CHG-2041 (30 min earlier) plus the blast radius on Reconciliation, Customer Services and Core Banking |

Each GIF also has an `.mp4` with the same name: sharper and smaller if you post a video instead.

LinkedIn shows several attached images as a grid, so the post text below tells the story in the same order.

---

🏦 A payment API starts failing 30 minutes after a release. Reconciliation breaks. Customers see delayed transactions. The clock on a P1 SLA is ticking.

In banking production support, the hard part is rarely fixing the bug. It's answering what changed, what's affected, and what's the root cause fast enough, with evidence an auditor would accept.

So I built BankOps AI, an open-source IT incident intelligence and operational risk platform for banking. 👇

🔹 Incident core: lifecycle state machine, priority from severity × business tier, and a full audit timeline
🔹 SLA & metrics: MTTA, MTTR, SLA breach tracking, repeat-incident detection, trends
🔹 RCA & CAPA: root-cause hypotheses that a human confirms or rejects, plus corrective and preventive actions
🔹 Change & release risk: correlates incidents with recent deployments and dependent applications
🔹 GenAI analysis: Claude, Groq (gpt-oss-120b) or a local Ollama model behind one provider interface, with structured JSON output
🔹 Guardrails: every AI claim must cite evidence (INC-, CHG-, metric and log IDs) or it gets demoted. Confidence is clamped. Production changes always need human approval.

🛡️ The rule I designed around: AI suggests, humans decide. The AI can never deploy, roll back, change config, close a critical incident or approve a change.

How it helps production support teams:
✅ Less time digging through logs, changes and metrics by hand
✅ RCA drafts backed by evidence, not guesses
✅ SLA breaches flagged before they happen
✅ Repeat incidents surfaced, so problems get fixed once
✅ A complete audit trail for risk and compliance reviews

🎬 In the attachments:
1️⃣ The architecture, end to end
2️⃣ The live dashboard, the AI review queue and its guardrails
3️⃣ AI root-cause analysis with confidence scores and cited evidence
4️⃣ Correlation: one P1 linked to the release behind it and to every downstream service it broke

📊 Under the hood: 12 banking applications, 4,000 incidents, 648 changes and 125K operational events, all synthetic. A seeded generator builds them, they pass 3-layer validation, and they bulk-load into PostgreSQL 17 + pgvector. 161 automated tests.

🧠 What's next:
• ML lab: logistic regression, random forests, gradient boosting, SVM, KNN, K-Means, Naive Bayes and time-series forecasting, trained on time-based splits with no data leakage
• Agentic AI: a LangGraph supervisor with 5 specialist agents, tool calling and a human review step

⚙️ Stack: Python · FastAPI · SQLAlchemy · Alembic · PostgreSQL · React · TypeScript · Tailwind · Docker. Deployed for free on Vercel + Render + Neon + Groq.

🔗 Live demo: https://bankops-ai-murex.vercel.app
💻 Code: https://github.com/srinivasand04/bankops-ai

I'm open to AI Engineer / ML Engineer roles, especially in banking and fintech. If you work on AIOps, SRE or operational risk, I'd love your feedback. 🙌

#AIEngineer #MLEngineer #GenerativeAI #AgenticAI #LLM #LangGraph #Claude #MachineLearning #RAG #AIOps #SRE #ProductionSupport #IncidentManagement #RootCauseAnalysis #MTTR #OperationalRisk #BankingTechnology #FinTech #Python #FastAPI #React #PostgreSQL #MLOps #OpenToWork

---

## Shorter version (if you want less text)

🏦 Banking production incidents aren't hard because of the fix. They're hard because of the finding: what changed, what's affected, and why.

I built BankOps AI, an incident intelligence platform for banking IT:
🔹 Incident lifecycle, SLA tracking, MTTA / MTTR
🔹 Evidence-cited AI root-cause analysis (Claude / Groq / Ollama)
🔹 Change-risk correlation, RCA & CAPA
🔹 Guardrails: AI suggests, humans decide
🔹 Next: ML lab (random forest, gradient boosting, K-Means, forecasting) + LangGraph agents

12 apps · 4,000 incidents · 125K events · 161 tests

🔗 https://bankops-ai-murex.vercel.app

#AIEngineer #MLEngineer #GenerativeAI #AgenticAI #AIOps #IncidentManagement #MTTR #OperationalRisk #FinTech #Python #OpenToWork
