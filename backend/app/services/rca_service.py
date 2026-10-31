"""Root cause analysis, CAPA actions and change correlation.

Governance rule: AI-generated content is always stored as a hypothesis / recommendation. Only a
human with the INCIDENT_MANAGER role can confirm a root cause or approve an RCA.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.security import CurrentUser, Role
from app.models import Incident, IncidentAction, IncidentRca, IncidentRelatedChange, IncidentRootCause
from app.models.enums import ActionStatus, ActionType, EventType, RcaStatus, RootCauseStatus
from app.repositories.application_repository import ChangeRepository
from app.schemas.rca import ActionCreate, ActionUpdate, RcaUpdate, RelatedChangeCreate, RootCauseCreate, RootCauseReview
from app.services.incident_service import IncidentService
from app.services.timeline import record_event, source_for
from app.utils.time import utcnow


def require_human_manager(user: CurrentUser, action: str) -> None:
    if user.is_ai:
        raise PermissionDeniedError(f"AI agents cannot {action}; human review is required")
    if not user.has_role(Role.INCIDENT_MANAGER):
        raise PermissionDeniedError(f"Only an INCIDENT_MANAGER can {action}")


class RcaService:
    def __init__(self, db: Session):
        self.db = db
        self.incident_service = IncidentService(db)
        self.changes = ChangeRepository(db)

    # ---- root causes --------------------------------------------------------------------

    def list_root_causes(self, incident_id: int) -> list[IncidentRootCause]:
        return self.incident_service.get(incident_id).root_causes

    def add_root_cause(
        self, incident_id: int, data: RootCauseCreate, user: CurrentUser, commit: bool = True
    ) -> IncidentRootCause:
        incident = self.incident_service.get(incident_id)
        root_cause = IncidentRootCause(
            **data.model_dump(),
            source=source_for(user),
            created_by=user.username,
        )
        incident.root_causes.append(root_cause)
        confidence = f" (confidence {data.confidence:.0%})" if data.confidence is not None else ""
        record_event(
            incident,
            EventType.ROOT_CAUSE_HYPOTHESIS,
            f"Root cause hypothesis recorded{confidence}: {data.description}",
            user,
            details={"status": data.status},
        )
        if commit:
            self.db.commit()
        return root_cause

    def review_root_cause(self, root_cause_id: int, data: RootCauseReview, user: CurrentUser) -> IncidentRootCause:
        root_cause = self.db.get(IncidentRootCause, root_cause_id)
        if root_cause is None:
            raise NotFoundError(f"Root cause {root_cause_id} not found")
        require_human_manager(user, "confirm or reject a root cause")
        if root_cause.status in (RootCauseStatus.CONFIRMED, RootCauseStatus.REJECTED):
            raise BusinessRuleError(f"Root cause {root_cause_id} has already been {root_cause.status.lower()}")

        incident = root_cause.incident
        if data.decision == "CONFIRM":
            root_cause.status = RootCauseStatus.CONFIRMED
            root_cause.confirmed_by = user.username
            root_cause.confirmed_at = utcnow()
            event_type, verb = EventType.ROOT_CAUSE_CONFIRMED, "confirmed"
        else:
            root_cause.status = RootCauseStatus.REJECTED
            event_type, verb = EventType.ROOT_CAUSE_REJECTED, "rejected"
        root_cause.review_notes = data.review_notes
        record_event(
            incident,
            event_type,
            f"Root cause {verb} by {user.username}: {root_cause.description}",
            user,
            details={"root_cause_id": root_cause.id, "original_source": root_cause.source},
        )
        self.db.commit()
        return root_cause

    # ---- CAPA ---------------------------------------------------------------------------

    def list_actions(self, incident_id: int) -> list[IncidentAction]:
        return self.incident_service.get(incident_id).actions

    def add_action(
        self, incident_id: int, data: ActionCreate, user: CurrentUser, commit: bool = True
    ) -> IncidentAction:
        incident = self.incident_service.get(incident_id)
        action = IncidentAction(**data.model_dump(), source=source_for(user), created_by=user.username)
        incident.actions.append(action)
        event_type = (
            EventType.CORRECTIVE_ACTION if data.action_type == ActionType.CORRECTIVE else EventType.PREVENTIVE_ACTION
        )
        owner = data.assigned_owner or data.assigned_team or "unassigned"
        record_event(
            incident,
            event_type,
            f"{data.action_type.capitalize()} action added (owner: {owner}): {data.description}",
            user,
            details={"due_date": data.due_date.isoformat() if data.due_date else None},
        )
        if commit:
            self.db.commit()
        return action

    def update_action(self, action_id: int, data: ActionUpdate, user: CurrentUser) -> IncidentAction:
        action = self.db.get(IncidentAction, action_id)
        if action is None:
            raise NotFoundError(f"Action {action_id} not found")
        if action.status in (ActionStatus.COMPLETED, ActionStatus.CANCELLED) and data.status not in (
            None,
            ActionStatus.OPEN,
            ActionStatus.IN_PROGRESS,
        ):
            raise BusinessRuleError(f"Action {action_id} is already {action.status.lower()}")

        changes = data.model_dump(exclude_unset=True)
        changed = [field for field, value in changes.items() if getattr(action, field) != value]
        for field in changed:
            setattr(action, field, changes[field])
        if "status" in changed:
            action.completed_at = utcnow() if action.status == ActionStatus.COMPLETED else None
        if changed:
            record_event(
                action.incident,
                EventType.ACTION_UPDATED,
                f"{action.action_type.capitalize()} action #{action.id} updated: {', '.join(changed)}"
                + (f" -> {action.status}" if "status" in changed else ""),
                user,
                details={"action_id": action.id, "fields": changed},
            )
        self.db.commit()
        return action

    # ---- related changes ----------------------------------------------------------------

    def link_change(self, incident_id: int, data: RelatedChangeCreate, user: CurrentUser) -> IncidentRelatedChange:
        incident = self.incident_service.get(incident_id)
        change = self.changes.get(data.change_id)
        if change is None:
            raise NotFoundError(f"Change {data.change_id} not found")
        link = IncidentRelatedChange(
            change=change,
            link_status=data.link_status,
            notes=data.notes,
            source=source_for(user),
            identified_by=user.username,
        )
        incident.related_changes.append(link)
        record_event(
            incident,
            EventType.CHANGE_LINKED,
            f"Change {change.change_reference} ({change.title}) linked as {data.link_status}",
            user,
            details={"change_id": change.id, "change_reference": change.change_reference},
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise BusinessRuleError(f"Change {change.change_reference} is already linked to this incident") from exc
        return link

    # ---- RCA document -------------------------------------------------------------------

    def get_rca(self, incident_id: int) -> tuple[Incident, IncidentRca | None]:
        incident = self.incident_service.get(incident_id)
        rca = self.db.scalar(select(IncidentRca).where(IncidentRca.incident_id == incident_id))
        return incident, rca

    def update_rca(self, incident_id: int, data: RcaUpdate, user: CurrentUser) -> tuple[Incident, IncidentRca]:
        incident, rca = self.get_rca(incident_id)
        if rca is None:
            rca = IncidentRca(updated_by=user.username)
            incident.rca = rca
        if rca.status == RcaStatus.APPROVED:
            raise BusinessRuleError("RCA is approved; it can no longer be edited")

        changes = data.model_dump(exclude_unset=True)
        new_status = changes.pop("status", None)
        for field, value in changes.items():
            setattr(rca, field, value)
        rca.updated_by = user.username

        if new_status == RcaStatus.APPROVED:
            require_human_manager(user, "approve an RCA")
            if not any(rc.status == RootCauseStatus.CONFIRMED for rc in incident.root_causes):
                raise BusinessRuleError("An RCA can only be approved once a root cause has been confirmed")
            rca.approved_by = user.username
            rca.approved_at = utcnow()
        if new_status:
            rca.status = new_status

        record_event(
            incident,
            EventType.RCA_UPDATED,
            f"RCA updated ({', '.join(list(changes) + (['status'] if new_status else [])) or 'no fields'})"
            + (f"; status {new_status}" if new_status else ""),
            user,
        )
        self.db.commit()
        return incident, rca
