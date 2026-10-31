"""Applications, dependencies, change records and reference data."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AnyUser, DbSession
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.enums import IncidentCategory, IncidentStatus, Priority
from app.repositories.application_repository import ApplicationRepository, ChangeRepository
from app.schemas.application import ApplicationDetailOut, ApplicationOut, ApplicationRef, ChangeRecordOut
from app.services.classification import SEVERITY_DEFINITIONS
from app.services.lifecycle import ALLOWED_TRANSITIONS

router = APIRouter(prefix="/api", tags=["Applications & Reference Data"])


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(db: DbSession, _: AnyUser):
    return ApplicationRepository(db).list_all()


@router.get("/applications/{application_id}", response_model=ApplicationDetailOut)
def get_application(application_id: int, db: DbSession, _: AnyUser):
    repo = ApplicationRepository(db)
    application = repo.get_with_dependencies(application_id)
    if application is None:
        raise NotFoundError(f"Application {application_id} not found")
    return ApplicationDetailOut.model_validate(
        {
            **ApplicationOut.model_validate(application).model_dump(),
            "dependencies": application.dependencies,
            "dependents": [ApplicationRef.model_validate(a) for a in repo.dependents_of(application_id)],
        }
    )


@router.get("/changes", response_model=list[ChangeRecordOut])
def list_changes(
    db: DbSession,
    _: AnyUser,
    application_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return ChangeRepository(db).list_all(application_id, limit)


@router.get("/reference-data")
def reference_data(_: AnyUser):
    """Severity definitions, demo SLA targets, categories, priorities and lifecycle rules for UIs."""
    targets = get_settings().sla_targets
    return {
        "severities": [
            {
                "code": severity,
                **definition,
                "response_target_minutes": targets[severity].response,
                "resolution_target_minutes": targets[severity].resolution,
            }
            for severity, definition in SEVERITY_DEFINITIONS.items()
        ],
        "sla_disclaimer": "Demonstration SLA targets - not universal banking requirements",
        "priorities": list(Priority),
        "categories": list(IncidentCategory),
        "statuses": list(IncidentStatus),
        "transitions": {state: sorted(targets_) for state, targets_ in ALLOWED_TRANSITIONS.items()},
    }
