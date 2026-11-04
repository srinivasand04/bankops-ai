"""Compact fact base for small local models.

Same structure and ids as the full fact base, roughly half the tokens:
- metric series become a summary (baseline, peak, latest, trend, attribute changes) instead of points
- identical log lines are merged with an occurrence count
- long text is trimmed and long lists are capped

Citable ids are recomputed from what remains, so the guardrails only accept ids the model saw.
"""

from copy import deepcopy

from app.ai.context import IncidentContext
from app.models.enums import EventType, Source

TEXT_LIMIT = 200
DUPLICATED_EVENTS = {
    EventType.AI_ANALYSIS,
    EventType.ROOT_CAUSE_HYPOTHESIS,
    EventType.ROOT_CAUSE_CONFIRMED,
    EventType.ROOT_CAUSE_REJECTED,
    EventType.CORRECTIVE_ACTION,
    EventType.PREVENTIVE_ACTION,
    EventType.ACTION_UPDATED,
}
LIMITS = {"timeline": 8, "other_recent_changes": 3, "existing_actions": 5, "similar_incidents": 3}


def _trim(text: str | None, limit: int = TEXT_LIMIT) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _keep(item: dict, *keys: str) -> dict:
    return {k: item[k] for k in keys if item.get(k) is not None}


def summarise_series(series: dict) -> dict:
    points = series["points"]
    first, latest = points[0]["value"], points[-1]["value"]
    peak = max(points, key=lambda p: p["value"])
    low = min(points, key=lambda p: p["value"])
    if first and latest / first >= 1.5:
        trend = "rose"
    elif first and latest / first <= 0.67:
        trend = "fell"
    else:
        trend = "stable"
    summary = {
        **_keep(series, "id", "application", "metric", "unit"),
        "first": first,
        "first_minutes_from_start": points[0]["minutes_from_start"],
        "peak": peak["value"],
        "peak_minutes_from_start": peak["minutes_from_start"],
        "min": low["value"],
        "latest": latest,
        "trend": trend,
    }
    changes, previous = [], None
    for p in points:
        attrs = p.get("attributes")
        if attrs and attrs != previous:
            changes.append({"minutes_from_start": p["minutes_from_start"], "attributes": attrs})
            previous = attrs
    if len(changes) > 1:
        summary["attribute_changes"] = changes
    return summary


def merge_repeated_events(events: list[dict]) -> list[dict]:
    merged: dict[tuple, dict] = {}
    for event in events:
        key = (event["application"], event["type"], event["message"])
        if key in merged:
            first = merged[key]
            first["occurrences"] = first.get("occurrences", 1) + 1
            first["last_minutes_from_start"] = event["minutes_from_start"]
        else:
            merged[key] = {**event, "message": _trim(event["message"])}
    return list(merged.values())


def _collect_ids(node, ids: set[str]) -> set[str]:
    if isinstance(node, dict):
        if isinstance(node.get("id"), str):
            ids.add(node["id"])
        for value in node.values():
            _collect_ids(value, ids)
    elif isinstance(node, list):
        for value in node:
            _collect_ids(value, ids)
    return ids


def compact_context(ctx: IncidentContext) -> IncidentContext:
    d = deepcopy(ctx.data)
    d["incident"]["description"] = _trim(d["incident"]["description"], 400)
    d["incident"]["business_impact"] = _trim(d["incident"].get("business_impact"))
    # Keep the human investigation history; AI entries and root-cause / action events repeat what
    # existing_root_causes and existing_actions already list (and would crowd out the evidence).
    investigation = [e for e in d["timeline"] if e["source"] != Source.AI and e["type"] not in DUPLICATED_EVENTS]
    d["timeline"] = [
        {**_keep(e, "id", "minutes_from_start", "type", "by"), "description": _trim(e["description"], 160)}
        for e in investigation[-LIMITS["timeline"]:]
    ]
    apps = d["applications"]
    apps["affected"] = _keep(apps["affected"], "id", "code", "name", "criticality", "health")
    apps["depends_on"] = [_keep(a, "id", "code", "name", "critical", "health") for a in apps["depends_on"]]
    apps["dependents"] = [_keep(a, "id", "code", "name", "health") for a in apps["dependents"]]
    d["related_changes"] = [
        {**_keep(c, "id", "application", "title", "version", "risk", "status", "minutes_before_incident_start",
                 "link_status"), "rollback_plan": _trim(c.get("rollback_plan"), 120)}
        for c in d["related_changes"]
    ]
    d["other_recent_changes"] = [
        _keep(c, "id", "application", "title", "minutes_before_incident_start")
        for c in d["other_recent_changes"][: LIMITS["other_recent_changes"]]
    ]
    evidence = d["evidence"]
    evidence["metric_series"] = [summarise_series(s) for s in evidence["metric_series"]]
    evidence["events"] = merge_repeated_events(evidence["events"])
    d["existing_root_causes"] = [
        {**_keep(r, "id", "status", "source", "confidence"), "description": _trim(r["description"])}
        for r in d["existing_root_causes"]
    ]
    d["existing_actions"] = [
        {**_keep(a, "id", "type", "status"), "description": _trim(a["description"], 120)}
        for a in d["existing_actions"][: LIMITS["existing_actions"]]
    ]
    d["similar_incidents"] = [
        _keep(i, "id", "application", "title", "category", "status")
        for i in d["similar_incidents"][: LIMITS["similar_incidents"]]
    ]
    return IncidentContext(data=d, valid_ids=_collect_ids(d, set()), application_codes=set(ctx.application_codes))
