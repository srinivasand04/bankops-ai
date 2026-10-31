"""Single entry point for writing incident audit events."""

from datetime import datetime

from app.core.security import CurrentUser
from app.models import Incident, IncidentEvent
from app.models.enums import EventType, Source
from app.utils.time import utcnow

SYSTEM_ACTOR = "system"


def source_for(user: CurrentUser | None) -> Source:
    if user is None:
        return Source.SYSTEM
    return Source.AI if user.is_ai else Source.HUMAN


def record_event(
    incident: Incident,
    event_type: EventType,
    description: str,
    user: CurrentUser | None,
    details: dict | None = None,
    at: datetime | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        event_type=event_type,
        description=description,
        details=details,
        source=source_for(user),
        created_by=user.username if user else SYSTEM_ACTOR,
        created_at=at or utcnow(),
    )
    incident.events.append(event)
    return event
