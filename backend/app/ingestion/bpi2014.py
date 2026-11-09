"""Adapter: BPI Challenge 2014 (Rabobank ITSM logs) -> BankOps standard dataset (small curated subset).

Source: van Dongen, B.F. (2014) BPI Challenge 2014. 4TU.ResearchData. Real, anonymised IT service
management data from Rabobank Group ICT: incidents, their activity logs, and changes, keyed by
configuration items (CIs) grouped into service components (WBS codes).

What the subset contains (deterministic, see `build`):
- Applications: the 6 service components with the most incidents. Tier is derived from each
  component's share of priority 1-3 incidents (highest share = Tier 1). Names are the anonymised WBS codes.
- Incidents: category "incident" (not information requests) opened in March 2014 on those components.
  All priority 1-3 incidents and all incidents with a recorded related change are kept; priority 4-5
  incidents are sampled (fixed seed) up to MAX_INCIDENTS.
- History: first assignment (team from the activity log), investigating, up to 4 reassignment / update
  notes, resolved and closed at the logged times.
- Changes: changes on the same components implemented between 15 Feb and 31 Mar 2014, plus any change an
  incident references; related changes become SUSPECTED change links (correlation, not proven cause).

BPI has no free-text descriptions, so titles and descriptions are built from the structured fields.
Mappings: priority 1/2/3 -> P1/P2/P3, 4-5 -> P4; closure code / CI type -> category; risk assessment
Minor / Business / Major Business change -> LOW / MEDIUM / HIGH; emergency flag -> EMERGENCY.
"""

import json
import random
from datetime import datetime
from pathlib import Path

import pandas as pd

SOURCE = "BPI2014"
TOP_COMPONENTS = 6
MONTH_START, MONTH_END = datetime(2014, 3, 1), datetime(2014, 4, 1)
CHANGE_FROM = datetime(2014, 2, 15)
MAX_INCIDENTS = 300
SEED = 2014
ACTOR = "bpi2014.import"

SEVERITY = {"1": "P1", "2": "P2", "3": "P3", "4": "P4", "5": "P4"}
CLOSURE_CATEGORY = {"Software": "APPLICATION", "Hardware": "INFRASTRUCTURE", "Data": "DATA_PROCESSING"}
CI_CATEGORY = {"computer": "INFRASTRUCTURE", "storage": "INFRASTRUCTURE", "hardware": "INFRASTRUCTURE",
               "displaydevice": "INFRASTRUCTURE", "database": "DATABASE", "networkcomponents": "NETWORK"}
RISK = {"Minor Change": "LOW", "Business Change": "MEDIUM", "Major Business Change": "HIGH"}
NOTE_ACTIVITIES = {"Reassignment", "Operator Update", "Update", "External Vendor Assignment", "Pending vendor"}


