"""Compact fact base for local models, and prompt improvements (summary answers the question)."""

import json

import pytest

from app.ai.compact import compact_context, merge_repeated_events, summarise_series
from app.ai.context import build_incident_context
from app.ai.prompts.incident_analysis import SYSTEM_PROMPT, build_user_message, system_prompt
from app.ai.providers import get_llm
from app.ai.schemas import field_guide
from app.main import app
from app.models import Incident
from tests.conftest import headers
from tests.test_ai_analysis import FakeLlm, _analysis


@pytest.fixture
def p1_contexts(db, seeded):
    incident = db.query(Incident).filter_by(reference_number="INC-1007").one()
    full = build_incident_context(db, incident)
    return full, compact_context(full)


def test_compact_is_smaller_and_keeps_the_key_evidence(p1_contexts):
    full, small = p1_contexts
    full_size, small_size = len(json.dumps(full.data, default=str)), len(json.dumps(small.data, default=str))
    assert small_size < full_size * 0.65
    assert small.valid_ids <= full.valid_ids  # nothing invented
    assert {"CHG-2041", "MS-PAY-http_5xx_rate_pct", "MS-PAY-db_pool_active_connections"} <= small.valid_ids
    messages = " ".join(e["message"] for e in small.data["evidence"]["events"])
    assert "maximumPoolSize=20" in messages


def test_metric_series_are_summarised(p1_contexts):
    _, small = p1_contexts
    series = {s["id"]: s for s in small.data["evidence"]["metric_series"]}
    errors = series["MS-PAY-http_5xx_rate_pct"]
    assert "points" not in errors
    assert (errors["first"], errors["trend"]) == (0.2, "rose") and errors["peak"] == 18.4
    pool = series["MS-PAY-db_pool_active_connections"]
    assert pool["trend"] == "fell"
    assert [c["attributes"]["pool_max"] for c in pool["attribute_changes"]] == [100, 20]
    assert series["MS-CBS-db_cpu_pct"]["trend"] == "stable"  # lets the model rule Core Banking out


def test_repeated_log_lines_are_merged():
    event = {"application": "PAY", "type": "LOG", "message": "pool timeout"}
    merged = merge_repeated_events([
        {**event, "id": "EV-1", "minutes_from_start": 1},
        {**event, "id": "EV-2", "minutes_from_start": 25},
        {**event, "id": "EV-3", "minutes_from_start": 45},
        {**event, "id": "EV-4", "message": "other", "minutes_from_start": 50},
    ])
    assert [(e["id"], e.get("occurrences"), e.get("last_minutes_from_start")) for e in merged] == [
        ("EV-1", 3, 45), ("EV-4", None, None)]


def test_summarise_series_attribute_changes_only_when_they_change():
    series = {"id": "MS-X", "application": "X", "metric": "m", "unit": "%",
              "points": [{"minutes_from_start": -10, "value": 1.0, "attributes": {"a": 1}},
                         {"minutes_from_start": 0, "value": 1.1, "attributes": {"a": 1}}]}
    assert "attribute_changes" not in summarise_series(series)


def test_compact_timeline_drops_ai_entries(client, db, seeded):
    app.dependency_overrides[get_llm] = lambda: FakeLlm()
    try:
        p1 = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
        inv = client.post(f"/api/ai/incidents/{p1['id']}/analyze?wait=true", headers=headers("ENGINEER")).json()
        client.post(f"/api/ai/investigations/{inv['id']}/review", json={"decision": "APPROVE"}, headers=headers())
    finally:
        app.dependency_overrides.pop(get_llm, None)
    db.expire_all()
    incident = db.get(Incident, p1["id"])
    small = compact_context(build_incident_context(db, incident))
    types = {e["type"] for e in small.data["timeline"]}
    assert "AI_ANALYSIS" not in types and "ROOT_CAUSE_HYPOTHESIS" not in types
    assert "EVIDENCE_ADDED" in types
    assert any(r["source"] == "AI" for r in small.data["existing_root_causes"])  # still listed, once


def test_approval_event_is_last_on_the_timeline(client, seeded):
    app.dependency_overrides[get_llm] = lambda: FakeLlm()
    try:
        p1 = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
        inv = client.post(f"/api/ai/incidents/{p1['id']}/analyze?wait=true", headers=headers("ENGINEER")).json()
        client.post(f"/api/ai/investigations/{inv['id']}/review", json={"decision": "APPROVE"}, headers=headers())
    finally:
        app.dependency_overrides.pop(get_llm, None)
    last = client.get(f"/api/incidents/{p1['id']}/timeline", headers=headers()).json()[-1]
    assert last["event_type"] == "AI_ANALYSIS" and "approved" in last["description"]


# ---- prompt ------------------------------------------------------------------------------------


def test_summary_must_answer_the_request():
    assert "Never repeat the question back" in SYSTEM_PROMPT
    assert "directly answer" in field_guide()
    assert "release is APPLICATION" in SYSTEM_PROMPT


def test_compact_system_prompt_is_fixed_and_carries_the_field_guide():
    compact = system_prompt(compact=True)
    assert compact.startswith(SYSTEM_PROMPT) and "Output fields:" in compact
    assert "- business_impact" in compact and "  - summary:" in compact
    assert system_prompt(compact=True) == compact  # stable text -> prefix cache works
    assert system_prompt() == SYSTEM_PROMPT
    user = build_user_message({"incident": {"id": "INC-9"}}, "Was it the release?")
    assert "Output fields" not in user  # incident-specific part stays out of the cached prefix


def test_compact_mode_end_to_end_uses_compact_ids(client, seeded):
    class CompactFake(FakeLlm):
        prefers_compact_context = True

    # EV-61 is a repeat of EV-47's log line: merged away in compact mode, so citing it is rejected
    fake = CompactFake(_analysis(confirmed_facts=[
        {"statement": "Pool timeouts repeated during the incident", "evidence_ids": ["EV-61", "MS-PAY-http_5xx_rate_pct"]}
    ]))
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        p1 = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
        inv = client.post(f"/api/ai/incidents/{p1['id']}/analyze?wait=true", headers=headers("ENGINEER")).json()
    finally:
        app.dependency_overrides.pop(get_llm, None)

    assert inv["report"]["context_summary"]["mode"] == "compact"
    assert "Output fields:" in fake.calls[0]["system"]
    sent = json.loads(fake.calls[0]["user"].split("Fact base (JSON):\n", 1)[1])
    assert "points" not in sent["evidence"]["metric_series"][0]
    assert inv["report"]["confirmed_facts"][0]["evidence_ids"] == ["MS-PAY-http_5xx_rate_pct"]
    assert inv["executions"][0]["tool_calls"][0]["mode"] == "compact"


def test_duplicate_hypotheses_are_removed(p1_contexts):
    from app.ai.analysis_service import apply_guardrails

    full, _ = p1_contexts
    base = _analysis().root_cause_hypotheses[0].model_dump()
    duplicate = {**base, "description": base["description"].upper() + "!", "confidence": 0.15}
    analysis = _analysis(root_cause_hypotheses=[base, duplicate])
    report, notes = apply_guardrails(analysis, full)
    assert len(report["root_cause_hypotheses"]) == 1
    assert report["root_cause_hypotheses"][0]["confidence"] == 1.0  # the stronger copy (clamped from 1.4)
    assert any("duplicate hypothesis removed" in n for n in notes)
