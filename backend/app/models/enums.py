"""Domain enumerations. Stored as VARCHAR + CHECK constraints (non-native enums) for easy migrations."""

from enum import StrEnum


class Severity(StrEnum):
    """Technical/business impact of the incident. Drives SLA targets."""

    P1 = "P1"  # Critical - critical banking service unavailable
    P2 = "P2"  # High - major functionality degraded
    P3 = "P3"  # Medium - partial degradation
    P4 = "P4"  # Low - minor issue


class Priority(StrEnum):
    """Order in which work is handled (impact x urgency). Separate from severity."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IncidentCategory(StrEnum):
    APPLICATION = "APPLICATION"
    DATABASE = "DATABASE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    NETWORK = "NETWORK"
    SECURITY = "SECURITY"
    BATCH_PROCESSING = "BATCH_PROCESSING"
    API_INTEGRATION = "API_INTEGRATION"
    THIRD_PARTY_SERVICE = "THIRD_PARTY_SERVICE"
    AUTHENTICATION = "AUTHENTICATION"
    PERFORMANCE = "PERFORMANCE"
    DATA_PROCESSING = "DATA_PROCESSING"


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    INVESTIGATING = "INVESTIGATING"
    ESCALATED = "ESCALATED"
    ON_HOLD = "ON_HOLD"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


ACTIVE_STATUSES = frozenset(
    {
        IncidentStatus.OPEN,
        IncidentStatus.ASSIGNED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.ESCALATED,
        IncidentStatus.ON_HOLD,
        IncidentStatus.REOPENED,
    }
)


class EventType(StrEnum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    ASSIGNED = "ASSIGNED"
    STATUS_CHANGED = "STATUS_CHANGED"
    SEVERITY_CHANGED = "SEVERITY_CHANGED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    ESCALATED = "ESCALATED"
    INVESTIGATION_UPDATE = "INVESTIGATION_UPDATE"
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    ROOT_CAUSE_HYPOTHESIS = "ROOT_CAUSE_HYPOTHESIS"
    ROOT_CAUSE_CONFIRMED = "ROOT_CAUSE_CONFIRMED"
    ROOT_CAUSE_REJECTED = "ROOT_CAUSE_REJECTED"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    PREVENTIVE_ACTION = "PREVENTIVE_ACTION"
    ACTION_UPDATED = "ACTION_UPDATED"
    CHANGE_LINKED = "CHANGE_LINKED"
    RCA_UPDATED = "RCA_UPDATED"
    SLA_BREACHED = "SLA_BREACHED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    COMMENT = "COMMENT"
    AI_ANALYSIS = "AI_ANALYSIS"


# Event types a user may post directly to the timeline; all others are system-generated.
MANUAL_EVENT_TYPES = frozenset({EventType.INVESTIGATION_UPDATE, EventType.EVIDENCE_ADDED, EventType.COMMENT})


class Source(StrEnum):
    """Who produced a record - used to separate AI output from human-verified facts."""

    HUMAN = "HUMAN"
    AI = "AI"
    SYSTEM = "SYSTEM"


class RootCauseStatus(StrEnum):
    HYPOTHESIS = "HYPOTHESIS"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class RcaStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"


class ActionType(StrEnum):
    CORRECTIVE = "CORRECTIVE"  # fixes the immediate incident
    PREVENTIVE = "PREVENTIVE"  # prevents recurrence


class ActionStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SlaState(StrEnum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"
    MET = "MET"


class EscalationStatus(StrEnum):
    NONE = "NONE"
    RECOMMENDED = "RECOMMENDED"  # SLA at risk or breached and not yet escalated
    ESCALATED = "ESCALATED"


class BusinessCriticality(StrEnum):
    TIER_1 = "TIER_1"  # critical banking service
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class CalendarPeriodType(StrEnum):
    """Business-calendar periods during which the same incident has a bigger business impact."""

    MONTH_END_CLOSE = "MONTH_END_CLOSE"
    QUARTER_END_CLOSE = "QUARTER_END_CLOSE"
    YEAR_END_CLOSE = "YEAR_END_CLOSE"
    PAYROLL = "PAYROLL"
    REGULATORY_DEADLINE = "REGULATORY_DEADLINE"
    PEAK_PERIOD = "PEAK_PERIOD"
    BANK_HOLIDAY = "BANK_HOLIDAY"  # context only by default: fewer staff, payment systems closed


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class DependencyType(StrEnum):
    API = "API"
    DATABASE = "DATABASE"
    BATCH_FEED = "BATCH_FEED"
    MESSAGE_QUEUE = "MESSAGE_QUEUE"
    AUTHENTICATION = "AUTHENTICATION"
    INFRASTRUCTURE = "INFRASTRUCTURE"


class ChangeType(StrEnum):
    STANDARD = "STANDARD"
    NORMAL = "NORMAL"
    EMERGENCY = "EMERGENCY"


class ChangeStatus(StrEnum):
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    IMPLEMENTED = "IMPLEMENTED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ChangeLinkStatus(StrEnum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    RULED_OUT = "RULED_OUT"


class DataSource(StrEnum):
    """Known data sources. Stored as plain text so new adapters need no migration."""

    MANUAL = "MANUAL"  # created through the API / UI
    SYNTHETIC = "SYNTHETIC"  # demo dataset in backend/datasets/synthetic
    BPI2014 = "BPI2014"  # Rabobank BPI Challenge 2014 subset (Phase 8)


class EvidenceType(StrEnum):
    """Operational evidence the investigation agents can retrieve."""

    METRIC = "METRIC"
    LOG = "LOG"
    ALERT = "ALERT"
    JOB_RUN = "JOB_RUN"
    HEALTH_CHECK = "HEALTH_CHECK"


class EvidenceLevel(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class InvestigationStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class AgentExecutionStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
