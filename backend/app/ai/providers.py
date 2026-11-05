"""Choose the LLM provider from settings (AI_PROVIDER). Everything downstream depends only on LlmClient."""

from functools import lru_cache

import anthropic

from app.ai.groq import GroqLlm
from app.ai.llm import AnthropicLlm, LlmClient
from app.ai.ollama import OllamaLlm
from app.core.config import get_settings
from app.core.exceptions import AiUnavailableError


@lru_cache
def _anthropic() -> AnthropicLlm:
    return AnthropicLlm(get_settings())


@lru_cache
def _ollama() -> OllamaLlm:
    return OllamaLlm(get_settings())


@lru_cache
def _groq() -> GroqLlm:
    return GroqLlm(get_settings())


def get_llm() -> LlmClient:
    """FastAPI dependency; tests override it with a fake."""
    provider = get_settings().ai_provider
    if provider == "ollama":
        return _ollama()
    if provider == "groq":
        return _groq()
    try:
        return _anthropic()
    except anthropic.AnthropicError as exc:
        raise AiUnavailableError(f"Claude API is not configured: {exc}") from exc


def provider_status() -> dict:
    s = get_settings()
    if s.ai_provider == "ollama":
        ready, detail = _ollama().status()
        return {"provider": "ollama", "model": s.ollama_model, "ready": ready, "detail": detail,
                "cost": "free (runs locally)"}
    if s.ai_provider == "groq":
        configured = bool(s.groq_api_key)
        return {"provider": "groq", "model": s.groq_model, "ready": configured,
                "detail": f"reasoning={s.groq_reasoning_effort}" if configured else "GROQ_API_KEY not set",
                "cost": "free tier (hosted)"}
    configured = bool(s.anthropic_api_key)
    return {
        "provider": "anthropic",
        "model": s.ai_model,
        "ready": configured,
        "detail": f"effort={s.ai_effort}, fallbacks={'on' if s.ai_fallbacks_enabled else 'off'}"
        if configured else "ANTHROPIC_API_KEY not set - analysis returns 503",
        "cost": "paid per token (Claude API)",
    }
