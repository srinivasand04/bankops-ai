"""business calendar periods and incident priority reason

Revision ID: 6a7f3c1e8d42
Revises: 5e2b8d3f1a20
Create Date: 2026-11-11 10:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6a7f3c1e8d42"
down_revision: Union[str, Sequence[str], None] = "5e2b8d3f1a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERIOD_TYPES = (
    "MONTH_END_CLOSE", "QUARTER_END_CLOSE", "YEAR_END_CLOSE", "PAYROLL",
    "REGULATORY_DEADLINE", "PEAK_PERIOD", "BANK_HOLIDAY",
)


def upgrade() -> None:
    ts = dict(server_default=sa.func.now(), nullable=False)
    op.create_table(
        "business_calendar_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "period_type",
            sa.Enum(*PERIOD_TYPES, name="calendar_period_type", native_enum=False, create_constraint=True, length=40),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("application_codes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("raises_priority", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("description", sa.Text()),
        sa.Column("created_by", sa.String(100), nullable=False, server_default="system"),
        sa.Column("data_source", sa.String(30), nullable=False, server_default="MANUAL"),
        sa.Column("external_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts),
        sa.CheckConstraint("ends_at > starts_at", name="ck_business_calendar_periods_period_not_empty"),
    )
    op.create_index("ix_business_calendar_periods_window", "business_calendar_periods", ["starts_at", "ends_at"])
    op.create_index("ix_business_calendar_periods_data_source", "business_calendar_periods", ["data_source"])
    op.add_column("incidents", sa.Column("priority_reason", sa.Text()))


def downgrade() -> None:
    op.drop_column("incidents", "priority_reason")
    op.drop_index("ix_business_calendar_periods_data_source", table_name="business_calendar_periods")
    op.drop_index("ix_business_calendar_periods_window", table_name="business_calendar_periods")
    op.drop_table("business_calendar_periods")
