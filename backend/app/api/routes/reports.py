"""Management reports across all applications (read-only, any signed-in role)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AnyUser, DbSession
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/reports", tags=["Reports"])

Days = Annotated[int, Query(ge=7, le=366, description="Period: incidents created in the last N days")]


@router.get("/scorecard")
def application_scorecard(db: DbSession, _: AnyUser, days: Days = 90):
    """Every application: incidents, open/P1, SLA compliance, MTTR/MTTA, changes and a RAG status."""
    return ReportService(db, days).scorecard()


@router.get("/sla")
def sla_performance(db: DbSession, _: AnyUser, days: Days = 90):
    """SLA compliance by severity and application, and the incidents breaching their SLA now."""
    return ReportService(db, days).sla_report()


@router.get("/trends")
def incident_trends(db: DbSession, _: AnyUser, days: Days = 90):
    """Weekly (up to 120 days) or monthly incident volume by severity, resolutions, MTTR and SLA breaches."""
    return ReportService(db, days).trends()


@router.get("/change-risk")
def change_risk(db: DbSession, _: AnyUser, days: Days = 90):
    """Changes per application, failures and roll-backs, incidents linked to changes, change failure rate."""
    return ReportService(db, days).change_risk()


@router.get("/problems")
def problem_management(db: DbSession, _: AnyUser, days: Days = 90):
    """Recurring incidents (same application + category) and reopened incidents."""
    return ReportService(db, days).problems()


@router.get("/management-pack")
def management_pack(db: DbSession, _: AnyUser, days: Days = 90):
    """All five reports in one response - the printable management report."""
    return ReportService(db, days).management_pack()
