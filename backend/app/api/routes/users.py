"""Users and roles. Anyone signed in can see who uses the tool; only an ADMIN can change it."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AnyUser, DbSession
from app.core.security import CurrentUser, Role, require_role
from app.services.user_service import UserCreate, UserOut, UserService, UserUpdate

router = APIRouter(prefix="/api/users", tags=["Users"])

Admin = Annotated[CurrentUser, Depends(require_role(Role.ADMIN))]


@router.get("", response_model=list[UserOut])
def list_users(db: DbSession, _: AnyUser, include_inactive: bool = True):
    """Users of the tool (the 'Acting as' picker uses active ones)."""
    return UserService(db).list(include_inactive)


@router.get("/me")
def who_am_i(user: AnyUser):
    """The identity and role the API is using for this request."""
    return {"username": user.username, "role": user.role}


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession, admin: Admin):
    return UserService(db).create(payload, admin)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: DbSession, admin: Admin):
    """Change name, e-mail, team or role, or (de)activate. Admins cannot lock themselves out."""
    return UserService(db).update(user_id, payload, admin)
