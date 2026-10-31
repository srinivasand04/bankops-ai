"""Structured output contract for Claude, and API schemas for investigations.

The output models are sent to Claude as a JSON schema (structured outputs), so the response is
guaranteed to parse. They deliberately carry no numeric/length constraints - those are enforced
afterwards by the guardrails in analysis_service, which can explain what they changed.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import ActionType, AgentExecutionStatus, IncidentCategory, InvestigationStatus, Severity

# ---- what Claude returns -----------------------------------------------------------------


class CitedFact(BaseModel):
    statement: str = Field(description="A fact directly supported by the context data")
    evidence_ids: list[str] = Field(description="IDs of the context items that prove the statement")


class RootCauseHypothesis(BaseModel):
    description: str
    category: IncidentCategory
    confidence: float = Field(description="0.0 - 1.0, how strongly the evidence supports this hypothesis")
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    missing_evidence: list[str] = Field(description="Evidence that would confirm or refute the hypothesis")
    verification_steps: list[str] = Field(description="How a human engineer can verify it")


class AffectedService(BaseModel):
    application_code: str
    impact: str
    evidence_ids: list[str]


class BusinessImpactAssessment(BaseModel):
    summary: str
    customer_impact: str
    regulatory_or_financial_exposure: str
    assessed_severity: Severity
    severity_rationale: str


class RecommendedAction(BaseModel):
    action_type: ActionType = Field(description="CORRECTIVE fixes this incident; PREVENTIVE stops recurrence")
    description: str
    owner_team: str
    urgency: Literal["IMMEDIATE", "SHORT_TERM", "LONG_TERM"]
    requires_human_approval: bool
    approval_reason: str | None


class EscalationRecommendation(BaseModel):
    recommended: bool
    reason: str


class IncidentAnalysis(BaseModel):
    summary: str
    confirmed_facts: list[CitedFact]
    root_cause_hypotheses: list[RootCauseHypothesis]
    affected_services: list[AffectedService]
    business_impact: BusinessImpactAssessment
    recommended_actions: list[RecommendedAction]
    escalation: EscalationRecommendation
    missing_information: list[str]
    overall_confidence: Literal["LOW", "MEDIUM", "HIGH"]


# ---- API ---------------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    focus: str | None = Field(
        default=None, max_length=1000, description="Optional question or angle, e.g. 'Was release 2.4.1 the cause?'"
    )


class ReviewRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    review_notes: str | None = Field(default=None, max_length=2000)
    apply_hypotheses: bool = Field(default=True, description="On approval, record hypotheses on the incident")
    apply_actions: bool = Field(default=True, description="On approval, create CAPA actions from recommendations")


class AgentExecutionOut(BaseModel):
    agent_name: str
    step_order: int
    status: AgentExecutionStatus
    tool_calls: list[dict]
    input_tokens: int | None
    output_tokens: int | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class InvestigationOut(BaseModel):
    id: int
    incident_id: int | None
    incident_reference: str | None
    status: InvestigationStatus
    request_text: str
    agents_selected: list[str]
    model_name: str | None
    report: dict | None
    error_message: str | None
    requested_by: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime
    completed_at: datetime | None
    executions: list[AgentExecutionOut]


class AiStatusOut(BaseModel):
    provider: Literal["anthropic", "ollama"]
    model: str
    ready: bool
    detail: str
    cost: str
