"""Business calendar: which sensitive periods are active, and a demonstration calendar generator.

The same incident matters more on day 2 of month-end close than on a quiet Tuesday. Periods are
looked up at incident start and feed `classification.decide_priority`. All generated periods are
demonstration values (tagged data_source=SYNTHETIC), not a real bank's calendar. Times are UTC.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Application, BusinessCalendarPeriod
from app.models.enums import CalendarPeriodType, Severity
from app.services.classification import PriorityDecision, decide_priority

logger = logging.getLogger(__name__)

DEMO_SOURCE = "SYNTHETIC"

# Which applications each period type affects in the demo bank (codes from the synthetic catalog)
CLOSE_APPS = ["GL", "CBS", "REC", "RDW"]
QUARTER_CLOSE_APPS = ["GL", "CBS", "RDW", "TRS"]
YEAR_CLOSE_APPS = ["GL", "CBS", "REC", "RDW", "TRS"]
PAYROLL_APPS = ["PAY", "CBS", "BATCH"]
REGULATORY_APPS = ["RDW", "GL"]
PEAK_APPS = ["CARDS", "PAY", "OLB", "MOB"]
TARGET2_APPS = ["PAY", "TRS", "REC"]

# EBA supervisory reporting (COREP / FINREP) remittance dates: (month, day, quarter reported, year offset)
REGULATORY_REMITTANCE = ((2, 11, 4, -1), (5, 12, 1, 0), (8, 11, 2, 0), (11, 11, 3, 0))


class CalendarIndex:
    """Periods of a time window held in memory - one query for a whole dataset load."""

    def __init__(self, periods: Iterable[BusinessCalendarPeriod]):
        self.periods = sorted(periods, key=lambda p: p.starts_at)

    @classmethod
    def load(cls, db: Session, start: datetime, end: datetime) -> "CalendarIndex":
        rows = db.scalars(
            select(BusinessCalendarPeriod).where(
                BusinessCalendarPeriod.starts_at <= end, BusinessCalendarPeriod.ends_at > start
            )
        )
        return cls(rows)

    def active(self, application_code: str, at: datetime) -> list[BusinessCalendarPeriod]:
        return [p for p in self.periods if p.starts_at <= at < p.ends_at and p.applies_to(application_code)]


def active_periods(db: Session, application_code: str, at: datetime) -> list[BusinessCalendarPeriod]:
    return CalendarIndex.load(db, at, at).active(application_code, at)


def priority_for(
    db: Session, severity: Severity, application: Application, at: datetime, index: CalendarIndex | None = None
) -> PriorityDecision:
    """Default priority of a new incident on `application` whose impact started at `at`."""
    periods = (index or CalendarIndex.load(db, at, at)).active(application.code, at)
    return decide_priority(severity, application.business_criticality, periods, at)


# ---- demonstration calendar ------------------------------------------------------------------


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - name from the published algorithm
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def french_public_holidays(year: int) -> dict[date, str]:
    easter = easter_sunday(year)
    return {
        date(year, 1, 1): "New Year's Day",
        easter + timedelta(days=1): "Easter Monday",
        date(year, 5, 1): "Labour Day",
        date(year, 5, 8): "Victory in Europe Day",
        easter + timedelta(days=39): "Ascension Day",
        easter + timedelta(days=50): "Whit Monday",
        date(year, 7, 14): "Bastille Day",
        date(year, 8, 15): "Assumption Day",
        date(year, 11, 1): "All Saints' Day",
        date(year, 11, 11): "Armistice Day",
        date(year, 12, 25): "Christmas Day",
    }


def target2_only_closing_days(year: int) -> dict[date, str]:
    """TARGET2 (euro payments) closing days that are not French public holidays."""
    return {easter_sunday(year) - timedelta(days=2): "Good Friday", date(year, 12, 26): "St Stephen's Day"}


class WorkingDays:
    def __init__(self, years: Iterable[int]):
        self.holidays: set[date] = set()
        for year in years:
            self.holidays |= set(french_public_holidays(year))

    def is_working(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def last_of_month(self, year: int, month: int) -> date:
        day = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
        while not self.is_working(day):
            day -= timedelta(days=1)
        return day

    def nth_of_month(self, year: int, month: int, n: int) -> date:
        day, count = date(year, month, 1), 0
        while True:
            if self.is_working(day):
                count += 1
                if count == n:
                    return day
            day += timedelta(days=1)

    def on_or_before(self, day: date) -> date:
        while not self.is_working(day):
            day -= timedelta(days=1)
        return day

    def shift(self, day: date, working_days: int) -> date:
        step = 1 if working_days > 0 else -1
        for _ in range(abs(working_days)):
            day += timedelta(days=step)
            while not self.is_working(day):
                day += timedelta(days=step)
        return day


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def demo_calendar(years: Iterable[int]) -> list[BusinessCalendarPeriod]:
    """Demonstration business calendar for the synthetic bank (French working days)."""
    years = sorted(set(years))
    wd = WorkingDays(range(years[0] - 1, years[-1] + 2))
    periods: list[BusinessCalendarPeriod] = []

    def add(key, name, kind, first: date, last: date, apps, description, raises=True):
        periods.append(BusinessCalendarPeriod(
            name=name, period_type=kind, starts_at=_midnight(first), ends_at=_midnight(last + timedelta(days=1)),
            application_codes=list(apps), raises_priority=raises, description=description + " (demonstration calendar)",
            data_source=DEMO_SOURCE, external_id=key, created_by="system",
        ))

    for year in years:
        for month in range(1, 13):
            label = date(year, month, 1).strftime("%b %Y")
            ny, nm = _next_month(year, month)
            close_start = wd.last_of_month(year, month)
            if month == 12:
                add(f"YEC-{year}", f"Year-end close {year}", CalendarPeriodType.YEAR_END_CLOSE, close_start,
                    wd.nth_of_month(ny, nm, 10), YEAR_CLOSE_APPS,
                    "Annual accounts closing: ledger, reconciliations and statutory reporting")
            elif month % 3 == 0:
                add(f"QEC-{year}-Q{month // 3}", f"Quarter-end close Q{month // 3} {year}",
                    CalendarPeriodType.QUARTER_END_CLOSE, close_start, wd.nth_of_month(ny, nm, 5), QUARTER_CLOSE_APPS,
                    "Quarterly closing: ledger, liquidity and capital figures")
            else:
                add(f"MEC-{year}-{month:02d}", f"Month-end close {label}", CalendarPeriodType.MONTH_END_CLOSE,
                    close_start, wd.nth_of_month(ny, nm, 3), CLOSE_APPS,
                    "Monthly closing: last working day to the 3rd working day of the next month")

            pay_day = wd.on_or_before(date(year, month, 25))
            add(f"PAY-{year}-{month:02d}", f"Salary payment run {label}", CalendarPeriodType.PAYROLL,
                wd.shift(pay_day, -1), wd.shift(pay_day, 1), PAYROLL_APPS,
                "Salary credits to customers: payment volumes peak around the 25th")

        for month, day, quarter, offset in REGULATORY_REMITTANCE:
            deadline = date(year, month, day)
            add(f"REG-{year + offset}-Q{quarter}", f"COREP/FINREP submission Q{quarter} {year + offset}",
                CalendarPeriodType.REGULATORY_DEADLINE, wd.shift(deadline, -3), deadline, REGULATORY_APPS,
                "Supervisory reporting to the regulator; remittance date from the EBA reporting calendar")

        november_first = date(year, 11, 1)
        black_friday = november_first + timedelta(days=(4 - november_first.weekday()) % 7 + 21)
        add(f"PEAK-{year}-BF", f"Black Friday to Cyber Monday {year}", CalendarPeriodType.PEAK_PERIOD,
            black_friday, black_friday + timedelta(days=3), PEAK_APPS, "Card and online payment volumes peak")

        for day, name in french_public_holidays(year).items():
            add(f"HOL-{day.isoformat()}", f"Bank holiday: {name}", CalendarPeriodType.BANK_HOLIDAY, day, day, [],
                "French public holiday: reduced support staffing, branches closed", raises=False)
        for day, name in target2_only_closing_days(year).items():
            add(f"T2-{day.isoformat()}", f"TARGET2 closed: {name}", CalendarPeriodType.BANK_HOLIDAY, day, day,
                TARGET2_APPS, "Euro large-value payment system closed: payments wait for the next business day",
                raises=False)
    return periods


def seed_demo_calendar(db: Session, years: Iterable[int], replace: bool = False) -> int:
    """Insert the demonstration calendar unless one is already loaded. Returns the number of periods added."""
    existing = db.scalar(select(BusinessCalendarPeriod.id).where(BusinessCalendarPeriod.data_source == DEMO_SOURCE).limit(1))
    if existing and not replace:
        return 0
    db.execute(delete(BusinessCalendarPeriod).where(BusinessCalendarPeriod.data_source == DEMO_SOURCE))
    periods = demo_calendar(years)
    db.add_all(periods)
    db.commit()
    logger.info("Seeded %d demonstration business-calendar periods", len(periods))
    return len(periods)
