"""a contact records the import batch it came from

Revision ID: a17e5c4b8d20
Revises: d83b2f16c907
Created: 2026-08-01 07:40:00.000000

T-144a (§9.3, §10.1 stage 1, §14.2). Adds `contact.source_import_batch_id`, the provenance link
`T-144b`'s approved-source-basis rule reads.

**Nullable, and it stays nullable.** Contacts that predate this column have no batch to name, and
backfilling one would be a provenance claim nobody checked — which is precisely what the rule
exists to refuse. `T-144b` decides what a missing basis means for eligibility (it fails closed);
this migration only makes the fact recordable.

`RESTRICT` rather than `CASCADE`: deleting the batch that explains where a person came from must
not silently delete the explanation, and must not take the person with it either.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a17e5c4b8d20"
down_revision: str | None = "d83b2f16c907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "fk_contact_source_import_batch_id_import_batch"
INDEX = "ix_contact_source_import_batch_id"


def upgrade() -> None:
    op.add_column("contact", sa.Column("source_import_batch_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        CONSTRAINT,
        "contact",
        "import_batch",
        ["source_import_batch_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # `T-144b` reads this per candidate during qualification, so the lookup has to be cheap.
    op.create_index(INDEX, "contact", ["source_import_batch_id"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="contact")
    op.drop_constraint(CONSTRAINT, "contact", type_="foreignkey")
    op.drop_column("contact", "source_import_batch_id")
