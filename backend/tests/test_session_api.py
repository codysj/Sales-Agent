"""The session API (T-151a; §12.2, §15.1, §17.5).

Four things, and the second is why this endpoint deserved its own change set.

* **A session obtained here works everywhere.** Signing in and then calling a protected route
  with the returned token, rather than asserting the response shape and trusting the rest — the
  whole point of the endpoint is the token, and a token that parses but does not authenticate
  would satisfy any test that stopped at the body.
* **It is refused outside `local`, at the route.** `stub_sign_in` already refuses, and this is
  the second guard rather than a duplicate one: the route's check runs before the body is read
  and before any database access, so a deployed environment cannot be probed for valid emails by
  timing or by the difference between `404` and `503`. Asserted here against the *endpoint*,
  because a refusal that only exists one layer down is a refusal the next endpoint will forget.
* **It creates nobody.** An unknown address is refused with the user table unchanged. The roster
  is `Q-005` and `Q-026`; auto-provisioning would make it "whoever can reach this port".
* **The token never reaches a log.** It is a bearer credential, and §17.5 asks for the actor.
  Asserted over everything the request logged, not over one line — the risk is a line nobody
  thought about.
"""

import uuid
from collections.abc import Iterator

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.settings import AppEnv, Settings, get_settings
from app.db.session import dispose_engines
from app.identity.dependencies import db_session
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.sessions import UserSession
from app.main import create_app

LOCAL_SETTINGS = Settings(app_env=AppEnv.LOCAL)
EMAIL = "synthetic.reviewer@example.com"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-session-api-test")


@pytest.fixture
def db_session_for_api(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def client(db_session_for_api: Session) -> Iterator[TestClient]:
    """The app in `local`, reading the test's own transaction."""
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session_for_api
    app.dependency_overrides[get_settings] = lambda: LOCAL_SETTINGS
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    dispose_engines()


@pytest.fixture
def reviewer(db_session: Session) -> User:
    """One active user holding the reviewer role."""
    user = User(email=EMAIL, display_name="SYNTHETIC Reviewer", active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.execute(
        select(Role).where(Role.key == RoleKey.OPERATOR_REVIEWER.value)
    ).scalar_one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id, granted_by="synthetic-admin"))
    db_session.flush()
    return user


def sign_in(client: TestClient, email: str = EMAIL) -> dict[str, object]:
    response = client.post("/api/auth/stub-sign-in", json={"email": email})
    assert response.status_code == 200, response.text
    return response.json()


# --- criterion 1: a session obtained here authenticates a later request --------------------------


def test_signing_in_returns_a_token_that_authenticates(client: TestClient, reviewer: User) -> None:
    """The token is the endpoint's whole purpose, so it is used rather than inspected."""
    body = sign_in(client)

    assert isinstance(body["token"], str)
    assert body["token"]

    read = client.get("/api/auth/session", headers={"authorization": f"Bearer {body['token']}"})

    assert read.status_code == 200
    assert read.json()["user_id"] == str(reviewer.id)


def test_the_token_authenticates_a_protected_route(client: TestClient, reviewer: User) -> None:
    """Not just the auth resource: a session that only worked on `/api/auth/session` would be a
    session that authenticated nothing a reviewer came for."""
    token = sign_in(client)["token"]

    queue = client.get("/api/review/candidates", headers={"authorization": f"Bearer {token}"})

    assert queue.status_code == 200


def test_the_response_reports_the_roles_the_session_holds(
    client: TestClient, reviewer: User
) -> None:
    body = sign_in(client)

    assert body["roles"] == [RoleKey.OPERATOR_REVIEWER.value]
    assert body["email"] == EMAIL
    assert body["issued_via"] == "stub"


def test_reading_the_session_never_re_issues_the_token(client: TestClient, reviewer: User) -> None:
    """A caller who lost the token signs in again. Handing it back on a read would make a stolen
    session self-renewing for anyone who could replay one request."""
    token = sign_in(client)["token"]

    read = client.get("/api/auth/session", headers={"authorization": f"Bearer {token}"})

    assert read.json()["token"] is None


