"""Machine learning: tasks, model runs and their comparisons, training, and predictions."""

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AnyUser, DbSession, Manager
from app.ml.registry import active_run
from app.ml.service import MlService
from app.ml.trainer import STATUS, TASKS, train_in_background
from app.models import ChangeRecord
from app.models.ml import MlModelRun, MlPrediction

router = APIRouter(prefix="/api/ml", tags=["Machine learning"])


def run_out(r: MlModelRun, with_details: bool = True) -> dict:
    out = {"id": r.id, "task": r.task, "algorithm": r.algorithm, "version": r.version, "is_active": r.is_active,
           "params": r.params, "metrics": r.metrics, "n_train": r.n_train, "n_test": r.n_test,
           "train_from": r.train_from, "train_to": r.train_to, "test_from": r.test_from, "test_to": r.test_to,
           "trained_by": r.trained_by, "created_at": r.created_at}
    if with_details:
        out["details"] = r.details
    return out


def prediction_out(p: MlPrediction) -> dict:
    return {"id": p.id, "evidence_id": f"ML-PRED-{p.id}", "task": p.model_run.task, "algorithm": p.model_run.algorithm,
            "version": p.model_run.version, "prediction": p.prediction, "explanation": p.explanation, "created_at": p.created_at}


@router.get("/tasks")
def list_tasks(db: DbSession, _: AnyUser):
    """Every ML task, its active model and its last training status."""
    out = []
    for task, description in TASKS.items():
        run = active_run(db, task)
        out.append({"task": task, "description": description, "active": run_out(run, False) if run else None,
                    "status": STATUS.get(task)})
    return out


@router.get("/runs")
def list_runs(db: DbSession, _: AnyUser, task: str | None = None, latest_only: bool = True):
    """Model runs with metrics and details (confusion matrices, importances, curves). By default only the
    latest training of each task - the side-by-side comparison of its algorithms."""
    stmt = select(MlModelRun).order_by(MlModelRun.task, MlModelRun.id)
    if task:
        stmt = stmt.where(MlModelRun.task == task)
    runs = list(db.scalars(stmt))
    if latest_only:
        latest = {}
        for r in runs:
            latest[r.task] = max(latest.get(r.task, ""), r.version)
        runs = [r for r in runs if r.version == latest[r.task]]
    return [run_out(r) for r in runs]


class TrainRequest(BaseModel):
    tasks: list[str] | Literal["all"] = "all"


@router.post("/train", status_code=status.HTTP_202_ACCEPTED)
def train(payload: TrainRequest, background: BackgroundTasks, user: Manager):
    """Retrain in the background (incident managers and admins). Poll GET /api/ml/tasks for status."""
    tasks = list(TASKS) if payload.tasks == "all" else [t for t in payload.tasks if t in TASKS]
    for t in tasks:
        STATUS[t] = {"state": "QUEUED"}
    background.add_task(train_in_background, tasks, user.username)
    return {"queued": tasks}


@router.get("/incidents/{incident_id}/predictions")
def incident_predictions(incident_id: int, db: DbSession, _: AnyUser, refresh: bool = False):
    """Model suggestions for an incident (computed on first request). They never change the incident."""
    return [prediction_out(p) for p in MlService(db).incident_predictions(incident_id, refresh)]


@router.get("/changes/{change_id}/risk")
def change_risk(change_id: int, db: DbSession, _: AnyUser):
    """Probability that a change causes an incident, with the factors behind it."""
    return prediction_out(MlService(db).change_risk(change_id))


@router.get("/changes")
def recent_changes_with_risk(db: DbSession, _: AnyUser, limit: Annotated[int, Query(ge=1, le=50)] = 15):
    """The most recent deployed changes, each scored by the change-risk model."""
    changes = list(db.scalars(select(ChangeRecord).where(ChangeRecord.deployed_at.is_not(None))
                              .order_by(ChangeRecord.deployed_at.desc()).limit(limit)))
    if not active_run(db, "change_risk"):
        return []
    service = MlService(db)
    out = []
    for c in changes:
        p = service.change_risk(c.id)
        out.append({"id": c.id, "reference": c.change_reference, "application": c.application.code, "title": c.title,
                    "risk_level": c.risk_level, "change_type": c.change_type, "status": c.status, "deployed_at": c.deployed_at,
                    **prediction_out(p)})
    return out
