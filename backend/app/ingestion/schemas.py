"""Canonical dataset format.

Every data source (synthetic demo data today, BPI 2014 or live feeds later) is converted into
these records before it touches the database. A dataset is a folder of JSON files:

    manifest.json            DatasetManifest
    applications.json        [ApplicationIn]
    dependencies.json        [DependencyIn]          (optional)
    changes.json             [ChangeIn]              (optional)
    incidents.json           [IncidentIn]            (optional)
    operational_events.json  [OperationalEventIn]    (optional)

Timestamps are either absolute ISO-8601 or relative: {"minutes_ago": 65} / {"minutes_from_now": 1440}
(resolved at load time, so demo data always looks current). Incident history steps use `after_minutes` from creation.
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    MANUAL_EVENT_TYPES,
    ActionStatus,
    ActionType,
    BusinessCriticality,
    ChangeLinkStatus,
    ChangeStatus,
    ChangeType,
    DependencyType,
    EventType,
    EvidenceLevel,
    EvidenceType,
    HealthStatus,
    IncidentCategory,
    IncidentStatus,
    Priority,
    RcaStatus,
    RootCauseStatus,
    Severity,
)
from app.schemas.common import UtcDatetime

Code = Annotated[str, Field(min_length=1, max_length=20)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Text = Annotated[str, Field(min_length=1, max_length=10_000)]
Offset = Annotated[float, Field(ge=0)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")  # typos in dataset files fail loudly


class RelativeTime(Record):
    """Exactly one of minutes_ago (past) or minutes_from_now (future, e.g. a planned change)."""

    minutes_ago: float | None = Field(default=None, ge=0)
    minutes_from_now: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.minutes_ago is None) == (self.minutes_from_now is None):
            raise ValueError("give exactly one of minutes_ago / minutes_from_now")
        return self


TimePoint = UtcDatetime | RelativeTime


def resolve_time(value: TimePoint, now: datetime) -> datetime:
    if isinstance(value, RelativeTime):
        if value.minutes_ago is not None:
            return now - timedelta(minutes=value.minutes_ago)
        return now + timedelta(minutes=value.minutes_from_now)
    return value


class DatasetManifest(Record):
    name: str
    data_source: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{1,29}$")]
    description: str
    license: str | None = None
    citation: str | None = None
    # Applications already loaded by another source (same code) are referenced instead of failing.
    # Lets a larger dataset build on the demo environment without taking ownership of its apps.
    reuse_applications: bool = False


class ApplicationIn(Record):
    code: Code
    name: Annotated[str, Field(min_length=1, max_length=120)]
    business_criticality: BusinessCriticality
    description: str | None = None
    business_service: str | None = None
    technology_stack: str | None = None
    owner_team: Name | None = None
    health_status: HealthStatus = HealthStatus.UNKNOWN
    external_id: str | None = None


class DependencyIn(Record):
    application: Code
    depends_on: Code
    dependency_type: DependencyType
    is_critical: bool = False
    description: str | None = None


class ChangeIn(Record):
    change_reference: Code
    application: Code
    title: Annotated[str, Field(min_length=1, max_length=200)]
    change_type: ChangeType
    status: ChangeStatus
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    description: str | None = None
    version: str | None = None
    implementer: Name | None = None
    approver: Name | None = None
    rollback_plan: str | None = None
    components_changed: int | None = Field(default=None, ge=1, le=500)
    planned_start: TimePoint | None = None
    deployed_at: TimePoint | None = None
    external_id: str | None = None


# ---- incident history steps ---------------------------------------------------------------


class AssignStep(Record):
    type: Literal["assign"]
    after_minutes: Offset
    team: Name
    engineer: Name | None = None
    actor: Name = "incident.manager"


class StatusStep(Record):
    type: Literal["status"]
    after_minutes: Offset
    status: IncidentStatus
    note: str | None = None
    actor: Name | None = None  # defaults to the assigned engineer


class EventStep(Record):
    type: Literal["event"]
    after_minutes: Offset
    event_type: EventType
    description: Text
    actor: Name

    @model_validator(mode="after")
    def manual_types_only(self):
        if self.event_type not in MANUAL_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(MANUAL_EVENT_TYPES)}; others are system-generated")
        return self


HistoryStep = Annotated[AssignStep | StatusStep | EventStep, Field(discriminator="type")]


class ChangeLinkIn(Record):
    change_reference: Code
    link_status: ChangeLinkStatus = ChangeLinkStatus.SUSPECTED
    notes: str | None = None
    after_minutes: Offset = 20
    identified_by: Name | None = None


class RootCauseIn(Record):
    description: Text
    category: IncidentCategory | None = None
    status: RootCauseStatus = RootCauseStatus.HYPOTHESIS
    confidence: float | None = Field(default=None, ge=0, le=1)
    supporting_evidence: list[str] = []
    missing_evidence: list[str] = []
    created_by: Name
    confirmed_by: Name | None = None
    after_minutes: Offset = 30

    @model_validator(mode="after")
    def confirmation_needs_reviewer(self):
        if (self.status == RootCauseStatus.CONFIRMED) != (self.confirmed_by is not None):
            raise ValueError("confirmed_by is required exactly when status is CONFIRMED")
        return self


class ActionIn(Record):
    action_type: ActionType
    description: Text
    status: ActionStatus = ActionStatus.OPEN
    assigned_team: Name | None = None
    assigned_owner: Name | None = None
    due_in_days: int | None = Field(default=None, description="relative to incident creation")
    after_minutes: Offset = 35


class RcaIn(Record):
    summary: Text
    confirmed_facts: list[str] = []
    contributing_factors: list[str] = []
    missing_evidence: list[str] = []
    status: RcaStatus = RcaStatus.DRAFT
    approved_by: Name | None = None


class IncidentIn(Record):
    reference: Annotated[str, Field(pattern=r"^INC-\d{4,}$")] | None = None
    external_id: str | None = None
    application: Code
    title: Annotated[str, Field(min_length=5, max_length=200)]
    description: Text
    severity: Severity
    priority: Priority | None = None
    category: IncidentCategory
    business_impact: str | None = None
    created_by: Name
    created_at: TimePoint
    started_at: TimePoint
    resolution_summary: str | None = None
    history: list[HistoryStep] = []
    change_links: list[ChangeLinkIn] = []
    root_causes: list[RootCauseIn] = []
    actions: list[ActionIn] = []
    rca: RcaIn | None = None

    @model_validator(mode="after")
    def history_is_consistent(self):
        offsets = [step.after_minutes for step in self.history]
        if offsets != sorted(offsets):
            raise ValueError("history steps must be in chronological order")
        resolves = any(isinstance(s, StatusStep) and s.status == IncidentStatus.RESOLVED for s in self.history)
        if resolves and not self.resolution_summary:
            raise ValueError("resolution_summary is required when history resolves the incident")
        return self


class OperationalEventIn(Record):
    application: Code
    event_type: EvidenceType
    level: EvidenceLevel
    source_system: Annotated[str, Field(min_length=1, max_length=60)]
    message: Text
    occurred_at: TimePoint
    metric_name: str | None = None
    metric_value: float | None = None
    unit: str | None = None
    attributes: dict | None = None
    external_id: str | None = None

    @model_validator(mode="after")
    def metric_fields(self):
        if self.event_type == EvidenceType.METRIC and (self.metric_name is None or self.metric_value is None):
            raise ValueError("METRIC events need metric_name and metric_value")
        return self


class Dataset(BaseModel):
    manifest: DatasetManifest
    applications: list[ApplicationIn]
    dependencies: list[DependencyIn] = []
    changes: list[ChangeIn] = []
    incidents: list[IncidentIn] = []
    operational_events: list[OperationalEventIn] = []
