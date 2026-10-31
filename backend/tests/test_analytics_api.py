"""Analytics over the seeded synthetic environment (deterministic relative timestamps)."""

import pytest

from tests.conftest import headers


def _get(client, path):
    response = client.get(f"/api/analytics/{path}", headers=headers("VIEWER"))
    assert response.status_code == 200, response.text
    return response.json()


def test_incident_summary(client, seeded):
    summary = _get(client, "incident-summary")
    assert summary["total_incidents"] == 10
    assert summary["open_incidents"] == 4
    assert summary["resolved_or_closed_incidents"] == 6
    assert summary["p1_incidents"] == 2
    assert summary["open_p1_incidents"] == 1
    assert summary["sla_breached_incidents"] == 2
    assert summary["mttr_minutes"] == pytest.approx(293.3)


def test_mttr_calculation(client, seeded):
    mttr = _get(client, "mttr")
    # Resolution minutes per resolved seed incident (resolved_at - started_at): 85, 200, 315, 630, 300, 230
    assert mttr["overall"]["resolved_count"] == 6
    assert mttr["overall"]["mttr_minutes"] == pytest.approx(1760 / 6, abs=0.1)
    assert mttr["overall"]["min_minutes"] == 85
    assert mttr["overall"]["max_minutes"] == 630
    by_severity = {row["severity"]: row for row in mttr["by_severity"]}
    assert by_severity["P1"]["mttr_minutes"] == 85
    assert by_severity["P2"]["mttr_minutes"] == pytest.approx(257.5)
    assert by_severity["P4"]["resolved_count"] == 0 and by_severity["P4"]["mttr_minutes"] is None


def test_mttr_for_api_created_incident(client, create_incident):
    from datetime import UTC, datetime, timedelta

    started = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
    incident = create_incident(severity="P2", started_at=started, assigned_team="Payments Production Support")
    client.patch(f"/api/incidents/{incident['id']}/status", json={"status": "INVESTIGATING"}, headers=headers())
    client.patch(
        f"/api/incidents/{incident['id']}/status",
        json={"status": "RESOLVED", "resolution_summary": "Restarted the payment API pods"},
        headers=headers(),
    )
    assert _get(client, "mttr")["overall"]["mttr_minutes"] == pytest.approx(45, abs=0.5)


def test_severity_and_category_breakdown(client, seeded):
    severity = {row["severity"]: row for row in _get(client, "severity-breakdown")}
    assert {s: r["total"] for s, r in severity.items()} == {"P1": 2, "P2": 3, "P3": 4, "P4": 1}
    assert severity["P1"]["open"] == 1

    categories = {row["category"]: row["total"] for row in _get(client, "category-breakdown")}
    assert categories["PERFORMANCE"] == 3
    assert categories["BATCH_PROCESSING"] == 2


def test_application_incidents(client, seeded):
    rows = {row["application_code"]: row for row in _get(client, "application-incidents")}
    assert rows["PAY"]["total"] == 2 and rows["PAY"]["p1"] == 2 and rows["PAY"]["open"] == 1
    assert rows["CUS"]["total"] == 3
    assert rows["PAY"]["mttr_minutes"] == 85


def test_sla_compliance(client, seeded):
    sla = _get(client, "sla-compliance")
    # response: 8 met (all acknowledged in time except INC-1004), 1 breached, 1 pending (P4 still OPEN)
    assert sla["response"] == {"met": 8, "breached": 1, "pending": 1, "compliance_pct": 88.9}
    # resolution: 4 met, 2 breached (P1 outage at 75 min, P2 SSO at 300 min), 4 pending
    assert sla["resolution"] == {"met": 4, "breached": 2, "pending": 4, "compliance_pct": 66.7}
    assert sla["overall_compliance_pct"] == 80.0
    assert sla["breached_incidents"] == 2
    assert "Demonstration" in sla["note"]


def test_trends_and_repeated_incidents(client, seeded):
    trends = _get(client, "trends?days=14")
    assert len(trends) == 14
    assert sum(day["created"] for day in trends) == 10
    assert sum(day["P1"] for day in trends) == 2

    repeated = _get(client, "repeated-incidents?days=30")
    pairs = {(r["application_name"], r["category"]): r["occurrences"] for r in repeated}
    assert pairs == {
        ("Transaction Reconciliation", "BATCH_PROCESSING"): 2,
        ("Reporting & Data Warehouse", "PERFORMANCE"): 2,
    }


def test_analytics_filter_by_application(client, seeded):
    apps = {a["code"]: a["id"] for a in client.get("/api/applications", headers=headers()).json()}
    summary = _get(client, f"incident-summary?application_id={apps['PAY']}")
    assert summary["total_incidents"] == 2


def test_application_dependencies_and_reference_data(client, seeded):
    apps = {a["code"]: a["id"] for a in client.get("/api/applications", headers=headers()).json()}
    pay = client.get(f"/api/applications/{apps['PAY']}", headers=headers()).json()
    assert [d["depends_on"]["code"] for d in pay["dependencies"]] == ["CBS"]
    assert {a["code"] for a in pay["dependents"]} == {"CUS", "REC"}

    ref = client.get("/api/reference-data", headers=headers()).json()
    p1 = next(s for s in ref["severities"] if s["code"] == "P1")
    assert (p1["response_target_minutes"], p1["resolution_target_minutes"]) == (15, 60)
    assert "API_INTEGRATION" in ref["categories"]
