"""Hosted open-model provider via Groq (free tier, fast) - used for the public web demo.

Groq exposes an OpenAI-compatible chat API. Structured output uses `response_format` json_schema
in strict mode (constrained decoding), which requires every property in `required` and
`additionalProperties: false` on every object; the schema is adapted below. The free tier allows
about 8K tokens per minute, so this provider uses the compact fact base and low reasoning effort.
"""

import copy
import json
import logging
import time
from collections.abc import Callable

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.llm import LlmResult, T
from app.core.config import Settings
from app.core.exceptions import AiResponseError, AiUnavailableError

logger = logging.getLogger(__name__)


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema adjusted to Groq strict-mode rules."""
    schema = copy.deepcopy(model.model_json_schema())

    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            node.pop("default", None)
            for value in node.values():
                fix(value)
        elif isinstance(node, list):
            for value in node:
                fix(value)

    fix(schema)
    return schema


MAX_RETRY_WAIT_SECONDS = 30


class GroqLlm:
    def __init__(self, settings: Settings, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.sleep = sleep  # injectable so tests do not wait
        # ~8K tokens/minute on the free tier: send the compact fact base (see app/ai/compact.py)
        self.prefers_compact_context = True
        self.client = client or httpx.Client(
            base_url=settings.groq_base_url,
            timeout=settings.groq_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.groq_api_key or ''}"},
        )

    def structured(self, *, system: str, user: str, output_model: type[T]) -> LlmResult[T]:
        s = self.settings
        if not s.groq_api_key:
            raise AiUnavailableError("Groq is not configured (set GROQ_API_KEY)")
        payload = {
            "model": s.groq_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": output_model.__name__, "strict": True, "schema": strict_schema(output_model)},
            },
            "reasoning_effort": s.groq_reasoning_effort,
            "include_reasoning": False,
            "max_completion_tokens": s.groq_max_tokens,
            "temperature": 0,
        }
        response = self._post(payload)

        if response.status_code in (401, 403):
            raise AiUnavailableError("Groq API key is missing or invalid (GROQ_API_KEY)")
        if response.status_code == 429:  # still limited after the retries in _post
            wait = response.headers.get("retry-after")
            raise AiUnavailableError(
                "Groq free-tier rate limit reached" + (f" - retry in about {wait} s" if wait else " - try again shortly")
            )
        if response.status_code == 413:
            raise AiResponseError("Prompt too large for the Groq free tier (tokens per minute)")
        if response.status_code >= 400:
            raise AiResponseError(f"Groq error {response.status_code}: {response.text[:300]}")

        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage") or {}
        logger.info(
            "Groq call model=%s finish=%s prompt_tokens=%s completion_tokens=%s",
            body.get("model"), choice.get("finish_reason"), usage.get("prompt_tokens"), usage.get("completion_tokens"),
        )
        if choice.get("finish_reason") == "length":
            raise AiResponseError("Groq's answer was truncated (raise GROQ_MAX_TOKENS)")
        content = (choice.get("message") or {}).get("content") or ""
        try:
            parsed = output_model.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AiResponseError("Groq returned output that does not match the analysis schema") from exc
        return LlmResult(
            parsed=parsed,
            model=f"groq/{body.get('model', s.groq_model)}",
            stop_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            request_id=response.headers.get("x-request-id"),
        )


    def _post(self, payload: dict) -> httpx.Response:
        """POST, waiting out short free-tier rate limits (429 + retry-after) instead of failing.

        Multi-agent investigations make several calls within seconds, which trips the tokens-per-minute
        limit; Groq says how long to wait, usually a few seconds.
        """
        retries = self.settings.groq_rate_limit_retries
        for attempt in range(retries + 1):
            try:
                response = self.client.post("/chat/completions", json=payload)
            except httpx.TimeoutException as exc:
                raise AiUnavailableError("Groq did not answer in time - try again") from exc
            except httpx.TransportError as exc:
                raise AiUnavailableError("Could not reach the Groq API") from exc
            if response.status_code != 429 or attempt == retries:
                return response
            try:
                wait = float(response.headers.get("retry-after", "2"))
            except ValueError:
                wait = 2.0
            if wait > MAX_RETRY_WAIT_SECONDS:
                return response  # a long (e.g. daily) limit: report it rather than block the request
            logger.info("Groq rate limited - waiting %.1f s (retry %s of %s)", wait, attempt + 1, retries)
            self.sleep(wait + 0.5)
        return response
