"""Pre-trained model bundle for the hosted demo.

The free hosted database only holds the small demo dataset (15 incidents) - too little to train on.
So models are trained locally on the 4,000-incident synthetic dataset, and `export-bundle` copies the
active models plus their run records into backend/ml_bundle/. At startup an empty ml_model_runs table
is filled from the bundle, so the ML Lab and predictions work on the hosted demo too.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ml.registry import artifacts_dir
from app.models.ml import MlModelRun

logger = logging.getLogger(__name__)

BUNDLE_DIR = Path(__file__).resolve().parents[2] / "ml_bundle"
COLUMNS = ["task", "algorithm", "version", "params", "metrics", "details", "train_from", "train_to", "test_from",
           "test_to", "n_train", "n_test", "data_source", "artifact", "is_active", "trained_by"]


def export_bundle(db: Session) -> dict:
    BUNDLE_DIR.mkdir(exist_ok=True)
    for old in BUNDLE_DIR.glob("*.joblib"):
        old.unlink()
    latest_versions = dict(db.execute(select(MlModelRun.task, func.max(MlModelRun.version)).where(MlModelRun.is_active)
                                      .group_by(MlModelRun.task)).all())
    runs = [r for r in db.scalars(select(MlModelRun).order_by(MlModelRun.id)) if latest_versions.get(r.task) == r.version]
    records = []
    for r in runs:
        rec = {c: getattr(r, c) for c in COLUMNS}
        for c in ("train_from", "train_to", "test_from", "test_to"):
            rec[c] = rec[c].isoformat() if rec[c] else None
        if r.artifact and r.is_active and (artifacts_dir() / r.artifact).exists():
            shutil.copy2(artifacts_dir() / r.artifact, BUNDLE_DIR / r.artifact)
        elif not r.is_active:
            rec["artifact"] = None  # comparison runs keep their metrics; only active models ship
        records.append(rec)
    (BUNDLE_DIR / "runs.json").write_text(json.dumps(records, indent=1, default=str), encoding="utf-8")
    size = sum(p.stat().st_size for p in BUNDLE_DIR.iterdir())
    return {"runs": len(records), "models": len(list(BUNDLE_DIR.glob("*.joblib"))), "size_mb": round(size / 1e6, 2)}


def import_bundle_if_empty(db: Session) -> int:
    """Load the shipped bundle when no model has been trained in this database yet."""
    runs_file = BUNDLE_DIR / "runs.json"
    if not runs_file.exists() or db.scalar(select(func.count()).select_from(MlModelRun)):
        return 0
    records = json.loads(runs_file.read_text(encoding="utf-8"))
    for rec in records:
        for c in ("train_from", "train_to", "test_from", "test_to"):
            rec[c] = datetime.fromisoformat(rec[c]) if rec.get(c) else None
        if rec.get("artifact") and (BUNDLE_DIR / rec["artifact"]).exists():
            shutil.copy2(BUNDLE_DIR / rec["artifact"], artifacts_dir() / rec["artifact"])
        db.add(MlModelRun(**rec))
    db.commit()
    logger.info("Imported %s pre-trained ML runs from the bundle", len(records))
    return len(records)
