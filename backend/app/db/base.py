"""Declarative base and shared column mixins.

Migrations are the machine-readable source of truth for the schema (specification §23), so
every table defined against this base must arrive through an Alembic revision — never through
``metadata.create_all``.

This module deliberately imports no domain module: `core` and `db` are foundation
(``tests/test_module_boundaries.py``). Alembic's autogenerate needs to *see* every model, but
that aggregation lives in ``alembic/env.py``, outside the ``app`` package, so the boundary holds.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint and index names. Without this, PostgreSQL invents names, autogenerate
# produces unstable diffs, and a downgrade cannot reliably drop what an upgrade created.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Row creation and last-modification times, stamped by the database.

    ``server_default``/``onupdate`` at the database level rather than in Python: the worker, the
    API, and migrations all write rows, and a clock that depends on which process wrote would
    undermine the audit trail (§17.5).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
