"""Users and roles: admin-only administration, roles from the database, lock-out protection."""

import pytest

from app.services.user_service import ensure_default_users
from tests.conftest import headers

ADMIN = {"X-User-Name": "srinivasan.d"}


@pytest.fixture
def users(db):
    ensure_default_users(db)


def _create(client, h=ADMIN, **body):
    payload = {"username": "j.martin", "full_name": "Julie Martin", "role": "ENGINEER", "email": "julie@example.test",
               "team": "Payments Production Support"} | body
    return client.post("/api/users", json=payload, headers=h)


def test_default_users_exist_once(client, db, users):
    assert ensure_default_users(db) == 0  # idempotent
    rows = client.get("/api/users", headers=headers()).json()
    by_name = {u["username"]: u for u in rows}
    assert by_name["srinivasan.d"]["role"] == "ADMIN"
    assert by_name["srinivasan.d"]["full_name"] == "Srinivasan Dhakshanamoorthy"
    assert {by_name[n]["role"] for n in ("engineer", "incident.manager", "risk.viewer")} == {"ENGINEER", "INCIDENT_MANAGER", "VIEWER"}


def test_role_comes_from_database_not_header(client, users):
    me = client.get("/api/users/me", headers={"X-User-Name": "risk.viewer", "X-User-Role": "INCIDENT_MANAGER"}).json()
    assert me["role"] == "VIEWER"
    assert client.get("/api/users/me", headers=ADMIN).json()["role"] == "ADMIN"


def test_unknown_names_cannot_claim_admin(client, users):
    r = client.get("/api/users/me", headers={"X-User-Name": "intruder", "X-User-Role": "ADMIN"})
    assert r.status_code == 403
    # scripts and tests with other roles keep working
    assert client.get("/api/users/me", headers=headers("ENGINEER", "script.user")).json()["role"] == "ENGINEER"


def test_admin_creates_user_who_can_then_act(client, users, seeded):
    r = _create(client)
    assert r.status_code == 201, r.text
    assert r.json()["created_by"] == "srinivasan.d"
    inc = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
    note = client.post(f"/api/incidents/{inc['id']}/events", json={"event_type": "COMMENT", "description": "Checked the pool"},
                       headers={"X-User-Name": "j.martin"})
    assert note.status_code in (200, 201) and note.json()["created_by"] == "j.martin"


def test_only_admin_manages_users(client, users):
    assert _create(client, h={"X-User-Name": "incident.manager"}).status_code == 403
    uid = next(u["id"] for u in client.get("/api/users", headers=ADMIN).json() if u["username"] == "engineer")
    assert client.patch(f"/api/users/{uid}", json={"role": "ADMIN"}, headers={"X-User-Name": "engineer"}).status_code == 403


def test_validation_and_duplicates(client, users):
    assert _create(client, username="Bad Name").status_code == 422
    assert _create(client, username="aiagent").status_code == 422  # reserved prefix
    assert _create(client, email="not-an-email").status_code == 422
    assert _create(client).status_code == 201
    assert _create(client).status_code == 409


def test_change_role_and_deactivate(client, users):
    uid = _create(client).json()["id"]
    r = client.patch(f"/api/users/{uid}", json={"role": "INCIDENT_MANAGER"}, headers=ADMIN)
    assert r.json()["role"] == "INCIDENT_MANAGER"
    assert client.get("/api/users/me", headers={"X-User-Name": "j.martin"}).json()["role"] == "INCIDENT_MANAGER"
    client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=ADMIN)
    assert client.get("/api/users/me", headers={"X-User-Name": "j.martin"}).status_code == 403
    active = [u["username"] for u in client.get("/api/users?include_inactive=false", headers=ADMIN).json()]
    assert "j.martin" not in active


def test_admin_cannot_lock_themselves_out(client, users):
    me = next(u for u in client.get("/api/users", headers=ADMIN).json() if u["username"] == "srinivasan.d")
    r = client.patch(f"/api/users/{me['id']}", json={"role": "VIEWER"}, headers=ADMIN)
    assert r.status_code == 422 and "your own" in r.json()["error"]["message"]
    assert client.patch(f"/api/users/{me['id']}", json={"is_active": False}, headers=ADMIN).status_code == 422


def test_last_admin_is_protected(client, users):
    other = _create(client, username="second.admin", role="ADMIN").json()
    me = next(u for u in client.get("/api/users", headers=ADMIN).json() if u["username"] == "srinivasan.d")
    # the second admin removes the first: allowed while another admin remains
    assert client.patch(f"/api/users/{me['id']}", json={"role": "ENGINEER"}, headers={"X-User-Name": "second.admin"}).status_code == 200
    # now second.admin is the only admin and cannot be demoted by anyone
    r = client.patch(f"/api/users/{other['id']}", json={"role": "VIEWER"}, headers={"X-User-Name": "second.admin"})
    assert r.status_code == 422
