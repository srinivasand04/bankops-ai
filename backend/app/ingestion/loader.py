"""Load a validated dataset into PostgreSQL.

- Every row is tagged with the dataset's `data_source`.
- Incident histories are replayed through the real lifecycle state machine, so imported data obeys
  the same transition rules as the API; an invalid history aborts the whole load (one transaction).
- Applications and changes are upserted by code / reference; incidents and evidence of the source
  are replaced. Records from other sources (e.g. incidents created through the API) are untouched.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, Role
from app.ingestion.schemas import AssignStep, Dataset, EventStep, IncidentIn, StatusStep, resolve_time
from app.models import (
    Application,
    ApplicationDependency,
    Base,
    ChangeRecord,
    Incident,
    IncidentAction,
    IncidentRca,
    IncidentRelatedChange,
    IncidentRootCause,
    IncidentSla,
    OperationalEvent,
)
from app.models.enums import ActionStatus, ActionType, EventType, IncidentStatus, RcaStatus, Source
from app.repositories.incident_repository import IncidentRepository
from app.services import lifecycle, sla_service
from app.services.classification import derive_priority
from app.services.timeline import record_event
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

_STATUS_EVENT = {
    IncidentStatus.ESCALATED: EventType.ESCALATED,
    IncidentStatus.RESOLVED: EventType.RESOLVED,
    IncidentStatus.CLOSED: EventType.CLOSED,
    IncidentStatus.REOPENED: EventType.REOPENED,
}


class LoadError(Exception):
    pass


@dataclass
class LoadReport:
    data_source: str
    skipped: bool = False
    counts: dict[str, int] = field(default_factory=dict)


def _actor(name: str) -> CurrentUser:
    return CurrentUser(username=name, role=Role.INCIDENT_MANAGER)


def source_counts(db: Session) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for label, model in (
        ("applications", Application),
        ("changes", ChangeRecord),
        ("incidents", Incident),
        ("operational_events", OperationalEvent),
    ):
        for source, count in db.execute(select(model.data_source, func.count()).group_by(model.data_source)):
            result.setdefault(source, {})[label] = count
    return result


def reset_all(db: Session) -> None:
    """Wipe every table and restart the incident reference sequence (development / tests only)."""
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    db.execute(text("ALTER SEQUENCE incident_reference_seq RESTART WITH 1001"))
    db.commit()


def load_dataset(db: Session, dataset: Dataset, replace: bool = False, now: datetime | None = None) -> LoadReport:
    source = dataset.manifest.data_source
    now = now or utcnow()
    already_loaded = db.scalar(select(func.count()).select_from(Application).where(Application.data_source == source))
    if already_loaded and not replace:
        return LoadReport(data_source=source, skipped=True)

    try:
        if replace:
            _remove_source(db, source)
        loader = _Loader(db, dataset, now)
        loader.run()
        _advance_reference_sequence(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    report = LoadReport(data_source=source, counts=source_counts(db).get(source, {}))
    logger.info("Loaded dataset %s: %s", dataset.manifest.name, report.counts)
    return report


def dry_run(db: Session, dataset: Dataset) -> LoadReport:
    """Full load inside a transaction that is always rolled back - validates lifecycle replay too."""
    try:
        _remove_source(db, dataset.manifest.data_source)
        loader = _Loader(db, dataset, utcnow())
        loader.run()
        db.flush()
        return LoadReport(data_source=dataset.manifest.data_source, counts=loader.counts)
    finally:
        db.rollback()


def _remove_source(db: Session, source: str) -> None:
    db.execute(delete(OperationalEvent).where(OperationalEvent.data_source == source))
    db.execute(delete(Incident).where(Incident.data_source == source))  # cascades to timeline, SLA, CAPA...
    source_apps = select(Application.id).where(Application.data_source == source)
    db.execute(delete(ApplicationDependency).where(ApplicationDependency.application_id.in_(source_apps)))
    db.flush()


def _advance_reference_sequence(db: Session) -> None:
    """Keep generated references (API-created incidents) above any reference supplied by a dataset."""
    highest = db.scalar(
        text(
            "SELECT MAX(CAST(SUBSTRING(reference_number FROM 5) AS INTEGER)) FROM incidents "
            "WHERE reference_number ~ '^INC-[0-9]+$'"
        )
    )
    if highest:
        db.execute(
            text("SELECT setval('incident_reference_seq', GREATEST(:highest, (SELECT last_value FROM incident_reference_seq)))"),
            {"highest": highest},
        )


class _Loader:
    def __init__(self, db: Session, dataset: Dataset, now: datetime):
        self.db = db
        self.ds = dataset
        self.source = dataset.manifest.data_source
        self.now = now
        self.apps: dict[str, Application] = {}
        self.changes: dict[str, ChangeRecord] = {}
        self.references = IncidentRepository(db)
        self.counts = {"applications": 0, "dependencies": 0, "changes": 0, "incidents": 0, "operational_events": 0}

    def at(self, value):
        return resolve_time(value, self.now) if value is not None else None

    def run(self) -> None:
        self._applications()
        self._dependencies()
        self._changes()
        # Oldest first so generated references follow creation order
        for record in sorted(self.ds.incidents, key=lambda r: self.at(r.created_at)):
            self._incident(record)
        self._operational_events()

    # ---- reference data -----------------------------------------------------------------

    def _applications(self) -> None:
        for record in self.ds.applications:
            app = self.db.scalar(select(Application).where(Application.code == record.code))
            if app is not None and app.data_source != self.source:
                raise LoadError(f"Application code {record.code} already belongs to source {app.data_source}")
            if app is None:
                app = Application(code=record.code)
                self.db.add(app)
            for key, value in record.model_dump().items():
                setattr(app, key, value)
            app.data_source = self.source
            app.last_health_check_at = self.now
            self.apps[record.code] = app
            self.counts["applications"] += 1
        self.db.flush()

    def _dependencies(self) -> None:
        for record in self.ds.dependencies:
            self.db.add(
                ApplicationDependency(
                    application=self.apps[record.application],
                    depends_on=self.apps[record.depends_on],
                    dependency_type=record.dependency_type,
                    is_critical=record.is_critical,
                    description=record.description,
                )
            )
            self.counts["dependencies"] += 1

    def _changes(self) -> None:
        for record in self.ds.changes:
            change = self.db.scalar(select(ChangeRecord).where(ChangeRecord.change_reference == record.change_reference))
            if change is not None and change.data_source != self.source:
                raise LoadError(f"Change {record.change_reference} already belongs to source {change.data_source}")
            if change is None:
                change = ChangeRecord(change_reference=record.change_reference)
                self.db.add(change)
            values = record.model_dump(exclude={"application", "planned_start", "deployed_at"})
            for key, value in values.items():
                setattr(change, key, value)
            change.application = self.apps[record.application]
            change.planned_start = self.at(record.planned_start)
            change.deployed_at = self.at(record.deployed_at)
            change.data_source = self.source
            self.changes[record.change_reference] = change
            self.counts["changes"] += 1
        self.db.flush()

    def _operational_events(self) -> None:
        for record in self.ds.operational_events:
            values = record.model_dump(exclude={"application", "occurred_at"})
            self.db.add(
                OperationalEvent(
                    **values,
                    application=self.apps[record.application],
                    occurred_at=self.at(record.occurred_at),
                    data_source=self.source,
                )
            )
            self.counts["operational_events"] += 1

    # ---- incidents ----------------------------------------------------------------------

    def _incident(self, record: IncidentIn) -> None:
        app = self.apps[record.application]
        created_at = self.at(record.created_at)

        def offset(minutes: float) -> datetime:
            return created_at + timedelta(minutes=minutes)

        incident = Incident(
            reference_number=record.reference or self.references.next_reference(),
            external_id=record.external_id,
            data_source=self.source,
            title=record.title,
            description=record.description,
            application=app,
            severity=record.severity,
            priority=record.priority or derive_priority(record.severity, app.business_criticality),
            category=record.category,
            status=IncidentStatus.OPEN,
            business_impact=record.business_impact,
            created_by=record.created_by,
            started_at=self.at(record.started_at),
            created_at=created_at,
            updated_at=created_at,
        )
        incident.sla = sla_service.apply_targets(IncidentSla(), record.severity, created_at)
        record_event(
            incident,
            EventType.CREATED,
            f"Incident created: {record.severity} {record.category} on {app.name}",
            _actor(record.created_by),
            details={"data_source": self.source, "external_id": record.external_id},
            at=created_at,
        )

        for step in record.history:
            when = offset(step.after_minutes)
            if isinstance(step, AssignStep):
                incident.assigned_team, incident.assigned_engineer = step.team, step.engineer
                who = step.team + (f" / {step.engineer}" if step.engineer else "")
                record_event(incident, EventType.ASSIGNED, f"Assigned to {who}", _actor(step.actor),
                             details={"team": step.team, "engineer": step.engineer}, at=when)
                if incident.status in (IncidentStatus.OPEN, IncidentStatus.REOPENED):
                    self._transition(incident, IncidentStatus.ASSIGNED, None, _actor(step.actor), when, record)
            elif isinstance(step, StatusStep):
                actor = _actor(step.actor or incident.assigned_engineer or "incident.manager")
                self._transition(incident, step.status, step.note, actor, when, record)
            elif isinstance(step, EventStep):
                record_event(incident, step.event_type, step.description, _actor(step.actor), at=when)
            incident.updated_at = when

        for link in record.change_links:
            who = link.identified_by or incident.assigned_engineer or "incident.manager"
            incident.related_changes.append(
                IncidentRelatedChange(change=self.changes[link.change_reference], link_status=link.link_status,
                                      notes=link.notes, source=Source.HUMAN, identified_by=who,
                                      created_at=offset(link.after_minutes))
            )
            record_event(incident, EventType.CHANGE_LINKED, f"Change {link.change_reference} linked as {link.link_status}",
                         _actor(who), at=offset(link.after_minutes))

        for rc in record.root_causes:
            when = offset(rc.after_minutes)
            incident.root_causes.append(
                IncidentRootCause(
                    **rc.model_dump(exclude={"after_minutes"}),
                    source=Source.HUMAN,  # datasets never inject AI output
                    confirmed_at=when if rc.confirmed_by else None,
                )
            )
            record_event(incident, EventType.ROOT_CAUSE_HYPOTHESIS, f"Root cause hypothesis recorded: {rc.description}",
                         _actor(rc.created_by), at=when)
            if rc.confirmed_by:
                record_event(incident, EventType.ROOT_CAUSE_CONFIRMED, f"Root cause confirmed by {rc.confirmed_by}",
                             _actor(rc.confirmed_by), at=when)

        for action in record.actions:
            when = offset(action.after_minutes)
            incident.actions.append(
                IncidentAction(
                    **action.model_dump(exclude={"due_in_days", "after_minutes"}),
                    due_date=(created_at + timedelta(days=action.due_in_days)).date()
                    if action.due_in_days is not None else None,
                    completed_at=when if action.status == ActionStatus.COMPLETED else None,
                    source=Source.HUMAN,
                    created_by="incident.manager",
                )
            )
            event_type = EventType.CORRECTIVE_ACTION if action.action_type == ActionType.CORRECTIVE else EventType.PREVENTIVE_ACTION
            record_event(incident, event_type, f"{action.action_type.capitalize()} action added: {action.description}",
                         _actor("incident.manager"), at=when)

        if record.rca:
            approved = record.rca.status == RcaStatus.APPROVED
            incident.rca = IncidentRca(
                **record.rca.model_dump(exclude={"approved_by"}),
                business_impact=record.business_impact,
                updated_by="incident.manager",
                approved_by=(record.rca.approved_by or "incident.manager") if approved else None,
                approved_at=(incident.closed_at or incident.updated_at) if approved else None,
            )

        sla_service.refresh_breach_flags(incident, incident.sla, self.now)
        self.db.add(incident)
        self.db.flush()
        self.counts["incidents"] += 1

    def _transition(self, incident, target, note, actor, when, record: IncidentIn) -> None:
        current = incident.status
        try:
            lifecycle.validate_transition(current, target)
        except Exception as exc:
            raise LoadError(f"Incident '{record.reference or record.external_id or record.title}': {exc}") from exc
        if incident.acknowledged_at is None and target in lifecycle.ACKNOWLEDGING_STATUSES:
            incident.acknowledged_at = when
        if target == IncidentStatus.RESOLVED:
            incident.resolution_summary = record.resolution_summary
            incident.resolved_at = when
        if target == IncidentStatus.CLOSED:
            incident.closed_at = when
        if target == IncidentStatus.REOPENED:
            incident.reopen_count += 1
            incident.resolved_at = incident.closed_at = None
        incident.status = target
        description = f"Status changed from {current} to {target}" + (f". Note: {note}" if note else "")
        record_event(incident, _STATUS_EVENT.get(target, EventType.STATUS_CHANGED), description, actor,
                     details={"from": current, "to": target}, at=when)
