"""Unit tests for pure business rules: lifecycle, priority derivation and SLA calculation."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.exceptions import InvalidTransitionError
from app.models import IncidentSla
from app.models.enums import BusinessCriticality, EscalationStatus, IncidentStatus as S, Priority, Severity, SlaState
from app.services import lifecycle, sla_service
from app.services.classification import derive_priority

T0 = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


# ---- lifecycle ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,target",
    [
        (S.OPEN, S.ASSIGNED),
        (S.ASSIGNED, S.INVESTIGATING),
        (S.INVESTIGATING, S.RESOLVED),
        (S.RESOLVED, S.CLOSED),
        (S.CLOSED, S.REOPENED),
        (S.REOPENED, S.ASSIGNED),
        (S.INVESTIGATING, S.ESCALATED),
        (S.ESCALATED, S.RESOLVED),
        (S.ASSIGNED, S.ON_HOLD),
        (S.ON_HOLD, S.INVESTIGATING),
    ],
)
def test_valid_transitions(current, target):
    lifecycle.validate_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        (S.OPEN, S.RESOLVED),
        (S.OPEN, S.CLOSED),
        (S.ASSIGNED, S.CLOSED),
        (S.INVESTIGATING, S.CLOSED),
        (S.CLOSED, S.INVESTIGATING),
        (S.RESOLVED, S.INVESTIGATING),
        (S.ON_HOLD, S.RESOLVED),
        (S.OPEN, S.OPEN),
    ],
)
def test_invalid_transitions_rejected(current, target):
    with pytest.raises(InvalidTransitionError):
        lifecycle.validate_transition(current, target)


def test_every_status_has_a_path_forward():
    assert set(lifecycle.ALLOWED_TRANSITIONS) == set(S)
    assert all(lifecycle.ALLOWED_TRANSITIONS[s] for s in S)


# ---- classification ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "severity,tier,expected",
    [
        (Severity.P1, BusinessCriticality.TIER_1, Priority.CRITICAL),
        (Severity.P2, BusinessCriticality.TIER_1, Priority.CRITICAL),
        (Severity.P3, BusinessCriticality.TIER_1, Priority.HIGH),
        (Severity.P2, BusinessCriticality.TIER_2, Priority.HIGH),
        (Severity.P3, BusinessCriticality.TIER_3, Priority.LOW),
        (Severity.P1, BusinessCriticality.TIER_3, Priority.CRITICAL),
        (Severity.P4, BusinessCriticality.TIER_3, Priority.LOW),
    ],
)
def test_priority_derivation(severity, tier, expected):
    assert derive_priority(severity, tier) == expected


# ---- SLA ---------------------------------------------------------------------------------


def _incident(severity=Severity.P1, acknowledged=None, resolved=None, status=S.INVESTIGATING):
    sla = sla_service.apply_targets(IncidentSla(), severity, T0)
    incident = SimpleNamespace(acknowledged_at=acknowledged, resolved_at=resolved, status=status, sla=sla)
    return incident, sla


@pytest.mark.parametrize(
    "severity,response,resolution",
    [(Severity.P1, 15, 60), (Severity.P2, 30, 240), (Severity.P3, 240, 1440), (Severity.P4, 480, 4320)],
)
def test_demo_sla_targets(severity, response, resolution):
    _, sla = _incident(severity)
    assert (sla.response_target_minutes, sla.resolution_target_minutes) == (response, resolution)
    assert sla.response_due_at == T0 + timedelta(minutes=response)
    assert sla.resolution_due_at == T0 + timedelta(minutes=resolution)


def test_sla_met_when_acknowledged_and_resolved_in_time():
    incident, sla = _incident(acknowledged=T0 + timedelta(minutes=10), resolved=T0 + timedelta(minutes=55))
    result = sla_service.evaluate(incident, sla, now=T0 + timedelta(hours=5))
    assert result.response.state == SlaState.MET
    assert result.response.actual_minutes == 10
    assert result.resolution.state == SlaState.MET
    assert result.resolution.actual_minutes == 55
    assert not result.is_breached


def test_sla_breach_detected_while_open():
    incident, sla = _incident(acknowledged=None)
    result = sla_service.evaluate(incident, sla, now=T0 + timedelta(minutes=20))
    assert result.response.state == SlaState.BREACHED
    assert result.response.remaining_minutes == -5
    assert result.resolution.state == SlaState.ON_TRACK
    assert result.resolution.remaining_minutes == 40
    assert result.is_breached
    assert result.escalation_status == EscalationStatus.RECOMMENDED


def test_sla_at_risk_after_warning_threshold():
    incident, sla = _incident(acknowledged=T0 + timedelta(minutes=5))
    result = sla_service.evaluate(incident, sla, now=T0 + timedelta(minutes=50))  # 83% of 60 min
    assert result.resolution.state == SlaState.AT_RISK
    assert result.escalation_status == EscalationStatus.RECOMMENDED


def test_late_resolution_is_breach():
    incident, sla = _incident(acknowledged=T0 + timedelta(minutes=5), resolved=T0 + timedelta(minutes=90))
    result = sla_service.evaluate(incident, sla, now=T0 + timedelta(minutes=95))
    assert result.resolution.state == SlaState.BREACHED
    assert result.resolution.actual_minutes == 90


def test_escalated_status_reported():
    incident, sla = _incident(status=S.ESCALATED, acknowledged=T0 + timedelta(minutes=1))
    assert sla_service.evaluate(incident, sla, T0 + timedelta(minutes=2)).escalation_status == EscalationStatus.ESCALATED


def test_refresh_breach_flags_reports_new_breaches_once():
    incident, sla = _incident(acknowledged=None)
    assert sla_service.refresh_breach_flags(incident, sla, T0 + timedelta(minutes=20)) == ["response"]
    assert sla.response_breached is True and sla.resolution_breached is None
    assert sla_service.refresh_breach_flags(incident, sla, T0 + timedelta(minutes=21)) == []


def test_sla_targets_are_configurable(monkeypatch):
    from app.core.config import SlaTarget, get_settings

    monkeypatch.setitem(get_settings().sla_targets, "P1", SlaTarget(response=5, resolution=30))
    _, sla = _incident(Severity.P1)
    assert (sla.response_target_minutes, sla.resolution_target_minutes) == (5, 30)
