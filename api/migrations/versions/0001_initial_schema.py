"""initial schema: pools, loans, rate curves, runs

Revision ID: 0001
Revises:
Create Date: 2026-10-21 18:55:51.302535
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pools",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("pass_through_rate", sa.Float(), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("wac", sa.Float(), nullable=False),
        sa.Column("wam", sa.Integer(), nullable=False),
        sa.Column("wala", sa.Integer(), nullable=False),
        sa.Column("loan_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "rate_curves",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "as_of"),
    )
    op.create_table(
        "loans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pool_id", sa.Integer(), nullable=False),
        sa.Column("loan_id", sa.String(length=64), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("note_rate", sa.Float(), nullable=False),
        sa.Column("remaining_term", sa.Integer(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["pool_id"], ["pools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pool_id", "loan_id"),
    )
    with op.batch_alter_table("loans", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_loans_pool_id"), ["pool_id"], unique=False)

    op.create_table(
        "rate_curve_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("curve_id", sa.Integer(), nullable=False),
        sa.Column("tenor_years", sa.Float(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["curve_id"], ["rate_curves.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("curve_id", "tenor_years"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pool_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("curve_id", sa.Integer(), nullable=True),
        sa.Column("prepay_model", sa.String(length=8), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("library_version", sa.String(length=16), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("yield", sa.Float(), nullable=False),
        sa.Column("wal", sa.Float(), nullable=False),
        sa.Column("modified_duration", sa.Float(), nullable=False),
        sa.Column("convexity", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["curve_id"], ["rate_curves.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pool_id"], ["pools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_runs_as_of"), ["as_of"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_pool_id"), ["pool_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_pool_id"))
        batch_op.drop_index(batch_op.f("ix_runs_as_of"))

    op.drop_table("runs")
    op.drop_table("rate_curve_points")
    with op.batch_alter_table("loans", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_loans_pool_id"))

    op.drop_table("loans")
    op.drop_table("rate_curves")
    op.drop_table("pools")
