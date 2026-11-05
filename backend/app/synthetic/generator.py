"""Generate 12 months of realistic banking IT history with signal the ML tasks can learn.

The output is a dataset folder in the standard ingestion format (see app/ingestion/schemas.py),
loadable with `python -m app.ingestion load datasets/synthetic_large`. Every rule below is a
named constant so the signal is documented in one place (also in documents/synthetic-data.md).

Determinism: one `random.Random(seed)` drives everything, iteration orders are fixed (lists and
insertion-ordered dicts only), and timestamps are absolute and anchored at `end`. The same
(seed, months, scale, end) always produces byte-identical files.

Time zone: all times are UTC and treated as the bank's local time (keeps the calendar rules simple).
"""

import bisect
import json
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import DEFAULT_SLA_TARGETS
from app.synthetic.catalog import APP_BY_CODE, APPS, DEPENDENCIES, ENGINEERS, PROBLEMS, SPECIALIST_ROUTING_RATE, SPECIALIST_TEAMS, AppSpec, Problem
from app.synthetic.vocabulary import CONFUSABLE, ENTITIES, RESOLUTIONS, SYMPTOMS, TITLES

DATA_SOURCE = "SYNTHETIC_LARGE"

# ---- volumes at scale 1.0 per 12 months -----------------------------------------------------------
INCIDENTS_PER_YEAR = 4000
CHANGES_PER_YEAR = 650

# ---- change risk (task: change risk scoring) --------------------------------------------------------
# P(change causes an incident within 0-6 h) = sigmoid(logit); each term below raises or lowers it.
CHANGE_RISK_BASE = -3.4
CHANGE_RISK_FRIDAY = 1.2  # deployed on a Friday
CHANGE_RISK_OUT_OF_WINDOW = 1.0  # outside the approved change window
CHANGE_RISK_PER_COMPONENT = 0.05  # per component touched (scope), capped below
CHANGE_RISK_COMPONENT_CAP = 40
CHANGE_RISK_TIER_1 = 0.7  # Tier 1 application
CHANGE_RISK_EMERGENCY = 0.8
CHANGE_RISK_STANDARD = -0.6  # pre-approved standard changes are safer
CHANGE_INCIDENT_DELAY_MIN = (10, 360)  # caused incidents start 10 min - 6 h after deployment
IN_WINDOW_SHARE = 0.72  # most changes respect the window
FRIDAY_SHARE_OF_OUT_OF_WINDOW = 0.4
# Approved change window: Mon-Thu 18:00-23:00 and Sat 08:00-14:00 (weekday(): Mon=0 ... Sun=6)
CHANGE_WINDOWS = {0: (18, 23), 1: (18, 23), 2: (18, 23), 3: (18, 23), 5: (8, 14)}
CHANGE_LINK_MISS_RATE = 0.05  # label noise: a caused incident whose link was never recorded
FALSE_LINK_RATE = 0.03  # label noise: an unrelated incident wrongly linked to a harmless change
SUSPECTED_LINK_RATE = 0.3  # nearby harmless changes investigated and ruled out

# ---- severity (task: SLA breach) -------------------------------------------------------------------
SEVERITY_TIER = {"TIER_1": 1.0, "TIER_2": 0.3, "TIER_3": -0.6}
SEVERITY_CATEGORY = {"INFRASTRUCTURE": 0.5, "NETWORK": 0.5, "SECURITY": 0.5, "DATABASE": 0.4,
                     "API_INTEGRATION": 0.2, "AUTHENTICATION": 0.3, "DATA_PROCESSING": -0.3}
SEVERITY_RECENT_CHANGE = 0.8  # a change on the application in the 24 h before the incident
SEVERITY_BUSINESS_HOURS = 0.3  # 08:00-18:00 on weekdays (more customers affected)
SEVERITY_NOISE = 0.8
SEVERITY_THRESHOLDS = ((2.75, "P1"), (1.75, "P2"), (0.45, "P3"))  # score above -> severity, else P4 (about 4% / 18% / 48% / 30%)

