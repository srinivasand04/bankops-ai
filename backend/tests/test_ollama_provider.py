"""Local Ollama provider - HTTP is mocked with httpx.MockTransport, so Ollama need not be installed."""

import json

import httpx
import pytest

from app.ai import providers
from app.ai.ollama import OllamaLlm, inline_schema
from app.ai.providers import get_llm
from app.ai.schemas import IncidentAnalysis
from app.core.config import get_settings
from app.core.exceptions import AiResponseError, AiUnavailableError
from app.main import app
from tests.conftest import headers
from tests.test_ai_analysis import _analysis


def _ollama_with(handler) -> tuple[OllamaLlm, list]:
    requests = []

    def recording(request: httpx.Request):
        requests.append(request)
        return handler(request)

    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(recording))
    return OllamaLlm(get_settings(), client=client), requests


def _chat_reply(content: str, done_reason="stop"):
    return httpx.Response(200, json={
        "model": "qwen3:8b", "message": {"role": "assistant", "content": content}, "done": True,
        "done_reason": done_reason, "prompt_eval_count": 6100, "eval_count": 2300, "total_duration": 9e10,
    })


GOOD_ANSWER = _analysis().model_dump_json()


def test_request_shape_and_parsing():
    llm, requests = _ollama_with(lambda r: _chat_reply(GOOD_ANSWER))
    result = llm.structured(system="rules", user="facts", output_model=IncidentAnalysis)

    body = json.loads(requests[0].content)
    assert requests[0].url.path == "/api/chat"
    assert body["model"] == "qwen3:8b" and body["stream"] is False and body["think"] is False
    assert body["options"] == {"num_ctx": 8192, "temperature": 0}
    assert body["keep_alive"] == "30m"
    assert llm.prefers_compact_context is True
    assert body["messages"][0] == {"role": "system", "content": "rules"}
    assert body["messages"][1]["content"].startswith("facts") and "JSON" in body["messages"][1]["content"]
    assert "$ref" not in json.dumps(body["format"])  # schema inlined for the grammar converter
    assert set(body["format"]["required"]) == set(IncidentAnalysis.model_fields)

    assert result.parsed.overall_confidence == "MEDIUM"
    assert result.model == "ollama/qwen3:8b"
    assert (result.input_tokens, result.output_tokens) == (6100, 2300)


def test_context_window_grows_to_fit_the_prompt():
    from app.ai.ollama import context_window

    assert context_window("x" * 1000, 8192) == 8192  # small prompt: configured minimum
    assert context_window("x" * 35_000, 8192) == 12288  # 10K tokens + answer reserve, rounded up
    assert context_window("x" * 1_000_000, 8192) == 32768  # capped


def test_inline_schema_resolves_nested_models():
    schema = inline_schema(IncidentAnalysis)
    assert "$defs" not in schema
    fact = schema["properties"]["confirmed_facts"]["items"]
    assert fact["properties"]["evidence_ids"]["type"] == "array"


@pytest.mark.parametrize(
    "handler,error,message",
    [
        (lambda r: httpx.Response(404, json={"error": "model 'qwen3:8b' not found"}), AiUnavailableError, "ollama pull"),
        (lambda r: _chat_reply("not json at all"), AiResponseError, "does not match"),
        (lambda r: _chat_reply('{"summary": "only one field"}'), AiResponseError, "does not match"),
        (lambda r: _chat_reply(GOOD_ANSWER, done_reason="length"), AiResponseError, "truncated"),
        (lambda r: httpx.Response(500, text="out of memory"), AiResponseError, "Ollama error 500"),
    ],
)
def test_error_mapping(handler, error, message):
    llm, _ = _ollama_with(handler)
    with pytest.raises(error, match=message):
        llm.structured(system="s", user="u", output_model=IncidentAnalysis)


def test_ollama_not_running():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    llm, _ = _ollama_with(refuse)
    with pytest.raises(AiUnavailableError, match="not reachable"):
        llm.structured(system="s", user="u", output_model=IncidentAnalysis)
    assert llm.status() == (False, "Ollama is not reachable at http://localhost:11434")


def test_status_checks_model_is_pulled():
    llm, _ = _ollama_with(lambda r: httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]}))
    assert llm.status()[0] is True
    llm, _ = _ollama_with(lambda r: httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]}))
    ready, detail = llm.status()
    assert not ready and "ollama pull qwen3:8b" in detail


def test_end_to_end_analysis_with_local_model(client, seeded):
    """Same pipeline as Claude: fact base -> local model -> guardrails -> awaiting review."""
    llm, requests = _ollama_with(lambda r: _chat_reply(GOOD_ANSWER))
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        p1 = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
        inv = client.post(f"/api/ai/incidents/{p1['id']}/analyze?wait=true", headers=headers("ENGINEER")).json()
    finally:
        app.dependency_overrides.pop(get_llm, None)

    assert inv["status"] == "AWAITING_REVIEW"
    assert inv["model_name"] == "ollama/qwen3:8b"
    assert inv["report"]["unverified_statements"]  # guardrails ran exactly as for Claude
    sent = json.loads(requests[0].content)
    assert "INC-1007" in sent["messages"][1]["content"]


def test_provider_switch(monkeypatch, client, applications):
    monkeypatch.setattr(get_settings(), "ai_provider", "ollama")
    monkeypatch.setattr(get_settings(), "ollama_base_url", "http://127.0.0.1:9")  # nothing listens here
    providers._ollama.cache_clear()
    try:
        assert isinstance(get_llm(), OllamaLlm)
        status = client.get("/api/ai/status", headers=headers("VIEWER")).json()
        assert status["provider"] == "ollama" and status["ready"] is False and "free" in status["cost"]
    finally:
        providers._ollama.cache_clear()
