"""Machine-learning bookkeeping: every trained model and every prediction it made.

- ml_model_runs: one row per (task, algorithm) training run, with parameters, test metrics, the
  train/test periods and whether it is the model currently used for predictions (is_active).
- ml_predictions: model suggestions for an incident or a change. They are evidence for people and the
  AI analyst - they never change severity, category or anything else on their own.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JsonType, TimestampMixin


class MlModelRun(TimestampMixin, Base):
    __tablename__ = "ml_model_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(40), index=True)
    algorithm: Mapped[str] = mapped_column(String(60))
    version: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JsonType, default=dict)
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)  # confusion matrix, importances, curves
    train_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    train_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    n_train: Mapped[int] = mapped_column(Integer, default=0)
    n_test: Mapped[int] = mapped_column(Integer, default=0)
    data_source: Mapped[str] = mapped_column(String(30), default="ALL")
    artifact: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    trained_by: Mapped[str] = mapped_column(String(100), default="system")


class MlPrediction(TimestampMixin, Base):
    __tablename__ = "ml_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("ml_model_runs.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(20))  # INCIDENT | CHANGE
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    prediction: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[dict] = mapped_column(JsonType, default=dict)

    model_run: Mapped[MlModelRun] = relationship(lazy="joined")
