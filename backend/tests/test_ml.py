"""Machine learning: time-based splits, no leakage, training every task, predictions, API, AI fact base."""

import pandas as pd
import pytest

from app.ai.context import build_incident_context
from app.core.config import get_settings
from app.ingestion.loader import load_dataset
from app.ingestion.reader import read_dataset
from app.ml.datasets import NotEnoughData, time_split
from app.ml.features import load_incidents
from app.ml.trainer import TASKS, train_all, train_task
from app.models import Incident
from app.synthetic.generator import GeneratorConfig, SyntheticGenerator, write_dataset
from tests.conftest import headers


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("ML_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    yield tmp_path / "artifacts"
    get_settings.cache_clear()


@pytest.fixture
def ml_data(db, tmp_path):
    """6 months of seeded synthetic history - enough to train every task quickly."""
    gen = SyntheticGenerator(GeneratorConfig(seed=7, months=6, scale=0.35))
    write_dataset(gen.generate(), tmp_path / "ds")
    load_dataset(db, read_dataset(tmp_path / "ds"))


def test_time_split_trains_on_the_past_only():
    df = pd.DataFrame({"t": pd.date_range("2026-01-01", periods=100, freq="D", tz="UTC"), "x": range(100)})
    split = time_split(df.sample(frac=1, random_state=1), "t")  # shuffled input
    assert split.train["t"].max() < split.test["t"].min()
    assert len(split.test) == 25
    with pytest.raises(NotEnoughData):
        time_split(df.head(10), "t")


def test_too_little_data_is_skipped_not_crashed(db, seeded, artifacts):
    out = train_task(db, "sla_breach")
    assert out["state"] == "SKIPPED" and "rows" in out["reason"]


def test_incident_features_use_only_the_past(db, seeded):
    df = load_incidents(db)
    inc = df[df["reference"] == "INC-1007"].iloc[0]
    # CHG-2041 was deployed 30 min before INC-1007 started, so it counts; nothing after the start does
    assert inc["changes_24h"] >= 1 and inc["recent_change"] == 1
    later = df[df["started_at"] > inc["started_at"]]
    assert inc["app_incidents_30d"] == len(df[(df["app"] == "PAY") & (df["started_at"] < inc["started_at"])
                                          & (df["started_at"] >= inc["started_at"] - pd.Timedelta(days=30))])
    assert not later.empty  # sanity: there is future data that must not leak in


def test_train_all_predict_and_serve(client, db, ml_data, artifacts):
    results = {r["task"]: r for r in train_all(db, "test")}
    assert set(results) == set(TASKS)
    assert all(r["state"] == "DONE" for r in results.values()), results

    runs = client.get("/api/ml/runs", headers=headers("VIEWER", "v")).json()
    by_task: dict[str, list] = {}
    for r in runs:
        by_task.setdefault(r["task"], []).append(r)
    # each task compares several algorithms on the same split; exactly one is active
    assert {r["algorithm"] for r in by_task["sla_breach"]} >= {"logistic_regression", "random_forest"}
    assert {r["algorithm"] for r in by_task["routing"]} == {"naive_bayes", "linear_svm", "rbf_svm"}
    assert all(sum(r["is_active"] for r in rs) == 1 for rs in by_task.values())
    tree = next(r for r in by_task["change_risk"] if r["algorithm"] == "decision_tree")
    assert len(tree["details"]["bias_variance"]) == 12 and "rules" in tree["details"]
    assert 0 <= by_task["sla_breach"][0]["metrics"]["roc_auc"] <= 1
    assert by_task["clusters"][0]["metrics"]["k"] in range(4, 17)
    assert "residual_check" in next(r for r in by_task["mttr"] if r["algorithm"] == "linear_regression")["details"]

    # predictions for an incident: suggestions only, nothing on the incident changes
    inc = db.query(Incident).order_by(Incident.id.desc()).first()
    before = (inc.severity, inc.category, inc.status)
    preds = client.get(f"/api/ml/incidents/{inc.id}/predictions", headers=headers()).json()
    tasks = {p["task"] for p in preds}
    assert {"sla_breach", "mttr", "routing", "similar", "clusters"} <= tasks
    sla = next(p for p in preds if p["task"] == "sla_breach")
    assert 0 <= sla["prediction"]["breach_probability"] <= 1 and sla["evidence_id"].startswith("ML-PRED-")
    similar = next(p for p in preds if p["task"] == "similar")["prediction"]["similar"]
    assert len(similar) == 5 and all(s["id"] != inc.id for s in similar)
    db.refresh(inc)
    assert (inc.severity, inc.category, inc.status) == before

    # the AI fact base cites them as ML-PRED evidence with model metrics
    ctx = build_incident_context(db, inc)
    ml_items = ctx.data["ml_predictions"]
    assert ml_items and all(i["id"] in ctx.valid_ids and i["test_metrics"] is not None for i in ml_items)

    # change risk
    changes = client.get("/api/ml/changes?limit=5", headers=headers()).json()
    assert len(changes) == 5 and all(0 <= c["prediction"]["incident_probability"] <= 1 for c in changes)

    tasks_view = client.get("/api/ml/tasks", headers=headers()).json()
    assert all(t["active"] for t in tasks_view)


def test_new_incident_gets_predictions(client, db, ml_data, artifacts):
    train_task(db, "routing")
    train_task(db, "sla_breach")
    app_id = db.query(Incident).first().application_id
    r = client.post("/api/incidents", json={"title": "Payment API timeouts calling card scheme", "description": "HTTP 504 from the card scheme gateway since 10:00",
                                           "application_id": app_id, "severity": "P2", "category": "API_INTEGRATION"},
                    headers=headers("ENGINEER", "eng"))
    assert r.status_code == 201
    preds = client.get(f"/api/ml/incidents/{r.json()['id']}/predictions", headers=headers()).json()
    assert {"routing", "sla_breach"} <= {p["task"] for p in preds}


def test_only_managers_can_train(client, artifacts):
    assert client.post("/api/ml/train", json={"tasks": ["mttr"]}, headers=headers("ENGINEER", "eng")).status_code == 403
    r = client.post("/api/ml/train", json={"tasks": ["mttr", "not_a_task"]}, headers=headers("INCIDENT_MANAGER", "mgr"))
    assert r.status_code == 202 and r.json()["queued"] == ["mttr"]


def test_hosted_demo_uses_the_pretrained_bundle(client, db, seeded, artifacts):
    """The hosted database only has the 15 demo incidents: models come from backend/ml_bundle."""
    from app.ml.bundle import BUNDLE_DIR, import_bundle_if_empty

    if not (BUNDLE_DIR / "runs.json").exists():
        pytest.skip("no bundle exported")
    assert import_bundle_if_empty(db) > 0
    assert import_bundle_if_empty(db) == 0  # only into an empty table
    inc = db.query(Incident).filter_by(reference_number="INC-1007").one()
    preds = client.get(f"/api/ml/incidents/{inc.id}/predictions", headers=headers()).json()
    assert {"sla_breach", "mttr", "routing", "similar"} <= {p["task"] for p in preds}
    similar = next(p for p in preds if p["task"] == "similar")["prediction"]["similar"]
    assert similar, "demo incidents are embedded on first use"


def test_missing_model_file_is_restored_from_bundle(client, db, seeded, artifacts):
    """A server whose disk lacks the model files (hosted redeploy) restores them from the shipped bundle."""
    from app.ml.bundle import BUNDLE_DIR, import_bundle_if_empty
    from app.ml.registry import _cache

    if not (BUNDLE_DIR / "runs.json").exists():
        pytest.skip("no bundle exported")
    import_bundle_if_empty(db)
    for f in artifacts.glob("*.joblib"):
        f.unlink()
    _cache.clear()
    inc = db.query(Incident).filter_by(reference_number="INC-1007").one()
    preds = client.get(f"/api/ml/incidents/{inc.id}/predictions", headers=headers()).json()
    assert {"sla_breach", "routing"} <= {p["task"] for p in preds}
    assert any(artifacts.glob("*.joblib"))
