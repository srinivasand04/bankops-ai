from datetime import datetime

from app.models.enums import BusinessCriticality, ChangeStatus, ChangeType, DependencyType, HealthStatus, RiskLevel
from app.schemas.common import OrmModel


class ApplicationRef(OrmModel):
    id: int
    code: str
    name: str
    business_criticality: BusinessCriticality


class ApplicationOut(ApplicationRef):
    description: str | None
    business_service: str | None
    technology_stack: str | None
    owner_team: str | None
    health_status: HealthStatus
    last_health_check_at: datetime | None
    is_active: bool
    data_source: str


class DependencyOut(OrmModel):
    id: int
    depends_on: ApplicationRef
    dependency_type: DependencyType
    description: str | None
    is_critical: bool


class ApplicationDetailOut(ApplicationOut):
    dependencies: list[DependencyOut]
    dependents: list[ApplicationRef]


class ChangeRecordOut(OrmModel):
    id: int
    change_reference: str
    application: ApplicationRef
    title: str
    description: str | None
    change_type: ChangeType
    status: ChangeStatus
    risk_level: RiskLevel
    version: str | None
    implementer: str | None
    approver: str | None
    rollback_plan: str | None
    planned_start: datetime | None
    deployed_at: datetime | None
    data_source: str
