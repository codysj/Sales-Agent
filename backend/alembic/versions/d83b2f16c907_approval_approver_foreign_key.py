"""the approval's approver becomes a foreign key to app_user.email

Revision ID: d83b2f16c907
Revises: c41d7b90ae52
Created: 2026-08-01 06:20:00.000000

T-136c (§14.4, §12.2, §11.4, ADR-024). The last approver column outside `audit_event`, and the
only one with an HTTP surface: the review API writes `principal.user.email` into it and the
dashboard renders it.

Same shape as `c41d7b90ae52`, and the same refusal: an approval whose approver has no user row
stops the migration rather than being nulled. §12.2 requires attribution to be immutable, and an
approval nobody can attribute is worse than a migration that stops.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d83b2f16c907"
down_revision: str | None = "c41d7b90ae52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "approval"
COLUMN = "approver_id"
CONSTRAINT = "fk_approval_approver_id_app_user"


def unresolvable_approvers(connection: sa.engine.Connection) -> list[str]:
    """Approver values on `approval` with no `app_user` row.

    Takes the connection rather than calling `op.get_bind()` so a test can run it: the rows it
    looks for are exactly the rows the constraint below makes uninsertable, so the only way to
    reach the condition is to drop the constraint inside a transaction. `c41d7b90ae52` learned
    that the hard way — a control removing its pre-flight passed, because nothing covered it.
    """
    return sorted(
        connection.execute(
            sa.text(
                f"SELECT DISTINCT {COLUMN} FROM {TABLE} "
                f"WHERE {COLUMN} NOT IN (SELECT email FROM app_user)"
            )
        )
        .scalars()
        .all()
    )


def _refuse_unresolvable_approvers() -> None:
    orphaned = unresolvable_approvers(op.get_bind())
    if orphaned:
        raise RuntimeError(
            f"{TABLE}.{COLUMN} holds {len(orphaned)} value(s) with no app_user row: {orphaned}. "
            f"Create those users, or re-seed a local database — see T-136a. Nulling them would "
            f"delete attribution the specification requires to be immutable (§12.2)."
        )


def upgrade() -> None:
    _refuse_unresolvable_approvers()
    op.create_foreign_key(
        CONSTRAINT,
        TABLE,
        "app_user",
        [COLUMN],
        ["email"],
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="foreignkey")