def _ts(value: str | float, fmt: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return datetime.strptime(value.strip(), fmt)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def app_code(wbs: str) -> str:
    return "BPI-" + wbs.replace("WBS", "W")


def build(raw_dir: Path) -> dict:
    inc = pd.read_csv(raw_dir / "Detail_Incident.csv", sep=";", usecols=range(28), dtype=str)
    act = pd.read_csv(raw_dir / "Detail_Incident_Activity.csv", sep=";", dtype=str)
    chg = pd.read_csv(raw_dir / "Detail_Change.csv", sep=";", dtype=str)

    inc["open"] = inc["Open Time"].map(lambda v: _ts(v, "%d/%m/%Y %H:%M:%S"))
    inc = inc[(inc["Category"] == "incident") & inc["open"].notna()]
    wbs_col = "Service Component WBS (aff)"
    components = inc[wbs_col].value_counts().head(TOP_COMPONENTS).index.tolist()
    inc = inc[inc[wbs_col].isin(components)]

    # Tier from the share of priority 1-3 incidents per component (whole log, not just March)
    share = inc.assign(high=inc["Priority"].isin(["1", "2", "3"])).groupby(wbs_col)["high"].mean().sort_values(ascending=False)
    tiers = {wbs: ("TIER_1" if i < 2 else "TIER_2" if i < 4 else "TIER_3") for i, wbs in enumerate(share.index)}
    ci_types = inc.groupby(wbs_col)["CI Subtype (aff)"].agg(lambda s: s.value_counts().index[0])
    applications = [{
        "code": app_code(w), "name": f"Rabobank service component {w}", "business_criticality": tiers[w],
        "description": f"BPI 2014 service component {w}; most incidents on '{ci_types[w]}' configuration items. "
                       f"Tier derived from its share of priority 1-3 incidents ({share[w]:.0%}).",
        "business_service": "Rabobank Group ICT (anonymised)", "technology_stack": ci_types[w],
        "owner_team": "Rabobank ICT", "health_status": "UNKNOWN", "external_id": w,
    } for w in components]

    month = inc[(inc["open"] >= MONTH_START) & (inc["open"] < MONTH_END)].copy()
    must = month[month["Priority"].isin(["1", "2", "3"]) | month["Related Change"].notna()]
    rest = month.drop(must.index)
    rng = random.Random(SEED)
    take = min(len(rest), max(0, MAX_INCIDENTS - len(must)))
    sample = rest.loc[sorted(rng.sample(list(rest.index), take))] if take else rest.iloc[:0]
    chosen = pd.concat([must, sample]).sort_values("open")

    # Changes on the chosen components, implemented around March, plus any change an incident references
    chg["start"] = chg["Actual Start"].map(lambda v: _ts(v, "%d-%m-%Y %H:%M"))
    referenced = {c.strip() for v in chosen["Related Change"].dropna() for c in v.split(",")}
    chg = chg[chg["CI Name (aff)"].notna() & chg[wbs_col].isin(components) & chg["start"].notna()]
    chg = chg[((chg["start"] >= CHANGE_FROM) & (chg["start"] < MONTH_END)) | chg["Change ID"].isin(referenced)]
    changes = []
    for _, c in chg.drop_duplicates("Change ID").sort_values("start").iterrows():
        kind = "EMERGENCY" if c["Emergency Change"] == "Y" else "STANDARD" if str(c["Change Type"]).startswith("Standard") else "NORMAL"
        changes.append({
            "change_reference": c["Change ID"], "application": app_code(c[wbs_col]),
            "title": f"{c['Change Type']} on {c['CI Subtype (aff)']} {c['CI Name (aff)']}"[:200],
            "change_type": kind, "status": "IMPLEMENTED", "risk_level": RISK.get(c["Risk Assessment"], "MEDIUM"),
            "description": f"BPI 2014 change {c['Change ID']}: {c['Risk Assessment']}; CAB approval needed: {c['CAB-approval needed']}; "
                           f"originated from: {c['Originated from']}.",
            "deployed_at": _iso(c["start"]), "external_id": c["Change ID"],
        })
    known_changes = {c["change_reference"]: datetime.fromisoformat(c["deployed_at"][:19]) for c in changes}

    act = act[act["Incident ID"].isin(chosen["Incident ID"])].copy()
    act["at"] = act["DateStamp"].map(lambda v: _ts(v, "%d-%m-%Y %H:%M:%S"))
    act = act.sort_values("at")
    activities = {k: g for k, g in act.groupby("Incident ID")}

    incidents = [i for i in (_incident(r, activities.get(r["Incident ID"]), known_changes) for _, r in chosen.iterrows()) if i]
    return {
        "manifest": {
            "name": "BPI Challenge 2014 (Rabobank) - curated subset", "data_source": SOURCE,
            "description": f"{len(incidents)} real anonymised incidents from March 2014 on the {TOP_COMPONENTS} busiest service "
                           f"components, with their activity history and {len(changes)} changes. Built by app/ingestion/bpi2014.py.",
            "license": "See 4TU.ResearchData terms for BPI Challenge 2014 (doi:10.4121/uuid:c3e5d162-0cfd-4bb0-bd82-af5268819c35)",
            "citation": "van Dongen, B.F. (2014) BPI Challenge 2014. 4TU.ResearchData.",
        },
        "applications": applications, "dependencies": [], "changes": changes, "incidents": incidents, "operational_events": [],
    }


def _incident(r, acts, known_changes: dict) -> dict | None:
    opened = r["open"]
    resolved = _ts(r["Resolved Time"], "%d/%m/%Y %H:%M:%S")
    closed = _ts(r["Close Time"], "%d/%m/%Y %H:%M:%S")
    end = resolved or closed
    if end is None or end <= opened:
        return None
    sev = SEVERITY.get(r["Priority"], "P4")
    closure = r["Closure Code"] if isinstance(r["Closure Code"], str) else "Unknown"
    category = CLOSURE_CATEGORY.get(closure) or CI_CATEGORY.get(str(r["CI Type (aff)"]).lower(), "APPLICATION")
    mins = lambda t: round(max((t - opened).total_seconds() / 60, 0), 1)  # noqa: E731

    acts = acts if acts is not None else pd.DataFrame(columns=["at", "IncidentActivity_Type", "Assignment Group"])
    first = acts[(acts["IncidentActivity_Type"] == "Assignment") & (acts["at"] >= opened)].head(1)
    team = str(first["Assignment Group"].iloc[0]) if len(first) and isinstance(first["Assignment Group"].iloc[0], str) else "BPI service desk"
    ack = mins(first["at"].iloc[0]) if len(first) else 1.0
    end_m = mins(end)
    ack = min(ack, max(end_m - 2, 0.5))
    steps = [{"type": "assign", "after_minutes": ack, "team": team, "actor": ACTOR},
             {"type": "status", "after_minutes": round(ack + 0.5, 1), "status": "INVESTIGATING", "actor": ACTOR}]
    notes = acts[acts["IncidentActivity_Type"].isin(NOTE_ACTIVITIES) & (acts["at"] > opened) & (acts["at"] < end)].head(4)
    for _, a in notes.iterrows():
        t = mins(a["at"])
        if ack + 0.5 < t < end_m:
            group = f" ({a['Assignment Group']})" if isinstance(a["Assignment Group"], str) else ""
            steps.append({"type": "event", "after_minutes": t, "event_type": "INVESTIGATION_UPDATE",
                          "description": f"BPI activity: {a['IncidentActivity_Type']}{group}", "actor": ACTOR})
    steps.append({"type": "status", "after_minutes": end_m, "status": "RESOLVED", "actor": ACTOR})
    root_causes = []
    if closed and closed > end and sev != "P1":  # P1 closure needs a confirmed root cause; BPI does not record one
        steps.append({"type": "status", "after_minutes": mins(closed), "status": "CLOSED", "actor": ACTOR})
    steps.sort(key=lambda s: s["after_minutes"])

    links = []
    for ref in (r["Related Change"].split(",") if isinstance(r["Related Change"], str) else []):
        ref = ref.strip()
        if ref in known_changes:
            links.append({"change_reference": ref, "link_status": "SUSPECTED", "after_minutes": round(ack + 1, 1),
                          "identified_by": ACTOR, "notes": "Related change recorded in the BPI 2014 incident log"})
    ci = f"{r['CI Subtype (aff)']} {r['CI Name (aff)']}"
    return {
        "external_id": r["Incident ID"], "application": app_code(r["Service Component WBS (aff)"]),
        "title": f"{closure if closure not in ('Other', 'Unknown') else 'Service'} incident on {ci}"[:200],
        "description": (f"BPI 2014 incident {r['Incident ID']} (Rabobank ITSM, anonymised). Affected CI {r['CI Name (aff)']} "
                        f"({r['CI Type (aff)']} / {r['CI Subtype (aff)']}). Impact {r['Impact']}, urgency {r['Urgency']}, "
                        f"priority {r['Priority']}. Knowledge article {r['KM number']}. Reassignments: {r['# Reassignments']}. "
                        f"Closure code: {closure}."),
        "severity": sev, "category": category, "created_by": ACTOR,
        "created_at": _iso(opened), "started_at": _iso(opened),
        "resolution_summary": f"Resolved per the BPI 2014 log (closure code: {closure}).",
        "history": steps, "change_links": links, "root_causes": root_causes,
    }


def write(dataset: dict, out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for key in ("manifest", "applications", "dependencies", "changes", "incidents", "operational_events"):
        (out / f"{key}.json").write_text(json.dumps(dataset[key], indent=1, ensure_ascii=False), encoding="utf-8")
        counts[key] = 1 if key == "manifest" else len(dataset[key])
    return counts
