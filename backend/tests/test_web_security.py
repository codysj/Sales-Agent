"""Secure session cookies and CSRF on state-changing routes (T-070a; §15.1, §12.2).

The rule this proves is not "the CSRF check exists" — it is that **no mutating route can be
reached by a cookie alone**. So the central test does not name a route: it walks the application's
own route table for every state-changing path and fires a cookie-authenticated request at each,
asserting a refusal. A route added next month without the dependency fails here rather than
becoming the one hole, which is the failure mode a hand-written list of three endpoints has.

`T-070b` (reauthentication) is `BLOCKED` on `Q-026` and is not tested here: §12.2 rejects
passwords, the local stub verifies nothing, and a reauthentication test against it would assert
that a caller can retype an email address.
"""

import ast
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    cookie_is_secure,
    csrf_token_for,
    csrf_token_matches,
)
from app.core.settings import AppEnv, Settings, get_settings
from app.db.session import dispose_engines
from app.identity.dependencies import SESSION_COOKIE, db_session
from app.identity.models import Role, User, UserRole
from app.identity.sessions import hash_token
from app.main import create_app
from tests.test_authz import application_routes

LOCAL_SETTINGS = Settings(app_env=AppEnv.LOCAL)
EMAIL = "synthetic.reviewer@example.com"

#: Methods that change state. `GET` and `HEAD` do not, and `OPTIONS` is the preflight itself.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: The one state-changing route that is deliberately reachable without a session at all — signing
#: in is how a caller *gets* one, and it has no session to CSRF-protect. Excluded by name rather
#: than by pattern so adding a second public mutation is a deliberate edit to this line.
PUBLIC_MUTATIONS = frozenset({"/api/auth/stub-sign-in"})

#: Sign-out is state-changing and takes no permission: it revokes the caller's own session, and
#: `T-151a` answers `204` to a caller with none. It carries no CSRF requirement because the worst
#: a forged sign-out achieves is signing the victim out — annoying, not a security boundary — and
#: refusing it would leave a reviewer whose cookie went stale unable to clear it.
UNPROTECTED_MUTATIONS = frozenset({"/api/auth/session"})


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-web-security-test")


