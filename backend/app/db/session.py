"""Engine and connectivity.

Synchronous SQLAlchemy: the worker is a synchronous job loop (specification §7.2) and the
pilot's volume does not justify an async stack in front of it. Sessions, the declarative
base, and migrations are added by T-006.
"""

import threading

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Fail fast rather than hanging a readiness probe on an unreachable host.
CONNECT_TIMEOUT_SECONDS = 5

# One pooled engine per URL. A plain dict keyed by URL (rather than lru_cache) so shutdown
# can iterate and dispose them. The lock matters because FastAPI runs synchronous endpoints
# in a threadpool, and two threads racing here would leak an undisposed pool.
_ENGINES: dict[str, Engine] = {}
_LOCK = threading.Lock()


def get_engine(database_url: str) -> Engine:
    engine = _ENGINES.get(database_url)
    if engine is not None:
        return engine

    with _LOCK:
        existing = _ENGINES.get(database_url)
        if existing is not None:
            return existing
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
        )
        _ENGINES[database_url] = engine
        return engine


def check_database(database_url: str) -> None:
    """Round-trip the database. Raises ``SQLAlchemyError`` if it is not usable."""
    engine = get_engine(database_url)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def dispose_engines() -> None:
    """Close every pooled connection. Called on application shutdown."""
    with _LOCK:
        while _ENGINES:
            _, engine = _ENGINES.popitem()
            engine.dispose()
