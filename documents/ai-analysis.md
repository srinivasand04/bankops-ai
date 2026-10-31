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
`OLLAMA_NUM_CTX=16384` is required: Ollama's default context window is smaller than the fact base,
and an undersized window truncates the prompt silently. `OLLAMA_THINK=false` keeps CPU runs short.

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
