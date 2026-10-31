from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AnyUser, DbSession
from app.services.analytics_service import AnalyticsFilter, AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


def analytics_filter(
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    application_id: int | None = None,
) -> AnalyticsFilter:
    return AnalyticsFilter(created_from=created_from, created_to=created_to, application_id=application_id)


Filter = Annotated[AnalyticsFilter, Depends(analytics_filter)]


@router.get("/incident-summary")
def incident_summary(db: DbSession, _: AnyUser, f: Filter):
    return AnalyticsService(db).summary(f)


@router.get("/severity-breakdown")
def severity_breakdown(db: DbSession, _: AnyUser, f: Filter):
    return AnalyticsService(db).severity_breakdown(f)


@router.get("/category-breakdown")
def category_breakdown(db: DbSession, _: AnyUser, f: Filter):
    return AnalyticsService(db).category_breakdown(f)


@router.get("/application-incidents")
def application_incidents(db: DbSession, _: AnyUser, f: Filter):
    return AnalyticsService(db).application_incidents(f)


@router.get("/mttr")
def mttr(db: DbSession, _: AnyUser, f: Filter):
    return AnalyticsService(db).mttr(f)


@router.get("/sla-compliance")
def sla_compliance(db: DbSession, _: AnyUser, f: Filter):
    return AnalyticsService(db).sla_compliance(f)


@router.get("/trends")
def trends(
    db: DbSession,
    _: AnyUser,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    application_id: int | None = None,
):
    return AnalyticsService(db).trends(days, application_id)


@router.get("/repeated-incidents")
def repeated_incidents(
    db: DbSession,
    _: AnyUser,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
    min_occurrences: Annotated[int, Query(ge=2, le=50)] = 2,
):
    return AnalyticsService(db).repeated_incidents(days, min_occurrences)
