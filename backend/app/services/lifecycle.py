"""Incident lifecycle state machine.

    OPEN -> ASSIGNED -> INVESTIGATING -> RESOLVED -> CLOSED
    with ESCALATED, ON_HOLD and REOPENED as side states.
"""

from app.core.exceptions import InvalidTransitionError
from app.models.enums import IncidentStatus as S

ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    S.OPEN: frozenset({S.ASSIGNED, S.ESCALATED}),
    S.ASSIGNED: frozenset({S.INVESTIGATING, S.ESCALATED, S.ON_HOLD}),
    S.INVESTIGATING: frozenset({S.RESOLVED, S.ESCALATED, S.ON_HOLD}),
    S.ESCALATED: frozenset({S.ASSIGNED, S.INVESTIGATING, S.RESOLVED}),
    S.ON_HOLD: frozenset({S.ASSIGNED, S.INVESTIGATING}),
    S.RESOLVED: frozenset({S.CLOSED, S.REOPENED}),
    S.CLOSED: frozenset({S.REOPENED}),
    S.REOPENED: frozenset({S.ASSIGNED, S.INVESTIGATING, S.ESCALATED}),
}

# Leaving OPEN into any of these counts as the incident being acknowledged (response SLA).
ACKNOWLEDGING_STATUSES = frozenset({S.ASSIGNED, S.INVESTIGATING, S.ESCALATED, S.ON_HOLD})


def allowed_transitions(current: S) -> list[S]:
    return sorted(ALLOWED_TRANSITIONS[current])


def validate_transition(current: S, target: S) -> None:
    if target == current:
        raise InvalidTransitionError(f"Incident is already {current}")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(
            f"Cannot move incident from {current} to {target}",
            details={"current_status": current, "allowed": allowed_transitions(current)},
        )
