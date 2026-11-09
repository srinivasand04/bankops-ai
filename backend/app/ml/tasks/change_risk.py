"""Task 3 - Change risk scoring: will this change cause an incident?

A Decision Tree asks a sequence of yes/no questions ("deployed on a Friday?", "outside the change
window?") - a shallow tree can be printed as rules a change advisory board can read. Random Forest
averages many trees for stability; Gradient Boosting adds trees that correct each other.
The bias-variance study trains trees of depth 1..12: shallow trees underfit (both scores low), deep
trees overfit (train score near 1, test score falls). The gap between the two curves is the variance.
"""

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier, export_text
from sqlalchemy.orm import Session

from app.ml import SEED
from app.ml.datasets import time_split
from app.ml.evaluation import binary_metrics
from app.ml.features import CHANGE_NUMERIC, load_changes
from app.ml.registry import RunResult
from app.ml.tasks import TaskOutput
from app.ml.tasks.common import feature_names, importances, labelled, preprocessor

CATEGORICAL = ["change_type", "risk_level"]
FEATURES = CHANGE_NUMERIC + CATEGORICAL


def _pipe(model):
    return Pipeline([("pre", preprocessor(CHANGE_NUMERIC, CATEGORICAL, scale=False)), ("model", model)])


def train(db: Session) -> TaskOutput:
    df = load_changes(db)
    split = time_split(df, "deployed_at")
    X_tr, X_te = split.train[FEATURES], split.test[FEATURES]
    y_tr, y_te = split.train["caused_incident"], split.test["caused_incident"]
    results = []

    tree = _pipe(DecisionTreeClassifier(max_depth=4, min_samples_leaf=10, class_weight="balanced", random_state=SEED))
    tree.fit(X_tr, y_tr)
    metrics, details = binary_metrics(y_te, tree.predict_proba(X_te)[:, 1])
    names = feature_names(tree.named_steps["pre"])
    details["rules"] = export_text(tree.named_steps["model"], feature_names=[labelled(names).get(n, n) for n in names], decimals=1)
    details["feature_importance"] = importances(tree, tree.named_steps["model"].feature_importances_)
    curve = []
    for depth in range(1, 13):
        t = _pipe(DecisionTreeClassifier(max_depth=depth, min_samples_leaf=2, class_weight="balanced", random_state=SEED)).fit(X_tr, y_tr)
        curve.append({"depth": depth,
                      "train_auc": round(float(roc_auc_score(y_tr, t.predict_proba(X_tr)[:, 1])), 3),
                      "test_auc": round(float(roc_auc_score(y_te, t.predict_proba(X_te)[:, 1])), 3)})
    details["bias_variance"] = curve
    results.append(RunResult("decision_tree", tree, metrics, {"max_depth": 4, "min_samples_leaf": 10}, details, score=metrics["roc_auc"] or 0))

    rf = _pipe(RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced_subsample", n_jobs=-1, random_state=SEED))
    rf.fit(X_tr, y_tr)
    metrics, details = binary_metrics(y_te, rf.predict_proba(X_te)[:, 1])
    details["feature_importance"] = importances(rf, rf.named_steps["model"].feature_importances_)
    results.append(RunResult("random_forest", rf, metrics, {"n_estimators": 300}, details, score=metrics["roc_auc"] or 0))

    gb = _pipe(HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, class_weight="balanced", random_state=SEED))
    gb.fit(X_tr, y_tr)
    metrics, details = binary_metrics(y_te, gb.predict_proba(X_te)[:, 1])
    results.append(RunResult("gradient_boosting", gb, metrics, {"max_iter": 200, "max_depth": 3}, details, score=metrics["roc_auc"] or 0))
    return TaskOutput(results, split.periods, len(split.train), len(split.test), {"features": FEATURES})


def factors(row) -> list[dict]:
    """Reasons for a change's risk, from its own attributes, as codes the UI translates (n = a count)."""
    r = row.iloc[0]
    out = []
    if r["is_friday"]:
        out.append({"code": "friday"})
    if r["out_of_window"]:
        out.append({"code": "out_of_window"})
    if r["tier_n"] == 1:
        out.append({"code": "tier1"})
    if r["components"] >= 8:
        out.append({"code": "large_scope", "n": int(r["components"])})
    if r["is_emergency"]:
        out.append({"code": "emergency"})
    if r["app_failed_changes_90d"] > 0:
        out.append({"code": "app_history", "n": int(r["app_failed_changes_90d"])})
    if r["risk_n"] == 2:
        out.append({"code": "declared_high"})
    return out
