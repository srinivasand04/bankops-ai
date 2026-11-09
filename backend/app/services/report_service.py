"""Management reports: five views over all applications for a chosen period.

1. Application scorecard - every application, its incidents, SLA, MTTR, changes and a RAG status
2. SLA performance       - compliance by severity and application, and the incidents breaching now
3. Trends                - incident volume by severity, resolutions, MTTR and SLA breaches over time
4. Change risk           - changes per application, failures, incidents linked to changes
5. Problem management    - recurring incidents (same application + category) and reopened incidents

All reports cover incidents created in the period. SLA targets are demonstration values.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Application, ChangeRecord, Incident
from app.models.enums import ACTIVE_STATUSES, ChangeStatus, ChangeType, RiskLevel, Severity, SlaState
from app.models.incident import IncidentRelatedChange
from app.services import sla_service
from app.utils.time import utcnow

RAG_RULES = (
    "RED: an open P1, resolution SLA compliance below 80%, or 3+ incidents breaching now. "
    "AMBER: compliance below 95%, an open P2, or any incident breaching now. GREEN otherwise."
)
RECURRING_MIN = 3


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 1) if values else None


def _minutes(start: datetime | None, end: datetime | None) -> float | None:
    return (end - start).total_seconds() / 60 if start and end else None


class ReportService:
    def __init__(self, db: Session, days: int = 90, now: datetime | None = None):
        self.db = db
        self.days = days
        self.now = now or utcnow()
        self.since = self.now - timedelta(days=days)
        self.apps = list(self.db.scalars(select(Application).where(Application.is_active).order_by(Application.code)))
        self.incidents = list(self.db.scalars(
            select(Incident)
            .options(selectinload(Incident.sla))
            .where(Incident.created_at >= self.since, Incident.created_at <= self.now)
        ))
        # resolution SLA state per incident, evaluated once
        self.sla = {i.id: sla_service.evaluate(i, i.sla, self.now) for i in self.incidents if i.sla}
        self.changes = list(self.db.scalars(
            select(ChangeRecord).where(ChangeRecord.deployed_at >= self.since, ChangeRecord.deployed_at <= self.now)
        ))
        change_ids = [c.id for c in self.changes]
        self.links = list(self.db.scalars(
            select(IncidentRelatedChange).where(IncidentRelatedChange.change_id.in_(change_ids or [0]))
        ))

    # ---- shared ---------------------------------------------------------------------------

    def period(self) -> dict:
        return {"days": self.days, "from": self.since, "to": self.now, "generated_at": utcnow()}

    def _by_app(self) -> dict[int, list[Incident]]:
        grouped: dict[int, list[Incident]] = defaultdict(list)
        for i in self.incidents:
            grouped[i.application_id].append(i)
        return grouped

    def _resolution_state(self, incident: Incident) -> SlaState | None:
        ev = self.sla.get(incident.id)
        return ev.resolution.state if ev else None

    def _breaching_now(self, incident: Incident) -> bool:
        return incident.status in ACTIVE_STATUSES and self._resolution_state(incident) == SlaState.BREACHED

    def _sla_counts(self, incidents: list[Incident], clock: str = "resolution") -> dict:
        met = breached = pending = 0
        for i in incidents:
            ev = self.sla.get(i.id)
            if not ev:
                continue
            state = getattr(ev, clock).state
            if state == SlaState.MET:
                met += 1
            elif state == SlaState.BREACHED:
                breached += 1
            else:
                pending += 1
        return {"met": met, "breached": breached, "pending": pending, "compliance_pct": _pct(met, met + breached)}

    @staticmethod
    def _mttr(incidents: list[Incident]) -> float | None:
        return _avg([m for i in incidents if (m := _minutes(i.started_at, i.resolved_at)) is not None])

    def _mtta(self, incidents: list[Incident]) -> float | None:
        return _avg([m for i in incidents if i.sla and (m := _minutes(i.sla.clock_started_at, i.acknowledged_at)) is not None])

    # ---- 1. application scorecard ---------------------------------------------------------

    def scorecard(self) -> dict:
        by_app = self._by_app()
        changes_by_app: dict[int, list[ChangeRecord]] = defaultdict(list)
        for c in self.changes:
            changes_by_app[c.application_id].append(c)
        linked_by_app = Counter()
        change_app = {c.id: c.application_id for c in self.changes}
        for link in self.links:
            linked_by_app[change_app[link.change_id]] += 1

        rows = []
        for app in self.apps:
            items = by_app.get(app.id, [])
            active = [i for i in items if i.status in ACTIVE_STATUSES]
            sla = self._sla_counts(items)
            breaching = sum(self._breaching_now(i) for i in items)
            open_p1 = sum(i.severity == Severity.P1 for i in active)
            open_p2 = sum(i.severity == Severity.P2 for i in active)
            compliance = sla["compliance_pct"]
            if open_p1 or (compliance is not None and compliance < 80) or breaching >= 3:
                rag = "RED"
            elif (compliance is not None and compliance < 95) or open_p2 or breaching:
                rag = "AMBER"
            else:
                rag = "GREEN"
            categories = Counter(i.category for i in items)
            app_changes = changes_by_app.get(app.id, [])
            rows.append({
                "application_id": app.id,
                "code": app.code,
                "name": app.name,
                "tier": app.business_criticality,
                "health": app.health_status,
                "owner_team": app.owner_team,
                "incidents": len(items),
                "open": len(active),
                "p1": sum(i.severity == Severity.P1 for i in items),
                "p2": sum(i.severity == Severity.P2 for i in items),
                "open_p1": open_p1,
                "sla_compliance_pct": compliance,
                "sla_breached": sla["breached"],
                "breaching_now": breaching,
                "mttr_minutes": self._mttr(items),
                "mtta_minutes": self._mtta(items),
                "reopened": sum((i.reopen_count or 0) > 0 for i in items),
                "changes": len(app_changes),
                "failed_changes": sum(c.status in (ChangeStatus.FAILED, ChangeStatus.ROLLED_BACK) for c in app_changes),
                "change_linked_incidents": linked_by_app.get(app.id, 0),
                "top_category": categories.most_common(1)[0][0] if categories else None,
                "rag": rag,
            })
        rows.sort(key=lambda r: ({"RED": 0, "AMBER": 1, "GREEN": 2}[r["rag"]], -r["incidents"]))
        all_sla = self._sla_counts(self.incidents)
        totals = {
            "applications": len(self.apps),
            "incidents": len(self.incidents),
            "open": sum(r["open"] for r in rows),
            "p1": sum(r["p1"] for r in rows),
            "open_p1": sum(r["open_p1"] for r in rows),
            "sla_compliance_pct": all_sla["compliance_pct"],
            "breaching_now": sum(r["breaching_now"] for r in rows),
            "mttr_minutes": self._mttr(self.incidents),
            "mtta_minutes": self._mtta(self.incidents),
            "changes": len(self.changes),
            "rag": dict(Counter(r["rag"] for r in rows)),
        }
        return {"period": self.period(), "totals": totals, "applications": rows, "rag_rules": RAG_RULES}

    # ---- 2. SLA performance ---------------------------------------------------------------

    def sla_report(self) -> dict:
        by_severity = []
        for sev in Severity:
            items = [i for i in self.incidents if i.severity == sev]
            response_target, resolution_target = sla_service.targets_for(sev)
            by_severity.append({
                "severity": sev, "incidents": len(items),
                "response_target_minutes": response_target, "resolution_target_minutes": resolution_target,
                "response": self._sla_counts(items, "response"), "resolution": self._sla_counts(items, "resolution"),
            })
        by_app = self._by_app()
        by_application = sorted(
            ({"code": a.code, "name": a.name, "tier": a.business_criticality,
              **self._sla_counts(by_app.get(a.id, []))} for a in self.apps),
            key=lambda r: (r["compliance_pct"] is None, r["compliance_pct"] if r["compliance_pct"] is not None else 0),
        )
        codes = {a.id: a.code for a in self.apps}
        breaches = []
        for i in self.incidents:
            if self._breaching_now(i):
                ev = self.sla[i.id]
                breaches.append({
                    "id": i.id, "reference": i.reference_number, "application": codes.get(i.application_id, "?"),
                    "severity": i.severity, "status": i.status, "title": i.title,
                    "assigned_team": i.assigned_team, "overdue_minutes": round(-ev.resolution.remaining_minutes),
                })
        breaches.sort(key=lambda b: -b["overdue_minutes"])
        return {
            "period": self.period(),
            "overall": {"response": self._sla_counts(self.incidents, "response"),
                        "resolution": self._sla_counts(self.incidents, "resolution")},
            "by_severity": by_severity,
            "by_application": by_application,
            "breaching_now": breaches[:20],
            "breaching_now_total": len(breaches),
            "note": "Demonstration SLA targets - not universal banking requirements",
        }

    # ---- 3. trends ------------------------------------------------------------------------

    def trends(self) -> dict:
        weekly = self.days <= 120

        def bucket(dt: datetime) -> str:
            if weekly:
                monday = (dt - timedelta(days=dt.weekday())).date()
                return monday.isoformat()
            return dt.strftime("%Y-%m")

        series: dict[str, dict] = {}
        cursor = self.since
        while cursor <= self.now:
            series.setdefault(bucket(cursor), {"created": 0, "resolved": 0, "sla_breached": 0, "mttr": [],
                                               **{s.value: 0 for s in Severity}})
            cursor += timedelta(days=1)
        for i in self.incidents:
            b = series.get(bucket(i.created_at))
            if b is None:
                continue
            b["created"] += 1
            b[i.severity] += 1
            if self._resolution_state(i) == SlaState.BREACHED:
                b["sla_breached"] += 1
            if i.resolved_at and (rb := series.get(bucket(i.resolved_at))):
                rb["resolved"] += 1
                if (m := _minutes(i.started_at, i.resolved_at)) is not None:
                    rb["mttr"].append(m)
        points = [{"period": k, **{kk: v for kk, v in b.items() if kk != "mttr"}, "mttr_minutes": _avg(b["mttr"])}
                  for k, b in sorted(series.items())]
        return {"period": self.period(), "granularity": "week" if weekly else "month", "points": points}

    # ---- 4. change risk -------------------------------------------------------------------

    def change_risk(self) -> dict:
        refs = {i.id: i for i in self.db.scalars(
            select(Incident).where(Incident.id.in_({link.incident_id for link in self.links} or {0})))}
        linked: dict[int, list[str]] = defaultdict(list)
        for link in self.links:
            if link.incident_id in refs:
                linked[link.change_id].append(refs[link.incident_id].reference_number)
        rows = []
        for app in self.apps:
            items = [c for c in self.changes if c.application_id == app.id]
            failed = sum(c.status in (ChangeStatus.FAILED, ChangeStatus.ROLLED_BACK) for c in items)
            causing = sum(1 for c in items if linked.get(c.id))
            rows.append({
                "code": app.code, "name": app.name, "tier": app.business_criticality,
                "changes": len(items),
                "emergency": sum(c.change_type == ChangeType.EMERGENCY for c in items),
                "high_risk": sum(c.risk_level == RiskLevel.HIGH for c in items),
                "failed_or_rolled_back": failed,
                "changes_with_incidents": causing,
                "linked_incidents": sum(len(linked.get(c.id, [])) for c in items),
                # change failure rate (DORA-style): changes that failed, were rolled back or led to an incident
                "change_failure_rate_pct": _pct(sum(1 for c in items if c.status in (ChangeStatus.FAILED, ChangeStatus.ROLLED_BACK) or linked.get(c.id)), len(items)),
            })
        rows.sort(key=lambda r: -(r["change_failure_rate_pct"] or 0))
        codes = {a.id: a.code for a in self.apps}
        top = sorted((c for c in self.changes if linked.get(c.id)), key=lambda c: -len(linked[c.id]))[:10]
        total_bad = sum(1 for c in self.changes if c.status in (ChangeStatus.FAILED, ChangeStatus.ROLLED_BACK) or linked.get(c.id))
        return {
            "period": self.period(),
            "totals": {"changes": len(self.changes), "change_failure_rate_pct": _pct(total_bad, len(self.changes)),
                       "linked_incidents": len(self.links)},
            "by_application": rows,
            "top_changes": [{
                "reference": c.change_reference, "application": codes.get(c.application_id, "?"), "title": c.title,
                "type": c.change_type, "risk": c.risk_level, "status": c.status, "deployed_at": c.deployed_at,
                "incidents": sorted(linked[c.id]),
            } for c in top],
            "definition": "Change failure rate = changes that failed, were rolled back or are linked to an incident / changes deployed",
        }

    # ---- 5. problem management ------------------------------------------------------------

    def problems(self) -> dict:
        codes = {a.id: (a.code, a.name) for a in self.apps}
        groups: dict[tuple[int, str], list[Incident]] = defaultdict(list)
        for i in self.incidents:
            groups[(i.application_id, i.category)].append(i)
        recurring = []
        for (app_id, category), items in groups.items():
            if len(items) < RECURRING_MIN:
                continue
            items.sort(key=lambda i: i.created_at)
            code, name = codes.get(app_id, ("?", "?"))
            recurring.append({
                "application": code, "application_name": name, "category": category,
                "occurrences": len(items),
                "open": sum(i.status in ACTIVE_STATUSES for i in items),
                "p1_p2": sum(i.severity in (Severity.P1, Severity.P2) for i in items),
                "mttr_minutes": self._mttr(items),
                "last_occurred_at": items[-1].created_at,
                "latest_references": [i.reference_number for i in items[-5:]][::-1],
            })
        recurring.sort(key=lambda r: (-r["occurrences"], -r["p1_p2"]))
        reopened = sorted((i for i in self.incidents if (i.reopen_count or 0) > 0), key=lambda i: -(i.reopen_count or 0))
        return {
            "period": self.period(),
            "threshold": RECURRING_MIN,
            "recurring": recurring[:20],
            "recurring_total": len(recurring),
            "reopened": [{"id": i.id, "reference": i.reference_number, "application": codes.get(i.application_id, ("?",))[0],
                          "severity": i.severity, "title": i.title, "reopen_count": i.reopen_count} for i in reopened[:15]],
            "reopened_total": len(reopened),
            "note": f"Recurring = the same application and category {RECURRING_MIN}+ times in the period - candidates for a problem record",
        }

    def management_pack(self) -> dict:
        return {
            "period": self.period(),
            "scorecard": self.scorecard(),
            "sla": self.sla_report(),
            "trends": self.trends(),
            "change_risk": self.change_risk(),
            "problems": self.problems(),
        }
