"""Single-call AI incident analysis with guardrails and human review (Phase 5).

Flow:  incident -> fact base (context.py) -> Claude structured output (llm.py) -> guardrails ->
       investigation report AWAITING_REVIEW -> human APPROVE / REJECT -> (approve) hypotheses and
       recommendations recorded on the incident, still as hypotheses / open actions.
"""

import logging
import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.compact import compact_context
from app.ai.context import IncidentContext, build_incident_context
from app.ai.llm import LlmClient
from app.ai.prompts.incident_analysis import build_user_message, system_prompt
from app.ai.schemas import AgentExecutionOut, IncidentAnalysis, InvestigationOut, ReviewRequest
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import BusinessRuleError, DomainError, NotFoundError, RateLimitedError
from app.core.security import AI_ACTOR_PREFIX, CurrentUser, Role
from app.models import AgentExecution, Incident, InvestigationReport
from app.models.enums import AgentExecutionStatus, EventType, InvestigationStatus, RootCauseStatus
from app.schemas.rca import ActionCreate, RootCauseCreate
from app.services.incident_service import IncidentService
from app.services.rca_service import RcaService, require_human_manager
from app.services.timeline import record_event
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

AGENT_NAME = "incident_analyst"
AI_ANALYST = CurrentUser(username=f"{AI_ACTOR_PREFIX}incident-analyst", role=Role.ENGINEER)
DISCLAIMER = (
    "AI-generated analysis for human review. Hypotheses are not confirmed root causes, and no action "
    "has been taken. Based on synthetic demonstration data."
)

# Recommendations matching these always require human approval, whatever the model said.
CONSEQUENTIAL = re.compile(
    r"\b(roll ?back|redeploy|deploy|revert|restart|reboot|fail ?over|hotfix|apply (the )?patch|"
    r"scale (up|out|down|in)|(change|update|modify|increase|decrease|raise|lower|set) (the )?\S*\s?"
    r"(config(uration)?|settings?|pool|limit|parameter|timeout)|flush|purge|kill|disable|"
    r"close (the )?incident|approve|reprocess|replay|correct(ing)? (the )?(data|transactions?)|"
    r"modify (the )?transactions?)\b",
    re.IGNORECASE,
)
URGENCY_DUE_DAYS = {"IMMEDIATE": 0, "SHORT_TERM": 7, "LONG_TERM": 30}


def apply_guardrails(analysis: IncidentAnalysis, ctx: IncidentContext) -> tuple[dict, list[str]]:
    """Enforce what the schema cannot: citations exist, facts are cited, confidences are sane, and
    consequential recommendations require approval. Returns the cleaned report and what changed."""
    notes: list[str] = []
    valid = ctx.valid_ids

    def keep_valid(ids: list[str], where: str) -> list[str]:
        bad = [i for i in ids if i not in valid]
        if bad:
            notes.append(f"{where}: removed citations not present in the fact base: {', '.join(bad)}")
        return [i for i in ids if i in valid]

    facts, unverified = [], []
    for n, fact in enumerate(analysis.confirmed_facts, start=1):
        ids = keep_valid(fact.evidence_ids, f"fact {n}")
        if ids:
            facts.append({"statement": fact.statement, "evidence_ids": ids})
        else:
            unverified.append(fact.statement)
            notes.append(f"fact {n} had no valid evidence and was moved to unverified_statements")

    hypotheses = []
    for n, h in enumerate(analysis.root_cause_hypotheses, start=1):
        confidence = min(max(h.confidence, 0.0), 1.0)
        if confidence != h.confidence:
            notes.append(f"hypothesis {n}: confidence {h.confidence} clamped to {confidence}")
        hypotheses.append({
            **h.model_dump(mode="json"),
            "confidence": round(confidence, 2),
            "supporting_evidence_ids": keep_valid(h.supporting_evidence_ids, f"hypothesis {n}"),
            "contradicting_evidence_ids": keep_valid(h.contradicting_evidence_ids, f"hypothesis {n}"),
            "status": RootCauseStatus.HYPOTHESIS,  # never anything else for AI output
        })
    hypotheses.sort(key=lambda h: -h["confidence"])
    # Small models sometimes repeat a hypothesis with a different confidence; keep the strongest copy.
    unique, seen = [], set()
    for h in hypotheses:
        key = re.sub(r"\W+", " ", h["description"]).strip().lower()
        if key in seen:
            notes.append(f"duplicate hypothesis removed (confidence {h['confidence']}): {h['description'][:80]}")
            continue
        seen.add(key)
        unique.append(h)
    hypotheses = unique

    services = []
    for s in analysis.affected_services:
        if s.application_code not in ctx.application_codes:
            notes.append(f"affected service '{s.application_code}' is not in the fact base and was removed")
            continue
        services.append({**s.model_dump(mode="json"), "evidence_ids": keep_valid(s.evidence_ids, "affected service")})

    actions = []
    for n, a in enumerate(analysis.recommended_actions, start=1):
        action = a.model_dump(mode="json")
        if not a.requires_human_approval and CONSEQUENTIAL.search(a.description):
            action["requires_human_approval"] = True
            action["approval_reason"] = "Changes production - requires authorised human approval (change management)"
            notes.append(f"action {n}: marked as requiring human approval (production change)")
        actions.append(action)

    report = analysis.model_dump(mode="json") | {
        "confirmed_facts": facts,
        "unverified_statements": unverified,
        "root_cause_hypotheses": hypotheses,
        "affected_services": services,
        "recommended_actions": actions,
        "disclaimer": DISCLAIMER,
    }
    return report, notes