@pytest.fixture
def db_session_for_api(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def client(db_session_for_api: Session) -> Iterator[TestClient]:
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session_for_api
    app.dependency_overrides[get_settings] = lambda: LOCAL_SETTINGS
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    dispose_engines()


@pytest.fixture
def reviewer(db_session: Session) -> User:
    """One user holding **every** role, so authorization can never be why a request is refused.

    This suite's claim is "no mutating route accepts a cookie without a CSRF token", and it walks
    every route to make it. A single-role user made that claim only for the routes that role
    happens to hold: `T-069b`'s administrator-only switch then answered `403` for the *role*, the
    assertion on the refusal's wording caught it, and the walk would otherwise have reported a
    CSRF refusal it never actually observed.

    §12.1 says one person may hold several roles, and `tests/test_authz.py` is where the matrix
    itself is proven — separating the two questions is the point.
    """
    user = User(email=EMAIL, display_name="SYNTHETIC Reviewer", active=True)
    db_session.add(user)
    db_session.flush()
    for role in db_session.execute(select(Role)).scalars().all():
        db_session.add(UserRole(user_id=user.id, role_id=role.id, granted_by="synthetic-admin"))
    db_session.flush()
    return user


def sign_in(client: TestClient) -> str:
    response = client.post("/api/auth/stub-sign-in", json={"email": EMAIL})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert isinstance(token, str)
    return token


def protected_mutations() -> list[tuple[str, str]]:
    """`(method, path)` for every state-changing route that requires a session.

    Read off the real application rather than listed here, so the coverage cannot go stale.
    `application_routes` is `T-062`'s walk, imported rather than rewritten: an included router
    arrives as a wrapper whose real routes hang off it, a flat walk over `app.routes` finds two
    health probes and nothing else, and "found nothing" reads exactly like "nothing unprotected".
    That walk already learned this; a second copy here would have to learn it again, and this
    file's first draft did — the guard below caught it on the first run.

    The two exclusion sets above are named constants with reasons attached, not silent skips.
    """
    return sorted(
        (method, path)
        for method, path in application_routes()
        if method in MUTATING_METHODS
        and path not in PUBLIC_MUTATIONS
        and path not in UNPROTECTED_MUTATIONS
    )


def concrete(path: str) -> str:
    """A path with its `{placeholders}` filled by UUIDs that match nothing.

    The rows do not need to exist: authentication and CSRF run in the dependency, before the
    handler that would `404`. A refusal that arrived only because the id was unknown would be a
    test proving nothing, which is why the success-path tests below use a real one.
    """
    filled = path
    while "{" in filled:
        start = filled.index("{")
        end = filled.index("}", start)
        filled = f"{filled[:start]}{uuid.uuid4()}{filled[end + 1 :]}"
    return filled


# --- criterion 1: a cookie-authenticated mutation with no CSRF token fails ------------------------


def test_the_walk_finds_the_routes_it_claims_to_check() -> None:
    """A guard on the guard: an empty walk would make every assertion below vacuous."""
    found = protected_mutations()

    assert len(found) >= 5
    assert ("POST", "/api/review/revisions/{revision_id}/approve") in found
    assert all(method in MUTATING_METHODS for method, _ in found)


@pytest.mark.parametrize(("method", "path"), protected_mutations(), ids=lambda value: str(value))
def test_no_mutation_accepts_a_cookie_without_a_csrf_token(
    client: TestClient, reviewer: User, method: str, path: str
) -> None:
    """Every state-changing route, not three of them. This is the property §15.1 asks for."""
    token = sign_in(client)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.request(method, concrete(path), json={})

    assert response.status_code == 403, f"{method} {path} answered {response.status_code}"
    assert CSRF_HEADER in response.json()["detail"].lower()


@pytest.mark.parametrize(("method", "path"), protected_mutations(), ids=lambda value: str(value))
def test_no_mutation_accepts_a_wrong_csrf_token(
    client: TestClient, reviewer: User, method: str, path: str
) -> None:
    """A token that is present but not this session's. The check is a comparison, not a
    presence test — an implementation that only asked "is the header there" would pass the test
    above and fail this one."""
    token = sign_in(client)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.request(
        method, concrete(path), json={}, headers={CSRF_HEADER: csrf_token_for("another-session")}
    )

    assert response.status_code == 403, f"{method} {path} answered {response.status_code}"


# --- criterion 2: a cookie plus a matching token gets through ------------------------------------


def test_a_cookie_with_a_matching_csrf_token_passes_the_check(
    client: TestClient, reviewer: User
) -> None:
    """Proven on a real route with a real id, so the pass is the CSRF check passing rather than
    the request dying earlier. The revision does not exist, so the *handler* answers `404` — which
    is exactly the evidence wanted: the dependency let it through."""
    token = sign_in(client)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.post(
        f"/api/review/revisions/{uuid.uuid4()}/approve",
        json={"recipient_contact_point_id": str(uuid.uuid4())},
        headers={CSRF_HEADER: csrf_token_for(token)},
    )

    assert response.status_code == 404, response.text


def test_the_csrf_cookie_the_server_sets_is_the_one_that_works(
    client: TestClient, reviewer: User
) -> None:
    """End to end through the browser's own path: sign in, read the CSRF cookie the server set,
    echo it. A derived token nobody could obtain from the response would be a mechanism no real
    client could use."""
    sign_in(client)
    presented = client.cookies.get(CSRF_COOKIE)
    assert presented is not None

    response = client.post(
        f"/api/review/revisions/{uuid.uuid4()}/approve",
        json={"recipient_contact_point_id": str(uuid.uuid4())},
        headers={CSRF_HEADER: presented},
    )

    assert response.status_code == 404, response.text


# --- criterion 3: the cookie attributes ----------------------------------------------------------


def cookie_attributes(client: TestClient, name: str) -> str:
    response = client.post("/api/auth/stub-sign-in", json={"email": EMAIL})
    assert response.status_code == 200, response.text
    headers = [value for value in response.headers.get_list("set-cookie") if value.startswith(name)]
    assert headers, f"no set-cookie for {name} in {response.headers.get_list('set-cookie')}"
    return headers[0].lower()


def test_the_session_cookie_is_httponly_and_samesite(client: TestClient, reviewer: User) -> None:
    """`HttpOnly` is what makes stealing the readable CSRF cookie useless on its own."""
    attributes = cookie_attributes(client, SESSION_COOKIE)

    assert "httponly" in attributes
    assert "samesite=lax" in attributes
    assert "path=/" in attributes


def test_the_csrf_cookie_is_readable_and_samesite(client: TestClient, reviewer: User) -> None:
    """Deliberately *not* `HttpOnly`: a client that cannot read it cannot echo it, and the whole
    mechanism is the echo. It authenticates nothing on its own."""
    attributes = cookie_attributes(client, CSRF_COOKIE)

    assert "httponly" not in attributes
    assert "samesite=lax" in attributes


def test_the_session_cookie_is_not_secure_only_where_there_is_no_tls() -> None:
    """The list is the exception, and everything else is secure by default — so a new environment
    is `Secure` without anybody remembering to add it."""
    assert cookie_is_secure(AppEnv.PRODUCTION)
    assert cookie_is_secure(AppEnv.STAGING)
    assert not cookie_is_secure(AppEnv.LOCAL)
    assert not cookie_is_secure(AppEnv.TEST)


def test_signing_out_clears_both_cookies(client: TestClient, reviewer: User) -> None:
    """A dead session cookie left in the browser is how a reviewer ends up unable to sign in
    again without knowing to clear cookies by hand."""
    token = sign_in(client)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.delete("/api/auth/session")

    assert response.status_code == 204
    cleared = " ".join(response.headers.get_list("set-cookie")).lower()
    assert SESSION_COOKIE in cleared
    assert CSRF_COOKIE in cleared


# --- criterion 4: bearer authentication is unchanged ----------------------------------------------


@pytest.mark.parametrize(("method", "path"), protected_mutations(), ids=lambda value: str(value))
def test_every_mutation_still_accepts_a_bearer_token(
    client: TestClient, reviewer: User, method: str, path: str
) -> None:
    """The relaxation added a way in; it must not have moved the existing one. A browser never
    sends `Authorization` unprompted, so a bearer caller needs no CSRF token — and every test and
    client built before `T-070a` takes this path."""
    token = sign_in(client)
    client.cookies.clear()

    response = client.request(
        method, concrete(path), json={}, headers={"authorization": f"Bearer {token}"}
    )

    # Anything but the two authentication refusals: the request got past the dependency and into
    # the handler, which is free to answer `404` or `422` for a body this test did not construct.
    assert response.status_code not in {401, 403}, f"{method} {path}: {response.text}"


def test_an_unauthenticated_mutation_is_still_401(client: TestClient, reviewer: User) -> None:
    """CSRF is a second gate, not a replacement for the first: no session is still `401`, and the
    distinction from `403` is what tells a reviewer whether signing in again would help."""
    response = client.post(
        f"/api/review/revisions/{uuid.uuid4()}/approve",
        json={"recipient_contact_point_id": str(uuid.uuid4())},
    )

    assert response.status_code == 401


# --- the derivation itself --------------------------------------------------------------------


def test_the_csrf_token_is_not_the_stored_session_hash() -> None:
    """Domain separation, and the reason for it: `hash_token` is the primary key stored in
    `user_session`. Without the prefix every client would hold a copy of a database lookup key in
    a JavaScript-readable cookie."""
    token = "SYNTHETIC-session-token"

    assert csrf_token_for(token) != hash_token(token)


def test_the_csrf_token_differs_per_session() -> None:
    """A constant would pass every test above and protect nothing."""
    assert csrf_token_for("SYNTHETIC-a") != csrf_token_for("SYNTHETIC-b")


@pytest.mark.parametrize("presented", [None, "", "not-the-token"])
def test_a_missing_or_wrong_token_never_matches(presented: str | None) -> None:
    assert not csrf_token_matches("SYNTHETIC-session-token", presented)


def test_the_right_token_matches() -> None:
    token = "SYNTHETIC-session-token"

    assert csrf_token_matches(token, csrf_token_for(token))


def test_the_application_registers_no_cors_middleware() -> None:
    """`T-195` criterion 4 — the other half of the same-origin fix, held from this side.

    The dashboard's requests were cross-origin and the browser refused them. There were two ways
    out: proxy the dashboard so the requests are same-origin, or permit the crossing with CORS
    headers here. `T-195` took the first, and this is what stops the second arriving later as a
    quick fix for a symptom nobody connects back to it.

    Permitting it here would matter more than it looks. `Access-Control-Allow-Origin` is a
    standing instruction to a browser that some other origin may read this API's responses, in a
    service whose posture is that external effects are structurally closed — and the session
    cookie is `SameSite` (`T-070a`), so a genuinely cross-site dashboard would then need that
    relaxed too. The proxy needs neither.
    """
    registered = [middleware.cls.__name__ for middleware in create_app().user_middleware]

    # Guard on the guard: an empty list would make the assertion below vacuous, and the walk
    # reads an attribute Starlette is free to rename.
    assert "RequestContextMiddleware" in registered, (
        f"the middleware walk is misreading the application; it found {registered}"
    )
    assert "CORSMiddleware" not in registered, (
        "the API registers CORS middleware. T-195 made the dashboard same-origin through a "
        "next.config.ts rewrite precisely so this would not be needed; if a real deployment now "
        "needs a cross-origin dashboard, that is a task and an ADR, not a middleware line."
    )


# --- T-070c: the actor comes from the session, never from the request -----------------------------
#
# §15.1 asks for "immutable actor attribution in audit events", and §12.2 for identities that are
# not the caller's to choose. Both are properties of *every* mutating handler, so this is a
# structural walk rather than a test per route: a handler that took `approver_id` from its request
# body would satisfy any behavioural test written against it — the request would be answered, the
# audit event written, and the name in it would simply be whoever asked.
#
# **It fails closed.** Only an expression rooted at `principal` — the object the authorization
# dependency hands over, and the only thing a route cannot obtain without being authorized — is
# accepted. A local variable, a literal, a request field, and anything else are all violations,
# because laundering `request.approver_id` through `who = ...` is the obvious evasion and an
# allow-list of safe shapes is the only form that catches it.

#: Keyword arguments that name who did something.
ACTOR_KEYWORDS = frozenset(
    {
        "actor",
        "actor_id",
        "approver_id",
        "approved_by",
        "created_by",
        "revoked_by",
        "granted_by",
        "decided_by",
    }
)

#: Router decorators that create state-changing routes. A `get` handler is excluded deliberately:
#: `/attention/approvals` reports the stored `approver_id` of an approval somebody else granted,
#: which is reading history rather than attributing an action.
MUTATING_DECORATORS = frozenset({"post", "put", "patch", "delete"})

#: The one root an actor may come from: what `requires`/`requires_mutation` returns.
ATTRIBUTION_ROOT = "principal"

APP_SOURCE = Path(__file__).resolve().parents[1] / "app"


def _root_name(node: ast.expr) -> str:
    """The leftmost `Name` of an attribute or call chain: `principal.user.email` -> `principal`.

    Returns a description rather than raising for expressions with no root — a literal, an f-string
    — because those are violations too, and the message has to say what was found.
    """
    current = node
    while True:
        if isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Subscript | ast.Await):
            current = current.value
        else:
            break
    if isinstance(current, ast.Name):
        return current.id
    return f"<{type(current).__name__}>"


