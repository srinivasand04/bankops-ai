"""SLA calculation.

The SLA clock starts when the incident is logged (`clock_started_at`). Response is measured to
`acknowledged_at`, resolution to `resolved_at`. Targets come from settings and are demonstration
values only. Pausing the clock while ON_HOLD is intentionally out of scope for the MVP.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.models.enums import EscalationStatus, IncidentStatus, Severity, SlaState
from app.models.incident import Incident, IncidentSla
from app.utils.time import minutes_between


@dataclass(frozen=True)
class SlaClock:
    state: SlaState
    target_minutes: int
    due_at: datetime
    elapsed_minutes: float
    remaining_minutes: float  # negative once overdue; 0 once met
    actual_minutes: float | None  # time to acknowledge / resolve, when known


@dataclass(frozen=True)
class SlaEvaluation:
    severity: Severity
    response: SlaClock
    resolution: SlaClock
    escalation_status: EscalationStatus

    @property
    def is_breached(self) -> bool:
        return SlaState.BREACHED in (self.response.state, self.resolution.state)


def targets_for(severity: Severity) -> tuple[int, int]:
    target = get_settings().sla_targets[severity.value]
    return target.response, target.resolution


def apply_targets(sla: IncidentSla, severity: Severity, clock_started_at: datetime) -> IncidentSla:
    """(Re)compute targets and due dates. Used at creation and whenever severity changes."""
    response, resolution = targets_for(severity)
    sla.severity = severity
    sla.clock_started_at = clock_started_at
    sla.response_target_minutes = response
    sla.resolution_target_minutes = resolution
    sla.response_due_at = clock_started_at + timedelta(minutes=response)
    sla.resolution_due_at = clock_started_at + timedelta(minutes=resolution)
    sla.response_breached = None
    sla.resolution_breached = None
    return sla


def _clock(started: datetime, due: datetime, target: int, completed_at: datetime | None, now: datetime) -> SlaClock:
    end = completed_at or now
    elapsed = minutes_between(started, end)
    if completed_at is not None:
        state = SlaState.MET if completed_at <= due else SlaState.BREACHED
        remaining = 0.0
    else:
        remaining = minutes_between(now, due)
        if now > due:
            state = SlaState.BREACHED
        elif elapsed >= target * get_settings().sla_warning_threshold:
            state = SlaState.AT_RISK
        else:
            state = SlaState.ON_TRACK
    return SlaClock(
        state=state,
        target_minutes=target,
        due_at=due,
        elapsed_minutes=round(elapsed, 1),
        remaining_minutes=round(remaining, 1),
        actual_minutes=round(elapsed, 1) if completed_at is not None else None,
    )


def evaluate(incident: Incident, sla: IncidentSla, now: datetime) -> SlaEvaluation:
    response = _clock(
        sla.clock_started_at, sla.response_due_at, sla.response_target_minutes, incident.acknowledged_at, now
    )
    resolution = _clock(
        sla.clock_started_at, sla.resolution_due_at, sla.resolution_target_minutes, incident.resolved_at, now
    )
    if incident.status == IncidentStatus.ESCALATED:
        escalation = EscalationStatus.ESCALATED
    elif incident.resolved_at is None and (
        response.state in (SlaState.AT_RISK, SlaState.BREACHED)
        or resolution.state in (SlaState.AT_RISK, SlaState.BREACHED)
    ):
        escalation = EscalationStatus.RECOMMENDED
    else:
        escalation = EscalationStatus.NONE
    return SlaEvaluation(severity=sla.severity, response=response, resolution=resolution, escalation_status=escalation)


def refresh_breach_flags(incident: Incident, sla: IncidentSla, now: datetime) -> list[str]:
    """Persist outcome flags. Returns the SLA kinds ("response"/"resolution") that newly breached."""
    evaluation = evaluate(incident, sla, now)
    newly_breached: list[str] = []
    for kind, clock in (("response", evaluation.response), ("resolution", evaluation.resolution)):
        attr = f"{kind}_breached"
        if clock.state == SlaState.BREACHED:
            if getattr(sla, attr) is not True:
                newly_breached.append(kind)
            setattr(sla, attr, True)
        elif clock.state == SlaState.MET:
            setattr(sla, attr, False)
        else:
            setattr(sla, attr, None)
    return newly_breached
