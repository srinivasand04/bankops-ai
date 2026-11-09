"""Phase 7: multi-agent investigation (LangGraph) with a scripted LLM - no network calls."""

import pytest

from app.ai.agents.definitions import AgentFinding, SupervisorPlan
from app.ai.context import build_incident_context
from app.ai.llm import LlmResult
from app.ai.providers import get_llm
from app.ai.schemas import IncidentAnalysis
from app.ai.tools.incident_tools import TOOL_NAMES, Toolkit, call_tool
from app.core.config import get_settings
from app.core.exceptions import AiUnavailableError
from app.main import app
from app.models import Incident
from tests.conftest import headers
from tests.test_ai_analysis import _analysis


class ScriptedLlm:
    """Answers by output model; records which agent asked (taken from the system prompt)."""

    def __init__(self, plan=("change_release", "dependency_impact"), fail_agent: str | None = None):
        self.plan, self.fail_agent, self.calls = list(plan), fail_agent, []

    def structured(self, *, system, user, output_model):
        agent = next((t for t in ("Triage", "Change & release", "Dependency & impact", "Operational risk")
                      if f"You are the {t} agent" in system), "supervisor" if output_model is SupervisorPlan else "root")
        self.calls.append({"agent": agent, "model": output_model.__name__, "user": user})
        if self.fail_agent and self.fail_agent == agent:
            raise AiUnavailableError("Model provider timed out")
        if output_model is SupervisorPlan:
            parsed = SupervisorPlan(specialists=self.plan, reasoning="A release went out 30 minutes before impact.")
        elif output_model is AgentFinding:
            parsed = AgentFinding(
                summary=f"{agent} summary",
                findings=[
                    {"statement": "Release 2.4.1 deployed 30 minutes before impact", "evidence_ids": ["CHG-2041", "BOGUS-1"]},
                    {"statement": "Unsupported claim", "evidence_ids": ["NOT-REAL"]},
                ],
                risk_signal="HIGH",
                open_questions=["Config diff between 2.4.0 and 2.4.1"],
            )
        else:
            parsed = _analysis()
        return LlmResult(parsed=parsed, model="fake-model", stop_reason="end_turn", input_tokens=900, output_tokens=300)


@pytest.fixture
def scripted():
    def install(**kwargs) -> ScriptedLlm:
        fake = ScriptedLlm(**kwargs)
        app.dependency_overrides[get_llm] = lambda: fake
        return fake
    yield install
    app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def p1(client, seeded):
    return client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()


def _investigate(client, incident_id, role="ENGINEER", focus=None):
    body = {"focus": focus} if focus else None
    return client.post(f"/api/ai/incidents/{incident_id}/investigate?wait=true", json=body,
                       headers=headers(role, "a.patel"))


# ---- graph run ---------------------------------------------------------------------------


def test_investigation_runs_planned_agents_in_order(client, p1, scripted):
    fake = scripted()
    r = _investigate(client, p1["id"], focus="Was release 2.4.1 the cause?")
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "AWAITING_REVIEW"
    assert inv["agents_selected"] == ["triage", "supervisor", "change_release", "dependency_impact", "root_cause"]
    assert [c["agent"] for c in fake.calls] == ["Triage", "supervisor", "Change & release", "Dependency & impact", "root"]
    steps = inv["executions"]
    assert [s["agent_name"] for s in steps] == inv["agents_selected"]
    assert [s["step_order"] for s in steps] == [1, 2, 3, 4, 5]
    assert all(s["status"] == "COMPLETED" for s in steps)
    assert [c["tool"] for c in steps[0]["tool_calls"]] == ["get_incident_details", "get_incident_timeline",
                                                         "get_application_health"]
    assert [c["tool"] for c in steps[3]["tool_calls"]] == ["get_application_dependencies", "calculate_incident_impact"]
    assert steps[1]["output"]["plan"] == ["change_release", "dependency_impact"]
    assert steps[0]["input_tokens"] == 900
    assert "Was release 2.4.1 the cause?" in fake.calls[0]["user"]


def test_report_keeps_contract_and_adds_agent_detail(client, p1, scripted):
    scripted()
    report = _investigate(client, p1["id"]).json()["report"]
    # same shape as the single-call analysis, so the existing UI and review work unchanged
    for key in ("summary", "confirmed_facts", "root_cause_hypotheses", "recommended_actions", "disclaimer"):
        assert key in report
    assert report["mode"] == "multi_agent"
    assert set(report["agent_findings"]) == {"triage", "change_release", "dependency_impact"}
    assert report["plan"]["reasoning"].startswith("A release")
    assert report["calculations"]["impact"]["id"] == "IMPACT-INC-1007"


def test_specialist_citations_are_guardrailed(client, p1, scripted):
    scripted()
    report = _investigate(client, p1["id"]).json()["report"]
    finding = report["agent_findings"]["triage"]
    assert finding["findings"] == [{"statement": "Release 2.4.1 deployed 30 minutes before impact",
                                    "evidence_ids": ["CHG-2041"]}]
    notes = " ".join(report["guardrail_notes"])
    assert "BOGUS-1" in notes and "no valid evidence and was dropped" in notes
    # the root cause guardrails still apply: out-of-range confidence clamped, rollback needs approval
    assert report["root_cause_hypotheses"][0]["confidence"] == 1.0
    assert report["recommended_actions"][0]["requires_human_approval"] is True


