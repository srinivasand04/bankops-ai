"""Task 7b - Anomaly detection on hourly operational metrics (time series).

Two detectors flag hours that look abnormal for an application's metric:
- Rolling z-score: how many standard deviations the value is from the previous 24 hours' mean.
  Simple, but it mistakes a normal daily peak for an anomaly.
- Seasonal residual: first forecast the value from the same hour-of-week's typical value (a seasonal
  baseline learned on the training weeks), then flag large forecast errors. It understands that
  09:00 Monday is always busy, so it should raise fewer false alarms.
The synthetic data injects anomalies 1-3 hours before related incidents start, so we can score each
detector: recall = share of incidents with an alert in the 3 hours before they started; precision =
share of alerts followed by an incident on the same application within 3 hours.
"""

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.ml.datasets import NotEnoughData
from app.ml.features import load_incidents, metric_catalog, metric_series
from app.ml.registry import RunResult
from app.ml.tasks import TaskOutput

Z_THRESHOLD = 3.0
LEAD = pd.Timedelta(hours=3)
EVAL_DAYS = 90


def rolling_z(series: pd.Series) -> pd.Series:
    mean = series.shift(1).rolling(24, min_periods=12).mean()
    std = series.shift(1).rolling(24, min_periods=12).std().replace(0, np.nan)
    return ((series - mean) / std).abs()


def seasonal_residual(series: pd.Series, train_end: pd.Timestamp) -> pd.Series:
    train = series[series.index < train_end]
    key = lambda idx: idx.day_of_week * 24 + idx.hour  # noqa: E731 - hour of week
    profile = train.groupby(key(train.index)).median()
    spread = (train - profile.reindex(key(train.index)).to_numpy()).abs().groupby(key(train.index)).median() * 1.4826
    expected = profile.reindex(key(series.index)).to_numpy()
    scale = spread.reindex(key(series.index)).replace(0, np.nan).to_numpy()
    return pd.Series(np.abs(series.to_numpy() - expected) / scale, index=series.index)


def train(db: Session) -> TaskOutput:
    catalog = metric_catalog(db)
    if not catalog:
        raise NotEnoughData("no hourly metrics loaded")
    incidents = load_incidents(db)[["app", "started_at"]]
    stats = {"rolling_zscore": {"tp_alerts": 0, "alerts": 0, "hit": 0, "incidents": 0, "examples": []},
             "seasonal_residual": {"tp_alerts": 0, "alerts": 0, "hit": 0, "incidents": 0, "examples": []}}
    test_from = test_to = None
    for app, metric, _ in catalog:
        s = metric_series(db, app, metric)
        if len(s) < 24 * 28:
            continue
        test_start = s.index.max() - pd.Timedelta(days=EVAL_DAYS)
        test_from, test_to = min(test_from or test_start, test_start), max(test_to or s.index.max(), s.index.max())
        starts = incidents[(incidents["app"] == app) & (incidents["started_at"] >= test_start)]["started_at"]
        for name, score in (("rolling_zscore", rolling_z(s)), ("seasonal_residual", seasonal_residual(s, test_start))):
            flags = score[(score.index >= test_start) & (score > Z_THRESHOLD)].index
            st = stats[name]
            st["alerts"] += len(flags)
            st["tp_alerts"] += sum(((starts > f) & (starts <= f + LEAD)).any() for f in flags)
            st["incidents"] += len(starts)
            st["hit"] += sum(((flags >= t - LEAD) & (flags < t)).any() for t in starts)
            if len(st["examples"]) < 3 and len(flags):
                window = s[(s.index >= flags[0] - pd.Timedelta(hours=36)) & (s.index <= flags[0] + pd.Timedelta(hours=12))]
                st["examples"].append({"application": app, "metric": metric, "flag": flags[0].isoformat(),
                                       "points": [{"t": t.isoformat(), "v": round(float(v), 3), "flag": bool(t in set(flags))} for t, v in window.items()]})
    results = []
    for name, st in stats.items():
        precision = st["tp_alerts"] / st["alerts"] if st["alerts"] else 0.0
        recall = st["hit"] / st["incidents"] if st["incidents"] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics = {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
                   "alerts": st["alerts"], "incidents": st["incidents"], "threshold": Z_THRESHOLD}
        results.append(RunResult(name, None, metrics, {"threshold": Z_THRESHOLD, "lead_hours": 3, "eval_days": EVAL_DAYS},
                                 {"examples": st["examples"]}, score=f1))
    return TaskOutput(results, {"test_from": test_from, "test_to": test_to}, 0, EVAL_DAYS * 24)
