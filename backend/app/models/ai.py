"""Agentic AI persistence (populated from Phase 4/5)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JsonType, TimestampMixin, str_enum
from app.models.enums import AgentExecutionStatus, InvestigationStatus


class InvestigationReport(TimestampMixin, Base):
    __tablename__ = "investigation_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), index=True)
    request_text: Mapped[str] = mapped_column(Text)
    status: Mapped[InvestigationStatus] = mapped_column(
        str_enum(InvestigationStatus, "investigation_status"), default=InvestigationStatus.PENDING, index=True
    )
    agents_selected: Mapped[list[str]] = mapped_column(JsonType, default=list)
    report: Mapped[dict | None] = mapped_column(JsonType)  # validated structured output
    model_name: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(100))
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    executions: Mapped[list["AgentExecution"]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", order_by="AgentExecution.step_order"
    )


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(
        ForeignKey("investigation_reports.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(60))
    step_order: Mapped[int] = mapped_column(Integer)
    status: Mapped[AgentExecutionStatus] = mapped_column(str_enum(AgentExecutionStatus, "agent_execution_status"))
    tool_calls: Mapped[list[dict]] = mapped_column(JsonType, default=list)
    output: Mapped[dict | None] = mapped_column(JsonType)
    error_message: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    investigation: Mapped[InvestigationReport] = relationship(back_populates="executions")
