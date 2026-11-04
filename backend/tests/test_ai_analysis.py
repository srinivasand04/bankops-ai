"""Phase 5: Claude incident analysis with a mocked LLM - no network calls, no API key needed."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ai.llm import AnthropicLlm, LlmResult
from app.ai.providers import get_llm
from app.ai.prompts.incident_analysis import SYSTEM_PROMPT
from app.ai.schemas import IncidentAnalysis
from app.core.config import get_settings
from app.core.exceptions import AiResponseError, AiUnavailableError, PermissionDeniedError
from app.core.security import CurrentUser, Role
from app.main import app
from tests.conftest import headers


def _analysis(**overrides) -> IncidentAnalysis:
    """A realistic Claude answer for INC-1007 with a few deliberate problems for the guardrails."""
    data = {
        "summary": "Payment API 5xx errors began 30 minutes after release 2.4.1 reduced the DB pool size.",
        "confirmed_facts": [
            {"statement": "CHG-2041 (v2.4.1) was deployed 30 minutes before impact began",
             "evidence_ids": ["CHG-2041"]},
            {"statement": "5xx rate rose from 0.2% to about 18%", "evidence_ids": ["MS-PAY-http_5xx_rate_pct", "EV-99999"]},
            {"statement": "Customers are complaining on social media", "evidence_ids": []},  # uncited
        ],
        "root_cause_hypotheses": [
            {"description": "Pool max lowered from 100 to 20 in 2.4.1 while fraud scoring holds connections longer",
             "category": "APPLICATION", "confidence": 1.4,  # out of range
             "supporting_evidence_ids": ["MS-PAY-db_pool_active_connections", "CHG-2041", "FAKE-1"],
             "contradicting_evidence_ids": [], "missing_evidence": ["Config diff 2.4.0 vs 2.4.1"],
             "verification_steps": ["Compare HikariCP settings between releases"]},
            {"description": "Core Banking database degradation", "category": "DATABASE", "confidence": 0.1,
             "supporting_evidence_ids": [], "contradicting_evidence_ids": ["MS-CBS-db_cpu_pct"],
             "missing_evidence": [], "verification_steps": ["Check Oracle AWR report"]},
        ],
        "affected_services": [
            {"application_code": "PAY", "impact": "Authorisations failing", "evidence_ids": ["MS-PAY-http_5xx_rate_pct"]},
            {"application_code": "REC", "impact": "Intraday batch failed", "evidence_ids": []},
            {"application_code": "ATM", "impact": "Invented system", "evidence_ids": []},  # not in fact base
        ],
        "business_impact": {"summary": "Customer payments failing", "customer_impact": "Retail and SME customers",
                            "regulatory_or_financial_exposure": "Possible incident reporting threshold",
                            "assessed_severity": "P1", "severity_rationale": "Payments substantially unavailable"},
        "recommended_actions": [
            {"action_type": "CORRECTIVE", "description": "Roll back Payment Processing to 2.4.0",
             "owner_team": "Release Management", "urgency": "IMMEDIATE",
             "requires_human_approval": False, "approval_reason": None},  # guardrail must force approval
            {"action_type": "PREVENTIVE", "description": "Add connection-pool load test to the release gate",
             "owner_team": "Payments Engineering", "urgency": "SHORT_TERM",
             "requires_human_approval": False, "approval_reason": None},
        ],
        "escalation": {"recommended": True, "reason": "Resolution SLA at risk on a Tier 1 service"},
        "missing_information": ["Fraud-scoring service latency metrics"],
        "overall_confidence": "MEDIUM",
    }
    data.update(overrides)
    return IncidentAnalysis.model_validate(data)


class FakeLlm:
    def __init__(self, analysis: IncidentAnalysis | None = None, error: Exception | None = None):
        self.analysis, self.error, self.calls = analysis or _analysis(), error, []

    def structured(self, *, system, user, output_model):
        self.calls.append({"system": system, "user": user, "output_model": output_model})
        if self.error:
            raise self.error
        return LlmResult(parsed=self.analysis, model="claude-opus-5-5", stop_reason="end_turn",
                         input_tokens=5200, output_tokens=1800, cache_read_tokens=0, request_id="req_test")


@pytest.fixture
def fake_llm():
    fake = FakeLlm()
    app.dependency_overrides[get_llm] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def p1(client, seeded):
    return client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()


def _analyze(client, incident_id, focus=None, role="ENGINEER"):
    body = {"focus": focus} if focus else None
    return client.post(f"/api/ai/incidents/{incident_id}/analyze?wait=true", json=body, headers=headers(role, "a.patel"))


# ---- fact base -----------------------------------------------------------------------------


def test_context_contains_only_database_facts(client, p1):
    ctx = client.get(f"/api/ai/incidents/{p1['id']}/context", headers=headers("VIEWER")).json()
    ids = set(ctx["citable_ids"])
    assert {"INC-1007", "CHG-2041", "MS-PAY-http_5xx_rate_pct", "APP-PAY", "APP-CBS"} <= ids
    assert ctx["fact_base"]["related_changes"][0]["minutes_before_incident_start"] == 30.0
    messages = [e["message"] for e in ctx["fact_base"]["evidence"]["events"]]
    assert any("maximumPoolSize=20" in m for m in messages)
    assert ctx["summary"]["citable_ids"] == len(ids)


# ---- analysis + guardrails -----------------------------------------------------------------


def test_analyze_applies_guardrails_and_awaits_review(client, p1, fake_llm):
    response = _analyze(client, p1["id"], focus="Was release 2.4.1 the cause?")
    assert response.status_code == 201, response.text
    inv = response.json()
    assert inv["status"] == "AWAITING_REVIEW"
    assert inv["incident_reference"] == "INC-1007"
    assert inv["model_name"] == "claude-opus-5-5"
    report = inv["report"]

    # facts: invalid citation stripped, uncited claim demoted
    assert [f["evidence_ids"] for f in report["confirmed_facts"]] == [["CHG-2041"], ["MS-PAY-http_5xx_rate_pct"]]
    assert report["unverified_statements"] == ["Customers are complaining on social media"]
    # hypotheses: always HYPOTHESIS, confidence clamped, fake citation removed, ranked
    top = report["root_cause_hypotheses"][0]
    assert top["confidence"] == 1.0 and top["status"] == "HYPOTHESIS"
    assert "FAKE-1" not in top["supporting_evidence_ids"]
    assert [h["confidence"] for h in report["root_cause_hypotheses"]] == [1.0, 0.1]
    # invented application dropped
    assert [s["application_code"] for s in report["affected_services"]] == ["PAY", "REC"]
    # rollback forced to require approval; the load-test action left alone
    rollback, load_test = report["recommended_actions"]
    assert rollback["requires_human_approval"] is True and "change management" in rollback["approval_reason"]
    assert load_test["requires_human_approval"] is False
    assert len(report["guardrail_notes"]) >= 5
    assert "not confirmed" in report["disclaimer"]

    step = inv["executions"][0]
    assert step["agent_name"] == "incident_analyst" and step["status"] == "COMPLETED"
    assert (step["input_tokens"], step["output_tokens"]) == (5200, 1800)

    # nothing written to the incident's RCA before a human reviews it
    assert client.get(f"/api/incidents/{p1['id']}/root-causes", headers=headers()).json()[-1]["source"] == "HUMAN"
    timeline = client.get(f"/api/incidents/{p1['id']}/timeline", headers=headers()).json()
    assert timeline[-1]["event_type"] == "AI_ANALYSIS"
    assert (timeline[-1]["source"], timeline[-1]["created_by"]) == ("AI", "ai:incident-analyst")


def test_prompt_contains_system_rules_and_fact_base(client, p1, fake_llm):
    _analyze(client, p1["id"], focus="Was release 2.4.1 the cause?")
    call = fake_llm.calls[0]
    assert call["system"] == SYSTEM_PROMPT  # fixed text -> cacheable
    assert call["output_model"] is IncidentAnalysis
    assert "Was release 2.4.1 the cause?" in call["user"]
    fact_base = json.loads(call["user"].split("Fact base (JSON):\n", 1)[1])
    assert fact_base["incident"]["id"] == "INC-1007"


def test_llm_unavailable_records_failed_investigation(client, p1):
    app.dependency_overrides[get_llm] = lambda: FakeLlm(error=AiUnavailableError("Claude API rate limit reached"))
    try:
        response = _analyze(client, p1["id"])
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"
    history = client.get(f"/api/ai/incidents/{p1['id']}/investigations", headers=headers()).json()
    assert history[0]["status"] == "FAILED"
    assert history[0]["error_message"] == "Claude API rate limit reached"
    assert history[0]["executions"][0]["status"] == "FAILED"


def test_viewer_cannot_start_analysis(client, p1, fake_llm):
    assert _analyze(client, p1["id"], role="VIEWER").status_code == 403
    assert fake_llm.calls == []


# ---- human review ----------------------------------------------------------------------------


def test_approval_records_ai_output_as_hypotheses_and_open_actions(client, p1, fake_llm):
    inv = _analyze(client, p1["id"]).json()
    url = f"/api/ai/investigations/{inv['id']}/review"
    assert client.post(url, json={"decision": "APPROVE"}, headers=headers("ENGINEER")).status_code == 403

    approved = client.post(url, json={"decision": "APPROVE", "review_notes": "Plausible, verify pool config"},
                           headers=headers(user="incident.manager")).json()
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by"] == "incident.manager"
    assert approved["report"]["applied"] == {"root_causes": 2, "actions": 2}

    rca = client.get(f"/api/incidents/{p1['id']}/rca", headers=headers()).json()
    ai_hypotheses = [h for h in rca["hypotheses"] if h["source"] == "AI"]
    assert len(ai_hypotheses) == 2 and rca["confirmed_root_causes"] == []  # still not confirmed
    ai_actions = [a for a in rca["corrective_actions"] + rca["preventive_actions"] if a["source"] == "AI"]
    assert len(ai_actions) == 2
    assert any("Requires human approval" in a["description"] for a in ai_actions)

    again = client.post(url, json={"decision": "REJECT"}, headers=headers())
    assert again.status_code == 422


def test_rejection_applies_nothing(client, p1, fake_llm):
    inv = _analyze(client, p1["id"]).json()
    rejected = client.post(f"/api/ai/investigations/{inv['id']}/review",
                           json={"decision": "REJECT", "review_notes": "Insufficient evidence"}, headers=headers()).json()
    assert rejected["status"] == "REJECTED"
    assert rejected["report"]["applied"] == {"root_causes": 0, "actions": 0}
    rca = client.get(f"/api/incidents/{p1['id']}/rca", headers=headers()).json()
    assert not [h for h in rca["hypotheses"] if h["source"] == "AI"]


def test_ai_identity_cannot_review(db, client, p1, fake_llm):
    from app.ai.analysis_service import AnalysisService
    from app.ai.schemas import ReviewRequest

    inv = _analyze(client, p1["id"]).json()
    ai_manager = CurrentUser("ai:supervisor", Role.ADMIN)
    with pytest.raises(PermissionDeniedError):
        AnalysisService(db).review(inv["id"], ReviewRequest(decision="APPROVE"), ai_manager)


# ---- SDK wrapper (mocked Anthropic client) -------------------------------------------------


def _sdk_response(stop_reason="end_turn", parsed=None):
    return SimpleNamespace(
        stop_reason=stop_reason, stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        parsed_output=parsed, model="claude-opus-5-5", _request_id="req_1",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
    )


@pytest.fixture
def sdk_llm():
    llm = AnthropicLlm(get_settings())
    llm.client = MagicMock()
    return llm


def test_sdk_request_shape(sdk_llm):
    sdk_llm.client.beta.messages.parse.return_value = _sdk_response(parsed=_analysis())
    result = sdk_llm.structured(system="rules", user="facts", output_model=IncidentAnalysis)
    kwargs = sdk_llm.client.beta.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "high"}
    assert kwargs["output_format"] is IncidentAnalysis
    assert kwargs["fallbacks"] == "default" and kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert result.parsed.overall_confidence == "MEDIUM" and result.request_id == "req_1"


@pytest.mark.parametrize("stop_reason,message", [("refusal", "declined"), ("max_tokens", "truncated")])
def test_sdk_unusable_responses(sdk_llm, stop_reason, message):
    sdk_llm.client.beta.messages.parse.return_value = _sdk_response(stop_reason=stop_reason, parsed=_analysis())
    with pytest.raises(AiResponseError, match=message):
        sdk_llm.structured(system="s", user="u", output_model=IncidentAnalysis)


def test_sdk_missing_credentials_maps_to_unavailable(sdk_llm):
    sdk_llm.client.beta.messages.parse.side_effect = TypeError(
        "Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set."
    )
    with pytest.raises(AiUnavailableError, match="not configured"):
        sdk_llm.structured(system="s", user="u", output_model=IncidentAnalysis)


def test_ai_status_endpoint(client, applications):
    body = client.get("/api/ai/status", headers=headers("VIEWER")).json()
    assert body["provider"] == "anthropic" and body["model"] == "claude-opus-5-5"


@pytest.mark.parametrize(
    "text,consequential",
    [
        ("Roll back Payment Processing to 2.4.0", True),
        ("Increase the HikariCP pool to 100", True),
        ("Raise maximumPoolSize setting back to 100", True),
        ("Restart payment-api pods", True),
        ("Rerun the reconciliation batch and reprocess unmatched transactions", True),
        ("Close the incident after verification", True),
        ("Add connection-pool load test to the release gate", False),
        ("Review the deployment checklist with the CAB", False),
        ("Add an alert on DB pool saturation", False),
    ],
)
def test_consequential_action_detection(text, consequential):
    from app.ai.analysis_service import CONSEQUENTIAL

    assert bool(CONSEQUENTIAL.search(text)) is consequential


# ---- background analysis (the UI flow) ---------------------------------------------------


def test_analyze_returns_202_and_finishes_in_background(client, p1, fake_llm):
    response = client.post(f"/api/ai/incidents/{p1['id']}/analyze", headers=headers("ENGINEER"))
    assert response.status_code == 202
    started = response.json()
    assert started["status"] == "RUNNING" and started["report"] is None

    # TestClient runs background tasks before returning, so the result is already stored
    done = client.get(f"/api/ai/investigations/{started['id']}", headers=headers()).json()
    assert done["status"] == "AWAITING_REVIEW"
    assert done["report"]["summary"]
    assert len(fake_llm.calls) == 1


def test_background_failure_is_recorded(client, p1):
    app.dependency_overrides[get_llm] = lambda: FakeLlm(error=AiUnavailableError("Ollama is not reachable"))
    try:
        started = client.post(f"/api/ai/incidents/{p1['id']}/analyze", headers=headers("ENGINEER"))
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert started.status_code == 202
    inv = client.get(f"/api/ai/investigations/{started.json()['id']}", headers=headers()).json()
    assert inv["status"] == "FAILED" and inv["error_message"] == "Ollama is not reachable"


def test_second_analysis_blocked_while_one_is_running(db, client, p1):
    from app.ai.analysis_service import AnalysisService

    AnalysisService(db).start(p1["id"], None, CurrentUser("a.patel", Role.ENGINEER))  # stays RUNNING
    response = client.post(f"/api/ai/incidents/{p1['id']}/analyze", headers=headers("ENGINEER"))
    assert response.status_code == 422
    assert "already analysing" in response.json()["error"]["message"]


def test_interrupted_analyses_are_failed_at_startup(db, p1):
    from app.ai.analysis_service import AnalysisService

    inv = AnalysisService(db).start(p1["id"], None, CurrentUser("a.patel", Role.ENGINEER))
    assert AnalysisService.fail_interrupted() == 1
    db.expire_all()
    assert AnalysisService(db).get(inv.id).status == "FAILED"


def test_recent_investigations_list(client, p1, fake_llm):
    _analyze(client, p1["id"])
    _analyze(client, p1["id"])
    listed = client.get("/api/ai/investigations", headers=headers("VIEWER")).json()
    assert [i["id"] for i in listed] == sorted((i["id"] for i in listed), reverse=True)
    awaiting = client.get("/api/ai/investigations?status=AWAITING_REVIEW", headers=headers()).json()
    assert len(awaiting) == 2 and all(i["incident_reference"] == "INC-1007" for i in awaiting)
