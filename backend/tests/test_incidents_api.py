"""Incident management API: CRUD, validation, lifecycle, timeline, SLA and permissions."""

from tests.conftest import headers


def _timeline_types(client, incident_id: int) -> list[str]:
    response = client.get(f"/api/incidents/{incident_id}/timeline", headers=headers())
    assert response.status_code == 200
    return [event["event_type"] for event in response.json()]


def _status(client, incident_id: int, status: str, role="INCIDENT_MANAGER", **extra):
    return client.patch(
        f"/api/incidents/{incident_id}/status", json={"status": status, **extra}, headers=headers(role)
    )


# ---- create / retrieve / update -----------------------------------------------------------


def test_create_incident_generates_reference_sla_and_timeline(client, create_incident):
    first = create_incident()
    second = create_incident(title="Second synthetic incident", severity="P3")

    assert first["reference_number"] == "INC-1001"
    assert second["reference_number"] == "INC-1002"
    assert first["status"] == "OPEN"
    assert first["application_name"] == "Payment Processing"
    # P1 on a Tier 1 application -> CRITICAL; P3 on Tier 1 is raised one level -> HIGH
    assert first["priority"] == "CRITICAL"
    assert second["priority"] == "HIGH"
    assert first["sla"]["response"]["target_minutes"] == 15
    assert first["sla"]["resolution"]["target_minutes"] == 60
    assert first["sla"]["response"]["state"] == "ON_TRACK"
    assert first["allowed_transitions"] == ["ASSIGNED", "ESCALATED"]
    assert _timeline_types(client, first["id"]) == ["CREATED"]


def test_explicit_priority_is_kept_separate_from_severity(create_incident):
    incident = create_incident(severity="P1", priority="MEDIUM")
    assert (incident["severity"], incident["priority"]) == ("P1", "MEDIUM")


def test_create_with_team_assigns_and_acknowledges(client, create_incident):
    incident = create_incident(assigned_team="Payments Production Support", assigned_engineer="a.patel")
    assert incident["status"] == "ASSIGNED"
    assert incident["acknowledged_at"] is not None
    assert incident["sla"]["response"]["state"] == "MET"
    assert _timeline_types(client, incident["id"]) == ["CREATED", "ASSIGNED", "STATUS_CHANGED"]


def test_retrieve_incident_by_id_and_reference(client, create_incident):
    created = create_incident()
    by_id = client.get(f"/api/incidents/{created['id']}", headers=headers())
    by_ref = client.get("/api/incidents/by-reference/inc-1001", headers=headers())
    assert by_id.status_code == by_ref.status_code == 200
    assert by_id.json()["id"] == by_ref.json()["id"] == created["id"]


