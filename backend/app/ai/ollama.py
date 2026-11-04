"""Local open-model provider via Ollama (free, runs on the laptop).

Implements the same `LlmClient.structured()` contract as AnthropicLlm: the Pydantic output model is
sent as a JSON schema in Ollama's `format` field (constrained decoding), and the answer is validated
with the same model. Context building, guardrails and human review are unchanged.
"""

import copy
import json
import logging

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.llm import LlmResult, T
from app.core.config import Settings
from app.core.exceptions import AiResponseError, AiUnavailableError

logger = logging.getLogger(__name__)

JSON_INSTRUCTION = (
    "\n\nRespond with a single JSON object that matches the required schema exactly. "
    "Do not add any text outside the JSON."
)


def inline_schema(model: type[BaseModel]) -> dict:
    """Pydantic emits $defs/$ref; inline them so any schema-to-grammar converter handles the schema."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


CHARS_PER_TOKEN = 3.5  # conservative estimate for JSON-heavy English text
OUTPUT_RESERVE = 2048  # room for the answer
MAX_CONTEXT = 32768


def context_window(prompt: str, configured: int) -> int:
    """Ollama silently drops the start of a prompt that exceeds num_ctx - size it to fit, never below
    the configured value (a smaller window is faster on CPU)."""
    needed = int(len(prompt) / CHARS_PER_TOKEN) + OUTPUT_RESERVE
    return min(MAX_CONTEXT, max(configured, -(-needed // 1024) * 1024))


class OllamaLlm:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        # Read by analysis_service: send a compact fact base plus a field guide (see app/ai/compact.py)
        self.prefers_compact_context = settings.ollama_compact
        self.client = client or httpx.Client(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds)

    def structured(self, *, system: str, user: str, output_model: type[T]) -> LlmResult[T]:
        s = self.settings
        payload = {
            "model": s.ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + JSON_INSTRUCTION},
            ],
            "format": inline_schema(output_model),
            "stream": False,
            "think": s.ollama_think,
            # Keep the model (and its prompt-prefix cache) in memory between demo runs
            "keep_alive": s.ollama_keep_alive,
            "options": {"num_ctx": context_window(system + user, s.ollama_num_ctx), "temperature": 0},
        }
        try:
            response = self.client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise AiUnavailableError(
                f"Ollama did not answer within {s.ollama_timeout_seconds:.0f}s (local CPU inference is slow; "
                "raise OLLAMA_TIMEOUT_SECONDS or use a smaller model)"
            ) from exc
        except httpx.TransportError as exc:
            raise AiUnavailableError(f"Ollama is not reachable at {s.ollama_base_url} - is it running?") from exc

        if response.status_code == 404:
            raise AiUnavailableError(f"Ollama model '{s.ollama_model}' is not installed - run: ollama pull {s.ollama_model}")
        if response.status_code >= 400:
            raise AiResponseError(f"Ollama error {response.status_code}: {response.text[:300]}")

        body = response.json()
        logger.info(
            "Ollama call model=%s done_reason=%s prompt_tokens=%s output_tokens=%s duration_s=%.1f",
            body.get("model"), body.get("done_reason"), body.get("prompt_eval_count"), body.get("eval_count"),
            (body.get("total_duration") or 0) / 1e9,
        )
        if body.get("done_reason") == "length":
            raise AiResponseError("Ollama's answer was truncated (context or output limit reached - raise OLLAMA_NUM_CTX)")
        content = (body.get("message") or {}).get("content") or ""
        try:
            parsed = output_model.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AiResponseError("Local model returned output that does not match the analysis schema") from exc

        return LlmResult(
            parsed=parsed,
            model=f"ollama/{body.get('model', s.ollama_model)}",
            stop_reason=body.get("done_reason"),
            input_tokens=body.get("prompt_eval_count"),
            output_tokens=body.get("eval_count"),
        )

    def status(self) -> tuple[bool, str]:
        """(ready, detail) - whether Ollama is up and the configured model is pulled."""
        try:
            tags = self.client.get("/api/tags", timeout=3).json()
        except (httpx.HTTPError, ValueError):
            return False, f"Ollama is not reachable at {self.settings.ollama_base_url}"
        names = {m.get("name") for m in tags.get("models", [])}
        wanted = self.settings.ollama_model
        if wanted in names or f"{wanted}:latest" in names:
            return True, f"Model {wanted} is installed"
        return False, f"Ollama is running but '{wanted}' is not pulled - run: ollama pull {wanted}"
