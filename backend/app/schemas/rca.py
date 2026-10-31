"""Root cause analysis and CAPA schemas."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    ActionStatus,
    ActionType,
    ChangeLinkStatus,
    IncidentCategory,
    RcaStatus,
    RootCauseStatus,
    Source,
)
from app.schemas.application import ChangeRecordOut
from app.schemas.common import EvidenceList, OrmModel, ShortText

LongText = Annotated[str, Field(min_length=5, max_length=5000)]
Notes = Annotated[str, Field(max_length=2000)]


# ---- Root causes --------------------------------------------------------------------------


class RootCauseCreate(BaseModel):
    description: LongText
    category: IncidentCategory | None = None
    # CONFIRMED is deliberately not accepted here: confirmation goes through the review endpoint.
    status: Literal[RootCauseStatus.HYPOTHESIS, RootCauseStatus.UNDER_REVIEW] = RootCauseStatus.HYPOTHESIS
    confidence: float | None = Field(default=None, ge=0, le=1)
    supporting_evidence: EvidenceList = []
    missing_evidence: EvidenceList = []


class RootCauseReview(BaseModel):
    decision: Literal["CONFIRM", "REJECT"]
    review_notes: Notes | None = None


class RootCauseOut(OrmModel):
    id: int
    incident_id: int
    description: str
    category: IncidentCategory | None
    status: RootCauseStatus
    source: Source
    confidence: float | None
    supporting_evidence: list[str]
    missing_evidence: list[str]
    created_by: str
    confirmed_by: str | None
    confirmed_at: datetime | None
    review_notes: str | None
    created_at: datetime


# ---- CAPA ---------------------------------------------------------------------------------


class ActionCreate(BaseModel):
    action_type: ActionType
    description: LongText
    assigned_team: ShortText | None = None
    assigned_owner: ShortText | None = None
    due_date: date | None = None


class ActionUpdate(BaseModel):
    description: LongText | None = None
    assigned_team: ShortText | None = None
    assigned_owner: ShortText | None = None
    due_date: date | None = None
    status: ActionStatus | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class ActionOut(OrmModel):
    id: int
    incident_id: int
    action_type: ActionType
    description: str
    assigned_team: str | None
    assigned_owner: str | None
    due_date: date | None
    status: ActionStatus
    completed_at: datetime | None
    is_overdue: bool
    source: Source
    created_by: str
    created_at: datetime
    updated_at: datetime


# ---- Related changes ----------------------------------------------------------------------


class RelatedChangeCreate(BaseModel):
    change_id: int = Field(gt=0)
    link_status: ChangeLinkStatus = ChangeLinkStatus.SUSPECTED
    notes: Notes | None = None


class RelatedChangeOut(OrmModel):
    id: int
    incident_id: int
    link_status: ChangeLinkStatus
    notes: str | None
    source: Source
    identified_by: str
    created_at: datetime
    change: ChangeRecordOut
    minutes_from_deployment_to_incident: float | None


# ---- RCA document -------------------------------------------------------------------------


class RcaUpdate(BaseModel):
    summary: LongText | None = None
    confirmed_facts: EvidenceList | None = None
    contributing_factors: EvidenceList | None = None
    missing_evidence: EvidenceList | None = None
    business_impact: LongText | None = None
    status: RcaStatus | None = None


class RcaOut(BaseModel):
    """Composite RCA view. Confirmed root causes and AI/human hypotheses are always kept apart."""

    incident_id: int
    incident_reference: str
    incident_summary: str
    status: RcaStatus
    summary: str | None
    confirmed_facts: list[str]
    contributing_factors: list[str]
    missing_evidence: list[str]
    business_impact: str | None
    confirmed_root_causes: list[RootCauseOut]
    hypotheses: list[RootCauseOut]
    rejected_root_causes: list[RootCauseOut]
    corrective_actions: list[ActionOut]
    preventive_actions: list[ActionOut]
    related_changes: list[RelatedChangeOut]
    updated_by: str | None
    approved_by: str | None
    approved_at: datetime | None
