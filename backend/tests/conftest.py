"""Shared test fixtures.

Integration tests run against a **throwaway database created and migrated per test session**,
never ``metadata.create_all``. That is the point: if migrations and models disagree, the tests
must fail, and ``create_all`` would hide exactly that (specification §23).

Every database fixture skips cleanly when PostgreSQL is unreachable, so the offline suite stays
runnable without Docker.
"""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings

BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND / "alembic.ini"

SKIP_REASON = "PostgreSQL is not reachable — start it with `docker compose up -d db`"


def render_url(url: URL) -> str:
    """Render a URL **with** its password.

    ``str(URL)`` masks the password as ``***`` — good for logs, silently fatal for a connection
    string. Always go through here when a URL has to become text.
    """
    return url.render_as_string(hide_password=False)


def alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _server_reachable(url: str) -> bool:
    """Connect to the maintenance database, not the application one, which may not exist yet."""
    admin_url = make_url(url).set(database="postgres")
    try:
        engine = create_engine(admin_url, connect_args={"connect_timeout": 5})
        with engine.connect():
            pass
    except SQLAlchemyError:
        return False
    else:
        return True
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A freshly created, empty database for this session; dropped afterwards."""
    configured = get_settings().database_url
    if not _server_reachable(configured):
        pytest.skip(SKIP_REASON)

    name = f"test_{uuid4().hex[:12]}"
    admin = create_engine(
        make_url(configured).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))

    try:
        yield render_url(make_url(configured).set(database=name))
    finally:
        with admin.connect() as connection:
            # Terminate stragglers first; a leaked connection would block DROP and leave
            # abandoned databases behind on the developer's machine.
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    """The throwaway database with ``alembic upgrade head`` applied."""
    command.upgrade(alembic_config(database_url), "head")

    engine = create_engine(database_url, connect_args={"connect_timeout": 5})
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A session in a transaction that is always rolled back, so tests cannot leak state."""
    connection = migrated_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        # A test that provoked a database error (a constraint or an append-only trigger) leaves
        # the transaction already unwound; rolling it back again warns, and warnings are errors.
        if transaction.is_active:
            transaction.rollback()
        connection.close()
