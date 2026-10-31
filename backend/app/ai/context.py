"""Build the fact base Claude analyses - everything comes from the database, nothing is invented.

Every item carries an `id` (e.g. TL-12, EV-40, MS-PAY-http_5xx_rate_pct, CHG-2041, INC-1002). Claude
must cite these IDs; the guardrails reject citations that are not in `valid_ids`.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChangeRecord, Incident, OperationalEvent
from app.models.enums import EvidenceType
from app.repositories.application_repository import ApplicationRepository
from app.repositories.evidence_repository import EvidenceFilters, EvidenceRepository
from app.repositories.incident_repository import IncidentRepository
from app.services import sla_service
from app.utils.time import minutes_between, utcnow

EVIDENCE_WINDOW_BEFORE = timedelta(hours=2)
RECENT_CHANGE_WINDOW = timedelta(days=7)
SIMILAR_INCIDENT_WINDOW = timedelta(days=90)
MAX_EVENTS = 150


@dataclass
class IncidentContext:
    data: dict
    valid_ids: set[str] = field(default_factory=set)
    application_codes: set[str] = field(default_factory=set)

    def counts(self) -> dict[str, int]:
        d = self.data
        return {
            "timeline_events": len(d["timeline"]),
            "related_changes": len(d["related_changes"]) + len(d["other_recent_changes"]),
            "metric_series": len(d["evidence"]["metric_series"]),
            "evidence_events": len(d["evidence"]["events"]),
            "similar_incidents": len(d["similar_incidents"]),
            "citable_ids": len(self.valid_ids),
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def build_incident_context(db: Session, incident: Incident, now: datetime | None = None) -> IncidentContext:
    now = now or utcnow()
    ctx = IncidentContext(data={})
    start = incident.started_at

    def rel(value: datetime | None) -> float | None:
        """Minutes relative to incident start (negative = before)."""
        return round(minutes_between(start, value), 1) if value else None

    # ---- incident -------------------------------------------------------------------------
    sla = sla_service.evaluate(incident, incident.sla, now)
    ctx.valid_ids.add(incident.reference_number)
    ctx.data["incident"] = {
        "id": incident.reference_number,
        "title": incident.title,
        "description": incident.description,
        "application": incident.application.code,
        "severity": incident.severity,
        "priority": incident.priority,
        "category": incident.category,
        "status": incident.status,
        "assigned_team": incident.assigned_team,
        "assigned_engineer": incident.assigned_engineer,
        "business_impact": incident.business_impact,
        "resolution_summary": incident.resolution_summary,
        "started_at": _iso(start),
        "acknowledged_at": _iso(incident.acknowledged_at),
        "resolved_at": _iso(incident.resolved_at),
        "sla": {
            "response": sla.response.state,
            "resolution": sla.resolution.state,
            "resolution_minutes_remaining": sla.resolution.remaining_minutes,
            "note": "demonstration SLA targets",
        },
    }

    # ---- timeline -------------------------------------------------------------------------
    ctx.data["timeline"] = []
    for event in IncidentRepository(db).timeline(incident.id):
        item_id = f"TL-{event.id}"
        ctx.valid_ids.add(item_id)
        ctx.data["timeline"].append({
            "id": item_id, "at": _iso(event.created_at), "minutes_from_start": rel(event.created_at),
            "type": event.event_type, "by": event.created_by, "source": event.source, "description": event.description,
        })

    # ---- applications & dependencies ------------------------------------------------------
    apps = ApplicationRepository(db)
    app = apps.get_with_dependencies(incident.application_id)
    dependents = apps.dependents_of(app.id)

    def app_view(a, **extra):
        ctx.application_codes.add(a.code)
        ctx.valid_ids.add(f"APP-{a.code}")
        return {"id": f"APP-{a.code}", "code": a.code, "name": a.name, "criticality": a.business_criticality,
                "health": a.health_status, **extra}

    ctx.data["applications"] = {
        "affected": app_view(app, technology=app.technology_stack, owner_team=app.owner_team),
        "depends_on": [app_view(d.depends_on, dependency=d.dependency_type, critical=d.is_critical, note=d.description)
                       for d in app.dependencies],
        "dependents": [app_view(a) for a in dependents],
    }
    related_app_ids = [app.id, *(d.depends_on_id for d in app.dependencies), *(a.id for a in dependents)]

    # ---- changes --------------------------------------------------------------------------
    def change_view(change: ChangeRecord, **extra):
        ctx.valid_ids.add(change.change_reference)
        return {
            "id": change.change_reference, "application": change.application.code, "title": change.title,
            "description": change.description, "type": change.change_type, "status": change.status,
            "risk": change.risk_level, "version": change.version, "deployed_at": _iso(change.deployed_at),
            "minutes_before_incident_start": -rel(change.deployed_at) if change.deployed_at else None,
            "rollback_plan": change.rollback_plan, **extra,
        }

    linked_ids = {link.change_id for link in incident.related_changes}
    ctx.data["related_changes"] = [
        change_view(link.change, link_status=link.link_status, link_notes=link.notes) for link in incident.related_changes
    ]
    recent = db.scalars(
        select(ChangeRecord)
        .where(
            ChangeRecord.application_id.in_(related_app_ids),
            ChangeRecord.deployed_at.between(start - RECENT_CHANGE_WINDOW, incident.resolved_at or now),
            ChangeRecord.id.not_in(linked_ids or [0]),
        )
        .order_by(ChangeRecord.deployed_at.desc())
    )
    ctx.data["other_recent_changes"] = [change_view(c) for c in recent]

    # ---- operational evidence -------------------------------------------------------------
    events = EvidenceRepository(db).search(
        EvidenceFilters(application_ids=related_app_ids, occurred_from=start - EVIDENCE_WINDOW_BEFORE,
                        occurred_to=incident.resolved_at or now),
        limit=1000,
    )
    series: dict[tuple[str, str], list[OperationalEvent]] = defaultdict(list)
    discrete: list[OperationalEvent] = []
    for event in events:
        if event.event_type == EvidenceType.METRIC:
            series[(event.application.code, event.metric_name)].append(event)
        else:
            discrete.append(event)

    metric_series = []
    for (code, name), points in sorted(series.items()):
        item_id = f"MS-{code}-{name}"
        ctx.valid_ids.add(item_id)
        metric_series.append({
            "id": item_id, "application": code, "metric": name, "unit": points[0].unit,
            "points": [{"minutes_from_start": rel(p.occurred_at), "value": p.metric_value,
                        **({"attributes": p.attributes} if p.attributes else {})} for p in points],
        })
    event_items = []
    for event in discrete[-MAX_EVENTS:]:
        item_id = f"EV-{event.id}"
        ctx.valid_ids.add(item_id)
        event_items.append({
            "id": item_id, "application": event.application.code, "type": event.event_type, "level": event.level,
            "source": event.source_system, "minutes_from_start": rel(event.occurred_at), "message": event.message,
            **({"attributes": event.attributes} if event.attributes else {}),
        })
    ctx.data["evidence"] = {
        "window": f"{int(EVIDENCE_WINDOW_BEFORE.total_seconds() // 60)} minutes before incident start until "
                  f"{'resolution' if incident.resolved_at else 'now'}",
        "metric_series": metric_series,
        "events": event_items,
    }

    # ---- existing analysis on record ------------------------------------------------------
    ctx.data["existing_root_causes"] = []
    for rc in incident.root_causes:
        item_id = f"RC-{rc.id}"
        ctx.valid_ids.add(item_id)
        ctx.data["existing_root_causes"].append({
            "id": item_id, "status": rc.status, "source": rc.source, "confidence": rc.confidence,
            "description": rc.description, "supporting_evidence": rc.supporting_evidence,
            "missing_evidence": rc.missing_evidence,
        })
    ctx.data["existing_actions"] = [
        {"id": f"ACT-{a.id}", "type": a.action_type, "status": a.status, "owner": a.assigned_owner or a.assigned_team,
         "description": a.description}
        for a in incident.actions
    ]
    ctx.valid_ids.update(a["id"] for a in ctx.data["existing_actions"])

    # ---- recurrence -----------------------------------------------------------------------
    similar = db.scalars(
        select(Incident)
        .where(
            Incident.id != incident.id,
            Incident.application_id.in_(related_app_ids),
            Incident.created_at >= start - SIMILAR_INCIDENT_WINDOW,
        )
        .order_by(Incident.created_at.desc())
        .limit(8)
    )
    ctx.data["similar_incidents"] = []
    for other in similar:
        ctx.valid_ids.add(other.reference_number)
        ctx.data["similar_incidents"].append({
            "id": other.reference_number, "application": other.application.code, "title": other.title,
            "severity": other.severity, "category": other.category, "status": other.status,
            "started_minutes_from_this_incident": rel(other.started_at),
            "resolution_summary": other.resolution_summary,
        })

    ctx.data["analysis_time"] = _iso(now)
    return ctx
