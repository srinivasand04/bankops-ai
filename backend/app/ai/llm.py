"""Thin wrapper around the Anthropic SDK for one structured Claude call.

The rest of the application depends on the `LlmClient` protocol, not on the SDK, so tests (and
Phase 6 agents) can swap in a fake without network access.
"""

import logging
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.exceptions import AiResponseError, AiUnavailableError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class LlmResult[T]:
    parsed: T
    model: str
    stop_reason: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    request_id: str | None = None


class LlmClient(Protocol):
    def structured(self, *, system: str, user: str, output_model: type[T]) -> LlmResult[T]: ...


class AnthropicLlm:
    def __init__(self, settings: Settings):
        self.settings = settings
        # api_key=None lets the SDK resolve other credential sources (auth token, CLI profile)
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key or None,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    def structured(self, *, system: str, user: str, output_model: type[T]) -> LlmResult[T]:
        s = self.settings
        extra = {"fallbacks": "default", "betas": [FALLBACK_BETA]} if s.ai_fallbacks_enabled else {}
        try:
            response = self.client.beta.messages.parse(
                model=s.ai_model,
                max_tokens=s.ai_max_tokens,
                # Stable system prompt first and cached; per-incident data goes in the user turn.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={"effort": s.ai_effort},
                output_format=output_model,
                **extra,
            )
        except anthropic.AuthenticationError as exc:
            raise AiUnavailableError("Claude API credentials are missing or invalid (set ANTHROPIC_API_KEY)") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AiUnavailableError("Claude API key lacks permission for this model") from exc
        except anthropic.RateLimitError as exc:
            raise AiUnavailableError("Claude API rate limit reached - retry shortly") from exc
        except anthropic.BadRequestError as exc:
            raise AiResponseError(f"Claude API rejected the request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise AiUnavailableError(f"Claude API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise AiUnavailableError("Could not reach the Claude API (network or timeout)") from exc
        except ValidationError as exc:
            raise AiResponseError("Claude returned output that does not match the analysis schema") from exc
        except TypeError as exc:
            # The SDK raises TypeError at request time when no credential source resolves at all
            if "authentication method" not in str(exc):
                raise
            raise AiUnavailableError("Claude API is not configured (set ANTHROPIC_API_KEY in .env)") from exc

        usage = response.usage
        logger.info(
            "Claude call model=%s stop=%s in=%s out=%s cache_read=%s request_id=%s",
            response.model, response.stop_reason, usage.input_tokens, usage.output_tokens,
            usage.cache_read_input_tokens, response._request_id,
        )
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise AiResponseError("Claude declined to analyse this request", details={"category": category})
        if response.stop_reason == "max_tokens":
            raise AiResponseError("Claude's answer was truncated (max_tokens reached)")
        if response.parsed_output is None:
            raise AiResponseError("Claude returned no structured output")
        return LlmResult(
            parsed=response.parsed_output,
            model=response.model,
            stop_reason=response.stop_reason,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            request_id=response._request_id,
        )
