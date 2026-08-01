"""The local development sign-in stub (T-061a; §12.2, §15.1).

A developer needs a session to open the dashboard, and `Q-026` has named no identity provider —
nobody has decided which business IdP or roster backs OIDC, and choosing one here would be
committing Matrix Power to a vendor. So this issues a session for a named local user, and does it
in the one environment where that is not a security hole.

**Refused anywhere but `local`, and that is the whole point of the file.** The check is at the
top of `stub_sign_in`, before any lookup, and `ALLOWED_ENVIRONMENTS` is a frozen allow-list
rather than a `!= production` test — a new environment is refused until someone decides
otherwise, which is the direction that fails safely. `AppEnv.TEST` is *not* on the list: the
tests that exercise this pass an explicit `Settings(app_env=AppEnv.LOCAL)`, so a test cannot
accidentally establish that the stub works in an environment it must not.

**It authenticates nothing.** There is no password to check and no proof to verify (§12.2). It
takes an email, finds that user, and issues a session — which is exactly why it must never run
outside a developer's machine, and why `UserSession.issued_via` records `stub` so an auditor can
tell a development session from a real one at a glance.

**It creates nobody.** An unknown email is refused rather than auto-provisioned. Auto-creating a
user would mean the roster grew by whoever typed something, and `Q-005`/`Q-026` leave the real
roster undecided; `T-061b` will refuse an unknown provider subject for the same reason.
"""

from datetime import datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.settings import AppEnv, Settings, get_settings
from app.identity.models import User
from app.identity.sessions import DEFAULT_SESSION_TTL, IssuedSession, issue_session

log = structlog.get_logger(__name__)

#: Recorded on every session this file issues.
ISSUED_VIA: Final = "stub"

#: Environments the stub may run in. An allow-list, not a denial of `production`: the day a
#: `preview` or `demo` environment appears, it is refused until someone decides otherwise.
#: `TEST` is deliberately absent — see the module docstring.
ALLOWED_ENVIRONMENTS: Final = frozenset({AppEnv.LOCAL})


class StubRefused(Exception):
    """The stub was used where it must not be."""


class UnknownStubUser(StubRefused):
    """No such user. The stub signs people in; it does not create them."""


def require_stub_allowed(settings: Settings) -> None:
    """Raise unless this environment permits the stub.

    Separate from `stub_sign_in` so the refusal can be asserted on its own, and so a future
    caller that needs to *ask* rather than *do* has something to call.
    """
    if settings.app_env not in ALLOWED_ENVIRONMENTS:
        raise StubRefused(
            f"the development sign-in stub is refused in {settings.app_env.value}; it verifies "
            f"nothing and exists only for local development. A real session needs the managed "
            f"provider (`T-061b`), which is blocked on `Q-026`."
        )


def stub_sign_in(
    session: DbSession,
    email: str,
    *,
    settings: Settings | None = None,
    at: datetime | None = None,
    ttl: timedelta = DEFAULT_SESSION_TTL,
) -> IssuedSession:
    """Issue a session for an existing local user. Adds to ``session`` without committing.

    Raises :class:`StubRefused` **before touching the database** outside a permitted environment,
    and :class:`UnknownStubUser` for an email nobody holds.
    """
    active = settings or get_settings()
    require_stub_allowed(active)

    # Lowercase to match `ck_app_user_email_lowercase`: a developer typing their address with a
    # capital should get their session, not a confusing "no such user".
    normalized = email.strip().lower()
    user = session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()
    if user is None:
        raise UnknownStubUser(
            f"no user with email {normalized!r}; the stub signs in an existing user and never "
            f"creates one — the roster is `Q-005` and `Q-026`, not this file"
        )

    log.warning(
        "session.stub_sign_in",
        # A warning, not info: a session that verified nothing should be visible in a log an
        # operator skims, even though it can only happen locally.
        user_id=str(user.id),
        app_env=active.app_env.value,
    )
    return issue_session(session, user, issued_via=ISSUED_VIA, at=at, ttl=ttl)
