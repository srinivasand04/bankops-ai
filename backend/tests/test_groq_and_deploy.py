"""Groq provider (mocked HTTP), public-demo daily limit, and cloud settings."""

import json

import httpx
import pytest

from app.ai.groq import GroqLlm, strict_schema
from app.ai.providers import get_llm
from app.ai.schemas import IncidentAnalysis
from app.core.config import Settings, get_settings
from app.core.exceptions import AiResponseError, AiUnavailableError
from app.main import app
from tests.conftest import headers
from tests.test_ai_analysis import FakeLlm, _analysis

GOOD = _analysis().model_dump_json()


def _groq(handler, key="gsk_test", sleeps: list | None = None) -> tuple[GroqLlm, list]:
    requests = []
    sleeps = [] if sleeps is None else sleeps

    def recording(request):
        requests.append(request)
        return handler(request)

    settings = get_settings().model_copy(update={"groq_api_key": key})
    client = httpx.Client(base_url="https://groq.test/openai/v1", transport=httpx.MockTransport(recording))
    return GroqLlm(settings, client=client, sleep=sleeps.append), requests


def _reply(content: str, finish="stop", status=200, headers=None):
    return httpx.Response(status, headers=headers, json={
        "model": "openai/gpt-oss-120b",
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 4100, "completion_tokens": 1300},
    })


def test_strict_schema_rules():
    schema = strict_schema(IncidentAnalysis)

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                yield node
            for v in node.values():
                yield from objects(v)
        elif isinstance(node, list):
            for v in node:
                yield from objects(v)

    found = list(objects(schema))
    assert found and all(o["additionalProperties"] is False and set(o["required"]) == set(o["properties"]) for o in found)


def test_request_shape_and_parsing():
    llm, requests = _groq(lambda r: _reply(GOOD))
    result = llm.structured(system="rules", user="facts", output_model=IncidentAnalysis)
    body = json.loads(requests[0].content)
    assert requests[0].url.path == "/openai/v1/chat/completions"
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert result.model == "groq/openai/gpt-oss-120b"
    assert (result.input_tokens, result.output_tokens) == (4100, 1300)
    assert llm.prefers_compact_context is True


@pytest.mark.parametrize(
    "handler,error,message",
    [
        (lambda r: _reply("", status=401), AiUnavailableError, "key is missing or invalid"),
        (lambda r: _reply("", status=429, headers={"retry-after": "3600"}), AiUnavailableError, "retry in about 3600 s"),
        (lambda r: _reply("", status=413), AiResponseError, "too large"),
        (lambda r: _reply(GOOD, finish="length"), AiResponseError, "truncated"),
        (lambda r: _reply('{"summary": "x"}'), AiResponseError, "does not match"),
    ],
)
def test_error_mapping(handler, error, message):
    llm, _ = _groq(handler)
    with pytest.raises(error, match=message):
        llm.structured(system="s", user="u", output_model=IncidentAnalysis)


def test_missing_key_fails_before_calling_groq():
    llm, requests = _groq(lambda r: _reply(GOOD), key="")
    with pytest.raises(AiUnavailableError, match="GROQ_API_KEY"):
        llm.structured(system="s", user="u", output_model=IncidentAnalysis)
    assert requests == []


def test_groq_provider_status(monkeypatch, client, applications):
    from app.ai import providers

    monkeypatch.setattr(get_settings(), "ai_provider", "groq")
    providers._groq.cache_clear()
    try:
        assert isinstance(get_llm(), GroqLlm)
        status = client.get("/api/ai/status", headers=headers("VIEWER")).json()
        assert status["provider"] == "groq" and status["ready"] is False and "free" in status["cost"]
    finally:
        providers._groq.cache_clear()


# ---- public demo guard ---------------------------------------------------------------------


def test_daily_analysis_limit(monkeypatch, client, seeded):
    monkeypatch.setattr(get_settings(), "ai_daily_limit", 2)
    app.dependency_overrides[get_llm] = lambda: FakeLlm()
    try:
        p1 = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
        for _ in range(2):
            assert client.post(f"/api/ai/incidents/{p1['id']}/analyze?wait=true", headers=headers("ENGINEER")).status_code == 201
        status = client.get("/api/ai/status", headers=headers()).json()
        assert (status["daily_limit"], status["runs_left_today"]) == (2, 0)
        blocked = client.post(f"/api/ai/incidents/{p1['id']}/analyze", headers=headers("ENGINEER"))
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


# ---- cloud settings ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("postgres://u:p@ep-x.neon.tech/db?sslmode=require", "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require"),
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_hosted_database_urls_get_the_driver(given, expected):
    assert Settings(database_url=given).database_url == expected


def test_short_rate_limit_is_waited_out():
    """Multi-agent runs trip the tokens-per-minute limit; a short retry-after is waited, not failed."""
    replies = iter([_reply("", status=429, headers={"retry-after": "2"}),
                    _reply("", status=429, headers={"retry-after": "3"}), _reply(GOOD)])
    sleeps = []
    llm, requests = _groq(lambda r: next(replies), sleeps=sleeps)
    result = llm.structured(system="s", user="u", output_model=IncidentAnalysis)
    assert result.parsed.summary and len(requests) == 3
    assert sleeps == [2.5, 3.5]


def test_rate_limit_gives_up_after_retries():
    sleeps = []
    llm, requests = _groq(lambda r: _reply("", status=429, headers={"retry-after": "1"}), sleeps=sleeps)
    with pytest.raises(AiUnavailableError, match="rate limit"):
        llm.structured(system="s", user="u", output_model=IncidentAnalysis)
    assert len(requests) == get_settings().groq_rate_limit_retries + 1 and len(sleeps) == len(requests) - 1


def test_long_rate_limit_is_not_waited():
    sleeps = []
    llm, requests = _groq(lambda r: _reply("", status=429, headers={"retry-after": "600"}), sleeps=sleeps)
    with pytest.raises(AiUnavailableError, match="600 s"):
        llm.structured(system="s", user="u", output_model=IncidentAnalysis)
    assert len(requests) == 1 and sleeps == []
