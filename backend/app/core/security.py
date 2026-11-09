"""Basic, role-aware authentication for the MVP.

Demo mode (AUTH_ENABLED=false): the caller names themselves with X-User-Name. If that name belongs
to a user stored in app_users, the role comes from the database (X-User-Role is ignored) and a
deactivated user is refused. Names that are not stored (scripts, tests) still use X-User-Role but
can never claim ADMIN. With no header the caller is a demo incident manager. No passwords: this is
NOT production security.

API-key mode (AUTH_ENABLED=true): X-API-Key must match an entry in the API_KEYS setting.
"""

import secrets
from dataclasses import dataclass
from enum import StrEnum

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, PermissionDeniedError


class Role(StrEnum):
    VIEWER = "VIEWER"
    ENGINEER = "ENGINEER"
    INCIDENT_MANAGER = "INCIDENT_MANAGER"
    ADMIN = "ADMIN"


_ROLE_RANK = {Role.VIEWER: 0, Role.ENGINEER: 1, Role.INCIDENT_MANAGER: 2, Role.ADMIN: 3}

# Identities used by automated actors. The AI may record hypotheses and recommendations,
# but services refuse consequential actions (confirming root causes, closing incidents) for them.
AI_ACTOR_PREFIX = "ai:"


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: Role

    @property
    def is_ai(self) -> bool:
        return self.username.startswith(AI_ACTOR_PREFIX)

    def has_role(self, minimum: Role) -> bool:
        return _ROLE_RANK[self.role] >= _ROLE_RANK[minimum]


def get_current_user(
    x_api_key: str | None = Header(default=None),
    x_user_name: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    settings = get_settings()
    if settings.auth_enabled:
        if not x_api_key:
            raise AuthenticationError("X-API-Key header is required")
        for key, user in settings.api_keys.items():
            if secrets.compare_digest(key, x_api_key):
                return CurrentUser(username=user.username, role=Role(user.role))
        raise AuthenticationError("Invalid API key")

    username = (x_user_name or "demo.manager").strip()[:100]
    if username.startswith(AI_ACTOR_PREFIX):
        # AI identities are assigned internally by the agent runtime, never via headers.
        raise PermissionDeniedError("Reserved user name")
    from app.models.user import AppUser  # local import: the model module imports Role from here

    stored = db.scalar(select(AppUser).where(AppUser.username == username))
    if stored is not None:
        if not stored.is_active:
            raise PermissionDeniedError(f"User '{username}' is deactivated - ask an administrator")
        return CurrentUser(username=stored.username, role=stored.role)
    try:
        role = Role((x_user_role or Role.INCIDENT_MANAGER).upper())
    except ValueError as exc:
        raise AuthenticationError(f"Unknown role '{x_user_role}'") from exc
    if role == Role.ADMIN:
        raise PermissionDeniedError("Only a user stored by an administrator can be ADMIN")
    return CurrentUser(username=username, role=role)


def require_role(minimum: Role):
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(minimum):
            raise PermissionDeniedError(f"This action requires role {minimum} or higher")
        return user

    return dependency
