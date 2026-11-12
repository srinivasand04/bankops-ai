"""Module 2 - IT Incident Intelligence."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.application import Application
from app.models.base import Base, DataSourceMixin, JsonType, TimestampMixin, str_enum
from app.models.change import ChangeRecord
from app.models.enums import (
    ActionStatus,
    ActionType,
    ChangeLinkStatus,
    EventType,
    IncidentCategory,
    IncidentStatus,
    Priority,
    RcaStatus,
    RootCauseStatus,
    Severity,
    Source,
)

# Drives INC-1001, INC-1002, ... (concurrency-safe, unlike MAX()+1)
incident_reference_seq = Sequence("incident_reference_seq", start=1001, metadata=Base.metadata)


class Incident(DataSourceMixin, TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("data_source", "external_id", name="uq_incidents_source_external_id"),
        Index("ix_incidents_status_severity", "status", "severity"),
        Index("ix_incidents_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_number: Mapped[str] = mapped_column(String(20), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    severity: Mapped[Severity] = mapped_column(str_enum(Severity, "severity"))
    priority: Mapped[Priority] = mapped_column(str_enum(Priority, "priority"))
    # Why the priority is what it is (tier and business-calendar adjustments, or who set it manually)
    priority_reason: Mapped[str | None] = mapped_column(Text)
    category: Mapped[IncidentCategory] = mapped_column(str_enum(IncidentCategory, "incident_category"), index=True)
    status: Mapped[IncidentStatus] = mapped_column(
        str_enum(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN
    )
    assigned_team: Mapped[str | None] = mapped_column(String(100), index=True)
    assigned_engineer: Mapped[str | None] = mapped_column(String(100))
    business_impact: Mapped[str | None] = mapped_column(Text)
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(100))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # when business impact began
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship(lazy="joined")
    sla: Mapped["IncidentSla | None"] = relationship(
        back_populates="incident", cascade="all, delete-orphan", uselist=False, lazy="joined"
    )
    events: Mapped[list["IncidentEvent"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="[IncidentEvent.created_at, IncidentEvent.id]",
    )
    root_causes: Mapped[list["IncidentRootCause"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="IncidentRootCause.id"
    )
    actions: Mapped[list["IncidentAction"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="IncidentAction.id"
    )
    related_changes: Mapped[list["IncidentRelatedChange"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="IncidentRelatedChange.id"
    )
    rca: Mapped["IncidentRca | None"] = relationship(
        back_populates="incident", cascade="all, delete-orphan", uselist=False
    )


class IncidentEvent(Base):
    """Append-only audit timeline. Rows are never updated or deleted by the application."""

    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_created", "incident_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    event_type: Mapped[EventType] = mapped_column(str_enum(EventType, "event_type"))
    description: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JsonType)
    source: Mapped[Source] = mapped_column(str_enum(Source, "event_source"), default=Source.HUMAN)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    incident: Mapped[Incident] = relationship(back_populates="events")


class IncidentSla(TimestampMixin, Base):
    """SLA targets snapshotted at creation / severity change, plus outcome flags."""

    __tablename__ = "incident_sla"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), unique=True)
    severity: Mapped[Severity] = mapped_column(str_enum(Severity, "sla_severity"))
    clock_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response_target_minutes: Mapped[int] = mapped_column(Integer)
    resolution_target_minutes: Mapped[int] = mapped_column(Integer)
    response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # NULL while the outcome is still open; set when acknowledged / resolved or once the deadline passes
    response_breached: Mapped[bool | None] = mapped_column(Boolean)
    resolution_breached: Mapped[bool | None] = mapped_column(Boolean)

    incident: Mapped[Incident] = relationship(back_populates="sla")


class IncidentRootCause(TimestampMixin, Base):
    """Root cause candidates. AI-sourced rows start as HYPOTHESIS and only a human can confirm them."""

    __tablename__ = "incident_root_causes"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        CheckConstraint(
            "status <> 'CONFIRMED' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="confirmed_requires_reviewer",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[IncidentCategory | None] = mapped_column(str_enum(IncidentCategory, "root_cause_category"))
    status: Mapped[RootCauseStatus] = mapped_column(
        str_enum(RootCauseStatus, "root_cause_status"), default=RootCauseStatus.HYPOTHESIS
    )
    source: Mapped[Source] = mapped_column(str_enum(Source, "root_cause_source"))
    confidence: Mapped[float | None] = mapped_column(Float)
    supporting_evidence: Mapped[list[str]] = mapped_column(JsonType, default=list)
    missing_evidence: Mapped[list[str]] = mapped_column(JsonType, default=list)
    created_by: Mapped[str] = mapped_column(String(100))
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)

    incident: Mapped[Incident] = relationship(back_populates="root_causes")


class IncidentRca(TimestampMixin, Base):
    """Structured RCA document (one per incident). Root causes and CAPA live in their own tables."""

    __tablename__ = "incident_rca"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), unique=True)
    summary: Mapped[str | None] = mapped_column(Text)
    confirmed_facts: Mapped[list[str]] = mapped_column(JsonType, default=list)
    contributing_factors: Mapped[list[str]] = mapped_column(JsonType, default=list)
    missing_evidence: Mapped[list[str]] = mapped_column(JsonType, default=list)
    business_impact: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RcaStatus] = mapped_column(str_enum(RcaStatus, "rca_status"), default=RcaStatus.DRAFT)
    updated_by: Mapped[str] = mapped_column(String(100))
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    incident: Mapped[Incident] = relationship(back_populates="rca")


class IncidentAction(TimestampMixin, Base):
    """Corrective and Preventive Actions (CAPA)."""

    __tablename__ = "incident_actions"
    __table_args__ = (Index("ix_incident_actions_status_due", "status", "due_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[ActionType] = mapped_column(str_enum(ActionType, "action_type"))
    description: Mapped[str] = mapped_column(Text)
    assigned_team: Mapped[str | None] = mapped_column(String(100))
    assigned_owner: Mapped[str | None] = mapped_column(String(100))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ActionStatus] = mapped_column(str_enum(ActionStatus, "action_status"), default=ActionStatus.OPEN)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[Source] = mapped_column(str_enum(Source, "action_source"), default=Source.HUMAN)
    created_by: Mapped[str] = mapped_column(String(100))

    incident: Mapped[Incident] = relationship(back_populates="actions")


class IncidentRelatedChange(Base):
    __tablename__ = "incident_related_changes"
    __table_args__ = (UniqueConstraint("incident_id", "change_id", name="uq_incident_related_changes_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_records.id"), index=True)
    link_status: Mapped[ChangeLinkStatus] = mapped_column(
        str_enum(ChangeLinkStatus, "change_link_status"), default=ChangeLinkStatus.SUSPECTED
    )
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[Source] = mapped_column(str_enum(Source, "change_link_source"), default=Source.HUMAN)
    identified_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    incident: Mapped[Incident] = relationship(back_populates="related_changes")
    change: Mapped[ChangeRecord] = relationship(lazy="joined")
