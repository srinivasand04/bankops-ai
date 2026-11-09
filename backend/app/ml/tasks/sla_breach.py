"""Task 2 - SLA-breach prediction at creation time (binary classification).

Logistic Regression turns a weighted sum of the features into a probability; its coefficients say
directly which factors raise or lower the risk, which is why risk teams like it.
Random Forest trains many decision trees on random samples and averages their votes - robust and
non-linear. XGBoost and LightGBM are gradient-boosted trees: each new tree fixes the previous trees'
mistakes; they are usually the strongest on tabular data. (When they are not installed, scikit-learn's
HistGradientBoosting stands in.)
Breaches are the minority class, so every model is told to weigh them more (class weights). We report
ROC-AUC (ranking quality), PR-AUC (quality on the rare class), F1 and calibration (does 0.7 mean 70%?).
"""

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sqlalchemy.orm import Session

from app.ml import SEED
from app.ml.datasets import time_split
from app.ml.evaluation import binary_metrics
from app.ml.features import INCIDENT_CATEGORICAL, INCIDENT_NUMERIC, load_incidents
from app.ml.registry import RunResult
from app.ml.tasks import TaskOutput
from app.ml.tasks.common import has, importances, preprocessor

FEATURES = INCIDENT_NUMERIC + INCIDENT_CATEGORICAL


def candidates(pos_weight: float) -> list[tuple[str, object, bool, dict]]:
    out = [
        ("logistic_regression", LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0), True, {"C": 1.0, "class_weight": "balanced"}),
        ("random_forest", RandomForestClassifier(n_estimators=300, min_samples_leaf=5, class_weight="balanced_subsample",
                                                 n_jobs=-1, random_state=SEED), False, {"n_estimators": 300, "min_samples_leaf": 5}),
    ]
    if has("xgboost"):
        from xgboost import XGBClassifier

        out.append(("xgboost", XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.9,
                                             scale_pos_weight=pos_weight, eval_metric="logloss", random_state=SEED, n_jobs=2),
                    False, {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05}))
    if has("lightgbm"):
        from lightgbm import LGBMClassifier

        out.append(("lightgbm", LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, class_weight="balanced",
                                               random_state=SEED, verbose=-1), False, {"n_estimators": 300, "num_leaves": 15}))
    if not (has("xgboost") or has("lightgbm")):
        out.append(("gradient_boosting", HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, class_weight="balanced",
                                                                       random_state=SEED), False, {"max_iter": 300}))
    return out


def train(db: Session) -> TaskOutput:
    df = load_incidents(db)
    df = df[df["sla_breached"].notna()]
    split = time_split(df, "created_at")
    X_tr, X_te = split.train[FEATURES], split.test[FEATURES]
    y_tr, y_te = split.train["sla_breached"].astype(int), split.test["sla_breached"].astype(int)
    pos_weight = float((y_tr == 0).sum() / max((y_tr == 1).sum(), 1))
    results = []
    for name, model, scale, params in candidates(pos_weight):
        pipe = Pipeline([("pre", preprocessor(INCIDENT_NUMERIC, INCIDENT_CATEGORICAL, scale)), ("model", model)])
        pipe.fit(X_tr, y_tr)
        proba = pipe.predict_proba(X_te)[:, 1]
        metrics, details = binary_metrics(y_te, proba)
        m = pipe.named_steps["model"]
        if hasattr(m, "coef_"):
            details["coefficients"] = importances(pipe, m.coef_[0])
        elif hasattr(m, "feature_importances_"):
            details["feature_importance"] = importances(pipe, m.feature_importances_)
        results.append(RunResult(name, pipe, metrics, params, details, score=metrics["roc_auc"] or 0))
    return TaskOutput(results, split.periods, len(split.train), len(split.test), {"features": FEATURES})


def explain_logistic(pipe, row) -> list[dict]:
    """Per-incident contributions (coefficient x scaled value) - the top reasons behind one prediction."""
    pre, model = pipe.named_steps["pre"], pipe.named_steps["model"]
    if not hasattr(model, "coef_"):
        return []
    x = pre.transform(row)[0]
    contrib = x * model.coef_[0]
    from app.ml.tasks.common import feature_names, labelled

    names = feature_names(pre)
    labels = labelled(names)
    order = np.argsort(-np.abs(contrib))[:5]
    return [{"feature": labels.get(names[i], names[i]), "effect": round(float(contrib[i]), 3)} for i in order if abs(contrib[i]) > 1e-6]
