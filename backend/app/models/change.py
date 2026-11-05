"""Module 4 foundation - simulated change / deployment records used for incident correlation.

In production this table would be fed by an ITSM integration (change management system);
for the MVP it holds synthetic records.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.application import Application
from app.models.base import Base, DataSourceMixin, TimestampMixin, str_enum
from app.models.enums import ChangeStatus, ChangeType, RiskLevel


class ChangeRecord(DataSourceMixin, TimestampMixin, Base):
    __tablename__ = "change_records"
    __table_args__ = (UniqueConstraint("data_source", "external_id", name="uq_change_records_source_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    change_reference: Mapped[str] = mapped_column(String(20), unique=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[ChangeType] = mapped_column(str_enum(ChangeType, "change_type"))
    status: Mapped[ChangeStatus] = mapped_column(str_enum(ChangeStatus, "change_status"))
    risk_level: Mapped[RiskLevel] = mapped_column(str_enum(RiskLevel, "risk_level"))
    version: Mapped[str | None] = mapped_column(String(40))
    implementer: Mapped[str | None] = mapped_column(String(100))
    approver: Mapped[str | None] = mapped_column(String(100))
    rollback_plan: Mapped[str | None] = mapped_column(Text)
    # Change scope: number of components / services touched (a change-risk feature)
    components_changed: Mapped[int | None] = mapped_column(Integer)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    application: Mapped[Application] = relationship(lazy="joined")
