"""Operational evidence - metrics, logs, alerts and job runs per application.

In production these would come from monitoring/APM, log platforms and schedulers. They are loaded
through the ingestion pipeline and read (never written) by the investigation agents.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.application import Application
from app.models.base import Base, DataSourceMixin, JsonType, str_enum
from app.models.enums import EvidenceLevel, EvidenceType


class OperationalEvent(DataSourceMixin, Base):
    __tablename__ = "operational_events"
    __table_args__ = (Index("ix_operational_events_app_time", "application_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    event_type: Mapped[EvidenceType] = mapped_column(str_enum(EvidenceType, "evidence_type"))
    level: Mapped[EvidenceLevel] = mapped_column(str_enum(EvidenceLevel, "evidence_level"))
    source_system: Mapped[str] = mapped_column(String(60))  # e.g. APM, app-log, Control-M
    message: Mapped[str] = mapped_column(Text)
    metric_name: Mapped[str | None] = mapped_column(String(80))
    metric_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    attributes: Mapped[dict | None] = mapped_column(JsonType)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship(lazy="joined")
