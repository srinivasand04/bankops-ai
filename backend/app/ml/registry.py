"""Save and load trained models (joblib) and record each run in ml_model_runs.

Artifacts live in ML_ARTIFACTS_DIR (a Docker volume locally). The best run of each task becomes the
active model used for predictions.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import joblib
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ml import MlModelRun
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """One algorithm's outcome on a task's test set."""

    algorithm: str
    model: object | None
    metrics: dict
    params: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    score: float = 0.0  # primary metric, higher is better - used to pick the active model


def artifacts_dir() -> Path:
    path = Path(get_settings().ml_artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_runs(db: Session, task: str, results: list[RunResult], periods: dict, n_train: int, n_test: int,
              trained_by: str = "system", shared: dict | None = None) -> list[MlModelRun]:
    """Store every algorithm's run; the best becomes active (the previous active run is retired)."""
    version = utcnow().strftime("%Y%m%d-%H%M%S")
    best = max(results, key=lambda r: r.score) if results else None
    db.execute(update(MlModelRun).where(MlModelRun.task == task).values(is_active=False))
    runs = []
    for r in results:
        artifact = None
        if r.model is not None:
            name = f"{task}-{r.algorithm}-{version}.joblib"
            joblib.dump({"model": r.model, **(shared or {})}, artifacts_dir() / name)
            artifact = name
        run = MlModelRun(
            task=task, algorithm=r.algorithm, version=version, params=r.params, metrics=r.metrics, details=r.details,
            n_train=n_train, n_test=n_test, artifact=artifact, is_active=r is best, trained_by=trained_by,
            **{k: _ts(v) for k, v in periods.items()},
        )
        db.add(run)
        runs.append(run)
    db.commit()
    if best:
        logger.info("ML task %s: active model %s (score %.3f)", task, best.algorithm, best.score)
    return runs


def _ts(value) -> datetime | None:
    return value.to_pydatetime() if hasattr(value, "to_pydatetime") else value


def active_run(db: Session, task: str) -> MlModelRun | None:
    return db.scalar(select(MlModelRun).where(MlModelRun.task == task, MlModelRun.is_active).order_by(MlModelRun.id.desc()))


_cache: dict[str, dict] = {}


def load_artifact(run: MlModelRun) -> dict | None:
    """Load (and cache) a run's saved model; None if the file is missing."""
    if not run.artifact:
        return None
    if run.artifact not in _cache:
        path = artifacts_dir() / run.artifact
        if not path.exists():
            logger.warning("ML artifact missing: %s", path)
            return None
        _cache[run.artifact] = joblib.load(path)
    return _cache[run.artifact]
