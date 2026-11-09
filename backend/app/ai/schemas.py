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
    statement: str = Field(description="One fact the data directly shows (timing, values, messages) - not an interpretation")
    evidence_ids: list[str] = Field(description="ids of the fact-base items that prove the statement")


class RootCauseHypothesis(BaseModel):
    description: str = Field(description="The candidate cause and the mechanism, in one or two sentences")
    category: IncidentCategory = Field(
        description="Where the fault lies: APPLICATION for code or configuration shipped in a release, "
        "INFRASTRUCTURE for servers, storage or platform, DATABASE for the database itself"
    )
    confidence: float = Field(description="0.0 - 1.0, how strongly the evidence supports this hypothesis")
    supporting_evidence_ids: list[str] = Field(description="ids of items that support it")
    contradicting_evidence_ids: list[str] = Field(description="ids of items that argue against it")
    missing_evidence: list[str] = Field(description="Evidence that would confirm or refute the hypothesis")
    verification_steps: list[str] = Field(description="How a human engineer can verify it")


class AffectedService(BaseModel):
    application_code: str = Field(description="Application code from the fact base, e.g. PAY")
    impact: str = Field(description="One sentence on how this service is affected, with the observed symptom")
    evidence_ids: list[str] = Field(description="ids of items that show the impact")


class BusinessImpactAssessment(BaseModel):
    summary: str = Field(description="One or two sentences on the business impact (not a single word)")
    customer_impact: str = Field(description="Who is affected and how")
    regulatory_or_financial_exposure: str = Field(description="Financial, regulatory or reporting exposure")
    assessed_severity: Severity = Field(description="Severity the evidence supports (may differ from recorded)")
    severity_rationale: str = Field(description="Why that severity")


class RecommendedAction(BaseModel):
    action_type: ActionType = Field(description="CORRECTIVE fixes this incident; PREVENTIVE stops recurrence")
    description: str = Field(description="A concrete action an engineer can carry out")
    owner_team: str = Field(description="Team that should own the action")
    urgency: Literal["IMMEDIATE", "SHORT_TERM", "LONG_TERM"]
    requires_human_approval: bool = Field(description="true for anything that changes production")
    approval_reason: str | None = Field(description="Why approval is needed, or null")


class EscalationRecommendation(BaseModel):
    recommended: bool
    reason: str = Field(description="Why escalation is or is not recommended now")


class IncidentAnalysis(BaseModel):
    summary: str = Field(
        description="Two or three sentences that directly answer the incident team's request first "
        "(for example 'Most likely yes - ...'), then state the most likely cause and the current impact"
    )
    confirmed_facts: list[CitedFact] = Field(description="Facts directly shown by the data, each with citations")
    root_cause_hypotheses: list[RootCauseHypothesis] = Field(description="Candidate causes, most likely first")
    affected_services: list[AffectedService] = Field(description="Impacted applications")
    business_impact: BusinessImpactAssessment
    recommended_actions: list[RecommendedAction] = Field(description="Corrective and preventive actions")
    escalation: EscalationRecommendation
    missing_information: list[str] = Field(description="Data that is not in the fact base but would help")
    overall_confidence: Literal["LOW", "MEDIUM", "HIGH"] = Field(description="Confidence in the analysis as a whole")


def field_guide(model: type[BaseModel] = IncidentAnalysis, indent: str = "") -> str:
    """Plain-text list of fields and descriptions - for models that only receive the schema as a grammar."""
    lines = []
    for name, info in model.model_fields.items():
        # list[CitedFact] -> CitedFact; plain types pass through
        nested = (getattr(info.annotation, "__args__", None) or (info.annotation,))[0]
        lines.append(f"{indent}- {name}" + (f": {info.description}" if info.description else ""))
        if isinstance(nested, type) and issubclass(nested, BaseModel):
            lines.append(field_guide(nested, indent + "  "))
    return "\n".join(lines)


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
    output: dict | None = None
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
    provider: Literal["anthropic", "ollama", "groq"]
    model: str
    ready: bool
    detail: str
    cost: str
    daily_limit: int | None = None
    runs_left_today: int | None = None
    agent_daily_limit: int | None = None
    agent_runs_left_today: int | None = None
