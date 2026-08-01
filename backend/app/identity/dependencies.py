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

**A mutation refuses cookie authentication, until `T-070`.** A CSRF attack works because a
browser attaches a cookie by itself; a bearer token it never sends unprompted. `T-061a` deferred
CSRF to the first cookie-bearing mutating endpoint and `T-070` owns it — so rather than accept
the exposure on trust in the meantime, `requires_bearer` refuses a cookie-only caller on any
state-changing route. The dashboard reads with a cookie and will mutate with a token until
`T-070` lands, at which point this can relax deliberately rather than by nobody noticing.

**Failures are two different answers.** No usable session is `401` — sign in. A usable session
without the role is `403` — signing in again will not help. Collapsing them would send a reviewer
round a login loop that could never succeed. Neither response says which of "unknown token",
"expired", or "revoked" applied, because `resolve` deliberately cannot tell them apart.
"""

from collections.abc import Callable, Iterator
from typing import Annotated, Final

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

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

    Reads the cookie first because that is how the dashboard calls; the bearer header is for a
    script or a test. Deliberately no query parameter — see the module docstring.
    """
    token = mp_session or bearer_token(authorization)
    if token is None:
        return None
    return resolve(session, token)


PrincipalDep = Annotated[Principal | None, Depends(current_principal)]


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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"this action requires {permission.value}",
            ) from exc

        assert principal is not None  # `authorize` raises for `None` on any real permission
        return principal

    return dependency


def requires_bearer(permission: Permission) -> Callable[[Principal | None, str | None], Principal]:
    """`requires`, plus a refusal of cookie-only authentication. For state-changing routes.

    See the module docstring: this is CSRF exposure removed rather than mitigated, and it is
    temporary. `T-070` adds real CSRF protection and this becomes a deliberate relaxation.
    """

    check = requires(permission)

    def dependency(
        principal: PrincipalDep,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Principal:
        resolved = check(principal)
        if bearer_token(authorization) is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "state-changing requests need an Authorization: Bearer token. Cookie "
                    "authentication is refused here until CSRF protection lands (T-070)."
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )
        return resolved

    return dependency
