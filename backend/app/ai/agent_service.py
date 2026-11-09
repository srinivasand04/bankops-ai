"""Multi-agent investigations (Phase 7): start, run the LangGraph team, record every step.

Shares the investigation table, guardrails and human review with the single-call analysis
(analysis_service.py); only the way the report is produced differs.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents.definitions import SUPERVISOR, TRIAGE
from app.ai.analysis_service import AI_ANALYST, AnalysisService
from app.ai.compact import compact_context
from app.ai.context import build_incident_context
from app.ai.graph.investigation_graph import InvestigationRunner, run_investigation
from app.ai.llm import LlmClient
from app.ai.tools.incident_tools import Toolkit
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import DomainError, RateLimitedError
from app.core.security import CurrentUser
from app.models import InvestigationReport
from app.models.enums import AgentExecutionStatus, EventType, InvestigationStatus
from app.services.timeline import record_event
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

DEFAULT_REQUEST = "Full multi-agent investigation"


def is_agent_run(inv: InvestigationReport) -> bool:
    return SUPERVISOR in (inv.agents_selected or [])


class AgentInvestigationService:
    def __init__(self, db: Session):
        self.db = db
        self.analysis = AnalysisService(db)

    def agent_runs_today(self) -> int:
        midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today = self.db.scalars(select(InvestigationReport).where(InvestigationReport.created_at >= midnight))
        return sum(1 for inv in today if is_agent_run(inv))

    def investigate(self, incident_id: int, focus: str | None, user: CurrentUser, llm: LlmClient) -> InvestigationReport:
        """Synchronous: start + run (scripts, tests, `?wait=true`)."""
        return self.run(self.start(incident_id, focus, user).id, llm)

    def start(self, incident_id: int, focus: str | None, user: CurrentUser) -> InvestigationReport:
        incident = self.analysis.check_can_start(incident_id)
        limit = get_settings().ai_agent_daily_limit
        if limit and self.agent_runs_today() >= limit:
            raise RateLimitedError(
                f"The demo allows {limit} multi-agent investigations per day - limit reached, try again tomorrow "
                "(UTC) or use the single-call analysis",
                details={"agent_daily_limit": limit},
            )
        now = utcnow()
        inv = InvestigationReport(
            incident_id=incident.id,
            request_text=focus or DEFAULT_REQUEST,
            status=InvestigationStatus.RUNNING,
            agents_selected=[TRIAGE.name, SUPERVISOR],  # the supervisor adds the rest once it has planned
            requested_by=user.username,
            created_at=now,
            updated_at=now,
        )
        self.db.add(inv)
        self.db.commit()
        return inv

    def run(self, investigation_id: int, llm: LlmClient) -> InvestigationReport:
        inv = self.analysis.get(investigation_id)
        incident = self.analysis.incidents.get(inv.incident_id)
        focus = None if inv.request_text == DEFAULT_REQUEST else inv.request_text
        compact = getattr(llm, "prefers_compact_context", False)
        try:
            ctx = build_incident_context(self.db, incident, utcnow())
            if compact:
                ctx = compact_context(ctx)
            kit = Toolkit(self.db, incident, ctx)
            report, notes, state = run_investigation(InvestigationRunner(self.db, llm, kit, inv, focus))
        except DomainError as exc:
            self._fail(inv, exc.message)
            raise
        except Exception as exc:
            logger.exception("Multi-agent investigation INV-%s failed", inv.id)
            self._fail(inv, f"Unexpected error: {type(exc).__name__}")
            raise

        finished = utcnow()
        report |= {
            "mode": "multi_agent",
            "guardrail_notes": notes,
            "context_summary": {"mode": "compact" if compact else "full", **ctx.counts()},
            "plan": {"specialists": state.get("plan", []), "reasoning": state.get("reasoning")},
            "agent_findings": state.get("findings", {}),
            "calculations": kit.computed,
        }
        inv.report = report
        inv.model_name = state.get("model")
        inv.status = InvestigationStatus.AWAITING_REVIEW
        inv.completed_at = finished
        self.db.flush()
        record_event(
            incident,
            EventType.AI_ANALYSIS,
            f"Multi-agent investigation INV-{inv.id} completed ({', '.join(inv.agents_selected)}): "
            f"{len(report['root_cause_hypotheses'])} hypotheses, {len(report['recommended_actions'])} "
            "recommendations - awaiting human review",
            AI_ANALYST,
            details={"investigation_id": inv.id, "model": inv.model_name, "agents": inv.agents_selected},
            at=finished,
        )
        self.db.commit()
        return inv

    @staticmethod
    def run_in_background(investigation_id: int, llm: LlmClient) -> None:
        with SessionLocal() as db:
            try:
                AgentInvestigationService(db).run(investigation_id, llm)
            except DomainError as exc:
                logger.warning("Background investigation INV-%s failed: %s", investigation_id, exc.message)
            except Exception:
                logger.exception("Background investigation INV-%s crashed", investigation_id)

    def _fail(self, inv: InvestigationReport, message: str) -> None:
        self.db.rollback()
        now = utcnow()
        inv.status = InvestigationStatus.FAILED
        inv.error_message = message
        inv.completed_at = now
        for step in inv.executions:
            if step.status == AgentExecutionStatus.RUNNING:
                step.status, step.error_message, step.completed_at = AgentExecutionStatus.FAILED, message, now
        self.db.add(inv)
        self.db.commit()
