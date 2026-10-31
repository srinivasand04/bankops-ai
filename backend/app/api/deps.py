from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser, Role, get_current_user, require_role

DbSession = Annotated[Session, Depends(get_db)]
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
Engineer = Annotated[CurrentUser, Depends(require_role(Role.ENGINEER))]
Manager = Annotated[CurrentUser, Depends(require_role(Role.INCIDENT_MANAGER))]
