"""Multi-agent incident investigation as a LangGraph state machine (Phase 7).

    START -> triage -> supervisor --(conditional: next planned specialist)--> change_release
                                                                         \\-> dependency_impact
                                                                          \\-> operational_risk
             each specialist --(conditional: next planned specialist, else)--> root_cause
             root_cause -> human_review_gate -> END   (investigation waits as AWAITING_REVIEW)

Specialists call their own read-only tools, then make one structured LLM call that turns the tool
results into cited findings. The supervisor decides which specialists run. The root cause agent writes
the final report in the same format as the single-call analysis, so the same guardrails and the same
human review apply. Every node is recorded as an `agent_executions` row as it starts and finishes,
so the UI can show progress live.
"""

import logging
import time
from collections.abc import Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.ai.agents.definitions import (
    ALL_AGENTS, ROOT_CAUSE, SPECIALISTS, SUPERVISOR, TRIAGE, AgentFinding, AgentSpec, SupervisorPlan,
)
from app.ai.analysis_service import apply_guardrails
from app.ai.llm import LlmClient
from app.ai.prompts import agents as prompts
from app.ai.schemas import IncidentAnalysis
from app.ai.tools.incident_tools import Toolkit, call_tool, summarise_result
from app.models import AgentExecution, InvestigationReport
from app.models.enums import AgentExecutionStatus
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


class InvestigationState(TypedDict, total=False):
    plan: list[str]
    pending: list[str]
    reasoning: str
    findings: dict[str, dict]
    analysis: IncidentAnalysis
    model: str
    notes: list[str]


def clean_finding(finding: AgentFinding, valid: set[str], agent: str, notes: list[str]) -> dict:
    """Guardrail for specialist output: keep only citations that exist; drop uncited findings."""
    kept = []
    for n, f in enumerate(finding.findings, start=1):
        ids = [i for i in f.evidence_ids if i in valid]
        bad = [i for i in f.evidence_ids if i not in valid]
        if bad:
            notes.append(f"{agent} finding {n}: removed citations not in the fact base: {', '.join(bad)}")
        if ids:
            kept.append({"statement": f.statement, "evidence_ids": ids})
        else:
            notes.append(f"{agent} finding {n} had no valid evidence and was dropped: {f.statement[:80]}")
    return {"summary": finding.summary, "findings": kept, "risk_signal": finding.risk_signal,
            "open_questions": finding.open_questions}


