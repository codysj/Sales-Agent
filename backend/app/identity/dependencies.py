"""Turning an HTTP request into an authorized principal (T-063a; §12.2, §15.1).

`T-061a` built sessions and `T-062` built the permission matrix; this is the piece that connects
them to a request, and it was deliberately left until there was an endpoint to depend on it.

**Every authenticated route asks for a permission, not for "a user".** `requires(permission)`
returns a dependency that resolves the session *and* authorizes it, so there is no shape in which
a route obtains a `Principal` and then forgets to check what they may do. `T-062`'s coverage test
catches a route that declared nothing; this makes the declared answer the thing the route
actually runs on.

**The token comes from a cookie or a bearer header, and nothing else.** A query parameter would
put session tokens in access logs, browser history, and any `Referer` a page leaked — which is
why it is not read from one here, and why `tests/test_review_api.py` asserts a token in the query
string does not authenticate.

**A mutation authenticated by cookie must carry a CSRF token (`T-070a`).** A CSRF attack works
because a browser attaches a cookie by itself; a bearer token it never sends unprompted. Until
`T-070a` the answer was to refuse cookie authentication outright on state-changing routes —
exposure removed rather than mitigated, and honest about being temporary. `requires_mutation` is
that relaxation, made deliberately: a bearer caller passes as before, and a cookie caller passes
only by echoing the CSRF token in a header, which an attacker on another origin cannot read.

The dashboard is unchanged by this and still mutates with a bearer token. That is the point of
accepting *either*: the relaxation adds a way in for a cookie client without moving the existing
one, so nothing already built has to be re-proved at the same time as the new path.

**Failures are two different answers.** No usable session is `401` — sign in. A usable session
without the role is `403` — signing in again will not help. Collapsing them would send a reviewer
round a login loop that could never succeed. Neither response says which of "unknown token",
"expired", or "revoked" applied, because `resolve` deliberately cannot tell them apart.
"""

from collections.abc import Callable, Iterator
from typing import Annotated, Final

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import CSRF_HEADER, csrf_token_matches
from app.core.settings import Settings, get_settings
from app.db.session import get_engine
from app.identity.rbac import Forbidden, NotAuthenticated, Permission, authorize
from app.identity.sessions import Principal, resolve

#: The cookie a browser session arrives in. `__Host-` is not used yet because the dashboard runs
#: over plain HTTP locally; adding it belongs with the deployment task that gives the API a
#: certificate, not here where it would break local development for no gain.
SESSION_COOKIE: Final = "mp_session"

#: The scheme a non-browser caller uses. One word, matched case-insensitively.
BEARER_PREFIX: Final = "bearer "


