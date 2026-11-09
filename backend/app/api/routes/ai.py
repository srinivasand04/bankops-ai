"""AI endpoints: single-call analysis (Phase 5), multi-agent investigation (Phase 7), human review."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

from app.ai.agent_service import AgentInvestigationService
from app.ai.agents.definitions import ALL_AGENTS
from app.ai.analysis_service import AnalysisService, investigation_out
from app.ai.llm import LlmClient
from app.ai.providers import get_llm, provider_status
from app.ai.schemas import AiStatusOut, AnalyzeRequest, InvestigationOut, ReviewRequest
from app.api.deps import AnyUser, DbSession, Engineer, Manager
from app.core.config import get_settings
from app.models.enums import InvestigationStatus

router = APIRouter(prefix="/api/ai", tags=["AI Analysis"])

Llm = Annotated[LlmClient, Depends(get_llm)]


def _out(service: AnalysisService, inv) -> InvestigationOut:
    return investigation_out(inv, service.reference_for(inv))


@router.get("/status", response_model=AiStatusOut)
def ai_status(db: DbSession, _: AnyUser):
    """Active provider (AI_PROVIDER), model, whether analysis can run now, and the daily demo limit."""
    limit = get_settings().ai_daily_limit or None
    left = max(limit - AnalysisService(db).runs_today(), 0) if limit else None
    agent_limit = get_settings().ai_agent_daily_limit or None
    agent_left = max(agent_limit - AgentInvestigationService(db).agent_runs_today(), 0) if agent_limit else None
    if left is not None and agent_left is not None:
        agent_left = min(agent_left, left)  # agent runs count towards the overall limit too
    return AiStatusOut(**provider_status(), daily_limit=limit, runs_left_today=left,
                       agent_daily_limit=agent_limit, agent_runs_left_today=agent_left)


@router.get("/incidents/{incident_id}/context")
def incident_context(incident_id: int, db: DbSession, _: AnyUser):
    """Exactly the fact base Claude receives - useful to audit what the AI saw."""
    ctx = AnalysisService(db).context(incident_id)
    return {"citable_ids": sorted(ctx.valid_ids), "summary": ctx.counts(), "fact_base": ctx.data}


@router.post(
    "/incidents/{incident_id}/analyze",
    response_model=InvestigationOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={201: {"description": "Finished analysis (wait=true)"}},
)
def analyze_incident(
    incident_id: int,
    db: DbSession,
    user: Engineer,
    llm: Llm,
    background: BackgroundTasks,
    response: Response,
    payload: AnalyzeRequest | None = None,
    wait: bool = Query(default=False, description="Block until the analysis finishes (scripts/tests)"),
):
    """Starts an analysis. Default: returns 202 with a RUNNING investigation at once and works in the
    background - poll GET /api/ai/investigations/{id}. With wait=true: returns 201 with the result."""
    service = AnalysisService(db)
    focus = payload.focus if payload else None
    if wait:
        response.status_code = status.HTTP_201_CREATED
        return _out(service, service.analyze(incident_id, focus, user, llm))
    inv = service.start(incident_id, focus, user)
    background.add_task(AnalysisService.run_in_background, inv.id, llm)
    return _out(service, inv)


@router.post(
    "/incidents/{incident_id}/investigate",
    response_model=InvestigationOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={201: {"description": "Finished investigation (wait=true)"}},
)
def investigate_incident(
    incident_id: int,
    db: DbSession,
    user: Engineer,
    llm: Llm,
    background: BackgroundTasks,
    response: Response,
    payload: AnalyzeRequest | None = None,
    wait: bool = Query(default=False, description="Block until the investigation finishes (scripts/tests)"),
):
    """Multi-agent investigation (LangGraph): triage -> supervisor -> chosen specialists -> root cause ->
    human review. Same report format, guardrails and review as /analyze; each agent step is recorded."""
    service = AgentInvestigationService(db)
    focus = payload.focus if payload else None
    if wait:
        response.status_code = status.HTTP_201_CREATED
        return _out(service.analysis, service.investigate(incident_id, focus, user, llm))
    inv = service.start(incident_id, focus, user)
    background.add_task(AgentInvestigationService.run_in_background, inv.id, llm)
    return _out(service.analysis, inv)


@router.get("/agents")
def agent_catalogue(_: AnyUser):
    """The investigation team: agents, their purpose and the read-only tools each one may call."""
    return [{"name": a.name, "title": a.title, "purpose": a.purpose, "tools": list(a.tools)} for a in ALL_AGENTS.values()]


@router.get("/investigations", response_model=list[InvestigationOut])
def recent_investigations(
    db: DbSession,
    _: AnyUser,
    status_: Annotated[InvestigationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """All investigations, newest first - the AI investigation centre's list."""
    service = AnalysisService(db)
    return [_out(service, inv) for inv in service.list_recent(status_, limit)]


@router.get("/incidents/{incident_id}/investigations", response_model=list[InvestigationOut])
def list_investigations(incident_id: int, db: DbSession, _: AnyUser):
    service = AnalysisService(db)
    return [_out(service, inv) for inv in service.list_for_incident(incident_id)]


@router.get("/investigations/{investigation_id}", response_model=InvestigationOut)
def get_investigation(investigation_id: int, db: DbSession, _: AnyUser):
    service = AnalysisService(db)
    return _out(service, service.get(investigation_id))


@router.post("/investigations/{investigation_id}/review", response_model=InvestigationOut)
def review_investigation(investigation_id: int, payload: ReviewRequest, db: DbSession, user: Manager):
    """Human-in-the-loop gate: only a human INCIDENT_MANAGER can approve or reject AI output."""
    service = AnalysisService(db)
    return _out(service, service.review(investigation_id, payload, user))
