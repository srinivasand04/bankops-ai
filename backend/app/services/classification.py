"""Severity definitions and default priority derivation.

Severity describes impact (and drives SLA targets); priority orders the work queue. Priority is
derived from severity and the business criticality of the affected application unless the caller
sets it explicitly.
"""

from app.models.enums import BusinessCriticality, Priority, Severity

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


def derive_priority(severity: Severity, criticality: BusinessCriticality) -> Priority:
    """Tier 1 services are raised one level (P3 on Payments -> HIGH); Tier 3 lowered one level."""
    index = _ORDER.index(_BASE_PRIORITY[severity])
    if criticality == BusinessCriticality.TIER_1:
        index = min(index + 1, len(_ORDER) - 1)
    elif criticality == BusinessCriticality.TIER_3 and severity != Severity.P1:
        index = max(index - 1, 0)
    return _ORDER[index]