class InvestigationRunner:
    def __init__(self, db: Session, llm: LlmClient, kit: Toolkit, inv: InvestigationReport, focus: str | None):
        self.db, self.llm, self.kit, self.inv, self.focus = db, llm, kit, inv, focus
        self.compact = getattr(llm, "prefers_compact_context", False)
        self.incident = kit.get_incident_details()

    # ---- bookkeeping ----------------------------------------------------------------------

    def _step(self, agent: str) -> AgentExecution:
        step = AgentExecution(agent_name=agent, step_order=len(self.inv.executions) + 1,
                              status=AgentExecutionStatus.RUNNING, started_at=utcnow(), tool_calls=[])
        self.inv.executions.append(step)
        self.db.commit()  # visible to pollers while the agent works
        return step

    def _finish(self, step: AgentExecution, output: dict, result=None) -> None:
        finished = utcnow()
        step.status = AgentExecutionStatus.COMPLETED
        step.completed_at = finished
        step.output = {**output, "duration_seconds": round((finished - step.started_at).total_seconds(), 1)}
        if result is not None:
            step.input_tokens, step.output_tokens = result.input_tokens, result.output_tokens
        self.db.commit()

    def _tools(self, step: AgentExecution, names: tuple[str, ...]) -> dict:
        results, calls = {}, []
        for name in names:
            t0 = time.perf_counter()
            results[name] = call_tool(self.kit, name)
            calls.append({"tool": name, "ms": round((time.perf_counter() - t0) * 1000, 1),
                          "result": summarise_result(results[name])})
        step.tool_calls = calls
        self.db.commit()
        return results

    # ---- nodes ----------------------------------------------------------------------------

    def _specialist(self, spec: AgentSpec, state: InvestigationState) -> InvestigationState:
        step = self._step(spec.name)
        results = self._tools(step, spec.tools)
        result = self.llm.structured(
            system=prompts.specialist_system(spec, self.compact),
            user=prompts.specialist_user(spec, self.incident, self.focus, results),
            output_model=AgentFinding,
        )
        notes = list(state.get("notes", []))
        finding = clean_finding(result.parsed, self.kit.ctx.valid_ids, spec.name, notes)
        self._finish(step, {"finding": finding}, result)
        pending = [a for a in state.get("pending", []) if a != spec.name]
        return {"findings": {**state.get("findings", {}), spec.name: finding}, "notes": notes, "pending": pending,
                "model": result.model}

    def triage(self, state: InvestigationState) -> InvestigationState:
        return self._specialist(TRIAGE, state)

    def supervisor(self, state: InvestigationState) -> InvestigationState:
        step = self._step(SUPERVISOR)
        d = self.kit.ctx.data
        hints = {
            "changes_linked_to_incident": len(d["related_changes"]),
            "other_changes_last_7_days": len(d["other_recent_changes"]),
            "connected_applications": len(d["applications"]["depends_on"]) + len(d["applications"]["dependents"]),
            "similar_incidents_last_90_days": len(d["similar_incidents"]),
            "sla_resolution": d["incident"]["sla"]["resolution"],
        }
        result = self.llm.structured(
            system=prompts.supervisor_system(self.compact),
            user=prompts.supervisor_user(self.incident, self.focus, state["findings"]["triage"], hints),
            output_model=SupervisorPlan,
        )
        plan = list(dict.fromkeys(a for a in result.parsed.specialists if a in SPECIALISTS))  # dedupe, keep order
        self._finish(step, {"plan": plan, "reasoning": result.parsed.reasoning, "hints": hints}, result)
        self.inv.agents_selected = [TRIAGE.name, SUPERVISOR, *plan, ROOT_CAUSE.name]
        self.db.commit()
        return {"plan": plan, "pending": plan, "reasoning": result.parsed.reasoning}

    def specialist_node(self, name: str) -> Callable[[InvestigationState], InvestigationState]:
        return lambda state: self._specialist(SPECIALISTS[name], state)

    def root_cause(self, state: InvestigationState) -> InvestigationState:
        step = self._step(ROOT_CAUSE.name)
        result = self.llm.structured(
            system=prompts.root_cause_system(self.compact),
            user=prompts.root_cause_user(self.incident, list(self.kit.ctx.application_codes), self.focus,
                                         state["findings"]),
            output_model=IncidentAnalysis,
        )
        step.tool_calls = [{"tool": "create_investigation_report", "result": {
            "hypotheses": len(result.parsed.root_cause_hypotheses), "actions": len(result.parsed.recommended_actions)}}]
        self._finish(step, {"overall_confidence": result.parsed.overall_confidence}, result)
        return {"analysis": result.parsed, "model": result.model}

    def human_review_gate(self, state: InvestigationState) -> InvestigationState:
        """The graph ends here: the report waits for an incident manager (POST .../review)."""
        return {}


def next_agent(state: InvestigationState) -> str:
    pending = state.get("pending") or []
    return pending[0] if pending else ROOT_CAUSE.name


def build_graph(runner: InvestigationRunner):
    g = StateGraph(InvestigationState)
    g.add_node(TRIAGE.name, runner.triage)
    g.add_node(SUPERVISOR, runner.supervisor)
    for name in SPECIALISTS:
        g.add_node(name, runner.specialist_node(name))
    g.add_node(ROOT_CAUSE.name, runner.root_cause)
    g.add_node("human_review_gate", runner.human_review_gate)

    routes = {name: name for name in [*SPECIALISTS, ROOT_CAUSE.name]}
    g.add_edge(START, TRIAGE.name)
    g.add_edge(TRIAGE.name, SUPERVISOR)
    g.add_conditional_edges(SUPERVISOR, next_agent, routes)
    for name in SPECIALISTS:  # a specialist never routes back to itself
        g.add_conditional_edges(name, next_agent, {k: v for k, v in routes.items() if k != name})
    g.add_edge(ROOT_CAUSE.name, "human_review_gate")
    g.add_edge("human_review_gate", END)
    return g.compile()


def run_investigation(runner: InvestigationRunner) -> tuple[dict, list[str], InvestigationState]:
    """Run the graph; returns the guardrailed report, guardrail notes and the final state."""
    state = build_graph(runner).invoke({"findings": {}, "notes": [], "pending": []})
    report, notes = apply_guardrails(state["analysis"], runner.kit.ctx)
    return report, [*state.get("notes", []), *notes], state


AGENT_TITLES = {name: spec.title for name, spec in ALL_AGENTS.items()} | {SUPERVISOR: "Supervisor"}