def db_session(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[Session]:
    """A database session for one request, rolled back unless the endpoint commits.

    Read endpoints never commit, so the rollback is the normal path and a handler that forgot to
    commit a write fails visibly rather than half-succeeding.
    """
    engine = get_engine(settings.database_url)
    with Session(engine) as session:
        try:
            yield session
        finally:
            session.rollback()


def bearer_token(authorization: str | None) -> str | None:
    """The token from an `Authorization: Bearer …` header, or `None`."""
    if authorization is None:
        return None
    if not authorization.lower().startswith(BEARER_PREFIX):
        return None
    token = authorization[len(BEARER_PREFIX) :].strip()
    return token or None


def current_principal(
    session: Annotated[Session, Depends(db_session)],
    mp_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal | None:
    """Who this request is, or `None`.

    **The bearer header wins over the cookie**, and `T-070a` is when that started to matter: once
    sign-in issues a cookie, every browser caller has both, and a script sending an explicit
    `Authorization` header would otherwise be answered as whoever the ambient cookie belongs to.
    The explicit credential is the one the caller chose; the cookie is the one the browser
    attached by itself. Found by `T-151a`'s sign-out test, which revoked the wrong session the
    moment cookies existed.

    This does not weaken CSRF: an attacker on another origin cannot make a browser send an
    `Authorization` header, which is exactly why `requires_mutation` lets a bearer caller skip the
    token check. Deliberately no query parameter — see the module docstring.
    """
    token = bearer_token(authorization) or mp_session
    if token is None:
        return None
    return resolve(session, token)


PrincipalDep = Annotated[Principal | None, Depends(current_principal)]

#: Attribute naming the permission a dependency actually enforces (`T-162`).
#:
#: `ROUTE_PERMISSIONS` says what a route *declares*; this says what its code *runs*. They were two
#: independent statements until now: a negative control on `T-069a` changed the table to the
#: permission every role holds and every role was still refused, because the handler names its own
#: permission in its signature and nothing compared the two. `tests/test_authz.py` now walks the
#: real dependency tree and reads this — so a marker is not decoration, it is the only way the
#: enforced answer is observable from outside the closure.
ENFORCED_PERMISSION_ATTR: Final = "enforced_permission"


def _marked[F: Callable[..., Principal]](dependency: F, permission: Permission) -> F:
    """Tag a dependency with the permission it enforces, and hand it back unchanged."""
    setattr(dependency, ENFORCED_PERMISSION_ATTR, permission)
    return dependency


def enforced_permission(call: object) -> Permission | None:
    """The permission ``call`` enforces, or `None` if it enforces none.

    Read through a function rather than by touching the attribute directly, so a test cannot
    disagree with the producer about the name — and so "this dependency authorizes nothing"
    is an answer rather than an `AttributeError`.
    """
    found = getattr(call, ENFORCED_PERMISSION_ATTR, None)
    return found if isinstance(found, Permission) else None


def requires(permission: Permission) -> Callable[[Principal | None], Principal]:
    """A dependency that resolves the caller and authorizes them for ``permission``.

    Returns the `Principal` so the endpoint can attribute what it does (§12.2) without resolving
    anything a second time — and without any route being able to obtain one *without* the check,
    because this is the only thing that hands one over.
    """

    def dependency(principal: PrincipalDep) -> Principal:
        try:
            authorize(principal, permission)
        except NotAuthenticated as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="a signed-in user is required",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except Forbidden as exc:
            # The message names the permission, never the roles the caller lacks: telling them
            # which role would work is telling them what to ask for.
            #
            # A sentence first, the permission name after it (`T-210`). This reaches a reviewer's
            # screen verbatim — the dashboard renders the backend's own `detail` — and three
            # rehearsal readers met the bare `this action requires view_operations`, which reads
            # as a system error rather than as "you do not have access to this". The identifier
            # stays, because it is what an administrator needs in order to grant it.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "your account does not have access to this. Ask an administrator for the "
                    f"{permission.value} permission."
                ),
            ) from exc

        assert principal is not None  # `authorize` raises for `None` on any real permission
        return principal

    return _marked(dependency, permission)


def requires_mutation(
    permission: Permission,
) -> Callable[[Principal | None, str | None, str | None, str | None], Principal]:
    """`requires`, plus CSRF protection. The dependency every state-changing route uses.

    Two ways through, and the difference is which credential the browser attaches by itself:

    * **A bearer token.** A browser never sends one unprompted, so a cross-site form post cannot
      produce this request at all. Nothing further is required, and this is the path the dashboard
      and every existing test take.
    * **The session cookie plus a matching `X-CSRF-Token` header.** The browser does attach the
      cookie by itself, so the header is what proves the request came from a page that could read
      the CSRF cookie — same-origin policy, not trust.

    A cookie with no header, or with the wrong one, is refused. `403` rather than `401`: the
    caller *is* authenticated, and telling them to sign in again would send them round a loop that
    cannot fix it (`T-063a`'s reason for keeping the two codes apart).
    """

    check = requires(permission)

    def dependency(
        principal: PrincipalDep,
        authorization: Annotated[str | None, Header()] = None,
        mp_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> Principal:
        resolved = check(principal)
        if bearer_token(authorization) is not None:
            return resolved

        # Cookie-authenticated. `mp_session` is not None here — `check` passed, and with no bearer
        # token the cookie is the only thing `current_principal` could have resolved — but it is
        # narrowed rather than asserted, because a future third credential must fail closed here
        # instead of skipping the check.
        if mp_session is None or not csrf_token_matches(mp_session, x_csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "state-changing requests authenticated by cookie must send a matching "
                    f"{CSRF_HEADER} header (§15.1). A bearer token needs no CSRF token."
                ),
            )
        return resolved

    return _marked(dependency, permission)
