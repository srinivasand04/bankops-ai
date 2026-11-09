"""Task 7a - Weekly incident volume forecast per application (time series).

A seasonal-naive baseline predicts next week = the average of the last 4 weeks: hard to beat when a
series is mostly noise, so every forecaster must be compared with it. Holt-Winters (exponential
smoothing) keeps a smoothed level and trend, giving recent weeks more weight; a damped trend stops it
from extrapolating a short spike forever. Both are fitted on the older weeks and scored on the newest
weeks (MAE in incidents per week, averaged over applications). The final model also forecasts the next
4 weeks for each application.
"""

import warnings

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from app.ml.datasets import NotEnoughData
from app.ml.features import load_incidents
from app.ml.registry import RunResult
from app.ml.tasks import TaskOutput

HORIZON = 4
MIN_WEEKS = 20


def weekly_counts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["week"] = df["created_at"].dt.tz_convert(None).dt.to_period("W-SUN").dt.start_time
    table = df.pivot_table(index="week", columns="app", values="id", aggfunc="count", fill_value=0)
    full = pd.date_range(table.index.min(), table.index.max(), freq="7D")
    return table.reindex(full, fill_value=0).iloc[1:-1]  # drop partial first/last weeks


def naive_forecast(history: np.ndarray, steps: int) -> np.ndarray:
    return np.repeat(history[-4:].mean(), steps)


def holt_forecast(history: np.ndarray, steps: int) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(history.astype(float), trend="add", damped_trend=True, initialization_method="estimated").fit()
    return np.clip(fit.forecast(steps), 0, None)


def train(db: Session) -> TaskOutput:
    weeks = weekly_counts(load_incidents(db))
    if len(weeks) < MIN_WEEKS:
        raise NotEnoughData(f"only {len(weeks)} full weeks of incidents (need {MIN_WEEKS})")
    cut = int(len(weeks) * 0.75)
    test_weeks = len(weeks) - cut
    results = []
    for name, fn in (("seasonal_naive", naive_forecast), ("holt_winters", holt_forecast)):
        errors, per_app = [], []
        for app in weeks.columns:
            series = weeks[app].to_numpy()
            pred = fn(series[:cut], test_weeks)
            mae = float(np.mean(np.abs(series[cut:] - pred)))
            errors.append(mae)
            nxt = fn(series, HORIZON)
            per_app.append({
                "application": app, "mae": round(mae, 2),
                "history": [{"week": w.strftime("%Y-%m-%d"), "actual": int(v)} for w, v in zip(weeks.index[-16:], series[-16:])],
                "test_prediction": [round(float(p), 1) for p in pred[-min(len(pred), 16):]],
                "next_weeks": [{"week": (weeks.index[-1] + pd.Timedelta(days=7 * (i + 1))).strftime("%Y-%m-%d"), "forecast": round(float(v), 1)}
                               for i, v in enumerate(nxt)],
            })
        metrics = {"mae_per_week": round(float(np.mean(errors)), 3), "applications": len(weeks.columns), "test_weeks": test_weeks}
        results.append(RunResult(name, None, metrics, {"horizon_weeks": HORIZON}, {"per_application": per_app}, score=-metrics["mae_per_week"]))
    periods = {"train_from": weeks.index[0], "train_to": weeks.index[cut - 1], "test_from": weeks.index[cut], "test_to": weeks.index[-1]}
    return TaskOutput(results, periods, cut, test_weeks)
