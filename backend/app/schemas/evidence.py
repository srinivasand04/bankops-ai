from datetime import datetime

from app.models.enums import EvidenceLevel, EvidenceType
from app.schemas.application import ApplicationRef
from app.schemas.common import OrmModel


class OperationalEventOut(OrmModel):
    id: int
    application: ApplicationRef
    event_type: EvidenceType
    level: EvidenceLevel
    source_system: str
    message: str
    metric_name: str | None
    metric_value: float | None
    unit: str | None
    attributes: dict | None
    occurred_at: datetime
    data_source: str
