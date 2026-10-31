from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.utils.time import utcnow


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes are interpreted as UTC; aware ones are normalised to UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


def _not_in_future(value: datetime) -> datetime:
    # A few minutes of tolerance for clock skew between monitoring tools and this service
    if (value - utcnow()).total_seconds() > 300:
        raise ValueError("timestamp cannot be in the future")
    return value


PastUtcDatetime = Annotated[UtcDatetime, AfterValidator(_not_in_future)]

NonEmptyStr = Annotated[str, Field(min_length=1)]
ShortText = Annotated[str, Field(min_length=1, max_length=100)]
EvidenceList = Annotated[list[Annotated[str, Field(min_length=1, max_length=2000)]], Field(max_length=50)]
