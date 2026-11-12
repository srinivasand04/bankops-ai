"""The investigation team: who does what, with which tools, and what each one returns."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.ai.schemas import CitedFact


@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    purpose: str
    tools: tuple[str, ...]


TRIAGE = AgentSpec(
    "triage", "Triage agent",
    "Establish what is happening: symptoms, timing, severity, SLA position and the signals that show it.",
    ("get_incident_details", "get_incident_timeline", "get_application_health"),
)
CHANGE_RELEASE = AgentSpec(
    "change_release", "Change & release agent",
    "Find deployments and changes close to the start of impact and judge whether their timing and content fit.",
    ("get_related_changes", "get_recent_deployments"),
)
DEPENDENCY_IMPACT = AgentSpec(
    "dependency_impact", "Dependency & impact agent",
    "Map the blast radius: upstream and downstream applications, their health and active incidents, business tier.",
    ("get_application_dependencies", "calculate_incident_impact"),
)
OPERATIONAL_RISK = AgentSpec(
    "operational_risk", "Operational risk agent",
    "Assess operational risk: change risk, recurrence on the application, SLA exposure, history and "
    "business-calendar timing (month-end close, payroll, regulatory deadlines).",
    ("calculate_operational_risk", "get_incident_history", "get_business_calendar"),
)
ROOT_CAUSE = AgentSpec(
    "root_cause", "Root cause agent",
    "Combine the specialists' findings into ranked, cited root-cause hypotheses and recommended actions.",
    (),
)

SPECIALISTS = {a.name: a for a in (CHANGE_RELEASE, DEPENDENCY_IMPACT, OPERATIONAL_RISK)}
ALL_AGENTS = {a.name: a for a in (TRIAGE, CHANGE_RELEASE, DEPENDENCY_IMPACT, OPERATIONAL_RISK, ROOT_CAUSE)}
SUPERVISOR = "supervisor"

SpecialistName = Literal["change_release", "dependency_impact", "operational_risk"]


class SupervisorPlan(BaseModel):
    """What the supervisor decides after triage."""

    specialists: list[SpecialistName] = Field(description="Specialist agents to run next, most useful first")
    reasoning: str = Field(description="One or two sentences on why these specialists (and not the others)")


class AgentFinding(BaseModel):
    """What every specialist returns."""

    summary: str = Field(description="Two sentences: the most important thing this agent found")
    findings: list[CitedFact] = Field(description="Facts from the tool results, each citing the ids that prove it")
    risk_signal: Literal["LOW", "MEDIUM", "HIGH"] = Field(description="How strongly this angle points to a problem")
    open_questions: list[str] = Field(description="What this agent could not establish from the data")
