"""Prompts for the multi-agent investigation (Phase 7). System prompts are fixed text (cacheable)."""

import json

from app.ai.agents.definitions import SPECIALISTS, AgentFinding, AgentSpec, SupervisorPlan
from app.ai.prompts.incident_analysis import COMPACT_GUIDANCE, SYSTEM_PROMPT as ANALYST_PROMPT
from app.ai.schemas import field_guide

COMMON = """\
You are part of the BankOps AI investigation team, analysing one IT incident at a bank. A human \
incident manager reviews everything the team produces. The environment uses synthetic demonstration data.

Rules for every agent:
- Use only the tool results you are given. Every item has an `id`; cite the exact ids that prove each finding.
- A finding is something the data shows (timing, values, messages). Causation is not a finding.
- If the data does not show something, put it under open_questions instead of assuming it.
- You recommend and investigate only. You never deploy, roll back, change configuration, restart systems, \
close incidents, approve changes or modify transactions.
"""

SMALL_MODEL = "\nAnswer briefly: at most 5 findings and 3 open questions, one sentence each.\n\nOutput fields:\n"


def specialist_system(spec: AgentSpec, compact: bool) -> str:
    text = f"{COMMON}\nYou are the {spec.title}. Your job: {spec.purpose}\n"
    return text + (SMALL_MODEL + field_guide(AgentFinding) if compact else "")


def specialist_user(spec: AgentSpec, incident: dict, focus: str | None, tool_results: dict) -> str:
    return (
        f"Incident {incident['id']} ({incident['severity']}, {incident['application']}): {incident['title']}\n"
        f"Request from the incident team: {focus or 'Full investigation.'}\n\n"
        f"Tool results (JSON):\n{json.dumps(tool_results, sort_keys=True, default=str)}"
    )


def supervisor_system(compact: bool) -> str:
    menu = "\n".join(f"- {s.name}: {s.purpose}" for s in SPECIALISTS.values())
    text = (
        f"{COMMON}\nYou are the supervisor. Triage has run. Decide which specialists should investigate next. "
        "Choose only the ones the incident needs; a smaller team answers faster. Specialists:\n"
        f"{menu}\n"
        "A root cause agent always runs last and combines the findings.\n"
    )
    return text + ("\nOutput fields:\n" + field_guide(SupervisorPlan) if compact else "")


def supervisor_user(incident: dict, focus: str | None, triage: dict, hints: dict) -> str:
    return (
        f"Incident {incident['id']} ({incident['severity']}, {incident['application']}): {incident['title']}\n"
        f"Request from the incident team: {focus or 'Full investigation.'}\n\n"
        f"Triage finding (JSON):\n{json.dumps(triage, default=str)}\n\n"
        f"What data exists (JSON):\n{json.dumps(hints, default=str)}"
    )


def root_cause_system(compact: bool) -> str:
    """Same contract as the single-call analyst, but the input is the team's findings."""
    team = (
        "\n\nIn this run you are the root cause agent of a multi-agent team. Instead of the raw fact base you "
        "receive the incident record and the cited findings of the triage, change & release, dependency & "
        "impact and operational risk agents (some may not have run). Cite the same ids they cited, including "
        "IMPACT- and RISK- calculation ids. Weigh agents' findings against each other; where they disagree, say so."
    )
    return ANALYST_PROMPT + team + (COMPACT_GUIDANCE + field_guide() if compact else "")


def root_cause_user(incident: dict, applications: list[str], focus: str | None, findings: dict) -> str:
    return (
        f"Analyse incident {incident['id']}.\n"
        f"Request from the incident team: {focus or 'Provide a full analysis of this incident.'}\n\n"
        f"Incident record (JSON):\n{json.dumps(incident, default=str)}\n\n"
        f"Application codes you may use in affected_services: {', '.join(sorted(applications))}\n\n"
        f"Team findings (JSON):\n{json.dumps(findings, sort_keys=True, default=str)}"
    )
