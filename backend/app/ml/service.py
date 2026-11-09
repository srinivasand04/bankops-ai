"""Use the active models: predictions for incidents and changes, stored in ml_predictions.

Predictions are suggestions with the model's name, version and test metrics attached, so people and
the AI analyst can judge how far to trust them. Nothing here changes an incident or a change.
"""

import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.ml.features import load_changes, load_incidents
from app.ml.registry import active_run, load_artifact
from app.models import ChangeRecord, Incident
from app.models.ml import MlModelRun, MlPrediction

logger = logging.getLogger(__name__)

INCIDENT_TASKS = ("sla_breach", "mttr", "routing", "similar", "clusters")
RELIABILITY_KEYS = ("roc_auc", "pr_auc", "f1", "mae_minutes", "r2", "macro_f1", "team_accuracy", "silhouette", "purity_vs_category")


def model_card(run: MlModelRun) -> dict:
    return {"task": run.task, "algorithm": run.algorithm, "version": run.version, "run_id": run.id,
            "test_metrics": {k: v for k, v in run.metrics.items() if k in RELIABILITY_KEYS}}


class MlService:
    def __init__(self, db: Session):
        self.db = db

    # ---- incidents ------------------------------------------------------------------------

    def predict_incident(self, incident_id: int) -> list[MlPrediction]:
        """Run every trained incident model once and store the results (replacing earlier ones)."""
        if self.db.get(Incident, incident_id) is None:
            raise NotFoundError(f"Incident {incident_id} not found")
        row = load_incidents(self.db, [incident_id])
        if row.empty:
            return []
        self.db.query(MlPrediction).filter(MlPrediction.entity_type == "INCIDENT", MlPrediction.entity_id == incident_id).delete()
        out = []
        for task in INCIDENT_TASKS:
            run = active_run(self.db, task)
            art = load_artifact(run) if run else None
            if not art:
                continue
            try:
                prediction, explanation = getattr(self, f"_{task}")(art, row, run, incident_id)
            except Exception:  # one model failing must not hide the others
                logger.exception("ML %s prediction failed for incident %s", task, incident_id)
                continue
            p = MlPrediction(model_run_id=run.id, entity_type="INCIDENT", entity_id=incident_id,
                             prediction=prediction, explanation={**explanation, "model": model_card(run)})
            self.db.add(p)
            out.append(p)
        self.db.commit()
        return out

    def incident_predictions(self, incident_id: int, refresh: bool = False) -> list[MlPrediction]:
        stored = list(self.db.scalars(select(MlPrediction).where(
            MlPrediction.entity_type == "INCIDENT", MlPrediction.entity_id == incident_id).order_by(MlPrediction.id)))
        return self.predict_incident(incident_id) if refresh or not stored else stored

    def _sla_breach(self, art, row, run, _id):
        pipe = art["model"]
        proba = float(pipe.predict_proba(row[art["features"]])[:, 1][0])
        from app.ml.tasks.sla_breach import explain_logistic

        reasons = explain_logistic(pipe, row[art["features"]])
        if not reasons and "feature_importance" in run.details:
            reasons = [{"feature": f["label"], "effect": f["value"]} for f in run.details["feature_importance"][:5]]
        return ({"breach_probability": round(proba, 3), "band": "HIGH" if proba >= 0.6 else "MEDIUM" if proba >= 0.35 else "LOW"},
                {"top_factors": reasons, "note": "Probability that the resolution SLA will be breached, from information known at creation."})

    def _mttr(self, art, row, run, _id):
        minutes = float(np.expm1(art["model"].predict(row[art["features"]])[0]))
        mae = run.metrics.get("mae_minutes")
        return ({"predicted_minutes": round(minutes, 1), "predicted_hours": round(minutes / 60, 1)},
                {"typical_error_minutes": mae, "note": "Expected time from start of impact to resolution."})

    def _routing(self, art, row, run, _id):
        models = art["model"]
        cat_model = models["category"] if isinstance(models, dict) else models
        text_value = row["text"]
        probs = cat_model.predict_proba(text_value)[0]
        order = np.argsort(-probs)[:3]
        top = [{"category": cat_model.classes_[i], "probability": round(float(probs[i]), 3)} for i in order]
        pred = {"suggested_category": top[0]["category"], "confidence": top[0]["probability"],
                "matches_recorded": top[0]["category"] == row["category"].iloc[0]}
        team_model = models.get("team") if isinstance(models, dict) else None
        if team_model is not None:
            tp = team_model.predict_proba(text_value)[0]
            j = int(np.argmax(tp))
            pred |= {"suggested_team": team_model.classes_[j], "team_confidence": round(float(tp[j]), 3)}
        return pred, {"alternatives": top, "note": "Suggested from the title and description; a person confirms."}

    def _similar(self, art, row, run, incident_id):
        from app.ml.tasks.similar import nearest, store_vectors

        from sqlalchemy import func, text

        stored = self.db.scalar(text("SELECT count(*) FROM ml_incident_vectors"))
        total = self.db.scalar(select(func.count()).select_from(Incident))
        # After a demo reset (or a bundle import) the vectors are gone: embed every incident once
        store_vectors(self.db, art["model"], run.id, None if stored < total - 1 else [incident_id])
        neighbours = nearest(self.db, incident_id, 5)
        return {"similar": neighbours}, {"note": "Nearest past incidents by text similarity (cosine, pgvector)."}

    def _clusters(self, art, row, run, _id):
        bundle = art["model"]
        vec = bundle["embedder"].transform(row["text"])
        c = int(bundle["kmeans"].predict(vec)[0])
        info = next((x for x in run.details.get("clusters", []) if x["cluster"] == c), {})
        return ({"cluster": c, "top_terms": info.get("top_terms", []), "main_category": info.get("main_category"),
                 "cluster_size": info.get("size")},
                {"note": "Recurring pattern this incident belongs to (K-Means on incident text)."})

    # ---- changes --------------------------------------------------------------------------

    def change_risk(self, change_id: int) -> MlPrediction:
        if self.db.get(ChangeRecord, change_id) is None:
            raise NotFoundError(f"Change {change_id} not found")
        run = active_run(self.db, "change_risk")
        art = load_artifact(run) if run else None
        if not art:
            raise NotFoundError("The change-risk model has not been trained yet (python -m app.ml train --task change_risk)")
        row = load_changes(self.db, [change_id])
        if row.empty:
            raise NotFoundError("This change has no deployment time, so it cannot be scored")
        from app.ml.tasks.change_risk import factors

        proba = float(art["model"].predict_proba(row[art["features"]])[:, 1][0])
        self.db.query(MlPrediction).filter(MlPrediction.entity_type == "CHANGE", MlPrediction.entity_id == change_id).delete()
        p = MlPrediction(model_run_id=run.id, entity_type="CHANGE", entity_id=change_id,
                         prediction={"incident_probability": round(proba, 3), "band": "HIGH" if proba >= 0.5 else "MEDIUM" if proba >= 0.25 else "LOW"},
                         explanation={"factors": factors(row), "model": model_card(run)})
        self.db.add(p)
        self.db.commit()
        return p


def predict_new_incident(db: Session, incident_id: int) -> None:
    """Called after an incident is created. Never fails the request: ML is optional."""
    try:
        MlService(db).predict_incident(incident_id)
    except Exception:
        db.rollback()
        logger.exception("Could not store ML predictions for incident %s", incident_id)
