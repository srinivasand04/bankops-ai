"""Feature builders: query the database and return pandas DataFrames.

No data leakage: every feature uses only what was known when the prediction is made -
  incidents: at creation (severity, category, application, time of day, changes deployed in the
             previous 24 h, incidents on the same application in the previous 30 days);
  changes:   at deployment (type, risk, scope, timing, application tier, the application's earlier
             change failures).
Labels (resolution time, SLA breach, caused-an-incident) are only used as targets, never as features.
"""

from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

# Real BPI 2014 data (from 2014, no free text) is kept out of training so it cannot distort the models;
# its incidents still get predictions like any other.
TRAINING_EXCLUDED_SOURCES = ("BPI2014",)

TIER_NUMBER = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}
SEVERITIES = ["P1", "P2", "P3", "P4"]
# Approved change window (bank change policy used by the synthetic data): Mon-Thu 18-23h, Sat 08-14h
CHANGE_WINDOWS = {0: (18, 23), 1: (18, 23), 2: (18, 23), 3: (18, 23), 5: (8, 14)}

INCIDENT_SQL = """
SELECT i.id, i.reference_number AS reference, i.title, i.description, i.severity, i.category, i.status,
       i.assigned_team, i.data_source, i.application_id, a.code AS app, a.business_criticality AS tier,
       i.created_at, i.started_at, i.acknowledged_at, i.resolved_at,
       s.resolution_due_at,
       (SELECT count(*) FROM change_records c WHERE c.application_id = i.application_id
          AND c.deployed_at > i.started_at - interval '24 hours' AND c.deployed_at <= i.started_at) AS changes_24h,
       (SELECT count(*) FROM change_records c WHERE c.application_id = i.application_id
          AND c.risk_level = 'HIGH'
          AND c.deployed_at > i.started_at - interval '24 hours' AND c.deployed_at <= i.started_at) AS high_risk_changes_24h,
       (SELECT count(*) FROM incidents p WHERE p.application_id = i.application_id
          AND p.started_at >= i.started_at - interval '30 days' AND p.started_at < i.started_at) AS app_incidents_30d,
       (SELECT count(*) FROM application_dependencies d WHERE d.depends_on_id = i.application_id) AS dependents,
       (SELECT count(*) FROM application_dependencies d WHERE d.application_id = i.application_id) AS dependencies
FROM incidents i
JOIN applications a ON a.id = i.application_id
LEFT JOIN incident_sla s ON s.incident_id = i.id
{where}
ORDER BY i.created_at
"""


