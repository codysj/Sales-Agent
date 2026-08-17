"""a reviewer may refuse a revision's wording

Two nullable columns and two check constraints (T-208; §10.6, §12.3 item 7, §8.2).

Refusing wording is `review_pending -> invalidated`, an edge §8.2 already has. What it did not
have was anywhere to record *why*, so a reviewer who judged the words unsendable had to either
approve them or write replacement copy. The reason lives on the revision because it is a fact
about that exact text; the constraints keep it from outliving the decision it describes.

Nullable, so the migration needs no backfill: every existing revision is one nobody refused.

Revision ID: 5b7fafd9744d
Revises: a17e5c4b8d20
Created: 2026-08-14 17:45:14.526126
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b7fafd9744d"
down_revision: str | None = "a17e5c4b8d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "message_revision", sa.Column("refusal_reason", sa.String(length=50), nullable=True)
    )
    op.add_column("message_revision", sa.Column("refusal_notes", sa.Text(), nullable=True))
    op.create_check_constraint(
        "refusal_reason_needs_an_invalidated_revision",
        "message_revision",
        "refusal_reason IS NULL OR state = 'INVALIDATED'",
    )
    op.create_check_constraint(
        "refusal_notes_need_a_reason",
        "message_revision",
        "refusal_notes IS NULL OR refusal_reason IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("refusal_notes_need_a_reason", "message_revision", type_="check")
    op.drop_constraint(
        "refusal_reason_needs_an_invalidated_revision", "message_revision", type_="check"
    )
    op.drop_column("message_revision", "refusal_notes")
    op.drop_column("message_revision", "refusal_reason")