def test_missing_incident_returns_404(client, applications):
    response = client.get("/api/incidents/999999", headers=headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_update_incident_fields_and_severity(client, create_incident):
    incident = create_incident(severity="P3")
    response = client.put(
        f"/api/incidents/{incident['id']}",
        json={"severity": "P1", "business_impact": "All payment channels affected", "reason": "Impact widened"},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["severity"] == "P1"
    assert body["business_impact"] == "All payment channels affected"
    # SLA re-based on the new severity
    assert body["sla"]["severity"] == "P1"
    assert body["sla"]["resolution"]["target_minutes"] == 60
    assert _timeline_types(client, incident["id"]) == ["CREATED", "SEVERITY_CHANGED", "UPDATED"]


def test_update_requires_at_least_one_field(client, create_incident):
    incident = create_incident()
    response = client.put(f"/api/incidents/{incident['id']}", json={}, headers=headers())
    assert response.status_code == 422


# ---- validation ---------------------------------------------------------------------------


def test_invalid_severity_rejected(client, applications):
    payload = {
        "title": "Bad severity incident",
        "description": "This incident has an invalid severity value.",
        "application_id": applications["PAY"].id,
        "severity": "P0",
        "category": "APPLICATION",
    }
    response = client.post("/api/incidents", json=payload, headers=headers())
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert any(e["field"] == "severity" for e in body["details"]["errors"])


def test_invalid_category_and_unknown_application_rejected(client, applications):
    base = {
        "title": "Validation incident",
        "description": "Checking that invalid input is rejected.",
        "application_id": applications["PAY"].id,
        "severity": "P2",
        "category": "APPLICATION",
    }
    assert client.post("/api/incidents", json=base | {"category": "WEATHER"}, headers=headers()).status_code == 422
    assert client.post("/api/incidents", json=base | {"title": "x"}, headers=headers()).status_code == 422
    unknown_app = client.post("/api/incidents", json=base | {"application_id": 9999}, headers=headers())
    assert unknown_app.status_code == 422
    assert unknown_app.json()["error"]["code"] == "business_rule_violation"


def test_future_start_time_rejected(client, create_incident, applications):
    response = client.post(
        "/api/incidents",
        json={
            "title": "Future incident",
            "description": "Started in the future, which is impossible.",
            "application_id": applications["PAY"].id,
            "severity": "P2",
            "category": "APPLICATION",
            "started_at": "2099-01-01T00:00:00Z",
        },
        headers=headers(),
    )
    assert response.status_code == 422


# ---- lifecycle ----------------------------------------------------------------------------


def test_full_lifecycle_records_every_transition(client, create_incident):
    incident = create_incident(severity="P2")
    iid = incident["id"]

    assign = client.patch(
        f"/api/incidents/{iid}/assign",
        json={"assigned_team": "Payments Production Support", "assigned_engineer": "a.patel"},
        headers=headers(),
    )
    assert assign.json()["status"] == "ASSIGNED"
    assert _status(client, iid, "INVESTIGATING").json()["status"] == "INVESTIGATING"
    assert _status(client, iid, "ESCALATED", note="Vendor engaged").json()["status"] == "ESCALATED"

    resolved = _status(client, iid, "RESOLVED", resolution_summary="Rolled back release 2.4.1 to 2.4.0")
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None
    assert resolved.json()["sla"]["resolution"]["state"] == "MET"

    closed = _status(client, iid, "CLOSED")
    assert closed.json()["status"] == "CLOSED"
    assert closed.json()["closed_at"] is not None

    assert _timeline_types(client, iid) == [
        "CREATED",
        "ASSIGNED",
        "STATUS_CHANGED",  # OPEN -> ASSIGNED
        "STATUS_CHANGED",  # ASSIGNED -> INVESTIGATING
        "ESCALATED",
        "RESOLVED",
        "CLOSED",
    ]


def test_invalid_status_transition_rejected(client, create_incident):
    incident = create_incident()
    response = _status(client, incident["id"], "CLOSED")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "invalid_status_transition"
    assert error["details"]["allowed"] == ["ASSIGNED", "ESCALATED"]
    # nothing recorded for a rejected transition
    assert _timeline_types(client, incident["id"]) == ["CREATED"]


def test_assigned_requires_team(client, create_incident):
    incident = create_incident()
    response = _status(client, incident["id"], "ASSIGNED")
    assert response.status_code == 422


def test_resolution_requires_summary(client, create_incident):
    incident = create_incident(severity="P3", assigned_team="Payments Production Support")
    _status(client, incident["id"], "INVESTIGATING")
    response = _status(client, incident["id"], "RESOLVED")
    assert response.status_code == 422
    assert "resolution_summary" in response.json()["error"]["message"]


def test_p1_closure_requires_confirmed_root_cause(client, create_incident):
    incident = create_incident(severity="P1", assigned_team="Payments Production Support")
    iid = incident["id"]
    _status(client, iid, "INVESTIGATING")
    _status(client, iid, "RESOLVED", resolution_summary="Rolled back release 2.4.1")

    blocked = _status(client, iid, "CLOSED")
    assert blocked.status_code == 422

    root_cause = client.post(
        f"/api/incidents/{iid}/root-causes",
        json={"description": "Connection pool exhaustion introduced by release 2.4.1"},
        headers=headers(),
    ).json()
    client.post(f"/api/root-causes/{root_cause['id']}/review", json={"decision": "CONFIRM"}, headers=headers())
    assert _status(client, iid, "CLOSED").status_code == 200


def test_engineer_cannot_close_and_viewer_cannot_modify(client, create_incident):
    incident = create_incident(severity="P3", assigned_team="Data Platform Support")
    iid = incident["id"]
    _status(client, iid, "INVESTIGATING")
    _status(client, iid, "RESOLVED", resolution_summary="ETL jobs rescheduled outside window")

    assert _status(client, iid, "CLOSED", role="ENGINEER").status_code == 403
    viewer_update = client.put(f"/api/incidents/{iid}", json={"title": "Viewer edit"}, headers=headers("VIEWER"))
    assert viewer_update.status_code == 403
    assert client.get(f"/api/incidents/{iid}", headers=headers("VIEWER")).status_code == 200


def test_reserved_ai_identity_cannot_be_claimed_via_headers(client, applications):
    response = client.get("/api/incidents", headers={"X-User-Name": "ai:supervisor"})
    assert response.status_code == 403


def test_reopen_requires_note_and_increments_counter(client, create_incident):
    incident = create_incident(severity="P3", assigned_team="Payments Production Support")
    iid = incident["id"]
    _status(client, iid, "INVESTIGATING")
    _status(client, iid, "RESOLVED", resolution_summary="Restarted payment API pods")

    assert _status(client, iid, "REOPENED").status_code == 422
    reopened = _status(client, iid, "REOPENED", note="Errors returned after restart")
    assert reopened.status_code == 200
    body = reopened.json()
    assert body["reopen_count"] == 1
    assert body["resolved_at"] is None
    assert "REOPENED" in _timeline_types(client, iid)


def test_closed_incident_cannot_be_updated(client, create_incident):
    incident = create_incident(severity="P4", assigned_team="Digital Channels Support")
    iid = incident["id"]
    _status(client, iid, "INVESTIGATING")
    _status(client, iid, "RESOLVED", resolution_summary="Field label corrected in API response")
    _status(client, iid, "CLOSED")
    response = client.put(f"/api/incidents/{iid}", json={"title": "Edited after closure"}, headers=headers())
    assert response.status_code == 422


# ---- timeline -----------------------------------------------------------------------------


def test_manual_timeline_events(client, create_incident):
    incident = create_incident()
    iid = incident["id"]
    evidence = client.post(
        f"/api/incidents/{iid}/events",
        json={"event_type": "EVIDENCE_ADDED", "description": "APM trace shows pool timeouts", "details": {"trace": "t-1"}},
        headers=headers("ENGINEER", "a.patel"),
    )
    assert evidence.status_code == 201
    assert evidence.json()["created_by"] == "a.patel"
    assert evidence.json()["source"] == "HUMAN"

    system_type = client.post(
        f"/api/incidents/{iid}/events",
        json={"event_type": "CLOSED", "description": "Trying to fake a closure"},
        headers=headers(),
    )
    assert system_type.status_code == 422
    assert _timeline_types(client, iid) == ["CREATED", "EVIDENCE_ADDED"]


# ---- list / filter / pagination -----------------------------------------------------------


def test_list_filters_and_pagination(client, create_incident, applications):
    create_incident(severity="P1")
    create_incident(severity="P2", title="Core banking DB connection errors", application_id=applications["CBS"].id,
                    category="DATABASE")
    create_incident(severity="P3", title="Reconciliation batch failed", application_id=applications["REC"].id,
                    category="BATCH_PROCESSING")

    page = client.get("/api/incidents?page=1&page_size=2", headers=headers()).json()
    assert page["total"] == 3 and page["pages"] == 2 and len(page["items"]) == 2

    p1 = client.get("/api/incidents?severity=P1", headers=headers()).json()
    assert [i["severity"] for i in p1["items"]] == ["P1"]

    multi = client.get("/api/incidents?severity=P2&severity=P3&sort=severity&order=asc", headers=headers()).json()
    assert [i["severity"] for i in multi["items"]] == ["P2", "P3"]

    by_app = client.get(f"/api/incidents?application_id={applications['CBS'].id}", headers=headers()).json()
    assert by_app["total"] == 1 and by_app["items"][0]["category"] == "DATABASE"

    search = client.get("/api/incidents?search=reconciliation", headers=headers()).json()
    assert search["total"] == 1

    assert client.get("/api/incidents?page_size=500", headers=headers()).status_code == 422
    assert client.get("/api/incidents?sort=password", headers=headers()).status_code == 422


def test_sla_endpoint_and_breach_filter(client, seeded):
    breached = client.get("/api/incidents?sla_breached=true", headers=headers()).json()
    refs = {i["reference_number"] for i in breached["items"]}
    assert refs == {"INC-1001", "INC-1004"}  # seeded P1 outage (75 min) and late SSO acknowledgement

    p1 = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
    sla = client.get(f"/api/incidents/{p1['id']}/sla", headers=headers()).json()
    assert sla["response"]["state"] == "MET"
    assert sla["resolution"]["state"] == "AT_RISK"
    assert sla["escalation_status"] == "RECOMMENDED"
    assert "Demonstration" in sla["note"]
