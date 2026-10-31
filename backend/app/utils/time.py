from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def minutes_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 60
