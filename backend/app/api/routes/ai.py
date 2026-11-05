"""AI endpoints (Phase 5: single-call analysis + human review; Phase 6 adds multi-agent investigations)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

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
    return AiStatusOut(**provider_status(), daily_limit=limit, runs_left_today=left)


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
