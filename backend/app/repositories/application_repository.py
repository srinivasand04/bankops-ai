from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Application, ApplicationDependency, ChangeRecord


class ApplicationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, application_id: int) -> Application | None:
        return self.db.get(Application, application_id)

    def list_all(self, active_only: bool = True) -> list[Application]:
        stmt = select(Application).order_by(Application.name)
        if active_only:
            stmt = stmt.where(Application.is_active.is_(True))
        return list(self.db.scalars(stmt))

    def get_with_dependencies(self, application_id: int) -> Application | None:
        stmt = (
            select(Application)
            .where(Application.id == application_id)
            .options(selectinload(Application.dependencies).joinedload(ApplicationDependency.depends_on))
        )
        return self.db.scalar(stmt)

    def dependents_of(self, application_id: int) -> list[Application]:
        """Applications that depend on the given one (i.e. the blast radius of its failure)."""
        stmt = (
            select(Application)
            .join(ApplicationDependency, ApplicationDependency.application_id == Application.id)
            .where(ApplicationDependency.depends_on_id == application_id)
            .order_by(Application.name)
        )
        return list(self.db.scalars(stmt))


class ChangeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, change_id: int) -> ChangeRecord | None:
        return self.db.get(ChangeRecord, change_id)

    def list_all(self, application_id: int | None = None, limit: int = 50) -> list[ChangeRecord]:
        stmt = select(ChangeRecord).order_by(ChangeRecord.deployed_at.desc().nulls_last()).limit(limit)
        if application_id:
            stmt = stmt.where(ChangeRecord.application_id == application_id)
        return list(self.db.scalars(stmt))