def test_no_session_is_401_not_500(client: TestClient, reviewer: User) -> None:
    read = client.get("/api/auth/session")

    assert read.status_code == 401
    assert read.headers["www-authenticate"] == "Bearer"


def test_no_cookie_is_set(client: TestClient, reviewer: User) -> None:
    """`T-065a` refuses cookie authentication on mutations until `T-070` adds CSRF. Issuing a
    cookie here would create exactly the exposure that refusal removes."""
    response = client.post("/api/auth/stub-sign-in", json={"email": EMAIL})

    assert response.cookies == {}
    assert "set-cookie" not in {name.lower() for name in response.headers}


# --- criterion 2: refused outside `local`, at the route ------------------------------------------


@pytest.mark.parametrize(
    "environment", [AppEnv.TEST, AppEnv.STAGING, AppEnv.PRODUCTION], ids=lambda env: env.value
)
def test_the_endpoint_is_refused_outside_local(
    db_session: Session, reviewer: User, environment: AppEnv
) -> None:
    """Every non-`local` environment, not one of them. `ALLOWED_ENVIRONMENTS` is an allow-list, and
    a test that checked only `production` would pass while `staging` minted sessions."""
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: Settings(app_env=environment)
    before = db_session.execute(select(func.count()).select_from(UserSession)).scalar_one()

    with TestClient(app) as elsewhere:
        response = elsewhere.post("/api/auth/stub-sign-in", json={"email": EMAIL})

    app.dependency_overrides.clear()
    dispose_engines()

    assert response.status_code == 503
    assert "local" in response.json()["detail"]
    after = db_session.execute(select(func.count()).select_from(UserSession)).scalar_one()
    assert after == before


def test_the_refusal_does_not_reveal_whether_the_email_exists(
    db_session: Session, reviewer: User
) -> None:
    """A known and an unknown address must be indistinguishable outside `local`. If they differed,
    the endpoint would be a user-enumeration oracle in exactly the environments it is refused in.
    """
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: Settings(app_env=AppEnv.PRODUCTION)

    with TestClient(app) as elsewhere:
        known = elsewhere.post("/api/auth/stub-sign-in", json={"email": EMAIL})
        unknown = elsewhere.post("/api/auth/stub-sign-in", json={"email": "nobody@example.com"})

    app.dependency_overrides.clear()
    dispose_engines()

    assert known.status_code == unknown.status_code == 503
    assert known.json() == unknown.json()


# --- criterion 3: an unknown email creates nobody -------------------------------------------------


def test_an_unknown_email_is_refused(client: TestClient, reviewer: User) -> None:
    response = client.post("/api/auth/stub-sign-in", json={"email": "nobody@example.com"})

    assert response.status_code == 404


def test_an_unknown_email_creates_nobody(client: TestClient, db_session: Session) -> None:
    """Auto-provisioning would mean the roster grew by whoever typed something (`Q-005`,
    `Q-026`)."""
    before = db_session.execute(select(func.count()).select_from(User)).scalar_one()

    client.post("/api/auth/stub-sign-in", json={"email": "nobody@example.com"})

    after = db_session.execute(select(func.count()).select_from(User)).scalar_one()
    assert after == before


def test_a_deactivated_user_gets_no_usable_session(
    client: TestClient, db_session: Session, reviewer: User
) -> None:
    """Deactivation is how a user is removed (§12.2 keeps the row for attribution). It has to mean
    they cannot sign in, not merely that an existing session stops resolving."""
    reviewer.active = False
    db_session.flush()

    response = client.post("/api/auth/stub-sign-in", json={"email": EMAIL})

    assert response.status_code == 403
    assert "attribution" in response.json()["detail"]