def _is_mutating_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in MUTATING_DECORATORS:
            return True
    return False


def attribution_violations(source: str, *, where: str) -> list[str]:
    """Every place a mutating handler names an actor that does not come from the session."""
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not _is_mutating_handler(node):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                # Building an `Actor` inside a handler is its own violation: the actor exists
                # already, on the principal, and a second construction is a second chance to put
                # the caller's own claim in it.
                if _root_name(inner.func) == "Actor":
                    violations.append(
                        f"{where}:{inner.lineno} {node.name} constructs Actor(...) instead of "
                        f"using {ATTRIBUTION_ROOT}.actor"
                    )
                for keyword in inner.keywords:
                    if keyword.arg not in ACTOR_KEYWORDS:
                        continue
                    root = _root_name(keyword.value)
                    if root != ATTRIBUTION_ROOT:
                        violations.append(
                            f"{where}:{keyword.value.lineno} {node.name} passes "
                            f"{keyword.arg}= rooted at {root!r}, not {ATTRIBUTION_ROOT!r}"
                        )
    return sorted(violations)


def mutating_handlers() -> list[tuple[str, str]]:
    """`(module, function)` for every mutating route handler in `app/`."""
    found: list[tuple[str, str]] = []
    for path in sorted(APP_SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _is_mutating_handler(
                node
            ):
                found.append((str(path.relative_to(APP_SOURCE)), node.name))
    return found


# --- criterion 1: the detector, and the proof that it fires --------------------------------------


def test_the_walk_finds_every_mutating_handler() -> None:
    """A guard on the guard. The whole file walk, not a list of modules: a handler in a new module
    is exactly the one nobody would remember to add here."""
    handlers = mutating_handlers()

    assert len(handlers) >= 8, handlers
    names = {name for _, name in handlers}
    assert "approve_message_endpoint" in names
    assert "revoke_approval_endpoint" in names
    assert "sign_out" in names


def test_no_mutating_handler_takes_its_actor_from_the_request() -> None:
    """§15.1, over the real application source."""
    violations = [
        violation
        for path in sorted(APP_SOURCE.rglob("*.py"))
        for violation in attribution_violations(
            path.read_text(encoding="utf-8"), where=str(path.relative_to(APP_SOURCE))
        )
    ]

    assert violations == [], (
        "an actor on a mutating route must come from the resolved session (§15.1, §12.2): "
        f"{violations}"
    )


def test_the_detector_fires_on_an_actor_taken_from_the_body() -> None:
    """The criterion is that a route taking its actor from the request *fails*, so the detector is
    run against one. Synthetic source rather than a mutated file: this asserts the rule, and the
    negative control on the real handler asserts the wiring."""
    source = (
        "@router.post('/x')\n"
        "def handler(request: Body, principal: Principal) -> None:\n"
        "    approve(session, approver_id=request.approver_id)\n"
    )

    violations = attribution_violations(source, where="synthetic.py")

    assert len(violations) == 1
    assert "approver_id=" in violations[0]
    assert "'request'" in violations[0]


def test_the_detector_fires_on_a_laundered_actor() -> None:
    """The obvious evasion: assign the request field to a local first. An allow-list of safe roots
    is the only shape that catches it — a deny-list of `request.*` would not."""
    source = (
        "@router.post('/x')\n"
        "def handler(request: Body, principal: Principal) -> None:\n"
        "    who = request.approver_id\n"
        "    approve(session, approver_id=who)\n"
    )

    assert len(attribution_violations(source, where="synthetic.py")) == 1


def test_the_detector_fires_on_an_actor_built_in_the_handler() -> None:
    """`Actor(type=..., id=...)` in a handler is a second construction of a value that already
    exists on the principal — and a second chance to fill it from the request."""
    source = (
        "@router.post('/x')\n"
        "def handler(request: Body, principal: Principal) -> None:\n"
        "    record(session, actor=Actor(type=ActorType.HUMAN, id=request.who))\n"
    )

    violations = attribution_violations(source, where="synthetic.py")

    assert any("constructs Actor(...)" in violation for violation in violations)


def test_the_detector_accepts_the_session_actor() -> None:
    """The other direction: a detector that flagged the correct shape too would be noise, and
    noise is what gets a structural test deleted."""
    source = (
        "@router.post('/x')\n"
        "def handler(request: Body, principal: Principal) -> None:\n"
        "    approve(session, actor=principal.actor, approver_id=principal.user.email)\n"
    )

    assert attribution_violations(source, where="synthetic.py") == []


def test_the_detector_ignores_a_read_handler() -> None:
    """A `get` route reporting the stored `approver_id` of somebody else's approval is reading
    history, not attributing an action — `/attention/approvals` does exactly this."""
    source = (
        "@router.get('/x')\n"
        "def handler(principal: Principal) -> None:\n"
        "    return Row(approver_id=approval.approver_id)\n"
    )

    assert attribution_violations(source, where="synthetic.py") == []
