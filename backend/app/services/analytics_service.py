"""Incident analytics.

Definitions used throughout:
- MTTR (Mean Time to Resolve): mean of (resolved_at - started_at) for resolved/closed incidents,
  i.e. measured from when business impact began.
- MTTA (Mean Time to Acknowledge): mean of (acknowledged_at - logged time).
- SLA compliance: met / (met + breached); incidents still within their window are "pending" and excluded.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.models import Application, Incident, IncidentSla
from app.models.enums import ACTIVE_STATUSES, IncidentStatus, Severity, SlaState
from app.services import sla_service
from app.utils.time import utcnow

RESOLVED_STATUSES = (IncidentStatus.RESOLVED, IncidentStatus.CLOSED)


@dataclass
class AnalyticsFilter:
    created_from: datetime | None = None
    created_to: datetime | None = None
    application_id: int | None = None


def _minutes(expr):
    return func.extract("epoch", expr) / 60.0


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _round(value) -> float | None:
    return round(float(value), 1) if value is not None else None


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    def _scoped(self, stmt: Select, f: AnalyticsFilter) -> Select:
        if f.created_from:
            stmt = stmt.where(Incident.created_at >= f.created_from)
        if f.created_to:
            stmt = stmt.where(Incident.created_at <= f.created_to)
        if f.application_id:
            stmt = stmt.where(Incident.application_id == f.application_id)
        return stmt

    def _incidents_with_sla(self, f: AnalyticsFilter) -> list[Incident]:
        stmt = self._scoped(select(Incident).join(IncidentSla), f)
        return list(self.db.scalars(stmt).unique())

    # ---- summary ------------------------------------------------------------------------

    def summary(self, f: AnalyticsFilter) -> dict:
        is_active = Incident.status.in_(ACTIVE_STATUSES)
        stmt = self._scoped(
            select(
                func.count(Incident.id),
                func.count(case((is_active, 1))),
                func.count(case((Incident.severity == Severity.P1, 1))),
                func.count(case((is_active & (Incident.severity == Severity.P1), 1))),
                func.count(case((Incident.status.in_(RESOLVED_STATUSES), 1))),
                func.count(case((Incident.reopen_count > 0, 1))),
            ),
            f,
        )
        total, open_, p1_total, p1_open, resolved, reopened = self.db.execute(stmt).one()
        sla = self.sla_compliance(f)
        return {
            "total_incidents": total,
            "open_incidents": open_,
            "resolved_or_closed_incidents": resolved,
            "p1_incidents": p1_total,
            "open_p1_incidents": p1_open,
            "reopened_incidents": reopened,
            "sla_breached_incidents": sla["breached_incidents"],
            "sla_compliance_pct": sla["overall_compliance_pct"],
            "mttr_minutes": self.mttr(f)["overall"]["mttr_minutes"],
            "generated_at": utcnow(),
        }

    # ---- breakdowns ---------------------------------------------------------------------

    def _breakdown(self, column, f: AnalyticsFilter) -> list[dict]:
        is_active = Incident.status.in_(ACTIVE_STATUSES)
        stmt = self._scoped(
            select(column, func.count(Incident.id), func.count(case((is_active, 1)))).group_by(column), f
        )
        return [{"key": key, "total": total, "open": open_} for key, total, open_ in self.db.execute(stmt)]

    def severity_breakdown(self, f: AnalyticsFilter) -> list[dict]:
        rows = {r["key"]: r for r in self._breakdown(Incident.severity, f)}
        return [
            {"severity": s, "total": rows.get(s, {}).get("total", 0), "open": rows.get(s, {}).get("open", 0)}
            for s in Severity
        ]

    def category_breakdown(self, f: AnalyticsFilter) -> list[dict]:
        rows = self._breakdown(Incident.category, f)
        return sorted(
            ({"category": r["key"], "total": r["total"], "open": r["open"]} for r in rows),
            key=lambda r: -r["total"],
        )

    def application_incidents(self, f: AnalyticsFilter) -> list[dict]:
        is_active = Incident.status.in_(ACTIVE_STATUSES)
        resolved = Incident.resolved_at.is_not(None)
        stmt = self._scoped(
            select(
                Application.id,
                Application.code,
                Application.name,
                Application.business_criticality,
                func.count(Incident.id),
                func.count(case((is_active, 1))),
                func.count(case((Incident.severity == Severity.P1, 1))),
                func.avg(case((resolved, _minutes(Incident.resolved_at - Incident.started_at)))),
            )
            .join(Incident, Incident.application_id == Application.id)
            .group_by(Application.id),
            f,
        )
        return sorted(
            (
                {
                    "application_id": app_id,
                    "application_code": code,
                    "application_name": name,
                    "business_criticality": criticality,
                    "total": total,
                    "open": open_,
                    "p1": p1,
                    "mttr_minutes": _round(mttr),
                }
                for app_id, code, name, criticality, total, open_, p1, mttr in self.db.execute(stmt)
            ),
            key=lambda r: -r["total"],
        )

    # ---- MTTR ---------------------------------------------------------------------------

    def mttr(self, f: AnalyticsFilter) -> dict:
        resolve_minutes = _minutes(Incident.resolved_at - Incident.started_at)
        ack_minutes = _minutes(Incident.acknowledged_at - IncidentSla.clock_started_at)
        metrics = (
            func.count(Incident.resolved_at),
            func.avg(resolve_minutes),
            func.min(resolve_minutes),
            func.max(resolve_minutes),
            func.avg(ack_minutes),
        )

        def row_to_dict(count, avg, minimum, maximum, mtta) -> dict:
            return {
                "resolved_count": count,
                "mttr_minutes": _round(avg),
                "min_minutes": _round(minimum),
                "max_minutes": _round(maximum),
                "mtta_minutes": _round(mtta),
            }

        overall_stmt = self._scoped(select(*metrics).select_from(Incident).join(IncidentSla), f)
        overall = row_to_dict(*self.db.execute(overall_stmt).one())
        by_severity_stmt = self._scoped(
            select(Incident.severity, *metrics).select_from(Incident).join(IncidentSla).group_by(Incident.severity), f
        )
        by_severity_rows = {severity: row_to_dict(*rest) for severity, *rest in self.db.execute(by_severity_stmt)}
        empty = {"resolved_count": 0, "mttr_minutes": None, "min_minutes": None, "max_minutes": None, "mtta_minutes": None}
        return {
            "definition": "MTTR = mean(resolved_at - started_at) over resolved incidents; MTTA = mean time to acknowledge",
            "overall": overall,
            "by_severity": [{"severity": s, **by_severity_rows.get(s, empty)} for s in Severity],
        }

    # ---- SLA ----------------------------------------------------------------------------

    def sla_compliance(self, f: AnalyticsFilter) -> dict:
        now = utcnow()
        counters: dict[Severity, dict[str, Counter]] = defaultdict(lambda: {"response": Counter(), "resolution": Counter()})
        breached_incidents = 0
        for incident in self._incidents_with_sla(f):
            evaluation = sla_service.evaluate(incident, incident.sla, now)
            breached_incidents += evaluation.is_breached
            for kind, clock in (("response", evaluation.response), ("resolution", evaluation.resolution)):
                bucket = "pending" if clock.state in (SlaState.ON_TRACK, SlaState.AT_RISK) else clock.state.lower()
                counters[incident.severity][kind][bucket] += 1

        def stats(counter: Counter) -> dict:
            met, breached = counter["met"], counter["breached"]
            return {"met": met, "breached": breached, "pending": counter["pending"], "compliance_pct": _pct(met, met + breached)}

        total = {"response": Counter(), "resolution": Counter()}
        by_severity = []
        for severity in Severity:
            entry = counters.get(severity, {"response": Counter(), "resolution": Counter()})
            total["response"] += entry["response"]
            total["resolution"] += entry["resolution"]
            response_target, resolution_target = sla_service.targets_for(severity)
            by_severity.append(
                {
                    "severity": severity,
                    "response_target_minutes": response_target,
                    "resolution_target_minutes": resolution_target,
                    "response": stats(entry["response"]),
                    "resolution": stats(entry["resolution"]),
                }
            )
        met = total["response"]["met"] + total["resolution"]["met"]
        breached = total["response"]["breached"] + total["resolution"]["breached"]
        return {
            "note": "Demonstration SLA targets - not universal banking requirements",
            "breached_incidents": breached_incidents,
            "overall_compliance_pct": _pct(met, met + breached),
            "response": stats(total["response"]),
            "resolution": stats(total["resolution"]),
            "by_severity": by_severity,
        }

    # ---- trends & recurrence ------------------------------------------------------------

    def trends(self, days: int, application_id: int | None = None) -> list[dict]:
        today = utcnow().date()
        start = today - timedelta(days=days - 1)
        f = AnalyticsFilter(application_id=application_id)
        created = self.db.execute(
            self._scoped(
                select(func.date(Incident.created_at), Incident.severity, func.count())
                .where(func.date(Incident.created_at) >= start)
                .group_by(func.date(Incident.created_at), Incident.severity),
                f,
            )
        ).all()
        resolved = self.db.execute(
            self._scoped(
                select(func.date(Incident.resolved_at), func.count())
                .where(Incident.resolved_at.is_not(None), func.date(Incident.resolved_at) >= start)
                .group_by(func.date(Incident.resolved_at)),
                f,
            )
        ).all()
        series = {
            start + timedelta(days=i): {"created": 0, "resolved": 0, **{s.value: 0 for s in Severity}}
            for i in range(days)
        }
        for day, severity, count in created:
            series[day]["created"] += count
            series[day][severity] += count
        for day, count in resolved:
            series[day]["resolved"] += count
        return [{"date": day.isoformat(), **values} for day, values in series.items()]

    def repeated_incidents(self, days: int, min_occurrences: int) -> list[dict]:
        """Same application + category recurring within the window - a problem-management signal."""
        since = utcnow() - timedelta(days=days)
        stmt = (
            select(
                Application.id,
                Application.name,
                Incident.category,
                func.count(Incident.id),
                func.array_agg(Incident.reference_number),
                func.max(Incident.created_at),
            )
            .join(Application)
            .where(Incident.created_at >= since)
            .group_by(Application.id, Application.name, Incident.category)
            .having(func.count(Incident.id) >= min_occurrences)
            .order_by(func.count(Incident.id).desc())
        )
        return [
            {
                "application_id": app_id,
                "application_name": name,
                "category": category,
                "occurrences": count,
                "incident_references": sorted(refs),
                "last_occurred_at": last,
            }
            for app_id, name, category, count, refs, last in self.db.execute(stmt)
        ]
