"""job retry disposition

Adds the §7.2 "requires human review" disposition and enforces §17.1's rule that a dead job always
carries a human-readable reason. Both check constraints are hand-written: Alembic's autogenerate
does not detect `CheckConstraint`, so a constraint added only to the model would silently never
reach the database.

Revision ID: 90aa0487c939
Revises: 63876c821f52
Created: 2026-07-29 14:19:40.855860
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "90aa0487c939"
down_revision: str | None = "63876c821f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job",
        sa.Column(
            "requires_human_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "dead_job_must_carry_a_reason",
        "job",
        "state <> 'DEAD' OR (last_error IS NOT NULL AND length(trim(last_error)) > 0)",
    )
    op.create_check_constraint(
        "human_review_is_a_terminal_disposition",
        "job",
        "NOT requires_human_review OR state = 'DEAD'",
    )


def downgrade() -> None:
    op.drop_constraint("human_review_is_a_terminal_disposition", "job", type_="check")
    op.drop_constraint("dead_job_must_carry_a_reason", "job", type_="check")
    op.drop_column("job", "requires_human_review")
