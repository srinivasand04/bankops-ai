"""User administration: who can use BankOps AI and with which role.

Rules:
- Only an ADMIN creates users, changes roles or deactivates people.
- There is always at least one active ADMIN, and an admin cannot lock themselves out.
- The default users (an admin and one user per role) are re-created at startup if missing, so a demo
  reset never leaves the tool without an administrator.
"""

import re

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.security import CurrentUser, Role
from app.models.user import AppUser

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,48}[a-z0-9]$")

DEFAULT_USERS = [
    {"username": "srinivasan.d", "full_name": "Srinivasan Dhakshanamoorthy", "role": Role.ADMIN,
     "team": "Platform owner", "email": None},
    {"username": "engineer", "full_name": "Engineer", "role": Role.ENGINEER, "team": "Production Support", "email": None},
    {"username": "incident.manager", "full_name": "Incident manager", "role": Role.INCIDENT_MANAGER,
     "team": "Major Incident Management", "email": None},
    {"username": "risk.viewer", "full_name": "Viewer", "role": Role.VIEWER, "team": "Technology Risk", "email": None},
]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    full_name: str = Field(min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    role: Role
    team: str | None = Field(default=None, max_length=100)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not USERNAME.match(value) or value.startswith("ai"):
            raise ValueError("use 3-50 lower-case letters, digits, '.', '_' or '-' (names starting with 'ai' are reserved)")
        return value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError("not a valid e-mail address")
        return value


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    team: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: str | None
    role: Role
    team: str | None
    is_active: bool
    created_by: str

    model_config = {"from_attributes": True}


def ensure_default_users(db: Session) -> int:
    """Create any missing default user; returns how many were created."""
    existing = set(db.scalars(select(AppUser.username)))
    created = 0
    for data in DEFAULT_USERS:
        if data["username"] not in existing:
            db.add(AppUser(**data, is_active=True, created_by="system"))
            created += 1
    db.commit()
    return created


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, include_inactive: bool = True) -> list[AppUser]:
        stmt = select(AppUser).order_by(AppUser.is_active.desc(), AppUser.full_name)
        if not include_inactive:
            stmt = stmt.where(AppUser.is_active)
        return list(self.db.scalars(stmt))

    def get(self, user_id: int) -> AppUser:
        user = self.db.get(AppUser, user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user

    def create(self, data: UserCreate, admin: CurrentUser) -> AppUser:
        if self.db.scalar(select(AppUser).where(AppUser.username == data.username)):
            raise ConflictError(f"User name '{data.username}' is already taken")
        user = AppUser(**data.model_dump(), is_active=True, created_by=admin.username)
        self.db.add(user)
        self.db.commit()
        return user

    def update(self, user_id: int, data: UserUpdate, admin: CurrentUser) -> AppUser:
        user = self.get(user_id)
        changes = data.model_dump(exclude_unset=True)
        losing_admin = user.role == Role.ADMIN and user.is_active and (
            changes.get("role", Role.ADMIN) != Role.ADMIN or changes.get("is_active") is False
        )
        if losing_admin:
            if user.username == admin.username:
                raise BusinessRuleError("You cannot remove your own administrator access")
            if self._active_admins() <= 1:
                raise BusinessRuleError("There must always be at least one active administrator")
        for key, value in changes.items():
            setattr(user, key, (value or None) if key in ("email", "team") else value)
        self.db.commit()
        return user

    def _active_admins(self) -> int:
        return self.db.scalar(select(func.count()).select_from(AppUser).where(AppUser.role == Role.ADMIN, AppUser.is_active))
