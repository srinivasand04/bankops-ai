"""Management reports over the synthetic dataset."""

import pytest

from tests.conftest import headers

REPORTS = ["scorecard", "sla", "trends", "change-risk", "problems", "management-pack"]


def _get(client, name, days=365):
    r = client.get(f"/api/reports/{name}?days={days}", headers=headers("VIEWER", "risk.viewer"))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("name", REPORTS)
def test_every_report_is_readable_by_a_viewer(client, seeded, name):
    assert _get(client, name)["period"]["days"] == 365


def test_period_is_validated(client, seeded):
    assert client.get("/api/reports/scorecard?days=3", headers=headers()).status_code == 422
    assert client.get("/api/reports/scorecard?days=400", headers=headers()).status_code == 422


def test_scorecard_covers_every_application(client, seeded):
    s = _get(client, "scorecard")
    codes = {a["code"] for a in s["applications"]}
    assert {"PAY", "CBS", "CUS", "REC", "RDW"} <= codes
    assert s["totals"]["applications"] == len(s["applications"])
    assert s["totals"]["incidents"] == sum(a["incidents"] for a in s["applications"])
    assert all(a["rag"] in {"RED", "AMBER", "GREEN"} for a in s["applications"])
    # RED rows come first, then AMBER, then GREEN
    order = [{"RED": 0, "AMBER": 1, "GREEN": 2}[a["rag"]] for a in s["applications"]]
    assert order == sorted(order)
    pay = next(a for a in s["applications"] if a["code"] == "PAY")
    assert pay["tier"] == "TIER_1" and pay["p1"] >= 1 and pay["changes"] >= 1


def test_sla_report_counts_add_up(client, seeded):
    s = _get(client, "sla")
    res = s["overall"]["resolution"]
    assert res["met"] + res["breached"] + res["pending"] == sum(r["incidents"] for r in s["by_severity"])
    assert [r["severity"] for r in s["by_severity"]] == ["P1", "P2", "P3", "P4"]
    for b in s["breaching_now"]:
        assert b["overdue_minutes"] >= 0
    assert s["breaching_now"] == sorted(s["breaching_now"], key=lambda b: -b["overdue_minutes"])


def test_trends_granularity_follows_period(client, seeded):
    assert _get(client, "trends", 90)["granularity"] == "week"
    yearly = _get(client, "trends", 365)
    assert yearly["granularity"] == "month"
    assert sum(p["created"] for p in yearly["points"]) == _get(client, "scorecard")["totals"]["incidents"]


def test_change_risk_links_release_to_incident(client, seeded):
    c = _get(client, "change-risk")
    top = {ch["reference"]: ch for ch in c["top_changes"]}
    assert "CHG-2041" in top and "INC-1007" in top["CHG-2041"]["incidents"]
    pay = next(a for a in c["by_application"] if a["code"] == "PAY")
    assert pay["changes_with_incidents"] >= 1 and pay["change_failure_rate_pct"] > 0


def test_problems_report_shape(client, seeded):
    p = _get(client, "problems")
    assert p["threshold"] == 3
    for r in p["recurring"]:
        assert r["occurrences"] >= 3 and len(r["latest_references"]) <= 5


def test_management_pack_contains_all_five(client, seeded):
    pack = _get(client, "management-pack", 90)
    assert set(pack) == {"period", "scorecard", "sla", "trends", "change_risk", "problems"}
