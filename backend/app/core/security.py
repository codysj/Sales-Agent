"""CSRF tokens and cookie attributes (T-070a; §15.1, §12.2).

**The CSRF token is derived from the session token, so nothing new is stored.** A double-submit
defence needs a value the legitimate client can echo and an attacker on another origin cannot
obtain. `sha256("csrf:" + session_token)` is exactly that: only the holder of the session token
can compute it, the server recomputes it from the cookie it already read, and no column, no
migration, and no server secret is involved. A random per-session token would have needed all
three, and the freshest of those three is the one that would be missing in the environment nobody
tested.

**The prefix is not decoration.** `sessions.hash_token` is plain `sha256(token)`, and that value
is the primary lookup key stored in `user_session`. Deriving the CSRF token without domain
separation would hand every client a copy of a database key to keep in a JavaScript-readable
cookie. `csrf:` makes the two values unrelated preimages of the same secret.

**Why double-submit at all, when `SameSite` already blocks the cross-site POST.** Two independent
mechanisms, because each fails differently: `SameSite=Lax` is enforced by the browser and is
worth nothing against a client that does not implement it, while the token check is enforced here
and is worth nothing if an attacker can read the cookie. Neither is a reason to skip the other.

**What this deliberately does not defend against.** An attacker who can *write* cookies for the
site — a compromised subdomain — can overwrite the CSRF cookie and the header to match. The
answer to that is `__Host-` cookie prefixes, which require TLS and therefore belong with the
deployment task that gives the API a certificate, not here where they would break local
development for no gain. Recorded rather than left for a reader to notice.
"""

import hashlib
import secrets
from typing import Final

from app.core.settings import AppEnv

#: The header a browser client echoes the CSRF cookie back in. Read case-insensitively by Starlette.
CSRF_HEADER: Final = "x-csrf-token"

#: The cookie carrying the CSRF token. Deliberately **not** `HttpOnly`: the client has to read it
#: in order to echo it, which is the whole mechanism. It is not a credential on its own — it
#: authenticates nothing without the session cookie beside it.
CSRF_COOKIE: Final = "mp_csrf"

#: Domain separation, so the derived token is not the value `sessions.hash_token` stores.
_CSRF_PREFIX: Final = "csrf:"

#: Environments with no TLS to require. Everything else gets `Secure`, so a new environment is
#: secure by default rather than by somebody remembering to add it to a list.
_INSECURE_TRANSPORT_ENVIRONMENTS: Final = frozenset({AppEnv.LOCAL, AppEnv.TEST})


def csrf_token_for(session_token: str) -> str:
    """The CSRF token a client holding ``session_token`` is expected to present."""
    return hashlib.sha256(f"{_CSRF_PREFIX}{session_token}".encode()).hexdigest()


def csrf_token_matches(session_token: str, presented: str | None) -> bool:
    """Whether ``presented`` is the token this session should carry.

    Compared with `compare_digest` rather than `==`: the comparison is against a value derived
    from a secret, and an early-exit comparison leaks how much of a guess was right.
    """
    if not presented:
        return False
    return secrets.compare_digest(csrf_token_for(session_token), presented)


def cookie_is_secure(app_env: AppEnv) -> bool:
    """Whether cookies must carry `Secure` in this environment.

    True everywhere except `local` and `test`, which have no TLS: a staging deployment served
    over plain HTTP gets cookies the browser will refuse to send, which is the correct failure —
    it stops rather than silently downgrading to an interceptable session.
    """
    return app_env not in _INSECURE_TRANSPORT_ENVIRONMENTS
