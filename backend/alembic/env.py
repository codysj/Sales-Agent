"""Alembic environment.

Lives outside the ``app`` package on purpose. Autogenerate must import every model module so
``Base.metadata`` is complete, but ``app/db`` is foundation and may not import domain modules
(``tests/test_module_boundaries.py``). Doing the aggregation here keeps both true.

**When you add a model, import its module in `_load_all_models` below.** A model that is never
imported is invisible to `alembic check` and will silently drift from the database.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.settings import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _load_all_models() -> None:
    """Import every module that defines a table, for autogenerate and `alembic check`.

    Imports are for their side effect of registering mappers on ``Base.metadata``.
    """
    from app.audit_and_operations import flags as _flag_models  # noqa: F401
    from app.audit_and_operations import models as _audit_models  # noqa: F401
    from app.audit_and_operations import versioning as _versioning_models  # noqa: F401
    from app.campaigns import candidate as _candidate_models  # noqa: F401
    from app.campaigns import decisions as _decision_models  # noqa: F401
    from app.campaigns import models as _campaign_models  # noqa: F401
    from app.drafts_and_approvals import approval as _approval_models  # noqa: F401
    from app.drafts_and_approvals import models as _draft_models  # noqa: F401
    from app.identity import models as _identity_models  # noqa: F401
    from app.identity import sessions as _session_models  # noqa: F401
    from app.jobs_and_outbox import models as _job_models  # noqa: F401
    from app.jobs_and_outbox import outbox as _outbox_models  # noqa: F401
    from app.model_gateway import models as _model_run_models  # noqa: F401
    from app.outreach_and_replies import models as _outreach_models  # noqa: F401
    from app.outreach_and_replies import webhooks as _webhook_models  # noqa: F401
    from app.products_and_claims import claim_models as _claim_models  # noqa: F401
    from app.products_and_claims import models as _product_models  # noqa: F401
    from app.prospects import imports as _import_models  # noqa: F401
    from app.prospects import models as _prospect_models  # noqa: F401
    from app.prospects import suppression as _suppression_models  # noqa: F401
    from app.qualification import models as _qualification_models  # noqa: F401
    from app.research_and_evidence import models as _evidence_models  # noqa: F401


_load_all_models()

target_metadata = Base.metadata


def _database_url() -> str:
    """Test harnesses set ``sqlalchemy.url`` per throwaway database; otherwise use settings."""
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Catch type and default drift, not just added/dropped tables.
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
