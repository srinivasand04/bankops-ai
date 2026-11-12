"""Business calendar - sensitive periods (month-end close, payroll, ...) used to prioritise incidents."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import Admin, AnyUser, DbSession
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import Application, BusinessCalendarPeriod
from app.models.enums import CalendarPeriodType, Severity
from app.repositories.application_repository import ApplicationRepository
from app.schemas.calendar import ActiveCalendarOut, CalendarPeriodIn, CalendarPeriodOut, PriorityPreview
from app.schemas.common import UtcDatetime
from app.services.business_calendar import CalendarIndex
from app.services.classification import decide_priority
from app.utils.time import utcnow

router = APIRouter(prefix="/api/business-calendar", tags=["Business Calendar"])


@router.get("", response_model=list[CalendarPeriodOut])
def list_periods(
    db: DbSession,
    _: AnyUser,
    start: UtcDatetime | None = None,
    end: UtcDatetime | None = None,
    application: Annotated[str | None, Query(description="Application code, e.g. GL")] = None,
    period_type: Annotated[list[CalendarPeriodType] | None, Query()] = None,
):
    """Periods overlapping [start, end) - by default the last 30 and the next 90 days."""
    now = utcnow()
    start, end = start or now - timedelta(days=30), end or now + timedelta(days=90)
    periods = CalendarIndex.load(db, start, end).periods
    return [
        p for p in periods
        if p.starts_at < end
        and (application is None or p.applies_to(application.upper()))
        and (not period_type or p.period_type in period_type)
    ]


@router.get("/active", response_model=ActiveCalendarOut)
def active(
    db: DbSession,
    _: AnyUser,
    application_id: int,
    at: UtcDatetime | None = None,
    severity: Annotated[Severity | None, Query(description="Also preview the priority a new incident would get")] = None,
):
    application = ApplicationRepository(db).get(application_id)
    if application is None:
        raise NotFoundError(f"Application {application_id} not found")
    at = at or utcnow()
    periods = CalendarIndex.load(db, at, at).active(application.code, at)
    preview = None
    if severity:
        decision = decide_priority(severity, application.business_criticality, periods, at)
        preview = PriorityPreview(priority=decision.priority, reason=decision.reason)
    return ActiveCalendarOut(application_code=application.code, at=at, periods=periods, priority_preview=preview)


def _validate_codes(db, codes: list[str]) -> None:
    known = set(db.scalars(select(Application.code).where(Application.code.in_(codes)))) if codes else set()
    unknown = sorted(set(codes) - known)
    if unknown:
        raise BusinessRuleError(f"Unknown application code(s): {', '.join(unknown)}", {"unknown": unknown})


def _get(db, period_id: int) -> BusinessCalendarPeriod:
    period = db.get(BusinessCalendarPeriod, period_id)
    if period is None:
        raise NotFoundError(f"Calendar period {period_id} not found")
    return period


@router.post("", response_model=CalendarPeriodOut, status_code=status.HTTP_201_CREATED)
def create_period(payload: CalendarPeriodIn, db: DbSession, admin: Admin):
    _validate_codes(db, payload.application_codes)
    period = BusinessCalendarPeriod(**payload.model_dump(), data_source="MANUAL", created_by=admin.username)
    db.add(period)
    db.commit()
    return period


@router.put("/{period_id}", response_model=CalendarPeriodOut)
def update_period(period_id: int, payload: CalendarPeriodIn, db: DbSession, _: Admin):
    period = _get(db, period_id)
    _validate_codes(db, payload.application_codes)
    for key, value in payload.model_dump().items():
        setattr(period, key, value)
    db.commit()
    return period


@router.delete("/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_period(period_id: int, db: DbSession, _: Admin):
    db.delete(_get(db, period_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