def load_incidents(db: Session, incident_ids: list[int] | None = None) -> pd.DataFrame:
    where, params = "WHERE i.data_source <> ALL(:excluded)", {"excluded": list(TRAINING_EXCLUDED_SOURCES)}
    if incident_ids is not None:
        where, params = "WHERE i.id = ANY(:ids)", {"ids": list(incident_ids) or [0]}
    df = pd.read_sql(text(INCIDENT_SQL.format(where=where)), db.connection(), params=params)
    for col in ("created_at", "started_at", "acknowledged_at", "resolved_at", "resolution_due_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    return add_incident_features(df)


def add_incident_features(df: pd.DataFrame) -> pd.DataFrame:
    start = df["started_at"]
    df["tier_n"] = df["tier"].map(TIER_NUMBER).fillna(2)
    df["hour"] = start.dt.hour
    df["weekday"] = start.dt.day_of_week
    df["is_weekend"] = (df["weekday"] >= 5).astype(int)
    df["is_night"] = ((df["hour"] >= 22) | (df["hour"] < 6)).astype(int)
    df["is_business_hours"] = ((df["weekday"] < 5) & (df["hour"] >= 8) & (df["hour"] < 18)).astype(int)
    df["sev_n"] = df["severity"].map({s: i + 1 for i, s in enumerate(SEVERITIES)})
    df["recent_change"] = (df["changes_24h"] > 0).astype(int)
    df["text"] = (df["title"].fillna("") + ". " + df["description"].fillna("")).str.strip()
    # targets (only for resolved incidents / decided SLAs)
    df["mttr_minutes"] = (df["resolved_at"] - df["started_at"]).dt.total_seconds() / 60
    now = pd.Timestamp.now(tz="UTC")
    decided = df["resolved_at"].notna() | (df["resolution_due_at"] < now)
    breached = (df["resolved_at"] > df["resolution_due_at"]) | (df["resolved_at"].isna() & (df["resolution_due_at"] < now))
    df["sla_breached"] = np.where(decided & df["resolution_due_at"].notna(), breached.astype(float), np.nan)
    return df


# Columns the incident models use: numeric + one-hot of these categoricals
INCIDENT_NUMERIC = ["tier_n", "sev_n", "hour", "is_weekend", "is_night", "is_business_hours",
                    "changes_24h", "high_risk_changes_24h", "recent_change", "app_incidents_30d", "dependents", "dependencies"]
INCIDENT_CATEGORICAL = ["category", "severity", "app"]


CHANGE_SQL = """
SELECT c.id, c.change_reference AS reference, c.title, c.change_type, c.risk_level, c.status,
       c.components_changed, c.deployed_at, c.application_id, a.code AS app, a.business_criticality AS tier,
       c.data_source,
       EXISTS (SELECT 1 FROM incident_related_changes l WHERE l.change_id = c.id AND l.link_status <> 'RULED_OUT') AS caused_incident,
       (SELECT count(*) FROM change_records p
          WHERE p.application_id = c.application_id AND p.deployed_at < c.deployed_at
            AND p.deployed_at >= c.deployed_at - interval '90 days'
            AND EXISTS (SELECT 1 FROM incident_related_changes l WHERE l.change_id = p.id AND l.link_status <> 'RULED_OUT')
       ) AS app_failed_changes_90d,
       (SELECT count(*) FROM application_dependencies d WHERE d.depends_on_id = c.application_id) AS dependents
FROM change_records c
JOIN applications a ON a.id = c.application_id
WHERE c.deployed_at IS NOT NULL {extra}
ORDER BY c.deployed_at
"""


def load_changes(db: Session, change_ids: list[int] | None = None) -> pd.DataFrame:
    extra, params = "AND c.data_source <> ALL(:excluded)", {"excluded": list(TRAINING_EXCLUDED_SOURCES)}
    if change_ids is not None:
        extra, params = "AND c.id = ANY(:ids)", {"ids": list(change_ids) or [0]}
    df = pd.read_sql(text(CHANGE_SQL.format(extra=extra)), db.connection(), params=params)
    df["deployed_at"] = pd.to_datetime(df["deployed_at"], utc=True)
    return add_change_features(df)


def in_change_window(ts: datetime) -> bool:
    window = CHANGE_WINDOWS.get(ts.weekday())
    return window is not None and window[0] <= ts.hour < window[1]


def add_change_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df["deployed_at"]
    df["tier_n"] = df["tier"].map(TIER_NUMBER).fillna(2)
    df["hour"] = d.dt.hour
    df["is_friday"] = (d.dt.day_of_week == 4).astype(int)
    df["is_weekend"] = (d.dt.day_of_week >= 5).astype(int)
    df["out_of_window"] = (~d.apply(in_change_window)).astype(int)
    df["scope_missing"] = df["components_changed"].isna().astype(int)
    df["components"] = df["components_changed"].fillna(df["components_changed"].median() if df["components_changed"].notna().any() else 3)
    df["risk_n"] = df["risk_level"].map({"LOW": 0, "MEDIUM": 1, "HIGH": 2}).fillna(1)
    df["is_emergency"] = (df["change_type"] == "EMERGENCY").astype(int)
    df["caused_incident"] = df["caused_incident"].astype(int)
    return df


CHANGE_NUMERIC = ["tier_n", "hour", "is_friday", "is_weekend", "out_of_window", "components", "scope_missing",
                  "risk_n", "is_emergency", "app_failed_changes_90d", "dependents"]

# Human-readable names for explanations in the UI
FEATURE_LABELS = {
    "tier_n": "application tier (1 = most critical)", "sev_n": "severity (1 = P1)", "hour": "hour of day",
    "is_weekend": "weekend", "is_night": "night (22:00-06:00)", "is_business_hours": "business hours",
    "changes_24h": "changes in the previous 24 h", "high_risk_changes_24h": "high-risk changes in the previous 24 h",
    "recent_change": "a change in the previous 24 h", "app_incidents_30d": "incidents on the app in the previous 30 days",
    "dependents": "applications that depend on it", "dependencies": "applications it depends on",
    "is_friday": "deployed on a Friday", "out_of_window": "outside the approved change window",
    "components": "components changed (scope)", "scope_missing": "scope not recorded", "risk_n": "declared risk level",
    "is_emergency": "emergency change", "app_failed_changes_90d": "app's changes that caused incidents (90 days)",
}


def metric_series(db: Session, app_code: str, metric: str) -> pd.Series:
    """Hourly metric values for one application, as a time-indexed series."""
    rows = db.execute(text(
        "SELECT e.occurred_at, avg(e.metric_value) FROM operational_events e JOIN applications a ON a.id = e.application_id "
        "WHERE e.event_type = 'METRIC' AND a.code = :app AND e.metric_name = :m GROUP BY e.occurred_at ORDER BY e.occurred_at"
    ), {"app": app_code, "m": metric}).all()
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series([float(v) for _, v in rows], index=pd.to_datetime([t for t, _ in rows], utc=True))
    return s.resample("1h").mean().interpolate(limit=3)


def metric_catalog(db: Session) -> list[tuple[str, str, int]]:
    return [(a, m, n) for a, m, n in db.execute(text(
        "SELECT a.code, e.metric_name, count(*) FROM operational_events e JOIN applications a ON a.id = e.application_id "
        "WHERE e.event_type = 'METRIC' GROUP BY a.code, e.metric_name HAVING count(*) >= 500 ORDER BY a.code, e.metric_name"
    ))]
