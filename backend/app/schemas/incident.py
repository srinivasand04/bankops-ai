from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    EscalationStatus,
    EventType,
    IncidentCategory,
    IncidentStatus,
    Priority,
    Severity,
    SlaState,
    Source,
)
from app.schemas.application import ApplicationRef
from app.schemas.common import NonEmptyStr, OrmModel, PastUtcDatetime, ShortText

Title = Annotated[str, Field(min_length=5, max_length=200)]
Description = Annotated[str, Field(min_length=10, max_length=10_000)]
ImpactText = Annotated[str, Field(max_length=5_000)]


class IncidentCreate(BaseModel):
    title: Title
    description: Description
    application_id: int = Field(gt=0)
    severity: Severity
    category: IncidentCategory
    priority: Priority | None = Field(
        default=None, description="Derived from severity and application criticality when omitted"
    )
    business_impact: ImpactText | None = None
    started_at: PastUtcDatetime | None = Field(default=None, description="When impact began; defaults to now")
    assigned_team: ShortText | None = None
    assigned_engineer: ShortText | None = None


class IncidentUpdate(BaseModel):
    """Partial update of descriptive / classification fields. Status and assignment have their own endpoints."""

    title: Title | None = None
    description: Description | None = None
    severity: Severity | None = None
    priority: Priority | None = None
    category: IncidentCategory | None = None
    business_impact: ImpactText | None = None
    started_at: PastUtcDatetime | None = None
    reason: Annotated[str, Field(max_length=1000)] | None = Field(
        default=None, description="Recorded on the timeline, recommended for severity changes"
    )

    @model_validator(mode="after")
    def at_least_one_field(self):
        if not self.model_fields_set - {"reason"}:
            raise ValueError("at least one field must be provided")
        return self


class StatusChange(BaseModel):
    status: IncidentStatus
    note: Annotated[str, Field(max_length=2000)] | None = None
    resolution_summary: Annotated[str, Field(min_length=10, max_length=5000)] | None = Field(
        default=None, description="Required when moving to RESOLVED (unless already set)"
    )


class AssignmentChange(BaseModel):
    assigned_team: ShortText
    assigned_engineer: ShortText | None = None
    note: Annotated[str, Field(max_length=2000)] | None = None


class SlaClockOut(BaseModel):
    state: SlaState
    target_minutes: int
    due_at: datetime
    elapsed_minutes: float
    remaining_minutes: float
    actual_minutes: float | None


class SlaOut(BaseModel):
    severity: Severity
    clock_started_at: datetime
    response: SlaClockOut
    resolution: SlaClockOut
    is_breached: bool
    escalation_status: EscalationStatus
    note: str = "Demonstration SLA targets - not universal banking requirements"


class IncidentOut(OrmModel):
    id: int
    reference_number: str
    title: str
    description: str
    application: ApplicationRef
    application_name: str
    severity: Severity
    priority: Priority
    category: IncidentCategory
    status: IncidentStatus
    assigned_team: str | None
    assigned_engineer: str | None
    business_impact: str | None
    resolution_summary: str | None
    reopen_count: int
    created_by: str
    data_source: str
    external_id: str | None
    started_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    sla: SlaOut | None


class IncidentDetailOut(IncidentOut):
    allowed_transitions: list[IncidentStatus]
    root_cause_count: int
    open_action_count: int


class EventCreate(BaseModel):
    event_type: EventType = Field(description="INVESTIGATION_UPDATE, EVIDENCE_ADDED or COMMENT")
    description: Annotated[str, Field(min_length=3, max_length=5000)]
    details: dict | None = None


class EventOut(OrmModel):
    id: int
    incident_id: int
    event_type: EventType
    description: NonEmptyStr
    details: dict | None
    source: Source
    created_by: str
    created_at: datetime
