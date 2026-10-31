from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OperationalEvent
from app.models.enums import EvidenceLevel, EvidenceType


@dataclass
class EvidenceFilters:
    application_ids: list[int] | None = None
    event_type: list[EvidenceType] | None = None
    level: list[EvidenceLevel] | None = None
    metric_name: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None


class EvidenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def search(self, f: EvidenceFilters, limit: int) -> list[OperationalEvent]:
        stmt = select(OperationalEvent)
        if f.application_ids:
            stmt = stmt.where(OperationalEvent.application_id.in_(f.application_ids))
        if f.event_type:
            stmt = stmt.where(OperationalEvent.event_type.in_(f.event_type))
        if f.level:
            stmt = stmt.where(OperationalEvent.level.in_(f.level))
        if f.metric_name:
            stmt = stmt.where(OperationalEvent.metric_name == f.metric_name)
        if f.occurred_from:
            stmt = stmt.where(OperationalEvent.occurred_at >= f.occurred_from)
        if f.occurred_to:
            stmt = stmt.where(OperationalEvent.occurred_at <= f.occurred_to)
        stmt = stmt.order_by(OperationalEvent.occurred_at, OperationalEvent.id).limit(limit)
        return list(self.db.scalars(stmt))
