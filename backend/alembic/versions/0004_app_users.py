"""app users and roles

Revision ID: 4d1a7c2e9b10
Revises: bc3690a5ae99
Create Date: 2026-11-09 20:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4d1a7c2e9b10"
down_revision: Union[str, Sequence[str], None] = "bc3690a5ae99"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = ("VIEWER", "ENGINEER", "INCIDENT_MANAGER", "ADMIN")


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("role", sa.Enum(*ROLES, name="user_role", native_enum=False, create_constraint=True), nullable=False),
        sa.Column("team", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(100), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_app_users_username", "app_users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_app_users_username", table_name="app_users")
    op.drop_table("app_users")
