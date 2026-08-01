"""request research decision kind

Adds `REQUEST_RESEARCH` to `decisionkind` (ADR-022, T-153).

Hand-written: Alembic's autogenerate does not detect a new enum *value*, so it produced an empty
migration and the model would have drifted from the schema in silence.

The downgrade recreates the type rather than dropping the value, because PostgreSQL has no
`ALTER TYPE ... DROP VALUE`. It deletes any row holding the value first — the cast would fail
otherwise, and a decision recorded under a value the schema no longer has is not a row worth
carrying into a version that cannot express it.

Revision ID: 8752f60aa338
Revises: 6fee8153160a
Created: 2026-07-31 12:49:31.583387
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8752f60aa338"
down_revision: str | None = "6fee8153160a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `IF NOT EXISTS` so a partially applied upgrade is re-runnable, matching the `checkfirst`
    # habit the enum drops in `6fee8153160a` and `ba1a2b2420a4` already follow.
    op.execute("ALTER TYPE decisionkind ADD VALUE IF NOT EXISTS 'REQUEST_RESEARCH'")


#: The two `6fee8153160a` constraints that compare `kind` against a literal. Renaming the type
#: leaves them bound to the old one — `operator does not exist: decisionkind <> decisionkind_old` —
#: so they come off before the swap and go back after it, unchanged.
_KIND_CONSTRAINTS = (
    (
        "ck_candidate_decision_deferral_has_a_waypoint",
        "kind <> 'DEFER' OR defer_until_date IS NOT NULL OR "
        "(defer_until_event IS NOT NULL AND length(trim(defer_until_event)) > 0)",
    ),
    (
        "ck_candidate_decision_only_deferrals_wait",
        "kind = 'DEFER' OR (defer_until_date IS NULL AND defer_until_event IS NULL)",
    ),
)


def downgrade() -> None:
    op.execute("DELETE FROM candidate_decision WHERE kind = 'REQUEST_RESEARCH'")
    for name, _ in _KIND_CONSTRAINTS:
        op.execute(f"ALTER TABLE candidate_decision DROP CONSTRAINT {name}")

    op.execute("ALTER TYPE decisionkind RENAME TO decisionkind_old")
    sa.Enum("REJECT", "DEFER", name="decisionkind").create(op.get_bind())
    op.execute(
        "ALTER TABLE candidate_decision "
        "ALTER COLUMN kind TYPE decisionkind USING kind::text::decisionkind"
    )
    op.execute("DROP TYPE decisionkind_old")

    for name, expression in _KIND_CONSTRAINTS:
        op.execute(f"ALTER TABLE candidate_decision ADD CONSTRAINT {name} CHECK ({expression})")
