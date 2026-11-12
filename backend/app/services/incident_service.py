"""Incident lifecycle: creation, classification, assignment, status transitions and timeline."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.security import CurrentUser, Role
from app.models import Incident, IncidentSla
from app.models.enums import (
    MANUAL_EVENT_TYPES,
    EventType,
    IncidentStatus,
    RootCauseStatus,
    Severity,
)
from app.repositories.application_repository import ApplicationRepository
from app.repositories.incident_repository import IncidentFilters, IncidentRepository
from app.schemas.incident import AssignmentChange, EventCreate, IncidentCreate, IncidentUpdate, StatusChange
from app.services import business_calendar, lifecycle, sla_service
from app.services.timeline import record_event
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

# Severities whose closure requires a human-confirmed root cause (problem management gate).
CLOSURE_REQUIRES_CONFIRMED_RCA = frozenset({Severity.P1})

_STATUS_EVENT = {
    IncidentStatus.ESCALATED: EventType.ESCALATED,
    IncidentStatus.RESOLVED: EventType.RESOLVED,
    IncidentStatus.CLOSED: EventType.CLOSED,
    IncidentStatus.REOPENED: EventType.REOPENED,
}


class IncidentService:
    def __init__(self, db: Session):
        self.db = db
        self.incidents = IncidentRepository(db)
        self.applications = ApplicationRepository(db)

    # ---- queries ------------------------------------------------------------------------

    def get(self, incident_id: int) -> Incident:
        incident = self.incidents.get(incident_id)
        if incident is None:
            raise NotFoundError(f"Incident {incident_id} not found")
        return incident

    def get_by_reference(self, reference: str) -> Incident:
        incident = self.incidents.get_by_reference(reference)
        if incident is None:
            raise NotFoundError(f"Incident {reference} not found")
        return incident

    def search(self, filters: IncidentFilters, page: int, page_size: int, sort: str, descending: bool):
        return self.incidents.search(filters, utcnow(), page, page_size, sort, descending)

    def timeline(self, incident_id: int):
        self.get(incident_id)
        return self.incidents.timeline(incident_id)

    # ---- commands -----------------------------------------------------------------------

    def create(self, data: IncidentCreate, user: CurrentUser) -> Incident:
        application = self.applications.get(data.application_id)
        if application is None or not application.is_active:
            raise BusinessRuleError(f"Application {data.application_id} does not exist or is inactive")

        now = utcnow()
        started_at = data.started_at or now
        decision = business_calendar.priority_for(self.db, data.severity, application, started_at)
        if data.priority:
            priority = data.priority
            priority_reason = f"Set manually by {user.username} (calculated: {decision.priority})"
        else:
            priority, priority_reason = decision.priority, decision.reason
        incident = Incident(
            reference_number=self.incidents.next_reference(),
            title=data.title,
            description=data.description,
            application=application,
            severity=data.severity,
            priority=priority,
            priority_reason=priority_reason,
            category=data.category,
            status=IncidentStatus.OPEN,
            business_impact=data.business_impact,
            created_by=user.username,
            started_at=started_at,
            created_at=now,
            updated_at=now,
        )
        incident.sla = sla_service.apply_targets(IncidentSla(), data.severity, clock_started_at=now)
        record_event(
            incident,
            EventType.CREATED,
            f"Incident created: {data.severity} {data.category} on {application.name}",
            user,
            details={
                "severity": data.severity,
                "priority": priority,
                "priority_derived": data.priority is None,
                "priority_reason": priority_reason,
                "calendar_period_ids": decision.calendar_period_ids,
            },
            at=now,
        )
        self.db.add(incident)
        self.db.flush()

        if data.assigned_team:
            self._assign(
                incident,
                AssignmentChange(assigned_team=data.assigned_team, assigned_engineer=data.assigned_engineer),
                user,
            )
        self.db.commit()
        logger.info("Created incident %s (%s)", incident.reference_number, incident.severity)
        return incident

    def update(self, incident_id: int, data: IncidentUpdate, user: CurrentUser) -> Incident:
        incident = self.get(incident_id)
        self._ensure_not_closed(incident)
        changes = data.model_dump(exclude_unset=True, exclude={"reason"})
        reason = data.reason

        new_severity = changes.pop("severity", None)
        if new_severity and new_severity != incident.severity:
            old = incident.severity
            incident.severity = new_severity
            # Targets are re-based on the new severity from the original logging time.
            sla_service.apply_targets(incident.sla, new_severity, incident.sla.clock_started_at)
            record_event(
                incident,
                EventType.SEVERITY_CHANGED,
                f"Severity changed from {old} to {new_severity}" + (f": {reason}" if reason else ""),
                user,
                details={"from": old, "to": new_severity},
            )

        new_priority = changes.pop("priority", None)
        if new_priority and new_priority != incident.priority:
            old = incident.priority
            incident.priority = new_priority
            incident.priority_reason = f"Set manually by {user.username}" + (f": {reason}" if reason else "")
            record_event(
                incident,
                EventType.PRIORITY_CHANGED,
                f"Priority changed from {old} to {new_priority}" + (f": {reason}" if reason else ""),
                user,
                details={"from": old, "to": new_priority},
            )

        changed_fields = [field for field, value in changes.items() if getattr(incident, field) != value]
        for field in changed_fields:
            setattr(incident, field, changes[field])
        if changed_fields:
            record_event(
                incident,
                EventType.UPDATED,
                f"Updated {', '.join(changed_fields)}" + (f": {reason}" if reason else ""),
                user,
                details={"fields": changed_fields},
            )

        self._refresh_sla(incident)
        self.db.commit()
        return incident

    def assign(self, incident_id: int, data: AssignmentChange, user: CurrentUser) -> Incident:
        incident = self.get(incident_id)
        self._ensure_not_closed(incident)
        self._assign(incident, data, user)
        self._refresh_sla(incident)
        self.db.commit()
        return incident

    def change_status(self, incident_id: int, data: StatusChange, user: CurrentUser) -> Incident:
        incident = self.get(incident_id)
        self._transition(incident, data.status, user, note=data.note, resolution_summary=data.resolution_summary)
        self._refresh_sla(incident)
        self.db.commit()
        logger.info("Incident %s moved to %s", incident.reference_number, incident.status)
        return incident

    def add_event(self, incident_id: int, data: EventCreate, user: CurrentUser):
        if data.event_type not in MANUAL_EVENT_TYPES:
            raise BusinessRuleError(
                f"Event type {data.event_type} is system-generated",
                details={"allowed": sorted(MANUAL_EVENT_TYPES)},
            )
        incident = self.get(incident_id)
        event = record_event(incident, data.event_type, data.description, user, details=data.details)
        self.db.commit()
        return event

    def evaluate_sla(self, incident: Incident) -> sla_service.SlaEvaluation:
        return sla_service.evaluate(incident, incident.sla, utcnow())

    # ---- internals ----------------------------------------------------------------------

    def _ensure_not_closed(self, incident: Incident) -> None:
        if incident.status == IncidentStatus.CLOSED:
            raise BusinessRuleError(f"{incident.reference_number} is closed; reopen it before making changes")

    def _assign(self, incident: Incident, data: AssignmentChange, user: CurrentUser) -> None:
        previous = (incident.assigned_team, incident.assigned_engineer)
        incident.assigned_team = data.assigned_team
        incident.assigned_engineer = data.assigned_engineer
        who = data.assigned_team + (f" / {data.assigned_engineer}" if data.assigned_engineer else "")
        record_event(
            incident,
            EventType.ASSIGNED,
            f"Assigned to {who}" + (f": {data.note}" if data.note else ""),
            user,
            details={
                "previous_team": previous[0],
                "previous_engineer": previous[1],
                "team": data.assigned_team,
                "engineer": data.assigned_engineer,
            },
        )
        if incident.status in (IncidentStatus.OPEN, IncidentStatus.REOPENED):
            self._transition(incident, IncidentStatus.ASSIGNED, user)

    def _transition(
        self,
        incident: Incident,
        target: IncidentStatus,
        user: CurrentUser,
        note: str | None = None,
        resolution_summary: str | None = None,
    ) -> None:
        current = incident.status
        lifecycle.validate_transition(current, target)
        now = utcnow()

        if target == IncidentStatus.ASSIGNED and not incident.assigned_team:
            raise BusinessRuleError("Assign a team before moving the incident to ASSIGNED")

        if target == IncidentStatus.RESOLVED:
            summary = resolution_summary or incident.resolution_summary
            if not summary:
                raise BusinessRuleError("resolution_summary is required to resolve an incident")
            incident.resolution_summary = summary
            incident.resolved_at = now

        if target == IncidentStatus.CLOSED:
            self._check_closure_allowed(incident, user)
            incident.closed_at = now

        if target == IncidentStatus.REOPENED:
            if not note:
                raise BusinessRuleError("A note explaining why the incident is reopened is required")
            incident.reopen_count += 1
            incident.resolved_at = None
            incident.closed_at = None

        if incident.acknowledged_at is None and target in lifecycle.ACKNOWLEDGING_STATUSES:
            incident.acknowledged_at = now

        incident.status = target
        description = f"Status changed from {current} to {target}"
        if target == IncidentStatus.RESOLVED:
            description += f". Resolution: {incident.resolution_summary}"
        if note:
            description += f". Note: {note}"
        record_event(
            incident,
            _STATUS_EVENT.get(target, EventType.STATUS_CHANGED),
            description,
            user,
            details={"from": current, "to": target},
            at=now,
        )

    def _check_closure_allowed(self, incident: Incident, user: CurrentUser) -> None:
        if user.is_ai:
            raise PermissionDeniedError("AI agents cannot close incidents; human approval is required")
        if not user.has_role(Role.INCIDENT_MANAGER):
            raise PermissionDeniedError("Closing an incident requires the INCIDENT_MANAGER role")
        if incident.severity in CLOSURE_REQUIRES_CONFIRMED_RCA and not any(
            rc.status == RootCauseStatus.CONFIRMED for rc in incident.root_causes
        ):
            raise BusinessRuleError(
                f"{incident.severity} incidents need a human-confirmed root cause before closure"
            )

    def _refresh_sla(self, incident: Incident, now: datetime | None = None) -> None:
        for kind in sla_service.refresh_breach_flags(incident, incident.sla, now or utcnow()):
            record_event(
                incident,
                EventType.SLA_BREACHED,
                f"{kind.capitalize()} SLA breached ({incident.severity} demo target "
                f"{getattr(incident.sla, f'{kind}_target_minutes')} min)",
                None,
                details={"sla": kind},
            )
