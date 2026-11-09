"""ml model runs, predictions and incident text vectors (pgvector)

Revision ID: 5e2b8d3f1a20
Revises: 4d1a7c2e9b10
Create Date: 2026-11-09 21:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5e2b8d3f1a20"
down_revision: Union[str, Sequence[str], None] = "4d1a7c2e9b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VECTOR_DIM = 64


def upgrade() -> None:
    ts = dict(server_default=sa.func.now(), nullable=False)
    op.create_table(
        "ml_model_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task", sa.String(40), nullable=False),
        sa.Column("algorithm", sa.String(60), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("train_from", sa.DateTime(timezone=True)),
        sa.Column("train_to", sa.DateTime(timezone=True)),
        sa.Column("test_from", sa.DateTime(timezone=True)),
        sa.Column("test_to", sa.DateTime(timezone=True)),
        sa.Column("n_train", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_test", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data_source", sa.String(30), nullable=False, server_default="ALL"),
        sa.Column("artifact", sa.String(300)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trained_by", sa.String(100), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts),
    )
    op.create_index("ix_ml_model_runs_task", "ml_model_runs", ["task"])
    op.create_index("ix_ml_model_runs_is_active", "ml_model_runs", ["is_active"])
    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("ml_model_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("prediction", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("explanation", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts),
    )
    op.create_index("ix_ml_predictions_model_run_id", "ml_predictions", ["model_run_id"])
    op.create_index("ix_ml_predictions_entity_id", "ml_predictions", ["entity_id"])
    # Incident text embeddings for nearest-neighbour search (similar incidents)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"CREATE TABLE ml_incident_vectors ("
        f" incident_id integer PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,"
        f" embedding vector({VECTOR_DIM}) NOT NULL,"
        f" model_run_id integer REFERENCES ml_model_runs(id) ON DELETE SET NULL)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_incident_vectors")
    op.drop_table("ml_predictions")
    op.drop_table("ml_model_runs")
