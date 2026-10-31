"""Root cause governance, CAPA tracking and change correlation."""

from datetime import timedelta

import pytest

from app.core.exceptions import PermissionDeniedError
from app.core.security import CurrentUser, Role
from app.schemas.rca import RootCauseCreate, RootCauseReview
from app.services.incident_service import IncidentService
from app.services.rca_service import RcaService
from app.utils.time import utcnow
from tests.conftest import headers

AI_AGENT = CurrentUser(username="ai:incident-investigation-agent", role=Role.ADMIN)


def test_ai_hypothesis_is_never_confirmed_by_ai(db, create_incident):
    incident = create_incident()
    service = RcaService(db)
    hypothesis = service.add_root_cause(
        incident["id"],
        RootCauseCreate(description="Connection pool exhausted after release 2.4.1", confidence=0.7),
        AI_AGENT,
    )
    assert hypothesis.status == "HYPOTHESIS"
    assert hypothesis.source == "AI"

    with pytest.raises(PermissionDeniedError):
        service.review_root_cause(hypothesis.id, RootCauseReview(decision="CONFIRM"), AI_AGENT)
    db.refresh(hypothesis)
    assert hypothesis.status == "HYPOTHESIS" and hypothesis.confirmed_by is None


def test_ai_cannot_close_incident(db, create_incident):
    from app.schemas.incident import StatusChange

    incident = create_incident(severity="P3", assigned_team="Payments Production Support")
    service = IncidentService(db)
    human = CurrentUser("test.manager", Role.INCIDENT_MANAGER)
    service.change_status(incident["id"], StatusChange(status="INVESTIGATING"), human)
    service.change_status(incident["id"], StatusChange(status="RESOLVED", resolution_summary="Rolled back release"), human)
    with pytest.raises(PermissionDeniedError):
        service.change_status(incident["id"], StatusChange(status="CLOSED"), AI_AGENT)


def test_root_cause_cannot_be_created_as_confirmed(client, create_incident):
    incident = create_incident()
    response = client.post(
        f"/api/incidents/{incident['id']}/root-causes",
        json={"description": "Claimed confirmed root cause", "status": "CONFIRMED"},
        headers=headers(),
    )
    assert response.status_code == 422


def test_human_review_confirms_hypothesis(client, create_incident):
    incident = create_incident()
    rc = client.post(
        f"/api/incidents/{incident['id']}/root-causes",
        json={
            "description": "Connection pool max reduced from 100 to 20 in 2.4.1",
            "confidence": 0.6,
            "supporting_evidence": ["ConnectionPoolTimeoutException in logs"],
            "missing_evidence": ["Config diff 2.4.0 vs 2.4.1"],
        },
        headers=headers("ENGINEER", "a.patel"),
    ).json()
    assert rc["status"] == "HYPOTHESIS" and rc["source"] == "HUMAN"

    engineer_review = client.post(
        f"/api/root-causes/{rc['id']}/review", json={"decision": "CONFIRM"}, headers=headers("ENGINEER")
    )
    assert engineer_review.status_code == 403

    confirmed = client.post(
        f"/api/root-causes/{rc['id']}/review",
        json={"decision": "CONFIRM", "review_notes": "Config diff verified"},
        headers=headers(user="incident.manager"),
    ).json()
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_by"] == "incident.manager"

    again = client.post(f"/api/root-causes/{rc['id']}/review", json={"decision": "REJECT"}, headers=headers())
    assert again.status_code == 422

    rca = client.get(f"/api/incidents/{incident['id']}/rca", headers=headers()).json()
    assert [c["id"] for c in rca["confirmed_root_causes"]] == [rc["id"]]
    assert rca["hypotheses"] == []


def test_rca_keeps_hypotheses_separate_and_approval_needs_confirmation(client, create_incident):
    incident = create_incident()
    iid = incident["id"]
    client.post(f"/api/incidents/{iid}/root-causes", json={"description": "Possible DB failover issue"}, headers=headers())

    updated = client.put(
        f"/api/incidents/{iid}/rca",
        json={"summary": "Payment API failure following release", "confirmed_facts": ["500s began 30 min after deploy"],
              "contributing_factors": ["No load test for 2.4.1"]},
        headers=headers(),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["confirmed_facts"] == ["500s began 30 min after deploy"]
    assert len(body["hypotheses"]) == 1 and body["confirmed_root_causes"] == []

    approve = client.put(f"/api/incidents/{iid}/rca", json={"status": "APPROVED"}, headers=headers())
    assert approve.status_code == 422


def test_capa_actions_lifecycle(client, create_incident):
    incident = create_incident()
    iid = incident["id"]
    due = (utcnow().date() + timedelta(days=7)).isoformat()
    corrective = client.post(
        f"/api/incidents/{iid}/actions",
        json={"action_type": "CORRECTIVE", "description": "Roll back Payment Processing to 2.4.0",
              "assigned_team": "Release Management", "assigned_owner": "r.singh", "due_date": due},
        headers=headers(),
    )
    assert corrective.status_code == 201
    action = corrective.json()
    assert action["status"] == "OPEN" and action["is_overdue"] is False

    client.post(
        f"/api/incidents/{iid}/actions",
        json={"action_type": "PREVENTIVE", "description": "Add connection pool load test to release gate",
              "due_date": (utcnow().date() - timedelta(days=1)).isoformat()},
        headers=headers(),
    )

    completed = client.patch(f"/api/actions/{action['id']}", json={"status": "COMPLETED"}, headers=headers()).json()
    assert completed["status"] == "COMPLETED" and completed["completed_at"] is not None

    actions = client.get(f"/api/incidents/{iid}/actions", headers=headers()).json()
    assert [a["action_type"] for a in actions] == ["CORRECTIVE", "PREVENTIVE"]
    assert actions[1]["is_overdue"] is True

    timeline = [e["event_type"] for e in client.get(f"/api/incidents/{iid}/timeline", headers=headers()).json()]
    assert timeline == ["CREATED", "CORRECTIVE_ACTION", "PREVENTIVE_ACTION", "ACTION_UPDATED"]

    detail = client.get(f"/api/incidents/{iid}", headers=headers()).json()
    assert detail["open_action_count"] == 1

    assert client.patch(f"/api/actions/{action['id']}", json={}, headers=headers()).status_code == 422
    assert client.patch("/api/actions/99999", json={"status": "OPEN"}, headers=headers()).status_code == 404


def test_link_related_change(client, seeded):
    p1 = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
    links = client.get(f"/api/incidents/{p1['id']}/related-changes", headers=headers()).json()
    assert links[0]["change"]["change_reference"] == "CHG-2041"
    assert links[0]["change"]["version"] == "2.4.1"
    assert links[0]["minutes_from_deployment_to_incident"] == 30.0

    changes = {c["change_reference"]: c for c in client.get("/api/changes", headers=headers()).json()}
    duplicate = client.post(
        f"/api/incidents/{p1['id']}/related-changes", json={"change_id": changes["CHG-2041"]["id"]}, headers=headers()
    )
    assert duplicate.status_code == 422

    new_link = client.post(
        f"/api/incidents/{p1['id']}/related-changes",
        json={"change_id": changes["CHG-2038"]["id"], "link_status": "RULED_OUT", "notes": "OS patching on CBS only"},
        headers=headers(),
    )
    assert new_link.status_code == 201
    assert new_link.json()["link_status"] == "RULED_OUT"
