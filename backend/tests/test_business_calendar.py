"""Business calendar: demo calendar dates, calendar-aware priority, API and loading."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.ingestion.loader import load_dataset
from app.ingestion.reader import read_dataset
from app.models import BusinessCalendarPeriod, Incident
from app.models.enums import BusinessCriticality, CalendarPeriodType, Priority, Severity
from app.services.business_calendar import demo_calendar, easter_sunday, seed_demo_calendar
from app.services.classification import decide_priority, derive_priority
from app.services.user_service import ensure_default_users
from app.utils.time import utcnow
from tests.conftest import SYNTHETIC_DATASET, headers

ADMIN = {"X-User-Name": "srinivasan.d"}
START = datetime(2026, 11, 30, tzinfo=UTC)


def _period(pid=1, raises=True, kind=CalendarPeriodType.MONTH_END_CLOSE, name="Month-end close Nov 2026"):
    return SimpleNamespace(id=pid, name=name, period_type=kind, starts_at=START, raises_priority=raises)


# ---- demonstration calendar ------------------------------------------------------------------


def test_easter_dates():
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert easter_sunday(2027) == date(2027, 3, 28)


def test_demo_calendar_uses_french_working_days():
    by_key = {p.external_id: p for p in demo_calendar([2026])}

    def window(key):
        p = by_key[key]
        return p.starts_at.date(), p.ends_at.date()

    # Nov 2026: last working day Mon 30 Nov, 3rd working day of December is Thu 3 Dec (end exclusive)
    assert window("MEC-2026-11") == (date(2026, 11, 30), date(2026, 12, 4))
    # Year-end: Thu 31 Dec to the 10th working day of January (1 Jan is a holiday) = Fri 15 Jan
    assert window("YEC-2026") == (date(2026, 12, 31), date(2027, 1, 16))
    # 25 Oct 2026 is a Sunday -> salaries on Fri 23 Oct, window Thu 22 to Mon 26
    assert window("PAY-2026-10") == (date(2026, 10, 22), date(2026, 10, 27))
    # Q3 regulatory remittance on 11 Nov (a holiday itself): window starts 3 working days earlier
    assert window("REG-2026-Q3") == (date(2026, 11, 6), date(2026, 11, 12))
    assert window("PEAK-2026-BF") == (date(2026, 11, 27), date(2026, 12, 1))

    holiday = by_key["HOL-2026-12-25"]
    assert holiday.period_type == CalendarPeriodType.BANK_HOLIDAY
    assert (holiday.raises_priority, holiday.application_codes) == (False, [])
    assert by_key["T2-2026-04-03"].application_codes == ["PAY", "TRS", "REC"]  # Good Friday, TARGET2 closed
    assert "MEC-2026-12" not in by_key and "MEC-2026-09" not in by_key  # covered by year / quarter-end close


# ---- priority rule ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "tier", "periods", "expected"),
    [
        (Severity.P3, BusinessCriticality.TIER_2, [], Priority.MEDIUM),
        (Severity.P3, BusinessCriticality.TIER_2, [_period()], Priority.HIGH),
        (Severity.P3, BusinessCriticality.TIER_3, [_period()], Priority.MEDIUM),  # LOW after tier, +1
        (Severity.P1, BusinessCriticality.TIER_1, [_period()], Priority.CRITICAL),  # already the highest
        (Severity.P4, BusinessCriticality.TIER_2, [_period(1), _period(2, kind=CalendarPeriodType.PAYROLL)], Priority.MEDIUM),
        (Severity.P3, BusinessCriticality.TIER_2, [_period(raises=False, kind=CalendarPeriodType.BANK_HOLIDAY)], Priority.MEDIUM),
    ],
)
def test_calendar_raises_priority_once(severity, tier, periods, expected):
    assert decide_priority(severity, tier, periods).priority == expected


def test_decision_reason_explains_each_step():
    decision = decide_priority(
        Severity.P3, BusinessCriticality.TIER_1,
        [_period(7), _period(8, raises=False, kind=CalendarPeriodType.BANK_HOLIDAY, name="Bank holiday: Christmas Day")],
        at=START + timedelta(days=1, hours=9),
    )
    assert decision.priority == Priority.CRITICAL
    assert decision.calendar_period_ids == [7, 8]
    assert decision.reason == (
        "P3 base priority MEDIUM · Tier 1 application +1 -> HIGH"
        " · Business calendar (Month-end close Nov 2026, day 2) +1 -> CRITICAL"
        " · Context only, no change: Bank holiday: Christmas Day, day 2"
    )


def test_derive_priority_without_calendar_is_unchanged():
    assert derive_priority(Severity.P3, BusinessCriticality.TIER_1) == Priority.HIGH
    assert decide_priority(Severity.P3, BusinessCriticality.TIER_2).reason == "P3 base priority MEDIUM"


# ---- API -------------------------------------------------------------------------------------


@pytest.fixture
def admin(db):
    ensure_default_users(db)


def _add(client, **body):
    now = utcnow()
    payload = {
        "name": "Month-end close (test)", "period_type": "MONTH_END_CLOSE",
        "starts_at": (now - timedelta(days=1)).isoformat(), "ends_at": (now + timedelta(days=1)).isoformat(),
        "application_codes": ["rec"],
    } | body
    return client.post("/api/business-calendar", json=payload, headers=ADMIN)


def test_incident_in_month_end_close_gets_higher_priority(client, admin, create_incident, applications):
    period = _add(client)
    assert period.status_code == 201, period.text
    assert period.json()["application_codes"] == ["REC"] and period.json()["raises_priority"] is True

    raised = create_incident(application_id=applications["REC"].id, severity="P3", category="BATCH_PROCESSING")
    assert raised["priority"] == "HIGH"  # P3 on Tier 2 = MEDIUM, +1 for month-end close
    assert "Month-end close (test), day 2" in raised["priority_reason"]
    created = client.get(f"/api/incidents/{raised['id']}/timeline", headers=headers()).json()[0]
    assert created["details"]["calendar_period_ids"] == [period.json()["id"]]

    other_app = create_incident(application_id=applications["CUS"].id, severity="P3", category="APPLICATION")
    assert other_app["priority"] == "MEDIUM"  # the period only covers REC
    assert other_app["priority_reason"] == "P3 base priority MEDIUM"


def test_bank_holiday_is_context_only(client, admin, create_incident, applications):
    holiday = _add(client, name="Bank holiday: test", period_type="BANK_HOLIDAY", application_codes=[])
    assert holiday.json()["raises_priority"] is False
    incident = create_incident(application_id=applications["REC"].id, severity="P3", category="BATCH_PROCESSING")
    assert incident["priority"] == "MEDIUM"
    assert "Context only, no change: Bank holiday: test" in incident["priority_reason"]


def test_manual_priority_records_who_set_it(client, admin, create_incident, applications):
    _add(client)
    incident = create_incident(application_id=applications["REC"].id, severity="P3", category="BATCH_PROCESSING",
                               priority="LOW")
    assert incident["priority"] == "LOW"
    assert incident["priority_reason"] == "Set manually by test.manager (calculated: HIGH)"

    updated = client.put(f"/api/incidents/{incident['id']}", json={"priority": "CRITICAL", "reason": "Regulator call"},
                           headers=headers())
    assert updated.status_code == 200
    assert updated.json()["priority_reason"] == "Set manually by test.manager: Regulator call"


def test_active_endpoint_previews_priority(client, admin, applications):
    _add(client)
    body = client.get("/api/business-calendar/active",
                      params={"application_id": applications["REC"].id, "severity": "P3"}, headers=headers()).json()
    assert [p["name"] for p in body["periods"]] == ["Month-end close (test)"]
    assert body["priority_preview"]["priority"] == "HIGH"

    listed = client.get("/api/business-calendar", params={"application": "cus"}, headers=headers()).json()
    assert listed == []


def test_only_admins_change_the_calendar(client, admin, applications):
    assert client.post("/api/business-calendar", json={}, headers=headers("ENGINEER", "engineer")).status_code == 403
    assert _add(client, application_codes=["NOPE"]).status_code == 422
    now = utcnow().isoformat()
    assert _add(client, starts_at=now, ends_at=now).status_code == 422

    period_id = _add(client).json()["id"]
    renamed = client.put(f"/api/business-calendar/{period_id}", headers=ADMIN, json={
        "name": "Quarter-end close (test)", "period_type": "QUARTER_END_CLOSE",
        "starts_at": "2026-09-30T00:00:00Z", "ends_at": "2026-10-08T00:00:00Z",
    })
    assert renamed.status_code == 200 and renamed.json()["application_codes"] == []
    assert client.delete(f"/api/business-calendar/{period_id}", headers=ADMIN).status_code == 204
    assert client.delete(f"/api/business-calendar/{period_id}", headers=ADMIN).status_code == 404


# ---- seeding and loading ---------------------------------------------------------------------


def test_seed_is_idempotent(db):
    added = seed_demo_calendar(db, [2026])
    assert added > 0
    assert seed_demo_calendar(db, [2026]) == 0
    assert seed_demo_calendar(db, [2026], replace=True) == added
    assert db.query(BusinessCalendarPeriod).count() == added


def test_loader_applies_calendar_to_derived_priorities(db):
    now = utcnow()
    db.add(BusinessCalendarPeriod(
        name="Everything is sensitive (test)", period_type=CalendarPeriodType.PEAK_PERIOD,
        starts_at=now - timedelta(days=400), ends_at=now + timedelta(days=1), application_codes=[],
    ))
    db.commit()
    load_dataset(db, read_dataset(SYNTHETIC_DATASET))
    incidents = db.query(Incident).all()
    assert incidents and all("Business calendar (Everything is sensitive (test)" in i.priority_reason for i in incidents)


# ---- AI evidence (Phase B) - no model is called -----------------------------------------------


def _calendar_around(db, incident, **extra):
    period = BusinessCalendarPeriod(
        name="Month-end close (AI test)", period_type=CalendarPeriodType.MONTH_END_CLOSE,
        starts_at=incident.started_at - timedelta(days=1), ends_at=incident.started_at + timedelta(days=2),
        application_codes=[incident.application.code], description="General ledger close", **extra,
    )
    other_app = BusinessCalendarPeriod(
        name="Not this application", period_type=CalendarPeriodType.PAYROLL,
        starts_at=period.starts_at, ends_at=period.ends_at, application_codes=["ZZZ"],
    )
    db.add_all([period, other_app])
    db.commit()
    return period


def test_calendar_periods_are_citable_evidence(db, seeded):
    from app.ai.compact import compact_context
    from app.ai.context import build_incident_context

    incident = db.query(Incident).filter_by(reference_number="INC-1007").one()
    period = _calendar_around(db, incident)
    ctx = build_incident_context(db, incident)

    periods = ctx.data["business_calendar"]["periods"]
    assert [p["id"] for p in periods] == [f"CAL-{period.id}"]  # the ZZZ period is filtered out
    assert periods[0]["active_at_incident_start"] is True and periods[0]["day_of_period"] == 2
    assert f"CAL-{period.id}" in ctx.valid_ids and ctx.counts()["business_calendar"] == 1
    assert "priority_reason" in ctx.data["incident"]
    assert f"CAL-{period.id}" in compact_context(ctx).valid_ids  # small local models see it too


def test_operational_risk_agent_has_calendar_tool(db, seeded):
    from app.ai.agents.definitions import OPERATIONAL_RISK
    from app.ai.context import build_incident_context
    from app.ai.tools.incident_tools import Toolkit, call_tool

    assert "get_business_calendar" in OPERATIONAL_RISK.tools
    incident = db.query(Incident).filter_by(reference_number="INC-1007").one()
    period = _calendar_around(db, incident)
    result = call_tool(Toolkit(db, incident, build_incident_context(db, incident)), "get_business_calendar")
    assert result["periods"][0]["id"] == f"CAL-{period.id}" and result["priority"] == incident.priority
