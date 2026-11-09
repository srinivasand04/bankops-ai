"""Shared building blocks for the table-based tasks."""

import importlib.util

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.ml.evaluation import top_importances
from app.ml.features import FEATURE_LABELS


def has(package: str) -> bool:
    """XGBoost / LightGBM are optional: compared when installed, skipped otherwise (smaller image)."""
    return importlib.util.find_spec(package) is not None


def preprocessor(numeric: list[str], categorical: list[str], scale: bool) -> ColumnTransformer:
    """One-hot encode categories; scale numbers for linear models (trees do not need it)."""
    return ColumnTransformer([
        ("num", StandardScaler() if scale else "passthrough", numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=5, sparse_output=False), categorical),
    ])


def feature_names(pre: ColumnTransformer) -> list[str]:
    return [n.split("__", 1)[1] for n in pre.get_feature_names_out()]


def labelled(names: list[str]) -> dict:
    """'category_DATABASE' -> 'category = DATABASE'; numeric features get their plain-English label."""
    out = {}
    for n in names:
        if n in FEATURE_LABELS:
            out[n] = FEATURE_LABELS[n]
        else:
            for prefix in ("category", "severity", "app", "change_type", "risk_level"):
                if n.startswith(prefix + "_"):
                    out[n] = f"{prefix} = {n[len(prefix) + 1:]}"
    return out


def importances(pipeline, values) -> list[dict]:
    names = feature_names(pipeline.named_steps["pre"])
    return top_importances(names, np.ravel(values), 12, labelled(names))