def test_the_email_is_matched_case_insensitively(client: TestClient, reviewer: User) -> None:
    """`ck_app_user_email_lowercase` stores it lowercase; a reviewer typing a capital should get
    their session, not a confusing "no such user"."""
    response = client.post("/api/auth/stub-sign-in", json={"email": EMAIL.upper()})

    assert response.status_code == 200


def test_an_extra_field_is_refused(client: TestClient, reviewer: User) -> None:
    """`extra="forbid"`. A request carrying `password` or `role` should fail loudly rather than
    have it silently ignored — the silence is what makes someone believe it was honoured."""
    response = client.post("/api/auth/stub-sign-in", json={"email": EMAIL, "role": "administrator"})

    assert response.status_code == 422


# --- criterion 4: signing out, and the token in no log --------------------------------------------


def test_signing_out_stops_the_token_working(client: TestClient, reviewer: User) -> None:
    token = sign_in(client)["token"]
    headers = {"authorization": f"Bearer {token}"}
    assert client.get("/api/auth/session", headers=headers).status_code == 200

    out = client.delete("/api/auth/session", headers=headers)

    assert out.status_code == 204
    assert client.get("/api/auth/session", headers=headers).status_code == 401


def test_signing_out_revokes_rather_than_deletes(
    client: TestClient, db_session: Session, reviewer: User
) -> None:
    """§17.5 wants state-transition history. A deleted session is a question nobody can answer."""
    token = sign_in(client)["token"]
    before = db_session.execute(select(func.count()).select_from(UserSession)).scalar_one()

    client.delete("/api/auth/session", headers={"authorization": f"Bearer {token}"})

    after = db_session.execute(select(func.count()).select_from(UserSession)).scalar_one()
    assert after == before
    revoked = db_session.execute(select(UserSession)).scalars().all()[-1]
    assert revoked.revoked_at is not None
    assert revoked.revoked_by == str(reviewer.id)
    assert revoked.revocation_reason == "signed out"


def test_signing_out_without_a_session_is_not_an_error(client: TestClient, reviewer: User) -> None:
    """The state they asked for. A `401` would make the dashboard's sign-out button fail for a
    reviewer whose session had just expired — the one moment they most want it to work."""
    response = client.delete("/api/auth/session")

    assert response.status_code == 204


def test_signing_out_revokes_only_the_callers_own_session(
    client: TestClient, db_session: Session, reviewer: User
) -> None:
    """Two sessions for the same user are two devices. Signing out of one must not sign out the
    other, which `revoke_all_for_user` would have done."""
    first = sign_in(client)["token"]
    second = sign_in(client)["token"]

    client.delete("/api/auth/session", headers={"authorization": f"Bearer {first}"})

    assert (
        client.get("/api/auth/session", headers={"authorization": f"Bearer {first}"}).status_code
        == 401
    )
    assert (
        client.get("/api/auth/session", headers={"authorization": f"Bearer {second}"}).status_code
        == 200
    )


def test_the_token_appears_in_no_log_line(client: TestClient, reviewer: User) -> None:
    """A bearer credential in a log is a credential in a file with different access rules to the
    database. Asserted over everything the request logged, because the risk is the line nobody
    thought about."""
    with structlog.testing.capture_logs() as logs:
        token = sign_in(client)["token"]

    assert isinstance(token, str)
    rendered = repr(logs)
    assert token not in rendered
    # And something *was* logged, or this test would pass against silence.
    assert any(entry.get("event") == "session.issued" for entry in logs)


def test_the_sign_in_log_records_the_actor(client: TestClient, reviewer: User) -> None:
    """§17.5: the actor, and the stub's own warning so a development session is visible in a log an
    operator skims."""
    with structlog.testing.capture_logs() as logs:
        sign_in(client)

    issued = next(entry for entry in logs if entry.get("event") == "session.issued")
    assert issued["user_id"] == str(reviewer.id)
    assert uuid.UUID(str(issued["session_id"]))
    assert any(entry.get("event") == "session.stub_sign_in" for entry in logs)
