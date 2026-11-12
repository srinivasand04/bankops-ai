"""Import every model so Alembic autogenerate and relationship resolution see them."""

from app.models.ai import AgentExecution, InvestigationReport
from app.models.application import Application, ApplicationDependency
from app.models.base import Base
from app.models.calendar import BusinessCalendarPeriod
from app.models.change import ChangeRecord
from app.models.evidence import OperationalEvent
from app.models.ml import MlModelRun, MlPrediction
from app.models.user import AppUser
from app.models.incident import (
    Incident,
    IncidentAction,
    IncidentEvent,
    IncidentRca,
    IncidentRelatedChange,
    IncidentRootCause,
    IncidentSla,
    incident_reference_seq,
)

__all__ = [
    "AgentExecution",
    "AppUser",
    "Application",
    "ApplicationDependency",
    "Base",
    "BusinessCalendarPeriod",
    "ChangeRecord",
    "Incident",
    "IncidentAction",
    "IncidentEvent",
    "IncidentRca",
    "IncidentRelatedChange",
    "IncidentRootCause",
    "IncidentSla",
    "MlModelRun",
    "MlPrediction",
    "InvestigationReport",
    "OperationalEvent",
    "incident_reference_seq",
]
