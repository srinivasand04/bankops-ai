"""Business calendar - periods (month-end close, payroll, ...) that make incidents more urgent."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, DataSourceMixin, JsonType, TimestampMixin, str_enum
from app.models.enums import CalendarPeriodType


class BusinessCalendarPeriod(DataSourceMixin, TimestampMixin, Base):
    """A time window [starts_at, ends_at) that matters to the business.

    `application_codes` lists the affected applications by code (empty = every application). Codes,
    not foreign keys, so the calendar can be maintained before or independently of application data.
    """

    __tablename__ = "business_calendar_periods"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="period_not_empty"),
        Index("ix_business_calendar_periods_window", "starts_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    period_type: Mapped[CalendarPeriodType] = mapped_column(str_enum(CalendarPeriodType, "calendar_period_type"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    application_codes: Mapped[list[str]] = mapped_column(JsonType, default=list)
    raises_priority: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(100), default="system")

    def applies_to(self, application_code: str) -> bool:
        return not self.application_codes or application_code in self.application_codes