def investigation_out(inv: InvestigationReport, incident_reference: str | None) -> InvestigationOut:
    return InvestigationOut(
        id=inv.id,
        incident_id=inv.incident_id,
        incident_reference=incident_reference,
        status=inv.status,
        request_text=inv.request_text,
        agents_selected=inv.agents_selected or [],
        model_name=inv.model_name,
        report=inv.report,
        error_message=inv.error_message,
        requested_by=inv.requested_by,
        reviewed_by=inv.reviewed_by,
        reviewed_at=inv.reviewed_at,
        review_notes=inv.review_notes,
        created_at=inv.created_at,
        completed_at=inv.completed_at,
        executions=[AgentExecutionOut.model_validate(e, from_attributes=True) for e in inv.executions],
    )


class AnalysisService:
    def __init__(self, db: Session):
        self.db = db
        self.incidents = IncidentService(db)

    # ---- queries ------------------------------------------------------------------------

    def get(self, investigation_id: int) -> InvestigationReport:
        inv = self.db.get(InvestigationReport, investigation_id)
        if inv is None:
            raise NotFoundError(f"Investigation {investigation_id} not found")
        return inv

    def list_for_incident(self, incident_id: int) -> list[InvestigationReport]:
        self.incidents.get(incident_id)
        stmt = (
            select(InvestigationReport)
            .where(InvestigationReport.incident_id == incident_id)
            .order_by(InvestigationReport.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def reference_for(self, inv: InvestigationReport) -> str | None:
        return self.db.get(Incident, inv.incident_id).reference_number if inv.incident_id else None

    def context(self, incident_id: int) -> IncidentContext:
        return build_incident_context(self.db, self.incidents.get(incident_id))

    # ---- analysis -----------------------------------------------------------------------

    def runs_today(self) -> int:
        midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.db.scalar(
            select(func.count()).select_from(InvestigationReport).where(InvestigationReport.created_at >= midnight)
        )

    def list_recent(self, status: InvestigationStatus | None = None, limit: int = 50) -> list[InvestigationReport]:
        stmt = select(InvestigationReport).order_by(InvestigationReport.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(InvestigationReport.status == status)
        return list(self.db.scalars(stmt))

    def analyze(self, incident_id: int, focus: str | None, user: CurrentUser, llm: LlmClient) -> InvestigationReport:
        """Synchronous analysis: start + run in one call (scripts, tests, `?wait=true`)."""
        inv = self.start(incident_id, focus, user)
        return self.run(inv.id, llm)

    def start(self, incident_id: int, focus: str | None, user: CurrentUser) -> InvestigationReport:
        """Record a RUNNING investigation and return at once; `run` does the slow AI call."""
        incident = self.check_can_start(incident_id)
        now = utcnow()
        inv = InvestigationReport(
            incident_id=incident.id,
            request_text=focus or "Full incident analysis",
            status=InvestigationStatus.RUNNING,
            agents_selected=[AGENT_NAME],
            requested_by=user.username,
            created_at=now,
            updated_at=now,
        )
        inv.executions.append(
            AgentExecution(agent_name=AGENT_NAME, step_order=1, status=AgentExecutionStatus.RUNNING, started_at=now)
        )
        self.db.add(inv)
        self.db.commit()
        return inv

    def check_can_start(self, incident_id: int) -> Incident:
        """One running analysis per incident, and the demo's daily limit."""
        incident = self.incidents.get(incident_id)
        running = self.db.scalar(
            select(InvestigationReport).where(
                InvestigationReport.incident_id == incident.id,
                InvestigationReport.status == InvestigationStatus.RUNNING,
            )
        )
        if running is not None:
            raise BusinessRuleError(
                f"INV-{running.id} is already analysing {incident.reference_number}",
                details={"investigation_id": running.id},
            )
        limit = get_settings().ai_daily_limit
        if limit and self.runs_today() >= limit:
            raise RateLimitedError(
                f"The demo allows {limit} AI analyses per day - limit reached, try again tomorrow (UTC)",
                details={"daily_limit": limit},
            )
        return incident

    def run(self, investigation_id: int, llm: LlmClient) -> InvestigationReport:
        inv = self.get(investigation_id)
        incident = self.incidents.get(inv.incident_id)
        step = inv.executions[0]
        now = step.started_at
        focus = None if inv.request_text == "Full incident analysis" else inv.request_text

        # Small local models get a compact fact base and an explicit field guide; Claude gets everything.
        compact = getattr(llm, "prefers_compact_context", False)
        mode = "compact" if compact else "full"
        try:
            ctx = build_incident_context(self.db, incident, utcnow())
            if compact:
                ctx = compact_context(ctx)
            step.tool_calls = [{"tool": "build_incident_context", "mode": mode, "result": ctx.counts()}]
            result = llm.structured(
                system=system_prompt(compact), user=build_user_message(ctx.data, focus), output_model=IncidentAnalysis
            )
            report, notes = apply_guardrails(result.parsed, ctx)
        except DomainError as exc:
            self._fail(inv, step, exc.message)
            raise
        except Exception as exc:
            logger.exception("AI analysis failed for incident %s", incident.reference_number)
            self._fail(inv, step, f"Unexpected error: {type(exc).__name__}")
            raise

        finished = utcnow()
        report["guardrail_notes"] = notes
        report["context_summary"] = {"mode": mode, **ctx.counts()}
        inv.report = report
        inv.model_name = result.model
        inv.status = InvestigationStatus.AWAITING_REVIEW
        inv.completed_at = finished
        step.status = AgentExecutionStatus.COMPLETED
        step.output = {"request_id": result.request_id, "stop_reason": result.stop_reason,
                       "cache_read_tokens": result.cache_read_tokens, "guardrail_notes": len(notes),
                       "duration_seconds": round((finished - now).total_seconds(), 1)}
        step.input_tokens, step.output_tokens = result.input_tokens, result.output_tokens
        step.completed_at = finished
        self.db.flush()
        record_event(
            incident,
            EventType.AI_ANALYSIS,
            f"AI analysis INV-{inv.id} completed: {len(report['root_cause_hypotheses'])} hypotheses, "
            f"{len(report['recommended_actions'])} recommendations - awaiting human review",
            AI_ANALYST,
            details={"investigation_id": inv.id, "model": result.model},
            at=finished,
        )
        self.db.commit()
        return inv

    @staticmethod
    def run_in_background(investigation_id: int, llm: LlmClient) -> None:
        """Entry point for FastAPI BackgroundTasks: own session; failures are recorded, never raised."""
        with SessionLocal() as db:
            try:
                AnalysisService(db).run(investigation_id, llm)
            except DomainError as exc:
                logger.warning("Background analysis INV-%s failed: %s", investigation_id, exc.message)
            except Exception:
                logger.exception("Background analysis INV-%s crashed", investigation_id)

    @staticmethod
    def fail_interrupted() -> int:
        """At startup: analyses still RUNNING were cut off by a restart - mark them FAILED."""
        with SessionLocal() as db:
            stale = list(db.scalars(select(InvestigationReport).where(
                InvestigationReport.status == InvestigationStatus.RUNNING)))
            for inv in stale:
                inv.status = InvestigationStatus.FAILED
                inv.error_message = "Interrupted: the backend restarted before the analysis finished"
                inv.completed_at = utcnow()
                for step in inv.executions:
                    if step.status == AgentExecutionStatus.RUNNING:
                        step.status = AgentExecutionStatus.FAILED
            db.commit()
            return len(stale)

    def _fail(self, inv: InvestigationReport, step: AgentExecution, message: str) -> None:
        self.db.rollback()
        inv.status = InvestigationStatus.FAILED
        step.status = AgentExecutionStatus.FAILED
        inv.error_message = step.error_message = message
        inv.completed_at = step.completed_at = utcnow()
        self.db.add(inv)
        self.db.commit()

    # ---- human review -------------------------------------------------------------------

    def review(self, investigation_id: int, data: ReviewRequest, user: CurrentUser) -> InvestigationReport:
        require_human_manager(user, "approve or reject an AI investigation")
        inv = self.get(investigation_id)
        if inv.status != InvestigationStatus.AWAITING_REVIEW:
            raise BusinessRuleError(f"Investigation {inv.id} is {inv.status}, not awaiting review")
        incident = self.incidents.get(inv.incident_id)
        now = utcnow()
        applied = {"root_causes": 0, "actions": 0}

        if data.decision == "APPROVE":
            rca = RcaService(self.db)
            report = inv.report
            if data.apply_hypotheses:
                for h in report["root_cause_hypotheses"]:
                    rca.add_root_cause(incident.id, RootCauseCreate(
                        description=h["description"][:5000],
                        category=h["category"],
                        confidence=h["confidence"],
                        supporting_evidence=[f"{i} (AI citation)" for i in h["supporting_evidence_ids"]][:50],
                        missing_evidence=[m[:2000] for m in h["missing_evidence"]][:50],
                    ), AI_ANALYST, commit=False)
                    applied["root_causes"] += 1
            if data.apply_actions:
                for a in report["recommended_actions"]:
                    approval = (f" [Requires human approval: {a['approval_reason']}]"
                                if a["requires_human_approval"] else "")
                    rca.add_action(incident.id, ActionCreate(
                        action_type=a["action_type"],
                        description=(a["description"] + approval)[:5000],
                        assigned_team=a["owner_team"][:100] or None,
                        due_date=(now + timedelta(days=URGENCY_DUE_DAYS[a["urgency"]])).date(),
                    ), AI_ANALYST, commit=False)
                    applied["actions"] += 1
            inv.status = InvestigationStatus.APPROVED
        else:
            inv.status = InvestigationStatus.REJECTED

        inv.reviewed_by, inv.reviewed_at, inv.review_notes = user.username, now, data.review_notes
        inv.report = {**inv.report, "applied": applied}
        record_event(
            incident,
            EventType.AI_ANALYSIS,
            f"AI investigation INV-{inv.id} {inv.status.lower()} by {user.username}"
            + (f": {applied['root_causes']} hypotheses and {applied['actions']} actions recorded"
               if inv.status == InvestigationStatus.APPROVED else "")
            + (f". Notes: {data.review_notes}" if data.review_notes else ""),
            user,
            details={"investigation_id": inv.id, "decision": data.decision, **applied},
        )
        self.db.commit()
        return inv