def test_supervisor_routes_only_to_chosen_specialists(client, p1, scripted):
    fake = scripted(plan=["operational_risk", "operational_risk"])  # duplicate is ignored
    inv = _investigate(client, p1["id"]).json()
    assert inv["agents_selected"] == ["triage", "supervisor", "operational_risk", "root_cause"]
    assert [c["agent"] for c in fake.calls] == ["Triage", "supervisor", "Operational risk", "root"]
    assert inv["report"]["calculations"]["risk"]["id"] == "RISK-INC-1007"


def test_supervisor_can_go_straight_to_root_cause(client, p1, scripted):
    scripted(plan=[])
    inv = _investigate(client, p1["id"]).json()
    assert inv["agents_selected"] == ["triage", "supervisor", "root_cause"]
    assert inv["status"] == "AWAITING_REVIEW"


def test_failed_agent_fails_investigation_and_keeps_completed_steps(client, p1, scripted):
    scripted(fail_agent="Change & release")
    r = _investigate(client, p1["id"])
    assert r.status_code == 503
    inv = client.get(f"/api/ai/incidents/{p1['id']}/investigations", headers=headers()).json()[0]
    assert inv["status"] == "FAILED" and "timed out" in inv["error_message"]
    states = {s["agent_name"]: s["status"] for s in inv["executions"]}
    assert states == {"triage": "COMPLETED", "supervisor": "COMPLETED", "change_release": "FAILED"}


def test_human_review_applies_multi_agent_report(client, p1, scripted):
    scripted()
    inv = _investigate(client, p1["id"]).json()
    denied = client.post(f"/api/ai/investigations/{inv['id']}/review", json={"decision": "APPROVE"},
                         headers=headers("ENGINEER", "a.patel"))
    assert denied.status_code == 403
    ok = client.post(f"/api/ai/investigations/{inv['id']}/review", json={"decision": "APPROVE"},
                     headers=headers("INCIDENT_MANAGER", "incident.manager"))
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    rca = client.get(f"/api/incidents/{p1['id']}/rca", headers=headers()).json()
    assert all(rc["status"] == "HYPOTHESIS" for rc in rca["hypotheses"]) and rca["hypotheses"]


def test_viewer_cannot_start_investigation(client, p1, scripted):
    scripted()
    assert _investigate(client, p1["id"], role="VIEWER").status_code == 403


def test_agent_daily_limit(client, p1, scripted, monkeypatch):
    scripted()
    monkeypatch.setenv("AI_AGENT_DAILY_LIMIT", "1")
    get_settings.cache_clear()
    try:
        assert _investigate(client, p1["id"]).status_code == 201
        status = client.get("/api/ai/status", headers=headers()).json()
        assert status["agent_daily_limit"] == 1 and status["agent_runs_left_today"] == 0
        r = _investigate(client, p1["id"])
        assert r.status_code == 429
        # the single-call analysis is not affected by the agent limit
        assert client.post(f"/api/ai/incidents/{p1['id']}/analyze?wait=true",
                           headers=headers("ENGINEER", "a.patel")).status_code == 201
    finally:
        monkeypatch.delenv("AI_AGENT_DAILY_LIMIT")
        get_settings.cache_clear()


def test_background_investigation_returns_202(client, p1, scripted):
    scripted()
    r = client.post(f"/api/ai/incidents/{p1['id']}/investigate", headers=headers("ENGINEER", "a.patel"))
    assert r.status_code == 202 and r.json()["status"] == "RUNNING"
    # TestClient runs background tasks before returning; the result is already stored
    done = client.get(f"/api/ai/investigations/{r.json()['id']}", headers=headers()).json()
    assert done["status"] == "AWAITING_REVIEW"


def test_agent_catalogue(client):
    agents = client.get("/api/ai/agents", headers=headers()).json()
    assert [a["name"] for a in agents] == ["triage", "change_release", "dependency_impact", "operational_risk", "root_cause"]
    tools = {t for a in agents for t in a["tools"]}
    assert tools == set(TOOL_NAMES)


# ---- tools -------------------------------------------------------------------------------


def _kit(db) -> Toolkit:
    incident = db.query(Incident).filter_by(reference_number="INC-1007").one()
    return Toolkit(db, incident, build_incident_context(db, incident))


def test_operational_risk_sees_release_and_tier(db, seeded):
    risk = call_tool(_kit(db), "calculate_operational_risk")
    assert risk["id"] == "RISK-INC-1007"
    assert risk["change_within_24h"]["id"] == "CHG-2041"
    assert risk["components"]["tier"] == 30  # Payment Processing is Tier 1
    assert 0 <= risk["score"] <= 100 and risk["band"] in {"LOW", "MEDIUM", "HIGH"}


def test_incident_impact_finds_connected_incidents(db, seeded):
    kit = _kit(db)
    impact = call_tool(kit, "calculate_incident_impact")
    active = impact["connected_with_active_incidents_within_3h"]
    assert "REC" in active and any(i["id"] == "INC-1008" for i in active["REC"])
    assert "IMPACT-INC-1007" in kit.ctx.valid_ids and "INC-1008" in kit.ctx.valid_ids


def test_every_tool_is_read_only(db, seeded):
    kit = _kit(db)
    for name in TOOL_NAMES:
        assert isinstance(call_tool(kit, name), dict)
    assert not db.dirty and not db.new and not db.deleted
    with pytest.raises(ValueError):
        call_tool(kit, "close_incident")
