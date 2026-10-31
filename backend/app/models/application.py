"""Module 1 foundation - banking applications and their dependencies."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, DataSourceMixin, TimestampMixin, str_enum
from app.models.enums import BusinessCriticality, DependencyType, HealthStatus


class Application(DataSourceMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("data_source", "external_id", name="uq_applications_source_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    business_service: Mapped[str | None] = mapped_column(String(120))
    business_criticality: Mapped[BusinessCriticality] = mapped_column(
        str_enum(BusinessCriticality, "business_criticality")
    )
    technology_stack: Mapped[str | None] = mapped_column(String(200))
    owner_team: Mapped[str | None] = mapped_column(String(100))
    health_status: Mapped[HealthStatus] = mapped_column(
        str_enum(HealthStatus, "health_status"), default=HealthStatus.UNKNOWN
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    dependencies: Mapped[list["ApplicationDependency"]] = relationship(
        foreign_keys="ApplicationDependency.application_id",
        back_populates="application",
        cascade="all, delete-orphan",
    )


class ApplicationDependency(Base):
    """`application` depends on `depends_on` (e.g. Payment Processing -> Core Banking)."""

    __tablename__ = "application_dependencies"
    __table_args__ = (
        UniqueConstraint("application_id", "depends_on_id", name="uq_application_dependencies_pair"),
        CheckConstraint("application_id <> depends_on_id", name="no_self_dependency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    dependency_type: Mapped[DependencyType] = mapped_column(str_enum(DependencyType, "dependency_type"))
    description: Mapped[str | None] = mapped_column(Text)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)

    application: Mapped[Application] = relationship(foreign_keys=[application_id], back_populates="dependencies")
    depends_on: Mapped[Application] = relationship(foreign_keys=[depends_on_id])
