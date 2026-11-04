# AI incident analysis (Phase 5)

One Claude call per analysis, with structured output, guardrails and a human approval gate.
Phase 6 replaces the single call with a LangGraph supervisor and specialist agents, reusing the same
context builder, guardrails and review flow.

```
POST /api/ai/incidents/{id}/analyze
   │
   ├─ 1. Fact base      app/ai/context.py      incident, timeline, apps + dependencies, changes,
   │                                           metric series, logs/alerts/jobs, similar incidents
   │                                           -> every item has a citable id (TL-12, EV-40, CHG-2041 ...)
   ├─ 2. Claude call    app/ai/llm.py          Anthropic SDK, structured output (Pydantic schema)
   ├─ 3. Guardrails     app/ai/analysis_service.py
   ├─ 4. Persist        investigation_reports (AWAITING_REVIEW) + agent_executions + AI_ANALYSIS timeline event
   │
POST /api/ai/investigations/{id}/review     (human INCIDENT_MANAGER only)
   ├─ APPROVE -> hypotheses recorded as AI root causes (still HYPOTHESIS), recommendations as OPEN CAPA actions
   └─ REJECT  -> nothing applied
```

## Providers: Claude or a free local model

Everything downstream depends on one interface, `LlmClient.structured(system, user, output_model)`.
`AI_PROVIDER` picks the implementation ([providers.py](../backend/app/ai/providers.py)):

| | `anthropic` ([llm.py](../backend/app/ai/llm.py)) | `ollama` ([ollama.py](../backend/app/ai/ollama.py)) |
|---|---|---|
| Model | `claude-opus-5-5` (`AI_MODEL`) | `qwen3:8b` (`OLLAMA_MODEL`) |
| Cost | paid per token | free, runs on the laptop |
| Structured output | `output_format=IncidentAnalysis` | Pydantic schema (refs inlined) sent as Ollama `format` |
| Speed on this laptop (CPU only) | under a minute | a few minutes |
| Reasoning quality | strongest | weaker - guardrails matter more |

The fact base, prompt, guardrails, persistence and human review are identical for both.

### Local setup (Ollama)

```powershell
winget install Ollama.Ollama        # or the installer from ollama.com
ollama pull qwen3:8b                 # ~5 GB; qwen3:4b (~2.5 GB) is faster but weaker
```

`.env`: `AI_PROVIDER=ollama`. The Docker backend reaches the Windows host at
`OLLAMA_DOCKER_URL=http://host.docker.internal:11434`; a backend run on the host uses `OLLAMA_BASE_URL`.
Ollama silently drops the start of a prompt that exceeds its context window, so the adapter sizes
`num_ctx` from the prompt (never below `OLLAMA_NUM_CTX=8192`). `OLLAMA_THINK=false` keeps CPU runs
short; `OLLAMA_KEEP_ALIVE=30m` keeps the model and its prompt-prefix cache loaded between runs.

### Compact mode for local models (`OLLAMA_COMPACT=true`)

Measured on the demo laptop (i5-1335U, 16 GB, no GPU): the JSON-schema constraint costs nothing
(about 4.8 tokens/s with or without it); **prompt length** is what costs time. A 6.5K-token prompt
was read at about 11 tokens/s and slowed generation to about 1.3 tokens/s, giving 26 minutes per analysis.
Compact mode ([compact.py](../backend/app/ai/compact.py)) keeps the same structure and ids but:

| Section | Full | Compact |
|---|---|---|
| Metric series | every 10-minute point | first, peak, min, latest, trend, attribute changes (e.g. `pool_max` 100 -> 20) |
| Logs / alerts | every event | identical lines merged with `occurrences` |
| Timeline | all events | human investigation history only (AI entries are already listed as root causes / actions) |
| Changes, similar incidents, actions | full records | key fields, capped lists |

Measured on INC-1007:

| Run | Model | Prompt | Output | Time | Quality |
|---|---|---|---|---|---|
| Full fact base | `qwen3:8b` | 6,561 tokens (~10 min to read) | 1,249 tokens at 1.3 tok/s | 26 min | correct cause; summary repeated the question |
| Compact + new prompt rules | `qwen3:8b` | 4,799 tokens (5.1 min) | 1,432 tokens at 2.0 tok/s | 17 min | correct cause; direct answer; APPLICATION category; full sentences |
| Compact + new prompt rules | `qwen3:4b` (default) | 4,794 tokens | 1,521 tokens | 11.6 min | correct cause at 0.85; repeated an existing hypothesis it was shown |

Generation is about 70% of the time, so the output length sets the floor on a CPU; Claude takes under a minute.

