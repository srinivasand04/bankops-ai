"""End-to-end HTTP smoke test against a running BankOps AI backend.

    python scripts/smoke_test.py [--base-url http://localhost:8000]

Walks one incident through its full lifecycle (create -> assign -> investigate -> evidence ->
change correlation -> hypothesis -> human confirmation -> CAPA -> resolve -> close) and checks
analytics. Creates a new synthetic incident each run.
"""

import argparse
import sys

import httpx

MANAGER = {"X-User-Name": "smoke.manager", "X-User-Role": "INCIDENT_MANAGER"}
ENGINEER = {"X-User-Name": "smoke.engineer", "X-User-Role": "ENGINEER"}


def check(condition: bool, label: str) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    api = httpx.Client(base_url=f"{args.base_url}/api", timeout=10)

    check(api.get("/health").json()["database"] == "ok", "health check")
    apps = {a["code"]: a for a in api.get("/applications", headers=ENGINEER).json()}
    check(len(apps) >= 5, f"{len(apps)} applications available")

    incident = api.post(
        "/incidents",
        headers=ENGINEER,
        json={
            "title": "Smoke test: payment API latency spike",
            "description": "Synthetic smoke test incident - p95 latency above 3 s on /payments/authorise.",
            "application_id": apps["PAY"]["id"],
            "severity": "P2",
            "category": "PERFORMANCE",
            "business_impact": "Synthetic - no real impact",
        },
    )
    check(incident.status_code == 201, f"create incident -> {incident.json().get('reference_number')}")
    iid = incident.json()["id"]

    r = api.patch(f"/incidents/{iid}/status", headers=ENGINEER, json={"status": "CLOSED"})
    check(r.status_code == 409, "invalid transition OPEN -> CLOSED rejected (409)")

    r = api.patch(f"/incidents/{iid}/assign", headers=MANAGER,
                  json={"assigned_team": "Payments Production Support", "assigned_engineer": "smoke.engineer"})
    check(r.json()["status"] == "ASSIGNED", "assign -> ASSIGNED, acknowledged")
    check(r.json()["sla"]["response"]["state"] == "MET", "response SLA met")

    r = api.patch(f"/incidents/{iid}/status", headers=ENGINEER, json={"status": "INVESTIGATING"})
    check(r.json()["status"] == "INVESTIGATING", "INVESTIGATING")

    r = api.post(f"/incidents/{iid}/events", headers=ENGINEER,
                 json={"event_type": "EVIDENCE_ADDED", "description": "APM shows GC pauses of 2 s"})
    check(r.status_code == 201, "evidence added to timeline")

    changes = {c["change_reference"]: c for c in api.get("/changes", headers=ENGINEER).json()}
    r = api.post(f"/incidents/{iid}/related-changes", headers=ENGINEER,
                 json={"change_id": changes["CHG-2041"]["id"], "notes": "Release 2.4.1 deployed shortly before"})
    check(r.status_code == 201, "related change CHG-2041 linked")

    rc = api.post(f"/incidents/{iid}/root-causes", headers=ENGINEER,
                  json={"description": "Heap size not increased for new fraud-scoring cache", "confidence": 0.5})
    check(rc.json()["status"] == "HYPOTHESIS", "root cause recorded as HYPOTHESIS")
    r = api.post(f"/root-causes/{rc.json()['id']}/review", headers=ENGINEER, json={"decision": "CONFIRM"})
    check(r.status_code == 403, "engineer cannot confirm root cause (403)")
    r = api.post(f"/root-causes/{rc.json()['id']}/review", headers=MANAGER, json={"decision": "CONFIRM"})
    check(r.json()["status"] == "CONFIRMED", "manager confirms root cause")

    for action_type, text in (("CORRECTIVE", "Increase JVM heap to 4 GB"), ("PREVENTIVE", "Add heap sizing to release checklist")):
        r = api.post(f"/incidents/{iid}/actions", headers=ENGINEER, json={"action_type": action_type, "description": text})
        check(r.status_code == 201, f"{action_type.lower()} action created")

    r = api.patch(f"/incidents/{iid}/status", headers=ENGINEER,
                  json={"status": "RESOLVED", "resolution_summary": "JVM heap increased; latency back to baseline"})
    check(r.json()["status"] == "RESOLVED", "RESOLVED")
    r = api.patch(f"/incidents/{iid}/status", headers=ENGINEER, json={"status": "CLOSED"})
    check(r.status_code == 403, "engineer cannot close (403)")
    r = api.patch(f"/incidents/{iid}/status", headers=MANAGER, json={"status": "CLOSED"})
    check(r.json()["status"] == "CLOSED", "manager closes incident")

    timeline = [e["event_type"] for e in api.get(f"/incidents/{iid}/timeline", headers=ENGINEER).json()]
    check(len(timeline) >= 11, f"timeline has {len(timeline)} audit events")
    rca = api.get(f"/incidents/{iid}/rca", headers=ENGINEER).json()
    check(len(rca["confirmed_root_causes"]) == 1 and rca["hypotheses"] == [], "RCA separates confirmed vs hypotheses")

    summary = api.get("/analytics/incident-summary", headers=ENGINEER).json()
    check(summary["total_incidents"] >= 11, f"analytics summary: {summary['total_incidents']} incidents, "
          f"MTTR {summary['mttr_minutes']} min, SLA compliance {summary['sla_compliance_pct']}%")
    print("Smoke test completed successfully.")


if __name__ == "__main__":
    main()
