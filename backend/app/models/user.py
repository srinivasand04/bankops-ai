"""People who use BankOps AI and the role each one has.

The role decides what a person may do (core.security.Role). In demo mode the browser says which user
is acting (X-User-Name); for users stored here the role always comes from this table, never from the
browser.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import Role
from app.models.base import Base, TimestampMixin, str_enum


class AppUser(TimestampMixin, Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"))
    team: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(100), default="system")
