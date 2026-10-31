"""AI endpoints (Phase 5: single-call analysis + human review; Phase 6 adds multi-agent investigations)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.ai.analysis_service import AnalysisService, investigation_out
from app.ai.llm import LlmClient
from app.ai.providers import get_llm, provider_status
from app.ai.schemas import AiStatusOut, AnalyzeRequest, InvestigationOut, ReviewRequest
from app.api.deps import AnyUser, DbSession, Engineer, Manager

router = APIRouter(prefix="/api/ai", tags=["AI Analysis"])

Llm = Annotated[LlmClient, Depends(get_llm)]


def _out(service: AnalysisService, inv) -> InvestigationOut:
    return investigation_out(inv, service.reference_for(inv))


@router.get("/status", response_model=AiStatusOut)
def ai_status(_: AnyUser):
    """Active provider (AI_PROVIDER), model and whether analysis can run right now."""
    return AiStatusOut(**provider_status())


@router.get("/incidents/{incident_id}/context")
def incident_context(incident_id: int, db: DbSession, _: AnyUser):
    """Exactly the fact base Claude receives - useful to audit what the AI saw."""
    ctx = AnalysisService(db).context(incident_id)
    return {"citable_ids": sorted(ctx.valid_ids), "summary": ctx.counts(), "fact_base": ctx.data}


@router.post("/incidents/{incident_id}/analyze", response_model=InvestigationOut, status_code=status.HTTP_201_CREATED)
def analyze_incident(incident_id: int, db: DbSession, user: Engineer, llm: Llm, payload: AnalyzeRequest | None = None):
    service = AnalysisService(db)
    inv = service.analyze(incident_id, payload.focus if payload else None, user, llm)
    return _out(service, inv)


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