Citable ids are recomputed from the compact data, so the guardrails reject any id the model did not
see. Because a local model receives the output schema only as a decoding grammar, compact mode also
appends a **field guide** (generated from the schema descriptions) and length limits to the system
prompt. It is fixed text, so Ollama reuses it between runs. The report records `context_summary.mode`
and the execution records `duration_seconds`.

### Prompt rules added after the first local run

- `summary` must answer the team's request in its first sentence ("Most likely yes - ..."), never
  repeat the question.
- Root-cause category is where the fault lies: code or configuration shipped in a release is
  APPLICATION, not INFRASTRUCTURE.
- Text fields are full sentences (the first local run returned "High" as a business-impact summary).

## Claude request

| Setting | Value | Why |
|---|---|---|
| SDK | `anthropic` 2.3.0, `client.beta.messages.parse(...)` | Official SDK; `parse` validates the answer against the Pydantic model |
| Model | `claude-opus-5-5` (`AI_MODEL`) | Current default Opus model |
| Thinking | `{"type": "adaptive"}` | Claude decides how much to reason |
| Effort | `high` (`AI_EFFORT`) | Analysis is accuracy-sensitive; Opus 5.5 defaults to `medium`, so it is set explicitly |
| Output | `output_format=IncidentAnalysis` | Structured outputs: the response always matches the schema |
| Caching | `cache_control` on the fixed system prompt | Per-incident data sits in the user turn, after the cached prefix |
| Refusal fallback | `fallbacks="default"` + beta `server-side-fallback-2026-07-01` (`AI_FALLBACKS_ENABLED`) | If a safety classifier declines, the API retries on a recommended model |
| Timeout / retries | 180 s, 2 retries (`AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`) | SDK retries 429 / 5xx / connection errors |

The API key comes only from the environment (`ANTHROPIC_API_KEY`) and is never logged. Logs record
the model, stop reason, token counts and request ID, never prompt content.

## Output contract (`app/ai/schemas.py`)

`summary`, `confirmed_facts` (each with `evidence_ids`), `root_cause_hypotheses` (confidence,
supporting / contradicting evidence, missing evidence, verification steps), `affected_services`,
`business_impact` (with assessed severity), `recommended_actions` (CORRECTIVE / PREVENTIVE, urgency,
`requires_human_approval`), `escalation`, `missing_information`, `overall_confidence`.

## Guardrails: facts stay facts, hypotheses stay hypotheses

| Rule | Enforcement |
|---|---|
| A fact must cite evidence that exists | invalid IDs stripped; a fact with no valid citation moves to `unverified_statements` |
| Hypotheses are never confirmed | every AI hypothesis is stored with `status: HYPOTHESIS`; confirmation remains the human `/api/root-causes/{id}/review` |
| Confidence is 0-1 | clamped, and the change is noted |
| No repeated hypotheses | duplicates (same wording) are removed, keeping the higher confidence |
| No invented systems | affected services must be applications in the fact base |
| Production changes need approval | rollback / deploy / restart / config / reprocess / close etc. are forced to `requires_human_approval: true` |
| Unusable answers fail clearly | refusal or truncation -> 502; no credentials, rate limit or network -> 503; the attempt is saved as FAILED |
| AI never reviews AI | review requires a human `INCIDENT_MANAGER`; `ai:` identities are rejected |

Every change the guardrails make is listed in `report.guardrail_notes`.

## Endpoints

| Method | Path | Role |
|---|---|---|
| GET | `/api/ai/status` | VIEWER - model, effort, whether credentials are configured |
| GET | `/api/ai/incidents/{id}/context` | VIEWER - the exact fact base Claude receives, plus citable IDs |
| POST | `/api/ai/incidents/{id}/analyze` | ENGINEER - body `{"focus": "optional question"}` |
| GET | `/api/ai/incidents/{id}/investigations` | VIEWER - history, newest first |
| GET | `/api/ai/investigations/{id}` | VIEWER |
| POST | `/api/ai/investigations/{id}/review` | INCIDENT_MANAGER (human) - `{decision: APPROVE/REJECT, review_notes, apply_hypotheses, apply_actions}` |

## Testing without an API key or Ollama

`tests/test_ai_analysis.py` swaps the LLM for a fake (FastAPI dependency override) that returns a
deliberately imperfect answer, then checks each guardrail, persistence, failures and the review flow.
A mocked SDK client checks the exact request shape (model, adaptive thinking, effort, structured
output, cache control, fallbacks) and the refusal, truncation and missing-credential paths. `tests/test_ollama_provider.py` mocks Ollama's
HTTP API (`httpx.MockTransport`): request shape, schema inlining, error mapping, model-pulled status,
the provider switch, and a full analysis through the local provider.
