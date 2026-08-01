"""The session lifecycle over HTTP (T-151a; §12.2, §15.1, §17.5).

`T-061a` built sessions and a local sign-in stub, and `T-062` built the permission matrix — but
nothing exposed any of it, so a browser had no way to obtain a session at all. Every authenticated
route in the dashboard was unreachable from the one client it exists for. This is the missing
resource: create a session, read the current one, delete it.

**`POST /api/auth/stub-sign-in` is `PUBLIC`, and that word means what it says.** It is the
repository's first endpoint anyone may call without a session — necessarily, since obtaining one
is the point. What keeps that from being a hole is that it is refused outside `local`:

* `require_stub_allowed` runs **first in the handler, before the request body is used and before
  any database read**, so a deployed environment cannot be probed for valid emails.
* The refusal is `503`, not `403`: nothing about the caller would make this work, and a `403`
  invites someone to go looking for the credential that unlocks it. The endpoint is simply not
  available here.
* `ALLOWED_ENVIRONMENTS` is `T-061a`'s frozen allow-list, imported rather than re-stated. Two
  copies of a security rule are one edit away from disagreeing, and the copy people forget is
  always the one at the edge.

**The token is returned in the body and never logged.** It is a bearer credential: a log line
carrying one is a credential in a file with different access rules to the database, and §17.5 asks
for the actor, not the secret. `sessions.issue_session` logs the session id; this logs nothing at
all beyond what that already recorded.

**Cookies are set, and `T-070a` is what made that safe.** Until then nothing here issued one:
`current_principal` read a cookie for a client that had one, and no client could get one, because
a cookie mutation had no CSRF defence and setting one would have created exactly the exposure the
refusal existed to remove. Now the session cookie is `HttpOnly` and `SameSite`, a readable CSRF
cookie goes with it, and `requires_mutation` refuses a cookie mutation that does not echo the
token. The token is still returned in the body as well — the dashboard uses that, and moving it
off bearer authentication is a separate, observable change.

**Signing out revokes; it does not forget.** The row stays, with `revoked_at`, `revoked_by`, and a
reason, because §17.5 wants state-transition history and a deleted session is a question nobody
can answer later.
"""

from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.security import CSRF_COOKIE, cookie_is_secure, csrf_token_for
from app.core.settings import Settings, get_settings
from app.identity.dependencies import SESSION_COOKIE, PrincipalDep, db_session
from app.identity.sessions import Principal, SessionError, resolve, revoke
from app.identity.stub import StubRefused, UnknownStubUser, require_stub_allowed, stub_sign_in

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class StubSignInRequest(BaseModel):
    """Who to sign in. There is no password field, and that is `§12.2` rather than an omission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: A plain string rather than `EmailStr`: the address is looked up, not delivered to, and an
    #: address that matches no user is a `404` whether or not it parses. Validating the syntax
    #: would add a dependency to reject earlier what is already rejected.
    email: str = Field(min_length=3, max_length=320)


class SessionResponse(BaseModel):
    """The current session. `token` is present only on the response that created it."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    email: str
    display_name: str
    roles: list[str]
    expires_at: datetime
    issued_via: str
    #: Returned once, by sign-in. Reading the session never re-issues it — a caller that lost the
    #: token has to sign in again, which is the property that makes a stolen one worth stealing
    #: less.
    token: str | None = None


def _set_session_cookies(response: Response, token: str, *, settings: Settings) -> None:
    """Put the session and its CSRF token in cookies (`T-070a`, §15.1).

    `max_age` is deliberately absent from both, making them session cookies that die with the
    browser: the row expires in eight hours (`T-061a`), and a cookie outliving it would leave a
    reviewer looking at a dashboard that answers `401` to everything with no visible reason.
    """
    secure = cookie_is_secure(settings.app_env)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        # The credential itself: script must never read it, which is what makes stealing the
        # readable CSRF cookie useless on its own.
        httponly=True,
        secure=secure,
        # `lax`, not `strict`: `strict` would drop the cookie on a link followed in from an email
        # or a chat message, so a reviewer clicking a dashboard link would land signed out. Both
        # values stop the cross-site POST this exists to stop.
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token_for(token),
        # Readable on purpose — the client has to echo it. It authenticates nothing by itself.
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _describe(principal: Principal, *, token: str | None = None) -> SessionResponse:
    return SessionResponse(
        user_id=str(principal.user.id),
        email=principal.user.email,
        display_name=principal.user.display_name,
        # Sorted so a client can compare two responses; the set has no order of its own.
        roles=sorted(principal.roles),
        expires_at=principal.session.expires_at,
        issued_via=principal.session.issued_via,
        token=token,
    )


@router.post(
    "/stub-sign-in",
    response_model=SessionResponse,
    summary="Sign in as an existing local user (local environment only)",
)
def stub_sign_in_endpoint(
    request: StubSignInRequest,
    response: Response,
    session: Annotated[Session, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    """Issue a session for a known local user. Verifies nothing; refused outside `local`.

    The environment check is the first statement on purpose — see the module docstring. An unknown
    email is `404` and creates nobody: the roster is `Q-005` and `Q-026`, not whoever can reach
    this port.
    """
    try:
        require_stub_allowed(settings)
    except StubRefused as refusal:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(refusal)
        ) from refusal

    try:
        issued = stub_sign_in(session, request.email, settings=settings)
    except UnknownStubUser as unknown:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(unknown)) from unknown
    except SessionError as refused:
        # A deactivated user: the row is kept for attribution (§12.2) and must not be a row that
        # can sign in. `403` rather than the `404` an unknown address gets — the distinction is a
        # mild enumeration signal, and it is worth it in the one environment this runs in, where
        # the alternative is a developer debugging "no such user" against a user they can see.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(refused)) from refused

    session.commit()

    # Resolved through the same path a real request takes, rather than assembled here. A second
    # way of building a `Principal` is a second place for its roles to be wrong, and this one
    # would be the one nobody tests against an expired session.
    principal = resolve(session, issued.token)
    if principal is None:  # pragma: no cover - the session was issued one statement ago
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="the session was issued but does not resolve",
        )

    _set_session_cookies(response, issued.token, settings=settings)

    # The token is deliberately absent from this line, and so is the CSRF value derived from it.
    # §17.5 wants the actor, not the credential.
    log.info("session.issued", user_id=str(principal.user.id), session_id=str(issued.session.id))
    return _describe(principal, token=issued.token)


@router.get(
    "/session",
    response_model=SessionResponse,
    summary="The current session, or 401",
)
def read_session(principal: PrincipalDep) -> SessionResponse:
    """Who the caller is. `401` when nobody.

    Not `requires(...)`: there is no permission to hold here — the question is whether a session
    resolves at all, and every role may ask it. The dashboard uses this to tell "signed out" from
    "signed in without the role", which are different screens.
    """
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _describe(principal)


@router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out, revoking the current session",
)
def sign_out(
    response: Response,
    principal: PrincipalDep,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    """Revoke the caller's own session, and only their own.

    A caller with no session gets `204` rather than `401`: signing out when already signed out is
    the state they asked for, and answering `401` would make a dashboard sign-out button fail for
    a reviewer whose session had just expired.

    Both cookies are cleared **before** the `principal is None` return, so a caller holding a
    cookie the server no longer honours still gets rid of it. Leaving a dead session cookie in the
    browser is how a reviewer ends up signed out and unable to sign in again without knowing to
    clear cookies by hand.
    """
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")

    if principal is None:
        return

    revoke(
        session,
        principal.session,
        revoked_by=principal.actor.id,
        reason="signed out",
    )
    session.commit()