# ---- response and resolution (tasks: MTTR, SLA breach) ------------------------------------------
# Resolution time = SLA resolution target x log-normal ratio, so breaches follow from the real targets.
MTTR_MEDIAN_RATIO = {"P1": 0.9, "P2": 0.6, "P3": 0.45, "P4": 0.35}  # P1s run closest to their target
MTTR_SIGMA = 0.6
MTTR_INFRA_FACTOR = 1.35  # infrastructure / network take longer
MTTR_NIGHT_FACTOR = 1.3  # started 22:00-06:00
MTTR_ESCALATED_FACTOR = 1.6
ESCALATION_RATE = {"P1": 0.35, "P2": 0.15, "P3": 0.05, "P4": 0.01}
ACK_MEDIAN_RATIO = 0.45  # acknowledgement time / response target
ACK_SIGMA = 0.75
ACK_NIGHT_FACTOR = 1.6
DETECTION_MEDIAN_MIN = 6
REOPEN_RATE = 0.03
CLOSE_DELAY_DAYS = (0.5, 3.0)

# ---- text (tasks: category classification, similarity, clustering) -----------------------------
AMBIGUOUS_TEXT_RATE = 0.12  # wording borrowed from a confusable category
CATEGORY_LABEL_NOISE = 0.05  # recorded category is wrong (text unchanged)
ROOT_CAUSE_RECORDED_RATE = 0.75  # closed recurring / change-caused incidents with a confirmed root cause

# ---- missing optional fields ---------------------------------------------------------------------
MISSING_BUSINESS_IMPACT = 0.15
MISSING_ENGINEER = 0.2
MISSING_IMPLEMENTER = 0.1
MISSING_EVIDENCE = 0.15  # incidents without logs/alerts

# ---- operational metrics (task: time series) -----------------------------------------------------
METRIC_DAILY_AMPLITUDE = 0.35  # +-35% over the day, peak around 13:00
METRIC_WEEKEND_FACTOR = 0.75
METRIC_YEARLY_TREND = 0.15  # +15% over the history (growth)
METRIC_NOISE = 0.05
ANOMALY_LEAD_MIN = (60, 180)  # anomalies start 1-3 h before the incident (an hourly point precedes it)
ANOMALY_FACTOR_UP = (2.5, 6.0)
ANOMALY_FACTOR_DOWN = (0.6, 0.85)
ANOMALY_P3_SHARE = 0.5  # P1/P2 always show in the metric, half of the P3s do
DOWN_METRICS = {"login_success_rate_pct"}  # metrics that drop when something is wrong

CHANGE_KINDS = (
    # (kind, title template, weight, categories of the incidents it causes)
    ("release", "{app} release {version}", 4, ("APPLICATION", "API_INTEGRATION", "PERFORMANCE")),
    ("config", "{app} configuration change: {component}", 3, ("APPLICATION", "PERFORMANCE")),
    ("os_patch", "OS patching on {host}", 2, ("INFRASTRUCTURE",)),
    ("db_maintenance", "Database maintenance on {table} ({app})", 2, ("DATABASE", "PERFORMANCE")),
    ("firewall", "Firewall rule update for {app}", 1, ("NETWORK",)),
    ("certificate", "Certificate renewal for {app}", 1, ("SECURITY", "AUTHENTICATION")),
)


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def in_change_window(dt: datetime) -> bool:
    window = CHANGE_WINDOWS.get(dt.weekday())
    return window is not None and window[0] <= dt.hour < window[1]


def is_night(dt: datetime) -> bool:
    return dt.hour >= 22 or dt.hour < 6


def is_business_hours(dt: datetime) -> bool:
    return dt.weekday() < 5 and 8 <= dt.hour < 18


@dataclass
class GeneratorConfig:
    seed: int = 42
    months: int = 12
    scale: float = 1.0
    end: datetime = field(default_factory=lambda: datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0))


@dataclass
class _Change:
    ref: str
    app: AppSpec
    kind: str
    deployed: datetime
    caused: bool
    record: dict


@dataclass
class _Incident:
    app: AppSpec
    start: datetime
    created: datetime
    resolved: datetime | None
    severity: str
    category: str
    problem: Problem | None
    change: _Change | None
    record: dict


