"""Train one task or all of them, store every run, and keep a simple training status for the UI."""

import logging
import time
from importlib import import_module

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.ml.datasets import NotEnoughData
from app.ml.registry import active_run, load_artifact, save_runs
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

TASKS = {
    "mttr": "Predict resolution time (regression)",
    "sla_breach": "Predict SLA breach at creation (classification)",
    "change_risk": "Score a change's risk of causing an incident",
    "routing": "Suggest category and team from the text",
    "similar": "Find similar past incidents (KNN, pgvector)",
    "clusters": "Discover incident patterns (K-Means)",
    "forecast": "Forecast weekly incident volume (time series)",
    "anomaly": "Detect metric anomalies before incidents (time series)",
}

# Last training outcome per task, shown in the ML Lab while a background run is going
STATUS: dict[str, dict] = {}


def train_task(db: Session, task: str, trained_by: str = "system") -> dict:
    if task not in TASKS:
        raise ValueError(f"Unknown task '{task}'")
    STATUS[task] = {"state": "RUNNING", "started_at": utcnow().isoformat()}
    t0 = time.perf_counter()
    try:
        out = import_module(f"app.ml.tasks.{task}").train(db)
        runs = save_runs(db, task, out.results, out.periods, out.n_train, out.n_test, trained_by, out.shared)
        if task == "similar":
            from app.ml.tasks.similar import store_vectors

            run = active_run(db, "similar")
            if run and (art := load_artifact(run)):
                store_vectors(db, art["model"], run.id)
        best = next((r for r in runs if r.is_active), None)
        STATUS[task] = {"state": "DONE", "seconds": round(time.perf_counter() - t0, 1), "runs": len(runs),
                        "active": best.algorithm if best else None, "finished_at": utcnow().isoformat()}
    except NotEnoughData as exc:
        db.rollback()
        STATUS[task] = {"state": "SKIPPED", "reason": str(exc), "finished_at": utcnow().isoformat()}
    except Exception as exc:
        db.rollback()
        logger.exception("Training %s failed", task)
        STATUS[task] = {"state": "FAILED", "reason": f"{type(exc).__name__}: {exc}"[:300], "finished_at": utcnow().isoformat()}
    return {"task": task, **STATUS[task]}


def train_all(db: Session, trained_by: str = "system") -> list[dict]:
    return [train_task(db, task, trained_by) for task in TASKS]


def train_in_background(tasks: list[str], trained_by: str) -> None:
    """Entry point for FastAPI BackgroundTasks (own session)."""
    with SessionLocal() as db:
        for task in tasks:
            train_task(db, task, trained_by)
