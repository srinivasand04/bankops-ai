from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.models.enums import CalendarPeriodType, Priority
from app.schemas.common import OrmModel, UtcDatetime

AppCode = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")]


class CalendarPeriodIn(BaseModel):
    name: Annotated[str, Field(min_length=3, max_length=120)]
    period_type: CalendarPeriodType
    starts_at: UtcDatetime
    ends_at: UtcDatetime
    application_codes: list[AppCode] = Field(default_factory=list, description="Empty = every application")
    raises_priority: bool | None = Field(
        default=None, description="Defaults to true, except for BANK_HOLIDAY (context only)"
    )
    description: Annotated[str, Field(max_length=2000)] | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        self.application_codes = sorted({code.upper() for code in self.application_codes})
        if self.raises_priority is None:
            self.raises_priority = self.period_type != CalendarPeriodType.BANK_HOLIDAY
        return self


class CalendarPeriodOut(OrmModel):
    id: int
    name: str
    period_type: CalendarPeriodType
    starts_at: datetime
    ends_at: datetime
    application_codes: list[str]
    raises_priority: bool
    description: str | None
    data_source: str
    created_by: str


class PriorityPreview(BaseModel):
    priority: Priority
    reason: str


class ActiveCalendarOut(BaseModel):
    application_code: str
    at: datetime
    periods: list[CalendarPeriodOut]
    priority_preview: PriorityPreview | None = None
