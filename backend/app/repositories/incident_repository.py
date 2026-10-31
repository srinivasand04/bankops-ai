from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import Incident, IncidentAction, IncidentEvent, IncidentRootCause, IncidentSla, incident_reference_seq
from app.models.enums import ActionStatus, IncidentCategory, IncidentStatus, Priority, Severity

SORTABLE_FIELDS = {
    "created_at": Incident.created_at,
    "updated_at": Incident.updated_at,
    "started_at": Incident.started_at,
    "severity": Incident.severity,
    "priority": Incident.priority,
    "status": Incident.status,
    "reference_number": Incident.id,
}


@dataclass
class IncidentFilters:
    status: list[IncidentStatus] | None = None
    severity: list[Severity] | None = None
    priority: list[Priority] | None = None
    category: list[IncidentCategory] | None = None
    application_id: int | None = None
    assigned_team: str | None = None
    search: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    sla_breached: bool | None = None
    active_only: bool = False
    data_source: str | None = None


class IncidentRepository:
    def __init__(self, db: Session):
        self.db = db

    def next_reference(self) -> str:
        return f"INC-{self.db.execute(incident_reference_seq.next_value()).scalar_one()}"

    def get(self, incident_id: int) -> Incident | None:
        return self.db.get(Incident, incident_id)

    def get_by_reference(self, reference: str) -> Incident | None:
        return self.db.scalar(select(Incident).where(Incident.reference_number == reference.upper()))

    def _filtered(self, f: IncidentFilters, now: datetime) -> Select:
        stmt = select(Incident)
        if f.status:
            stmt = stmt.where(Incident.status.in_(f.status))
        if f.active_only:
            stmt = stmt.where(Incident.status.not_in([IncidentStatus.RESOLVED, IncidentStatus.CLOSED]))
        if f.severity:
            stmt = stmt.where(Incident.severity.in_(f.severity))
        if f.priority:
            stmt = stmt.where(Incident.priority.in_(f.priority))
        if f.category:
            stmt = stmt.where(Incident.category.in_(f.category))
        if f.application_id:
            stmt = stmt.where(Incident.application_id == f.application_id)
        if f.data_source:
            stmt = stmt.where(Incident.data_source == f.data_source.upper())
        if f.assigned_team:
            stmt = stmt.where(Incident.assigned_team.ilike(f.assigned_team))
        if f.search:
            pattern = f"%{f.search}%"
            stmt = stmt.where(
                or_(
                    Incident.title.ilike(pattern),
                    Incident.description.ilike(pattern),
                    Incident.reference_number.ilike(pattern),
                )
            )
        if f.created_from:
            stmt = stmt.where(Incident.created_at >= f.created_from)
        if f.created_to:
            stmt = stmt.where(Incident.created_at <= f.created_to)
        if f.sla_breached is not None:
            breached = or_(
                IncidentSla.response_breached.is_(True),
                IncidentSla.resolution_breached.is_(True),
                (Incident.acknowledged_at.is_(None) & (IncidentSla.response_due_at < now)),
                (Incident.resolved_at.is_(None) & (IncidentSla.resolution_due_at < now)),
            )
            stmt = stmt.join(IncidentSla, IncidentSla.incident_id == Incident.id)
            stmt = stmt.where(breached if f.sla_breached else ~breached)
        return stmt

    def search(
        self, f: IncidentFilters, now: datetime, page: int, page_size: int, sort: str, descending: bool
    ) -> tuple[list[Incident], int]:
        stmt = self._filtered(f, now)
        total = self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        column = SORTABLE_FIELDS[sort]
        stmt = stmt.order_by(column.desc() if descending else column.asc(), Incident.id.desc())
        items = self.db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
        return list(items), total or 0

    def timeline(self, incident_id: int) -> list[IncidentEvent]:
        stmt = (
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.created_at, IncidentEvent.id)
        )
        return list(self.db.scalars(stmt))

    def count_root_causes(self, incident_id: int) -> int:
        return self.db.scalar(
            select(func.count()).select_from(IncidentRootCause).where(IncidentRootCause.incident_id == incident_id)
        )

    def count_open_actions(self, incident_id: int) -> int:
        return self.db.scalar(
            select(func.count())
            .select_from(IncidentAction)
            .where(
                IncidentAction.incident_id == incident_id,
                IncidentAction.status.in_([ActionStatus.OPEN, ActionStatus.IN_PROGRESS]),
            )
        )
