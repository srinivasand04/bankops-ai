from datetime import datetime
from math import ceil
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.api import serializers
from app.api.deps import AnyUser, DbSession, Engineer
from app.models.enums import IncidentCategory, IncidentStatus, Priority, Severity
from app.repositories.incident_repository import SORTABLE_FIELDS, IncidentFilters
from app.schemas.common import Page
from app.schemas.incident import (
    AssignmentChange,
    EventCreate,
    EventOut,
    IncidentCreate,
    IncidentDetailOut,
    IncidentOut,
    IncidentUpdate,
    SlaOut,
    StatusChange,
)
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/api/incidents", tags=["Incidents"])

SortField = Literal[tuple(SORTABLE_FIELDS)]  # type: ignore[valid-type]


def _detail(service: IncidentService, incident) -> IncidentDetailOut:
    return serializers.incident_detail_out(
        incident,
        root_cause_count=service.incidents.count_root_causes(incident.id),
        open_action_count=service.incidents.count_open_actions(incident.id),
    )


@router.post("", response_model=IncidentDetailOut, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, db: DbSession, user: Engineer, background: BackgroundTasks):
    service = IncidentService(db)
    incident = service.create(payload, user)
    # Model suggestions (SLA-breach risk, MTTR, category/team, similar incidents) are stored in the
    # background; they never change the incident itself.
    background.add_task(_store_ml_predictions, incident.id)
    return _detail(service, incident)


def _store_ml_predictions(incident_id: int) -> None:
    from app.core.database import SessionLocal
    from app.ml.service import predict_new_incident

    with SessionLocal() as db:
        predict_new_incident(db, incident_id)


@router.get("", response_model=Page[IncidentOut])
def list_incidents(
    db: DbSession,
    _: AnyUser,
    status_: Annotated[list[IncidentStatus] | None, Query(alias="status")] = None,
    severity: Annotated[list[Severity] | None, Query()] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    category: Annotated[list[IncidentCategory] | None, Query()] = None,
    application_id: int | None = None,
    assigned_team: Annotated[str | None, Query(max_length=100)] = None,
    search: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sla_breached: bool | None = None,
    active_only: bool = False,
    data_source: Annotated[str | None, Query(max_length=30)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: SortField = "created_at",
    order: Literal["asc", "desc"] = "desc",
):
    filters = IncidentFilters(
        status=status_,
        severity=severity,
        priority=priority,
        category=category,
        application_id=application_id,
        assigned_team=assigned_team,
        search=search,
        created_from=created_from,
        created_to=created_to,
        sla_breached=sla_breached,
        active_only=active_only,
        data_source=data_source,
    )
    items, total = IncidentService(db).search(filters, page, page_size, sort, order == "desc")
    return Page[IncidentOut](
        items=[serializers.incident_out(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total else 0,
    )


@router.get("/by-reference/{reference}", response_model=IncidentDetailOut)
def get_incident_by_reference(reference: str, db: DbSession, _: AnyUser):
    service = IncidentService(db)
    return _detail(service, service.get_by_reference(reference))


@router.get("/{incident_id}", response_model=IncidentDetailOut)
def get_incident(incident_id: int, db: DbSession, _: AnyUser):
    service = IncidentService(db)
    return _detail(service, service.get(incident_id))


@router.put("/{incident_id}", response_model=IncidentDetailOut)
def update_incident(incident_id: int, payload: IncidentUpdate, db: DbSession, user: Engineer):
    service = IncidentService(db)
    return _detail(service, service.update(incident_id, payload, user))


@router.patch("/{incident_id}/status", response_model=IncidentDetailOut)
def change_status(incident_id: int, payload: StatusChange, db: DbSession, user: Engineer):
    service = IncidentService(db)
    return _detail(service, service.change_status(incident_id, payload, user))


@router.patch("/{incident_id}/assign", response_model=IncidentDetailOut)
def assign_incident(incident_id: int, payload: AssignmentChange, db: DbSession, user: Engineer):
    service = IncidentService(db)
    return _detail(service, service.assign(incident_id, payload, user))


@router.get("/{incident_id}/sla", response_model=SlaOut)
def get_sla(incident_id: int, db: DbSession, _: AnyUser):
    return serializers.sla_out(IncidentService(db).get(incident_id))


@router.get("/{incident_id}/timeline", response_model=list[EventOut], tags=["Timeline"])
def get_timeline(incident_id: int, db: DbSession, _: AnyUser):
    return IncidentService(db).timeline(incident_id)


@router.post(
    "/{incident_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED, tags=["Timeline"]
)
def add_event(incident_id: int, payload: EventCreate, db: DbSession, user: Engineer):
    return IncidentService(db).add_event(incident_id, payload, user)
