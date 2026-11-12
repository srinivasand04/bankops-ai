"""Severity definitions and default priority derivation.

Severity describes impact (and drives SLA targets); priority orders the work queue. Priority is
derived from severity, the business criticality of the affected application and the business
calendar (month-end close, payroll, ...) unless the caller sets it explicitly. The calendar never
changes severity, so SLA targets stay technical.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.models.enums import BusinessCriticality, CalendarPeriodType, Priority, Severity

SEVERITY_DEFINITIONS: dict[Severity, dict[str, str | list[str]]] = {
    Severity.P1: {
        "label": "Critical",
        "criteria": [
            "Critical banking service unavailable",
            "Payment processing completely unavailable",
            "Significant business disruption",
        ],
    },
    Severity.P2: {
        "label": "High",
        "criteria": [
            "Major functionality degraded",
            "Significant transaction delays",
            "Multiple users or services affected",
        ],
    },
    Severity.P3: {
        "label": "Medium",
        "criteria": ["Partial service degradation", "Limited application functionality affected"],
    },
    Severity.P4: {
        "label": "Low",
        "criteria": ["Minor application issue", "Limited operational impact"],
    },
}

_BASE_PRIORITY = {
    Severity.P1: Priority.CRITICAL,
    Severity.P2: Priority.HIGH,
    Severity.P3: Priority.MEDIUM,
    Severity.P4: Priority.LOW,
}
_ORDER = [Priority.LOW, Priority.MEDIUM, Priority.HIGH, Priority.CRITICAL]


class CalendarPeriodLike(Protocol):
    id: int
    name: str
    period_type: CalendarPeriodType
    starts_at: datetime
    raises_priority: bool


@dataclass(frozen=True)
class PriorityDecision:
    priority: Priority
    reason: str
    calendar_period_ids: list[int] = field(default_factory=list)


def derive_priority(severity: Severity, criticality: BusinessCriticality) -> Priority:
    """Tier 1 services are raised one level (P3 on Payments -> HIGH); Tier 3 lowered one level."""
    return decide_priority(severity, criticality).priority


def decide_priority(
    severity: Severity,
    criticality: BusinessCriticality,
    periods: Sequence[CalendarPeriodLike] = (),
    at: datetime | None = None,
) -> PriorityDecision:
    """Priority plus a human-readable reason.

    `periods` are the business-calendar periods active for the application at incident start (`at`).
    Any period with `raises_priority` adds one level - once, however many periods overlap; the others
    (bank holidays by default) are listed in the reason as context only.
    """
    index = _ORDER.index(_BASE_PRIORITY[severity])
    steps = [f"{severity} base priority {_ORDER[index]}"]
    tier = criticality.replace("TIER_", "Tier ")
    if criticality == BusinessCriticality.TIER_1:
        index = min(index + 1, len(_ORDER) - 1)
        steps.append(f"{tier} application +1 -> {_ORDER[index]}")
    elif criticality == BusinessCriticality.TIER_3 and severity != Severity.P1:
        index = max(index - 1, 0)
        steps.append(f"{tier} application -1 -> {_ORDER[index]}")

    def label(period: CalendarPeriodLike) -> str:
        if at is None:
            return period.name
        return f"{period.name}, day {(at.date() - period.starts_at.date()).days + 1}"

    raising = [p for p in periods if p.raises_priority]
    context = [p for p in periods if not p.raises_priority]
    if raising:
        before = _ORDER[index]
        index = min(index + 1, len(_ORDER) - 1)
        names = "; ".join(label(p) for p in raising)
        change = f"+1 -> {_ORDER[index]}" if _ORDER[index] != before else f"already {before} (highest)"
        steps.append(f"Business calendar ({names}) {change}")
    if context:
        steps.append("Context only, no change: " + "; ".join(label(p) for p in context))
    return PriorityDecision(_ORDER[index], " · ".join(steps), [p.id for p in periods])
