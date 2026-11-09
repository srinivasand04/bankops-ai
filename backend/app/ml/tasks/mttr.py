"""Task 1 - MTTR prediction (regression): how many minutes will this incident take to resolve?

Linear Regression fits a straight-line relationship between the features and log(MTTR). Resolution
times are log-normal (a few incidents take days), so predicting the logarithm keeps those outliers from
dominating; it is the transparent baseline, and its residuals tell us whether a linear model is enough.
Gradient Boosting builds hundreds of small decision trees, each correcting the errors of the previous
ones, so it captures interactions (a P1 on Tier 1 at night) that a straight line cannot.
Metrics are reported in minutes: MAE, RMSE and R².
"""

import numpy as np
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sqlalchemy.orm import Session

from app.ml import SEED
from app.ml.datasets import time_split
from app.ml.evaluation import regression_metrics
from app.ml.features import INCIDENT_CATEGORICAL, INCIDENT_NUMERIC, load_incidents
from app.ml.registry import RunResult
from app.ml.tasks import TaskOutput
from app.ml.tasks.common import importances, preprocessor

FEATURES = INCIDENT_NUMERIC + INCIDENT_CATEGORICAL


def train(db: Session) -> TaskOutput:
    df = load_incidents(db)
    df = df[df["mttr_minutes"].notna() & (df["mttr_minutes"] > 0)]
    split = time_split(df, "started_at")
    X_tr, X_te = split.train[FEATURES], split.test[FEATURES]
    y_tr, y_te = np.log1p(split.train["mttr_minutes"]), split.test["mttr_minutes"].to_numpy()
    results = []

    lin = Pipeline([("pre", preprocessor(INCIDENT_NUMERIC, INCIDENT_CATEGORICAL, scale=True)), ("model", LinearRegression())])
    lin.fit(X_tr, y_tr)
    pred = np.expm1(lin.predict(X_te))
    m = regression_metrics(y_te, pred)
    residuals = np.log1p(y_te) - lin.predict(X_te)
    fitted = lin.predict(X_te)
    hist, edges = np.histogram(residuals, bins=15)
    residual_check = {
        "mean": round(float(residuals.mean()), 3), "std": round(float(residuals.std()), 3),
        "skew": round(float(stats.skew(residuals)), 3),
        "corr_abs_residual_vs_fitted": round(float(np.corrcoef(np.abs(residuals), fitted)[0, 1]), 3),
        "histogram": [{"x": round(float(edges[i]), 2), "n": int(hist[i])} for i in range(len(hist))],
        "reading": "Residuals of log(MTTR) should be centred on 0, roughly symmetric (skew near 0) and not grow with the "
                   "prediction (correlation near 0). Departures mean the linear model misses non-linear effects.",
    }
    results.append(RunResult("linear_regression", lin, m, {"target": "log1p(mttr_minutes)"},
                             {"residual_check": residual_check, "coefficients": importances(lin, lin.named_steps["model"].coef_),
                              "sample": _sample(y_te, pred)}, score=-m["mae_minutes"]))

    gb = Pipeline([("pre", preprocessor(INCIDENT_NUMERIC, INCIDENT_CATEGORICAL, scale=False)),
                   ("model", HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, random_state=SEED))])
    gb.fit(X_tr, y_tr)
    pred = np.expm1(gb.predict(X_te))
    m = regression_metrics(y_te, pred)
    results.append(RunResult("gradient_boosting", gb, m, {"max_iter": 300, "learning_rate": 0.05, "target": "log1p(mttr_minutes)"},
                             {"feature_importance": _perm_importance(gb, X_te, np.log1p(y_te)), "sample": _sample(y_te, pred)},
                             score=-m["mae_minutes"]))
    return TaskOutput(results, split.periods, len(split.train), len(split.test), {"features": FEATURES})


def _sample(actual, pred, n: int = 150) -> list[dict]:
    idx = np.linspace(0, len(actual) - 1, min(n, len(actual))).astype(int)
    return [{"actual": round(float(actual[i]), 1), "predicted": round(float(pred[i]), 1)} for i in idx]


def _perm_importance(pipeline, X, y) -> list[dict]:
    """Permutation importance on raw features: how much worse the model gets when one feature is shuffled."""
    from sklearn.inspection import permutation_importance

    from app.ml.features import FEATURE_LABELS

    r = permutation_importance(pipeline, X, y, n_repeats=3, random_state=SEED, scoring="neg_mean_absolute_error")
    order = np.argsort(-r.importances_mean)[:12]
    return [{"feature": X.columns[i], "label": FEATURE_LABELS.get(X.columns[i], X.columns[i]),
             "value": round(float(r.importances_mean[i]), 4)} for i in order]
