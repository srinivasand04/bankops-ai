"""Root causes, RCA document, CAPA actions and related changes."""

from fastapi import APIRouter, status

from app.api import serializers
from app.api.deps import AnyUser, DbSession, Engineer, Manager
from app.schemas.rca import (
    ActionCreate,
    ActionOut,
    ActionUpdate,
    RcaOut,
    RcaUpdate,
    RelatedChangeCreate,
    RelatedChangeOut,
    RootCauseCreate,
    RootCauseOut,
    RootCauseReview,
)
from app.services.rca_service import RcaService

router = APIRouter(prefix="/api", tags=["Root Cause & CAPA"])


# ---- CAPA ---------------------------------------------------------------------------------


@router.get("/incidents/{incident_id}/actions", response_model=list[ActionOut])
def list_actions(incident_id: int, db: DbSession, _: AnyUser):
    return [serializers.action_out(a) for a in RcaService(db).list_actions(incident_id)]


@router.post("/incidents/{incident_id}/actions", response_model=ActionOut, status_code=status.HTTP_201_CREATED)
def create_action(incident_id: int, payload: ActionCreate, db: DbSession, user: Engineer):
    return serializers.action_out(RcaService(db).add_action(incident_id, payload, user))


@router.patch("/actions/{action_id}", response_model=ActionOut)
def update_action(action_id: int, payload: ActionUpdate, db: DbSession, user: Engineer):
    return serializers.action_out(RcaService(db).update_action(action_id, payload, user))


# ---- Root causes --------------------------------------------------------------------------


@router.get("/incidents/{incident_id}/root-causes", response_model=list[RootCauseOut])
def list_root_causes(incident_id: int, db: DbSession, _: AnyUser):
    return RcaService(db).list_root_causes(incident_id)


@router.post(
    "/incidents/{incident_id}/root-causes", response_model=RootCauseOut, status_code=status.HTTP_201_CREATED
)
def add_root_cause(incident_id: int, payload: RootCauseCreate, db: DbSession, user: Engineer):
    return RcaService(db).add_root_cause(incident_id, payload, user)


@router.post("/root-causes/{root_cause_id}/review", response_model=RootCauseOut)
def review_root_cause(root_cause_id: int, payload: RootCauseReview, db: DbSession, user: Manager):
    """Human confirmation / rejection of a hypothesis. Never available to AI actors."""
    return RcaService(db).review_root_cause(root_cause_id, payload, user)


# ---- RCA document -------------------------------------------------------------------------


@router.get("/incidents/{incident_id}/rca", response_model=RcaOut)
def get_rca(incident_id: int, db: DbSession, _: AnyUser):
    return serializers.rca_out(*RcaService(db).get_rca(incident_id))


@router.put("/incidents/{incident_id}/rca", response_model=RcaOut)
def update_rca(incident_id: int, payload: RcaUpdate, db: DbSession, user: Engineer):
    return serializers.rca_out(*RcaService(db).update_rca(incident_id, payload, user))


# ---- Related changes ----------------------------------------------------------------------


@router.get("/incidents/{incident_id}/related-changes", response_model=list[RelatedChangeOut])
def list_related_changes(incident_id: int, db: DbSession, _: AnyUser):
    incident = RcaService(db).incident_service.get(incident_id)
    return [serializers.related_change_out(link) for link in incident.related_changes]


@router.post(
    "/incidents/{incident_id}/related-changes",
    response_model=RelatedChangeOut,
    status_code=status.HTTP_201_CREATED,
)
def link_change(incident_id: int, payload: RelatedChangeCreate, db: DbSession, user: Engineer):
    return serializers.related_change_out(RcaService(db).link_change(incident_id, payload, user))
