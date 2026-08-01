"""The Stage 1 network guard (T-058a; §19.6 "no external writes").

Its own module rather than a `conftest.py` body for one boring but load-bearing reason: pytest
imports `conftest.py` as the top-level module `conftest`, so a test doing
`from tests.conftest import NetworkUsed` gets a *second* class object with the same name, and
`pytest.raises` against it never matches what the fixture actually raised. Living here, the
exception has one identity for everybody.

The guard patches `socket.socket.connect`, not an HTTP client. The guarantee Stage 1 needs is
"no external effect by any means", and a guard that knew about `httpx` would say nothing about
`smtplib`, a raw socket, or a provider SDK that vendors its own transport. Everything above them
eventually calls `connect`.
"""

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.engine.url import make_url


class NetworkUsed(AssertionError):
    """A socket was opened to something other than the test database.

    An `AssertionError` on purpose: a Stage 1 test that reaches the network has not failed to
    connect, it has violated the stage's defining constraint, and it should read as a failed
    assertion rather than as a flaky environment.
    """


def permitted_addresses(database_url: str) -> set[tuple[str, int]]:
    """Host/port pairs the guard allows: the test database, and nothing else.

    Both the configured hostname and its resolved addresses are permitted, because a driver may
    connect to either depending on how it resolves ``localhost``.
    """
    url = make_url(database_url)
    host = url.host or "localhost"
    port = url.port or 5432

    allowed = {(host, port)}
    try:
        for *_, address in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
            allowed.add((address[0], address[1]))
    except OSError:  # pragma: no cover - resolution failure is the database fixture's problem
        pass
    return allowed


@contextmanager
def guarded(allowed: set[tuple[str, int]]) -> Iterator[None]:
    """Refuse every connection to an address outside ``allowed`` for the duration.

    A non-INET address (a Unix socket, say) has no inspectable host/port, so it is refused
    outright: no Stage 1 code path has a reason to open one, and permitting an address family
    the guard cannot read would be a hole rather than a convenience.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection

    def check(address: Any) -> None:
        pair = (address[0], address[1]) if isinstance(address, tuple) else (str(address), -1)
        if pair not in allowed:
            raise NetworkUsed(
                f"Stage 1 opened a socket to {pair}; the shadow slice must reach nothing but "
                f"the database (§19.6: 'no external writes')"
            )

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        check(address)
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        check(address)
        return real_connect_ex(self, address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        check(address)
        return real_create_connection(address, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.create_connection = real_create_connection  # type: ignore[assignment]
