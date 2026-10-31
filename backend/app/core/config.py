"""Application settings loaded from environment variables / .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> project root is three levels up from backend/
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SlaTarget(BaseModel):
    """Response and resolution targets in minutes."""

    response: int = Field(gt=0)
    resolution: int = Field(gt=0)


# Demonstration targets only - real targets are set by each bank's service catalogue.
DEFAULT_SLA_TARGETS: dict[str, SlaTarget] = {
    "P1": SlaTarget(response=15, resolution=60),
    "P2": SlaTarget(response=30, resolution=240),
    "P3": SlaTarget(response=240, resolution=1440),
    "P4": SlaTarget(response=480, resolution=4320),
}


class ApiKeyUser(BaseModel):
    username: str
    role: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BankOps AI"
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://bankops:bankops@localhost:5445/bankops"
    test_database_url: str | None = None

    cors_origins: list[str] = ["http://localhost:5173"]

    auth_enabled: bool = False
    api_keys: dict[str, ApiKeyUser] = {}

    sla_targets: dict[str, SlaTarget] = DEFAULT_SLA_TARGETS
    # Fraction of the SLA window after which an incident is flagged "AT_RISK"
    sla_warning_threshold: float = Field(default=0.75, gt=0, lt=1)

    # ---- AI provider ----
    # "anthropic" = Claude API (paid, strongest reasoning); "ollama" = local open model (free, slower)
    ai_provider: Literal["anthropic", "ollama"] = "anthropic"

    # ---- Ollama (local models) ----
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    # Context window in tokens. Ollama's default is too small for the fact base (~6K tokens) + answer.
    ollama_num_ctx: int = Field(default=16384, ge=4096, le=131072)
    # Qwen3 "thinking" improves reasoning but multiplies generated tokens - slow on a laptop CPU.
    ollama_think: bool = False
    ollama_timeout_seconds: float = Field(default=900, gt=0)

    # ---- Claude (Phase 5) ----
    # Unset key: the SDK falls back to other credential sources (ANTHROPIC_AUTH_TOKEN, `ant auth login`).
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    ai_max_tokens: int = Field(default=16000, ge=1024, le=64000)
    ai_timeout_seconds: float = Field(default=180, gt=0)
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    # Server-side refusal fallback (`fallbacks: "default"`) - re-runs a declined request on a recommended model
    ai_fallbacks_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