class SyntheticGenerator:
    def __init__(self, config: GeneratorConfig):
        self.cfg = config
        self.rng = random.Random(config.seed)
        self.end = config.end
        self.start = self.end - timedelta(days=round(config.months * 30.44))
        self.factor = config.scale * config.months / 12
        self.changes: list[_Change] = []
        self.changes_by_app: dict[str, list[datetime]] = {a.code: [] for a in APPS}
        self.incidents: list[_Incident] = []
        self.events: list[dict] = []

    # ---- small helpers --------------------------------------------------------------------------

    def pick(self, weights: dict[str, float]) -> str:
        keys = list(weights)
        return self.rng.choices(keys, weights=[weights[k] for k in keys])[0]

    def fill(self, template: str, app: AppSpec) -> str:
        values = {k: self.rng.choice(v) for k, v in ENTITIES.items()}
        values.update(
            app=app.name, host=self.rng.choice(app.hosts or ("app-host-01",)),
            job=self.rng.choice(app.batch_jobs or ("NIGHTLY_EXTRACT",)), version=f"{self.rng.randint(1, 9)}.{self.rng.randint(0, 20)}.{self.rng.randint(0, 9)}",
            count=self.rng.randint(12, 900), pct=self.rng.randint(5, 95), seconds=self.rng.randint(3, 40),
            exit=self.rng.choice((4, 8, 12, 255)), time=f"{self.rng.randint(0, 23):02d}:{self.rng.randint(0, 59):02d}",
        )
        return template.format(**values)

    def random_time(self, category: str) -> datetime:
        """A start time with a realistic hour profile: business hours busier, batch failures at night."""
        day = self.start + timedelta(days=self.rng.randrange((self.end - self.start).days))
        if category == "BATCH_PROCESSING":
            hour_weights = [2.5 if h < 6 else 0.5 for h in range(24)]
        else:
            hour_weights = [1.6 if 8 <= h < 18 else 0.6 if h < 6 else 1.0 for h in range(24)]
        hour = self.rng.choices(range(24), weights=hour_weights)[0]
        return day + timedelta(hours=hour, minutes=self.rng.randrange(60))

    def recent_change(self, app: AppSpec, when: datetime) -> bool:
        times = self.changes_by_app[app.code]
        i = bisect.bisect_right(times, when)
        return i > 0 and when - times[i - 1] <= timedelta(hours=24)

    # ---- changes --------------------------------------------------------------------------------

    def _change_time(self) -> datetime:
        span_days = (self.end - self.start).days
        day = self.start + timedelta(days=self.rng.randrange(span_days))
        if self.rng.random() < IN_WINDOW_SHARE:
            while day.weekday() not in CHANGE_WINDOWS:
                day += timedelta(days=1)
            lo, hi = CHANGE_WINDOWS[day.weekday()]
            return day + timedelta(hours=self.rng.randrange(lo, hi), minutes=self.rng.randrange(60))
        if self.rng.random() < FRIDAY_SHARE_OF_OUT_OF_WINDOW:
            while day.weekday() != 4:
                day += timedelta(days=1)
        return day + timedelta(hours=self.rng.randrange(24), minutes=self.rng.randrange(60))

    def generate_changes(self) -> None:
        app_weights = {a.code: {"TIER_1": 1.3, "TIER_2": 1.0, "TIER_3": 0.7}[a.tier] for a in APPS}
        kinds = {k[0]: k for k in CHANGE_KINDS}
        drafts = []
        for _ in range(round(CHANGES_PER_YEAR * self.factor)):
            app = APP_BY_CODE[self.pick(app_weights)]
            deployed = self._change_time()
            if deployed > self.end - timedelta(hours=6):  # outcome must be observable before `end`
                continue
            drafts.append((deployed, app))
        drafts.sort(key=lambda d: d[0])

        for n, (deployed, app) in enumerate(drafts, start=1):
            kind, title_tpl, _, _ = kinds[self.pick({k[0]: k[2] for k in CHANGE_KINDS})]
            change_type = self.pick({"STANDARD": 0.45, "NORMAL": 0.45, "EMERGENCY": 0.10})
            components = min(1 + int(self.rng.lognormvariate(1.0, 0.8)), 60)
            friday, out_of_window = deployed.weekday() == 4, not in_change_window(deployed)
            logit = (CHANGE_RISK_BASE + CHANGE_RISK_FRIDAY * friday + CHANGE_RISK_OUT_OF_WINDOW * out_of_window
                     + CHANGE_RISK_PER_COMPONENT * min(components, CHANGE_RISK_COMPONENT_CAP)
                     + CHANGE_RISK_TIER_1 * (app.tier == "TIER_1")
                     + CHANGE_RISK_EMERGENCY * (change_type == "EMERGENCY") + CHANGE_RISK_STANDARD * (change_type == "STANDARD"))
            caused = self.rng.random() < sigmoid(logit)
            # Humans rate risk imperfectly: their rating is the true risk plus noise
            perceived = logit + self.rng.gauss(0, 1.0)
            risk = "HIGH" if perceived > -1.5 else "MEDIUM" if perceived > -2.8 else "LOW"
            status = "ROLLED_BACK" if caused and self.rng.random() < 0.35 else "FAILED" if self.rng.random() < 0.02 else "IMPLEMENTED"
            ref = f"CHG-L{n:05d}"
            record = {
                "change_reference": ref, "application": app.code, "title": self.fill(title_tpl, app)[:200],
                "description": f"{kind.replace('_', ' ').capitalize()} touching {components} component(s).",
                "change_type": change_type, "status": status, "risk_level": risk, "components_changed": components,
                "planned_start": iso(deployed - timedelta(minutes=30)), "deployed_at": iso(deployed),
                "external_id": ref, "rollback_plan": "Redeploy the previous version" if kind == "release" else "Restore previous configuration",
            }
            if self.rng.random() >= MISSING_IMPLEMENTER:
                record["implementer"] = self.rng.choice(ENGINEERS[app.owner_team])
                record["approver"] = "standard-change-catalogue" if change_type == "STANDARD" else "cab.chair"
            change = _Change(ref, app, kind, deployed, caused, record)
            self.changes.append(change)
            self.changes_by_app[app.code].append(deployed)
            self.events.append({"application": app.code, "event_type": "LOG", "level": "INFO", "source_system": "release-pipeline",
                                "message": f"Change {ref} deployed: {record['title']}", "occurred_at": iso(deployed),
                                "attributes": {"change": ref, "components": components}})

    # ---- incidents ------------------------------------------------------------------------------

    def _severity(self, app: AppSpec, category: str, start: datetime, recent: bool) -> str:
        score = (SEVERITY_TIER[app.tier] + SEVERITY_CATEGORY.get(category, 0.0) + SEVERITY_RECENT_CHANGE * recent
                 + SEVERITY_BUSINESS_HOURS * is_business_hours(start) + self.rng.gauss(0, SEVERITY_NOISE))
        return next((sev for threshold, sev in SEVERITY_THRESHOLDS if score > threshold), "P4")

    def _text(self, app: AppSpec, category: str, problem: Problem | None) -> tuple[str, str]:
        if problem is not None:
            host = self.rng.choice(app.hosts or ("app-host-01",))
            return problem.title, f"{problem.description} Seen on {host}. " + self.fill(self.rng.choice(SYMPTOMS[category]), app)
        text_category = category
        if self.rng.random() < AMBIGUOUS_TEXT_RATE:
            text_category = self.rng.choice(CONFUSABLE[category])
        title = self.fill(self.rng.choice(TITLES[text_category]), app)
        symptoms = " ".join(self.fill(s, app) for s in self.rng.sample(SYMPTOMS[text_category], k=2))
        return title[:200], f"{symptoms} Reported by monitoring for {app.name}."

    def make_incident(self, n: int, app: AppSpec, category: str, start: datetime,
                      problem: Problem | None = None, change: _Change | None = None) -> _Incident | None:
        recent = change is not None or self.recent_change(app, start)
        severity = self._severity(app, category, start, recent)
        night = is_night(start)
        created = start + timedelta(minutes=max(1.0, self.rng.lognormvariate(math.log(DETECTION_MEDIAN_MIN), 0.7) * (1.5 if night else 1)))
        if created >= self.end:
            return None
        target = DEFAULT_SLA_TARGETS[severity]
        ack = max(1.0, target.response * self.rng.lognormvariate(math.log(ACK_MEDIAN_RATIO), ACK_SIGMA) * (ACK_NIGHT_FACTOR if night else 1))
        escalated = self.rng.random() < ESCALATION_RATE[severity]
        ratio = self.rng.lognormvariate(math.log(MTTR_MEDIAN_RATIO[severity]), MTTR_SIGMA)
        ratio *= (MTTR_INFRA_FACTOR if category in ("INFRASTRUCTURE", "NETWORK") else 1) * (MTTR_NIGHT_FACTOR if night else 1)
        ratio *= MTTR_ESCALATED_FACTOR if escalated else 1
        detection = (created - start).total_seconds() / 60
        resolve_after = max(target.resolution * ratio - detection, ack + 15)  # minutes after creation

        # Routing label: owning team, or a specialist team for some categories
        team = app.owner_team
        if category in SPECIALIST_TEAMS and self.rng.random() < SPECIALIST_ROUTING_RATE:
            team = SPECIALIST_TEAMS[category]
        engineer = None if self.rng.random() < MISSING_ENGINEER else self.rng.choice(ENGINEERS[team])

        steps: list[dict] = [{"type": "assign", "after_minutes": round(ack, 1), "team": team, "engineer": engineer, "actor": "incident.manager"}]
        t = ack + self.rng.uniform(2, 20)
        steps.append({"type": "status", "after_minutes": round(t, 1), "status": "INVESTIGATING"})
        if escalated:
            t = max(t + 5, ack + (resolve_after - ack) * 0.25)
            steps.append({"type": "status", "after_minutes": round(t, 1), "status": "ESCALATED", "note": "Major incident bridge opened"})
        resolved_at = max(resolve_after, t + 5)
        steps.append({"type": "status", "after_minutes": round(resolved_at, 1), "status": "RESOLVED"})
        if self.rng.random() < REOPEN_RATE:
            t = resolved_at + self.rng.uniform(60, 600)
            steps.append({"type": "status", "after_minutes": round(t, 1), "status": "REOPENED", "note": "Symptoms returned"})
            steps.append({"type": "assign", "after_minutes": round(t + 5, 1), "team": team, "engineer": engineer, "actor": "incident.manager"})
            steps.append({"type": "status", "after_minutes": round(t + 15, 1), "status": "INVESTIGATING"})
            resolved_at = t + 15 + self.rng.uniform(60, 300)
            steps.append({"type": "status", "after_minutes": round(resolved_at, 1), "status": "RESOLVED"})
        closed_at = resolved_at + self.rng.uniform(*CLOSE_DELAY_DAYS) * 1440
        steps.append({"type": "status", "after_minutes": round(closed_at, 1), "status": "CLOSED", "actor": "incident.manager"})
        # Incidents still open at `end` keep only the steps that already happened
        steps = [s for s in steps if created + timedelta(minutes=s["after_minutes"]) < self.end]
        resolved = next((created + timedelta(minutes=s["after_minutes"]) for s in reversed(steps) if s.get("status") == "RESOLVED"), None)
        if steps and steps[-1].get("status") in ("REOPENED",):
            resolved = None
        for s in steps:
            if s.get("engineer") is None:
                s.pop("engineer", None)

        title, description = self._text(app, category, problem)
        recorded_category = category
        if self.rng.random() < CATEGORY_LABEL_NOISE:
            recorded_category = self.rng.choice([c for c in TITLES if c != category])
        record = {
            "external_id": f"SL-INC-{n:05d}", "application": app.code, "title": title, "description": description,
            "severity": severity, "category": recorded_category,
            "created_by": "monitoring.integration" if self.rng.random() < 0.6 else self.rng.choice(ENGINEERS[app.owner_team]),
            "created_at": iso(created), "started_at": iso(start),
            "resolution_summary": self.fill(self.rng.choice(RESOLUTIONS[category]), app), "history": steps,
        }
        if self.rng.random() >= MISSING_BUSINESS_IMPACT:
            reach = {"TIER_1": "customers across channels", "TIER_2": "internal operations teams", "TIER_3": "report consumers"}[app.tier]
            record["business_impact"] = f"{severity} impact on {app.name}: {reach} affected."

        closed = any(s.get("status") == "CLOSED" for s in steps)
        if closed and (problem or (change and change.caused)) and self.rng.random() < ROOT_CAUSE_RECORDED_RATE:
            cause = f"{problem.key}: {problem.root_cause}" if problem else f"Change {change.ref} introduced a {change.kind.replace('_', ' ')} regression"
            record["root_causes"] = [{"description": cause, "category": category, "status": "CONFIRMED", "created_by": engineer or "incident.manager",
                                      "confirmed_by": "incident.manager", "after_minutes": round(resolved_at, 1)}]
        return _Incident(app, start, created, resolved, severity, category, problem, change, record)

    def generate_incidents(self) -> None:
        drafts: list[tuple[datetime, AppSpec, str, Problem | None, _Change | None]] = []
        for change in self.changes:  # change-caused incidents
            if change.caused:
                start = change.deployed + timedelta(minutes=self.rng.uniform(*CHANGE_INCIDENT_DELAY_MIN))
                category = self.rng.choice(next(k[3] for k in CHANGE_KINDS if k[0] == change.kind))
                drafts.append((start, change.app, category, None, change))
        for problem in PROBLEMS:  # recurring problems
            for _ in range(max(1, round(problem.occurrences * self.factor))):
                drafts.append((self.random_time(problem.category), APP_BY_CODE[problem.app], problem.category, problem, None))
        app_weights = {a.code: a.incident_weight for a in APPS}
        for _ in range(max(0, round(INCIDENTS_PER_YEAR * self.factor) - len(drafts))):  # background
            app = APP_BY_CODE[self.pick(app_weights)]
            category = self.pick(app.categories)
            drafts.append((self.random_time(category), app, category, None, None))
        drafts.sort(key=lambda d: (d[0], d[1].code))

        for n, (start, app, category, problem, change) in enumerate(drafts, start=1):
            incident = self.make_incident(n, app, category, start, problem, change)
            if incident is not None:
                self.incidents.append(incident)
        self._link_changes()

    def _link_changes(self) -> None:
        by_app: dict[str, list[_Incident]] = {a.code: [] for a in APPS}
        for inc in self.incidents:
            by_app[inc.app.code].append(inc)
        for inc in self.incidents:
            if inc.change is not None and self.rng.random() >= CHANGE_LINK_MISS_RATE:
                inc.record.setdefault("change_links", []).append(
                    {"change_reference": inc.change.ref, "link_status": "CONFIRMED", "notes": "Incident started after this change"})
        for change in self.changes:
            if change.caused:
                continue
            window = [i for i in by_app[change.app.code]
                      if timedelta(0) < i.start - change.deployed <= timedelta(hours=24) and i.change is None]
            for inc in window:
                links = inc.record.setdefault("change_links", [])
                if any(link["change_reference"] == change.ref for link in links):
                    continue
                if self.rng.random() < FALSE_LINK_RATE:
                    links.append({"change_reference": change.ref, "link_status": "CONFIRMED", "notes": "Linked during review"})
                elif self.rng.random() < SUSPECTED_LINK_RATE:
                    links.append({"change_reference": change.ref, "link_status": "RULED_OUT", "notes": "Investigated; not related"})
            for inc in window:
                if not inc.record.get("change_links"):
                    inc.record.pop("change_links", None)

    # ---- operational evidence -------------------------------------------------------------------

    def generate_evidence(self) -> None:
        for inc in self.incidents:  # alert + error log around each incident
            if self.rng.random() < MISSING_EVIDENCE:
                continue
            level = {"P1": "CRITICAL", "P2": "ERROR"}.get(inc.severity, "WARNING")
            self.events.append({"application": inc.app.code, "event_type": "ALERT", "level": level, "source_system": "APM",
                                "message": f"{inc.severity} alert: {inc.record['title']}"[:300], "occurred_at": iso(inc.created - timedelta(minutes=1))})
            self.events.append({"application": inc.app.code, "event_type": "LOG", "level": "ERROR", "source_system": "app-log",
                                "message": self.fill(self.rng.choice(SYMPTOMS[inc.category]), inc.app),
                                "occurred_at": iso(inc.start + timedelta(minutes=1))})
        self._job_runs()
        self._metrics()

    def _job_runs(self) -> None:
        batch_failures = {(i.app.code, i.start.date()) for i in self.incidents if i.category == "BATCH_PROCESSING"}
        day = self.start
        while day < self.end:
            for app in APPS:
                for job in app.batch_jobs:
                    run = day + timedelta(hours=self.rng.randint(1, 4), minutes=self.rng.randrange(60))
                    failed = (app.code, day.date()) in batch_failures
                    self.events.append({"application": app.code, "event_type": "JOB_RUN", "level": "ERROR" if failed else "INFO",
                                        "source_system": "Control-M", "message": f"{job} ended {'NOTOK' if failed else 'OK'}",
                                        "occurred_at": iso(run), "attributes": {"job": job}})
            day += timedelta(days=1)

    def _metrics(self) -> None:
        total = (self.end - self.start).total_seconds()
        for app in APPS:
            windows = []
            for inc in self.incidents:
                if inc.app is app and (inc.severity in ("P1", "P2") or (inc.severity == "P3" and self.rng.random() < ANOMALY_P3_SHARE)):
                    lead = timedelta(minutes=self.rng.uniform(*ANOMALY_LEAD_MIN))
                    windows.append((inc.start - lead, inc.resolved or self.end, self.rng.random()))
            windows.sort(key=lambda w: w[0])
            series = [(app.metric, timedelta(hours=1))] + ([(app.metric2, timedelta(hours=4))] if app.metric2 else [])
            for (name, unit, baseline), step in series:
                down = name in DOWN_METRICS
                t = self.start
                while t < self.end:
                    hour = t.hour + t.minute / 60
                    value = baseline
                    if not down:  # traffic-driven metrics follow the day and week; rates like login success stay flat
                        value *= 1 + METRIC_DAILY_AMPLITUDE * math.sin(2 * math.pi * (hour - 7) / 24)
                        value *= METRIC_WEEKEND_FACTOR if t.weekday() >= 5 else 1
                        value *= 1 + METRIC_YEARLY_TREND * (t - self.start).total_seconds() / total
                    value += self.rng.gauss(0, METRIC_NOISE * baseline)
                    anomalous = False
                    for w_start, w_end, strength in windows:
                        if w_start > t:
                            break
                        if t <= w_end:
                            lo, hi = ANOMALY_FACTOR_DOWN if down else ANOMALY_FACTOR_UP
                            value *= lo + (hi - lo) * strength
                            anomalous = True
                            break
                    if unit == "%":
                        value = min(max(value, 0.0), 100.0)
                    value = max(value, 0.0)
                    level = "ERROR" if anomalous else "INFO"
                    self.events.append({"application": app.code, "event_type": "METRIC", "level": level, "source_system": "APM",
                                        "message": f"{name}={value:.2f}", "metric_name": name, "metric_value": round(value, 2),
                                        "unit": unit, "occurred_at": iso(t)})
                    t += step

    # ---- assemble -------------------------------------------------------------------------------

    def generate(self) -> dict:
        self.generate_changes()
        self.generate_incidents()
        self.generate_evidence()
        self.events.sort(key=lambda e: (e["occurred_at"], e["application"], e["event_type"], e["message"]))
        applications = [{"code": a.code, "name": a.name, "business_criticality": a.tier, "description": a.description,
                         "technology_stack": a.stack, "owner_team": a.owner_team, "health_status": "HEALTHY"} for a in APPS]
        dependencies = [{"application": a, "depends_on": b, "dependency_type": t, "is_critical": c} for a, b, t, c in DEPENDENCIES]
        manifest = {
            "name": f"BankOps AI large synthetic history ({self.cfg.months} months)",
            "data_source": DATA_SOURCE,
            "description": (f"Generated by scripts/generate_synthetic.py (seed={self.cfg.seed}, months={self.cfg.months}, "
                            f"scale={self.cfg.scale}) for {iso(self.start)} to {iso(self.end)}. Synthetic data with "
                            "designed signal for the ML module; see documents/synthetic-data.md."),
            "license": "Project-internal synthetic data",
            "reuse_applications": True,
        }
        return {
            "manifest": manifest, "applications": applications, "dependencies": dependencies,
            "changes": [c.record for c in self.changes], "incidents": [i.record for i in self.incidents],
            "operational_events": self.events,
        }

    def stats(self) -> dict:
        caused = [c for c in self.changes if c.caused]
        risky = [c for c in self.changes if c.deployed.weekday() == 4 or not in_change_window(c.deployed)]
        safe = [c for c in self.changes if c not in risky]
        return {
            "changes": len(self.changes), "change_caused_incident_rate": round(len(caused) / max(len(self.changes), 1), 3),
            "risky_change_incident_rate": round(sum(c.caused for c in risky) / max(len(risky), 1), 3),
            "safe_change_incident_rate": round(sum(c.caused for c in safe) / max(len(safe), 1), 3),
            "incidents": len(self.incidents),
            "active_incidents": sum(1 for i in self.incidents if i.resolved is None),
            "severity_mix": {s: sum(1 for i in self.incidents if i.severity == s) for s in ("P1", "P2", "P3", "P4")},
            "events": len(self.events),
        }


def write_dataset(dataset: dict, out: Path) -> dict[str, int]:
    """Write compact JSON files; returns bytes per file."""
    out.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, content in dataset.items():
        path = out / f"{name}.json"
        indent = 2 if name in ("manifest", "applications", "dependencies") else None
        path.write_text(json.dumps(content, indent=indent, ensure_ascii=False, separators=None if indent else (",", ":")) + "\n", encoding="utf-8")
        sizes[path.name] = path.stat().st_size
    return sizes
