"""Operational evidence (metrics, logs, alerts, job runs) and data-source overview."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AnyUser, DbSession
from app.ingestion.loader import source_counts
from app.models.enums import EvidenceLevel, EvidenceType
from app.repositories.application_repository import ApplicationRepository
from app.repositories.evidence_repository import EvidenceFilters, EvidenceRepository
from app.schemas.evidence import OperationalEventOut
from app.services.incident_service import IncidentService
from app.utils.time import utcnow

router = APIRouter(prefix="/api", tags=["Operational Evidence & Data Sources"])

Limit = Annotated[int, Query(ge=1, le=1000)]


@router.get("/operational-events", response_model=list[OperationalEventOut])
def list_operational_events(
    db: DbSession,
    _: AnyUser,
    application_id: Annotated[list[int] | None, Query()] = None,
    event_type: Annotated[list[EvidenceType] | None, Query()] = None,
    level: Annotated[list[EvidenceLevel] | None, Query()] = None,
    metric_name: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: Limit = 200,
):
    filters = EvidenceFilters(application_id, event_type, level, metric_name, occurred_from, occurred_to)
    return EvidenceRepository(db).search(filters, limit)


@router.get("/incidents/{incident_id}/evidence", response_model=list[OperationalEventOut])
def incident_evidence(
    incident_id: int,
    db: DbSession,
    _: AnyUser,
    minutes_before: Annotated[int, Query(ge=0, le=7 * 24 * 60)] = 120,
    include_related: bool = Query(default=True, description="include direct dependencies and dependents"),
    event_type: Annotated[list[EvidenceType] | None, Query()] = None,
    limit: Limit = 500,
):
    """Evidence from `minutes_before` the incident started until it was resolved (or now)."""
    incident = IncidentService(db).get(incident_id)
    app_ids = [incident.application_id]
    if include_related:
        apps = ApplicationRepository(db)
        detail = apps.get_with_dependencies(incident.application_id)
        app_ids += [d.depends_on_id for d in detail.dependencies]
        app_ids += [a.id for a in apps.dependents_of(incident.application_id)]
    filters = EvidenceFilters(
        application_ids=app_ids,
        event_type=event_type,
        occurred_from=incident.started_at - timedelta(minutes=minutes_before),
        occurred_to=incident.resolved_at or utcnow(),
    )
    return EvidenceRepository(db).search(filters, limit)


@router.get("/data-sources")
def data_sources(db: DbSession, _: AnyUser):
    """Row counts per data source (SYNTHETIC, MANUAL, later BPI2014)."""
    return source_counts(db)
