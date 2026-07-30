"""initial empty baseline

Revision ID: 3c526b2ea3ca
Revises:
Created: 2026-07-29 03:52:36.209407
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "3c526b2ea3ca"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
