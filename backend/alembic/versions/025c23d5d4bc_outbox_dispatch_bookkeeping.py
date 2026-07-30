"""outbox dispatch bookkeeping

Revision ID: 025c23d5d4bc
Revises: 4a4c4bf4623e
Created: 2026-07-29 17:00:28.571124
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "025c23d5d4bc"
down_revision: str | None = "4a4c4bf4623e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Hand-written: autogenerate does not detect a new *value* on an existing enum, only a new
    # enum. Without this the column accepts every state except the one §17.3 requires.
    # `ADD VALUE` is allowed inside a transaction on PostgreSQL 12+ provided the new value is not
    # used in the same transaction, which it is not here.
    op.execute("ALTER TYPE outboxstate ADD VALUE IF NOT EXISTS 'DELIVERY_UNKNOWN'")

    op.add_column(
        "outbox_event",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "outbox_event", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("outbox_event", sa.Column("leased_by", sa.String(length=255), nullable=True))
    op.add_column(
        "outbox_event", sa.Column("provider_correlation_id", sa.String(length=255), nullable=True)
    )
    op.add_column("outbox_event", sa.Column("last_outcome", sa.String(length=32), nullable=True))
    op.add_column("outbox_event", sa.Column("last_detail", sa.Text(), nullable=True))
    op.drop_index(
        op.f("ix_outbox_pending"),
        table_name="outbox_event",
        postgresql_where="(state = 'PENDING'::outboxstate)",
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_event",
        ["next_attempt_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("state = 'PENDING'"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # `DELIVERY_UNKNOWN` is deliberately left on the enum. PostgreSQL cannot drop a single value
    # from a type; removing it would mean recreating `outboxstate` and rewriting the column. An
    # unused extra value is harmless, and downgrading past `f09d40b96a8b` drops the type outright.
    op.drop_index(
        "ix_outbox_pending",
        table_name="outbox_event",
        postgresql_where=sa.text("state = 'PENDING'"),
    )
    op.create_index(
        op.f("ix_outbox_pending"),
        "outbox_event",
        ["created_at"],
        unique=False,
        postgresql_where="(state = 'PENDING'::outboxstate)",
    )
    op.drop_column("outbox_event", "last_detail")
    op.drop_column("outbox_event", "last_outcome")
    op.drop_column("outbox_event", "provider_correlation_id")
    op.drop_column("outbox_event", "leased_by")
    op.drop_column("outbox_event", "lease_expires_at")
    op.drop_column("outbox_event", "next_attempt_at")
    # ### end Alembic commands ###
