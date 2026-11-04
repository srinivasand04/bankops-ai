"""Data ingestion pipeline: validation, loading, source isolation and evidence APIs."""

import json
import shutil
from datetime import timedelta

import pytest

from app.ingestion.loader import LoadError, dry_run, load_dataset, source_counts
from app.ingestion.reader import DatasetError, read_dataset
from app.utils.time import utcnow
from tests.conftest import SYNTHETIC_DATASET, headers


@pytest.fixture
def dataset_copy(tmp_path):
    """Editable copy of the synthetic dataset."""
    target = tmp_path / "synthetic"
    shutil.copytree(SYNTHETIC_DATASET, target)
    return target


def _edit(folder, file, mutate):
    path = folder / f"{file}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_synthetic_dataset_is_valid():
    dataset = read_dataset(SYNTHETIC_DATASET)
    assert dataset.manifest.data_source == "SYNTHETIC"
    assert len(dataset.applications) == 5
    assert len(dataset.incidents) == 10
    assert len(dataset.operational_events) > 50


def test_schema_errors_are_reported_with_location(dataset_copy):
    def break_records(incidents):
        incidents[0]["severity"] = "P0"
        incidents[1]["unexpected_field"] = True

    _edit(dataset_copy, "incidents", break_records)
    with pytest.raises(DatasetError) as exc:
        read_dataset(dataset_copy)
    errors = "\n".join(exc.value.errors)
    assert "incidents.json[0] severity" in errors
    assert "incidents.json[1] unexpected_field" in errors


def test_unknown_references_rejected(dataset_copy):
    _edit(dataset_copy, "changes", lambda changes: changes[0].update(application="NOPE"))
    with pytest.raises(DatasetError) as exc:
        read_dataset(dataset_copy)
    assert any("unknown application 'NOPE'" in e for e in exc.value.errors)


def test_invalid_lifecycle_history_aborts_load(db, dataset_copy):
    def skip_to_closed(incidents):
        incidents[-1]["history"] = [{"type": "status", "after_minutes": 1, "status": "CLOSED"}]

    _edit(dataset_copy, "incidents", skip_to_closed)
    dataset = read_dataset(dataset_copy)  # schema is fine...
    with pytest.raises(LoadError, match="Cannot move incident from OPEN to CLOSED"):
        dry_run(db, dataset)  # ...but the state machine rejects the history
    assert source_counts(db) == {}  # nothing persisted


def test_load_tags_source_and_is_idempotent(db, seeded):
    counts = source_counts(db)["SYNTHETIC"]
    assert counts == {"applications": 5, "changes": 5, "incidents": 10, "operational_events": counts["operational_events"]}
    second = load_dataset(db, read_dataset(SYNTHETIC_DATASET))
    assert second.skipped
    assert source_counts(db)["SYNTHETIC"]["incidents"] == 10


def test_replace_keeps_manual_incidents_and_references(db, client, seeded):
    apps = {a["code"]: a["id"] for a in client.get("/api/applications", headers=headers()).json()}
    manual = client.post(
        "/api/incidents",
        json={"title": "Manually raised incident", "description": "Created through the API during the demo.",
              "application_id": apps["PAY"], "severity": "P3", "category": "APPLICATION"},
        headers=headers(),
    ).json()
    assert manual["reference_number"] == "INC-1011"  # sequence advanced past dataset references
    assert manual["data_source"] == "MANUAL"

    report = load_dataset(db, read_dataset(SYNTHETIC_DATASET), replace=True)
    assert report.counts["incidents"] == 10
    db.expire_all()
    assert client.get(f"/api/incidents/{manual['id']}", headers=headers()).status_code == 200
    assert client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()["data_source"] == "SYNTHETIC"
    assert source_counts(db)["MANUAL"]["incidents"] == 1


def test_code_owned_by_another_source_is_rejected(db, applications, dataset_copy):
    # `applications` fixture created PAY etc. as SYNTHETIC; a different source may not take them over
    _edit(dataset_copy, "manifest", lambda m: m.update(data_source="OTHER_SOURCE"))
    with pytest.raises(LoadError, match="already belongs to source SYNTHETIC"):
        load_dataset(db, read_dataset(dataset_copy))


def test_data_source_filter_and_summary(client, seeded):
    synthetic = client.get("/api/incidents?data_source=synthetic", headers=headers()).json()
    assert synthetic["total"] == 10
    assert client.get("/api/incidents?data_source=BPI2014", headers=headers()).json()["total"] == 0
    summary = client.get("/api/data-sources", headers=headers()).json()
    assert summary["SYNTHETIC"]["incidents"] == 10


def test_incident_evidence_window_includes_related_apps(client, seeded):
    p1 = client.get("/api/incidents/by-reference/INC-1007", headers=headers()).json()
    evidence = client.get(f"/api/incidents/{p1['id']}/evidence", headers=headers()).json()
    apps = {e["application"]["code"] for e in evidence}
    assert apps == {"PAY", "CBS", "CUS", "REC"}  # incident app + its dependency + its dependents
    messages = " ".join(e["message"] for e in evidence)
    assert "maximumPoolSize=20" in messages
    assert "CHG-2041" in messages
    times = [e["occurred_at"] for e in evidence]
    assert times == sorted(times)

    only_pay = client.get(f"/api/incidents/{p1['id']}/evidence?include_related=false", headers=headers()).json()
    assert {e["application"]["code"] for e in only_pay} == {"PAY"}


def test_operational_event_filters(client, seeded):
    apps = {a["code"]: a["id"] for a in client.get("/api/applications", headers=headers()).json()}
    errors = client.get(
        f"/api/operational-events?application_id={apps['PAY']}&level=ERROR&level=CRITICAL&event_type=LOG",
        headers=headers(),
    ).json()
    assert errors and all(e["level"] in ("ERROR", "CRITICAL") and e["event_type"] == "LOG" for e in errors)

    # The payment scenario's 10-minute series; older points belong to other incidents' evidence windows
    since = (utcnow() - timedelta(hours=3)).isoformat()
    series = client.get(
        "/api/operational-events",
        params={"application_id": apps["PAY"], "metric_name": "http_5xx_rate_pct", "occurred_from": since},
        headers=headers(),
    ).json()
    assert len(series) == 13
    assert series[0]["metric_value"] < 1 < series[-1]["metric_value"]
    all_time = client.get(
        f"/api/operational-events?application_id={apps['PAY']}&metric_name=http_5xx_rate_pct", headers=headers()
    ).json()
    assert len(all_time) > len(series)
