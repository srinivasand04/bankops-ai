"""Metrics, confusion matrices and calibration - plain numbers the UI can draw."""

import numpy as np
from sklearn.metrics import (
    average_precision_score, brier_score_loss, classification_report, confusion_matrix, f1_score,
    mean_absolute_error, mean_squared_error, precision_score, r2_score, recall_score, roc_auc_score,
)


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def binary_metrics(y_true, proba, threshold: float = 0.5) -> tuple[dict, dict]:
    y_true = np.asarray(y_true).astype(int)
    pred = (np.asarray(proba) >= threshold).astype(int)
    metrics = {
        "roc_auc": _r(roc_auc_score(y_true, proba)) if len(set(y_true)) > 1 else None,
        "pr_auc": _r(average_precision_score(y_true, proba)) if len(set(y_true)) > 1 else None,
        "f1": _r(f1_score(y_true, pred, zero_division=0)),
        "precision": _r(precision_score(y_true, pred, zero_division=0)),
        "recall": _r(recall_score(y_true, pred, zero_division=0)),
        "brier": _r(brier_score_loss(y_true, proba)),
        "positive_rate": _r(y_true.mean()),
    }
    # Calibration: mean predicted probability vs observed rate in 10 bins
    bins = np.clip((np.asarray(proba) * 10).astype(int), 0, 9)
    calibration = [
        {"bin": b / 10, "predicted": _r(np.asarray(proba)[bins == b].mean()), "observed": _r(y_true[bins == b].mean()), "n": int((bins == b).sum())}
        for b in range(10) if (bins == b).any()
    ]
    details = {"confusion_matrix": confusion_matrix(y_true, pred, labels=[0, 1]).tolist(), "labels": ["no", "yes"],
               "calibration": calibration, "threshold": threshold}
    return metrics, details


def regression_metrics(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    return {
        "mae_minutes": _r(mean_absolute_error(y_true, y_pred), 1),
        "rmse_minutes": _r(np.sqrt(mean_squared_error(y_true, y_pred)), 1),
        "r2": _r(r2_score(y_true, y_pred)),
        "median_abs_error_minutes": _r(np.median(np.abs(y_true - y_pred)), 1),
    }


def multiclass_metrics(y_true, y_pred, labels: list[str]) -> tuple[dict, dict]:
    report = classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0)
    metrics = {"macro_f1": _r(report["macro avg"]["f1-score"]), "weighted_f1": _r(report["weighted avg"]["f1-score"]),
               "accuracy": _r(report.get("accuracy", np.mean(np.asarray(y_true) == np.asarray(y_pred))))}
    per_class = {k: {"precision": _r(v["precision"]), "recall": _r(v["recall"]), "f1": _r(v["f1-score"]), "support": int(v["support"])}
                 for k, v in report.items() if k in labels}
    details = {"confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(), "labels": labels, "per_class": per_class}
    return metrics, details


def top_importances(names: list[str], values, n: int = 10, labels: dict | None = None) -> list[dict]:
    values = np.asarray(values, float)
    order = np.argsort(-np.abs(values))[:n]
    return [{"feature": names[i], "label": (labels or {}).get(names[i], names[i]), "value": _r(values[i], 4)} for i in order]
