"""Tools the investigation agents call. Read-only: they query the platform, they never change it.

Most tools return a slice of the incident fact base (context.py), so every item keeps the `id` the
guardrails check citations against. Two tools compute scores (impact, operational risk); their results
get their own citable ids (IMPACT-<ref>, RISK-<ref>) so agents can cite the calculation itself.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.compact import summarise_series
from app.ai.context import IncidentContext
from app.models import Incident
from app.models.enums import IncidentStatus
from app.repositories.application_repository import ApplicationRepository

ACTIVE = [s for s in IncidentStatus if s not in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED)]
REPEAT_WINDOW = timedelta(days=90)
TIER_POINTS = {"TIER_1": 30, "TIER_2": 18, "TIER_3": 8}
SEVERITY_POINTS = {"P1": 30, "P2": 20, "P3": 10, "P4": 4}
CHANGE_RISK_POINTS = {"HIGH": 25, "MEDIUM": 15, "LOW": 6}
MAX_EVENTS = 25


def band(score: int) -> str:
    return "HIGH" if score >= 60 else "MEDIUM" if score >= 35 else "LOW"


@dataclass
class Toolkit:
    """Everything a tool needs: the database, the incident and its (possibly compact) fact base."""

    db: Session
    incident: Incident
    ctx: IncidentContext
    computed: dict = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return self.incident.reference_number

    # ---- fact-base slices -----------------------------------------------------------------

    def get_incident_details(self) -> dict:
        return self.ctx.data["incident"]

    def get_incident_timeline(self) -> dict:
        return {"timeline": self.ctx.data["timeline"]}

    def get_application_health(self) -> dict:
        apps = self.ctx.data["applications"]
        evidence = self.ctx.data["evidence"]
        series = [s if "points" not in s else summarise_series(s) for s in evidence["metric_series"]]
        return {
            "health": [{"id": a["id"], "code": a["code"], "health": a["health"]}
                       for a in [apps["affected"], *apps["depends_on"], *apps["dependents"]]],
            "evidence_window": evidence["window"],
            "metric_series": series,
            "alerts_logs_jobs": evidence["events"][-MAX_EVENTS:],
        }

    def get_application_dependencies(self) -> dict:
        return self.ctx.data["applications"]

    def get_related_changes(self) -> dict:
        return {"linked_to_incident": self.ctx.data["related_changes"]}

    def get_recent_deployments(self) -> dict:
        return {"other_recent_changes": self.ctx.data["other_recent_changes"]}

    def get_incident_history(self) -> dict:
        return {"similar_incidents": self.ctx.data["similar_incidents"],
                "existing_root_causes": self.ctx.data["existing_root_causes"]}

    def get_business_calendar(self) -> dict:
        """Month-end close, payroll, regulatory deadlines, peaks and holidays overlapping the incident."""
        return {"priority": self.ctx.data["incident"]["priority"],
                "priority_reason": self.ctx.data["incident"].get("priority_reason"),
                **self.ctx.data.get("business_calendar", {"periods": []})}

    # ---- calculations ---------------------------------------------------------------------

    def calculate_incident_impact(self) -> dict:
        """Blast radius: tier, severity, SLA state and connected applications with active incidents."""
        apps = self.ctx.data["applications"]
        connected = {a["code"] for a in [*apps["depends_on"], *apps["dependents"]]}
        active = {}
        if connected:
            rows = self.db.execute(
                select(Incident.reference_number, Incident.severity, Incident.title, Incident.application_id)
                .where(Incident.id != self.incident.id, Incident.status.in_(ACTIVE),
                       Incident.started_at.between(self.incident.started_at - timedelta(hours=3),
                                                   self.incident.started_at + timedelta(hours=3)))
            ).all()
            codes = {a.id: a.code for a in [self.incident.application, *self._connected_apps()]}
            for ref, sev, title, app_id in rows:
                code = codes.get(app_id)
                if code in connected:
                    active.setdefault(code, []).append({"id": ref, "severity": sev, "title": title})
                    self.ctx.valid_ids.add(ref)
        sla = self.ctx.data["incident"]["sla"]
        score = (TIER_POINTS.get(apps["affected"]["criticality"], 10)
                 + SEVERITY_POINTS.get(self.ctx.data["incident"]["severity"], 5)
                 + min(len(active) * 10, 30)
                 + (10 if "BREACH" in str(sla["resolution"]) else 0))
        result = {
            "id": f"IMPACT-{self.ref}",
            "score": min(score, 100),
            "band": band(score),
            "affected_tier": apps["affected"]["criticality"],
            "connected_applications": sorted(connected),
            "connected_with_active_incidents_within_3h": active,
            "sla_resolution": sla["resolution"],
            "method": "tier + severity + 10 per connected app with an active incident (max 30) + 10 if SLA breached",
        }
        self.ctx.valid_ids.add(result["id"])
        self.computed["impact"] = result
        return result

    def calculate_operational_risk(self) -> dict:
        """Operational risk: change risk near the incident, recurrence on this application, SLA, tier."""
        changes = [c for c in [*self.ctx.data["related_changes"], *self.ctx.data["other_recent_changes"]]
                   if c.get("minutes_before_incident_start") is not None and 0 <= c["minutes_before_incident_start"] <= 24 * 60]
        riskiest = max(changes, key=lambda c: CHANGE_RISK_POINTS.get(c.get("risk"), 0), default=None)
        repeats = self.db.scalar(
            select(func.count()).select_from(Incident).where(
                Incident.id != self.incident.id,
                Incident.application_id == self.incident.application_id,
                Incident.started_at.between(self.incident.started_at - REPEAT_WINDOW, self.incident.started_at),
            )
        ) or 0
        sla = self.ctx.data["incident"]["sla"]
        tier = self.ctx.data["applications"]["affected"]["criticality"]
        parts = {
            "change_risk": CHANGE_RISK_POINTS.get(riskiest.get("risk"), 0) if riskiest else 0,
            "recurrence": min(repeats * 3, 25),
            "sla": 15 if "BREACH" in str(sla["resolution"]) else 8 if "RISK" in str(sla["resolution"]) else 0,
            "tier": TIER_POINTS.get(tier, 10),
        }
        score = min(sum(parts.values()), 100)
        result = {
            "id": f"RISK-{self.ref}",
            "score": score,
            "band": band(score),
            "components": parts,
            "change_within_24h": {"id": riskiest["id"], "risk": riskiest.get("risk"),
                                  "minutes_before_incident_start": riskiest["minutes_before_incident_start"]}
            if riskiest else None,
            "incidents_on_same_application_last_90_days": repeats,
            "method": "change risk (0-25) + recurrence (3 per incident, max 25) + SLA (0-15) + tier (8-30)",
        }
        self.ctx.valid_ids.add(result["id"])
        self.computed["risk"] = result
        return result

    def _connected_apps(self):
        app = self.incident.application
        repo = ApplicationRepository(self.db)
        full = repo.get_with_dependencies(app.id)
        return [*(d.depends_on for d in full.dependencies), *repo.dependents_of(app.id)]


TOOL_NAMES = [
    "get_incident_details", "get_incident_timeline", "get_application_health", "get_application_dependencies",
    "get_related_changes", "get_recent_deployments", "calculate_incident_impact", "calculate_operational_risk",
    "get_incident_history", "get_business_calendar",
]


def call_tool(kit: Toolkit, name: str) -> dict:
    if name not in TOOL_NAMES:
        raise ValueError(f"Unknown tool {name}")
    fn: Callable[[], dict] = getattr(kit, name)
    return fn()


def summarise_result(result: dict) -> dict:
    """What the audit log keeps per tool call: sizes and ids, not the full payload."""
    out = {}
    for key, value in result.items():
        if isinstance(value, list):
            out[key] = len(value)
        elif isinstance(value, dict) and key not in ("components", "sla"):
            out[key] = len(value)
        elif key in ("id", "score", "band"):
            out[key] = value
    return out
