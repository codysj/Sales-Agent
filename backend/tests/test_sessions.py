"""Sessions and the local sign-in stub (T-061a; §12.2, §15.1).

Four things, and none of them is "a session can be created":

* **No password exists.** §12.2 rejects custom password authentication outright, so the test is
  an absence — asserted against the migrated schema *and* the source, because "we did not add
  one" is a claim that decays with every later task.
* **The stub is refused outside `local`.** It verifies nothing; the environment check is the only
  thing standing between that and a production sign-in.
* **Sessions expire and can be revoked**, and either one resolves to nobody.
* **A session is a human's.** A `ServiceIdentity` cannot hold one, so a machine actor can never
  become indistinguishable from a person downstream.

`AppEnv.LOCAL` is passed explicitly wherever the stub is exercised. That is deliberate: if these
tests relied on the ambient environment being permitted, they would be establishing that the stub
works somewhere it must not.
"""

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import structlog
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.core.settings import AppEnv, Settings
from app.identity.models import Role, RoleKey, ServiceIdentity, User, UserRole
from app.identity.sessions import (
    DEFAULT_SESSION_TTL,
    Principal,
    SessionError,
    UserSession,
    hash_token,
    issue_session,
    resolve,
    revoke,
    revoke_all_for_user,
)
from app.identity.stub import (
    ALLOWED_ENVIRONMENTS,
    ISSUED_VIA,
    StubRefused,
    UnknownStubUser,
    require_stub_allowed,
    stub_sign_in,
)
from tests.factories import NOW

LOCAL = Settings(app_env=AppEnv.LOCAL)


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-session-test")


def make_user(session: Session, *, email: str | None = None, active: bool = True) -> User:
    user = User(
        email=email or f"synthetic.{uuid.uuid4().hex[:8]}@example.com",
        display_name="SYNTHETIC Person",
        active=active,
    )
    session.add(user)
    session.flush()
    return user


# --- criterion 1: no password authentication exists ----------------------------------------------


def test_no_session_or_identity_table_stores_a_secret(db_session: Session) -> None:
    """§12.2, asserted against the *migrated* schema.

    The models are not the thing that must stay clean — the database is. A later migration could
    add a column no model names, and this is what would catch it.
    """
    columns = (
        db_session.execute(
            text(
                "SELECT table_name || '.' || column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name IN "
                "('app_user', 'user_session', 'service_identity', 'channel_identity')"
            )
        )
        .scalars()
        .all()
    )

    forbidden = [
        name
        for name in columns
        # `token_hash` is deliberately excluded by name: it is a hash *of a session token*, not a
        # credential the user knows, and the test would be useless if it could not tell them
        # apart. Every other "hash"-shaped column is a finding.
        if name != "user_session.token_hash"
        and any(word in name.lower() for word in ("password", "passwd", "secret", "credential"))
    ]
    assert forbidden == [], f"§12.2 forbids password authentication; found {forbidden}"


def test_the_identity_module_contains_no_password_verification() -> None:
    """The other half: a column is not the only way to build password auth.

    A `verify_password` helper with the hash kept elsewhere would pass the schema check above and
    be exactly the thing §12.2 rejects.
    """
    identity = Path(__file__).resolve().parents[1] / "app" / "identity"
    offenders = [
        path.name
        for path in identity.rglob("*.py")
        if any(
            marker in path.read_text(encoding="utf-8").lower()
            for marker in (
                "bcrypt",
                "scrypt",
                "argon2",
                "pbkdf2",
                "check_password",
                "verify_password",
            )
        )
    ]

    assert offenders == []


def test_the_token_itself_is_never_stored(db_session: Session) -> None:
    """A database dump must contain nothing replayable as a session."""
    user = make_user(db_session)

    issued = issue_session(db_session, user, issued_via="test", at=NOW)

    stored = db_session.execute(select(UserSession)).scalars().one()
    assert stored.token_hash == hash_token(issued.token)
    assert issued.token not in stored.token_hash
    assert len(stored.token_hash) == 64


def test_two_sessions_cannot_share_a_token(db_session: Session) -> None:
    user = make_user(db_session)
    first = issue_session(db_session, user, issued_via="test", at=NOW)

    db_session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(first.token),
            issued_at=NOW,
            expires_at=NOW + DEFAULT_SESSION_TTL,
            issued_via="test",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- criterion 2: the stub is refused outside local ----------------------------------------------


@pytest.mark.parametrize("env", [AppEnv.TEST, AppEnv.STAGING, AppEnv.PRODUCTION])
def test_the_stub_is_refused_outside_local(db_session: Session, env: AppEnv) -> None:
    """Criterion 2, over every environment that is not `local`.

    `TEST` is in this list, not in the allow-list: a stub that worked under `APP_ENV=test` would
    be one environment away from working anywhere, and the tests that need it pass `LOCAL`
    explicitly.
    """
    user = make_user(db_session)

    with pytest.raises(StubRefused):
        stub_sign_in(db_session, user.email, settings=Settings(app_env=env), at=NOW)


@pytest.mark.parametrize("env", [AppEnv.TEST, AppEnv.STAGING, AppEnv.PRODUCTION])
def test_a_refused_stub_issues_no_session(db_session: Session, env: AppEnv) -> None:
    """Refused *before touching the database*, so a rejected attempt leaves nothing behind."""
    user = make_user(db_session)

    with pytest.raises(StubRefused):
        stub_sign_in(db_session, user.email, settings=Settings(app_env=env), at=NOW)

    assert db_session.execute(select(func.count()).select_from(UserSession)).scalar_one() == 0


def test_the_allow_list_names_only_local() -> None:
    """An allow-list, not a denial of production: a `preview` environment added tomorrow is
    refused until someone decides otherwise."""
    assert frozenset({AppEnv.LOCAL}) == ALLOWED_ENVIRONMENTS


def test_the_refusal_names_what_would_be_needed() -> None:
    """An operator who hits this should learn why, not just that."""
    with pytest.raises(StubRefused, match="Q-026"):
        require_stub_allowed(Settings(app_env=AppEnv.PRODUCTION))


def test_the_stub_signs_in_an_existing_local_user(db_session: Session) -> None:
    user = make_user(db_session)

    issued = stub_sign_in(db_session, user.email, settings=LOCAL, at=NOW)

    assert issued.session.user_id == user.id
    assert issued.session.issued_via == ISSUED_VIA, "an auditor must be able to spot a stub session"


def test_the_stub_creates_nobody(db_session: Session) -> None:
    """An unknown email is refused. Auto-provisioning would mean the roster grew by whoever typed
    something, and `Q-005`/`Q-026` leave the real roster undecided."""
    with pytest.raises(UnknownStubUser):
        stub_sign_in(db_session, "synthetic.nobody@example.com", settings=LOCAL, at=NOW)

    assert db_session.execute(select(func.count()).select_from(User)).scalar_one() == 0


def test_the_stub_accepts_the_address_as_typed(db_session: Session) -> None:
    """Emails are stored lowercase (`T-012`); a developer typing a capital should get a session,
    not a confusing "no such user"."""
    user = make_user(db_session, email="synthetic.casing@example.com")

    issued = stub_sign_in(db_session, "  SYNTHETIC.Casing@Example.com  ", settings=LOCAL, at=NOW)

    assert issued.session.user_id == user.id


# --- criterion 3: sessions expire and can be revoked ---------------------------------------------


def test_a_live_session_resolves_to_its_user(db_session: Session) -> None:
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW)

    principal = resolve(db_session, issued.token, at=NOW + timedelta(hours=1))

    assert principal is not None
    assert principal.user.id == user.id


def test_an_expired_session_resolves_to_nobody(db_session: Session) -> None:
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW, ttl=timedelta(minutes=30))

    assert resolve(db_session, issued.token, at=NOW + timedelta(minutes=31)) is None


def test_a_revoked_session_resolves_to_nobody(db_session: Session) -> None:
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW)

    revoke(db_session, issued.session, revoked_by="operator-1", reason="SYNTHETIC", at=NOW)

    assert resolve(db_session, issued.token, at=NOW + timedelta(minutes=1)) is None


def test_an_unknown_token_resolves_to_nobody(db_session: Session) -> None:
    assert resolve(db_session, "synthetic-not-a-real-token", at=NOW) is None


def test_a_deactivated_user_stops_resolving(db_session: Session) -> None:
    """`T-012` keeps the row for attribution. A row kept for history must not be one that logs
    in — including through a session issued before the deactivation."""
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW)

    user.active = False
    db_session.flush()

    assert resolve(db_session, issued.token, at=NOW + timedelta(minutes=1)) is None


def test_a_deactivated_user_cannot_be_issued_a_session(db_session: Session) -> None:
    user = make_user(db_session, active=False)

    with pytest.raises(SessionError):
        issue_session(db_session, user, issued_via="test", at=NOW)


def test_revocation_is_attributed(db_session: Session) -> None:
    """§12.2's attribution requirement does not stop at events people cause deliberately."""
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW)

    revoke(db_session, issued.session, revoked_by="operator-1", reason="SYNTHETIC reason", at=NOW)

    assert issued.session.revoked_by == "operator-1"
    assert issued.session.revocation_reason == "SYNTHETIC reason"


def test_a_revocation_cannot_be_unattributed(db_session: Session) -> None:
    """The constraint, not the function: a row revoked with nobody named is refused."""
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW)

    issued.session.revoked_at = NOW

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_revoking_twice_keeps_the_first_decision(db_session: Session) -> None:
    """The question an auditor asks is *when did this stop being valid and who decided*. A second
    revocation overwriting the answer would move the moment it ended."""
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW)
    revoke(db_session, issued.session, revoked_by="operator-1", reason="first", at=NOW)

    revoke(
        db_session,
        issued.session,
        revoked_by="operator-2",
        reason="second",
        at=NOW + timedelta(hours=1),
    )

    assert issued.session.revoked_by == "operator-1"
    assert issued.session.revoked_at == NOW


def test_every_session_a_user_holds_can_be_ended_at_once(db_session: Session) -> None:
    """What "revocable" means in practice: an administrator disabling someone needs one call,
    not a list of ids they would have to enumerate correctly."""
    user = make_user(db_session)
    tokens = [issue_session(db_session, user, issued_via="test", at=NOW).token for _ in range(3)]

    ended = revoke_all_for_user(
        db_session, user, revoked_by="operator-1", reason="SYNTHETIC", at=NOW
    )

    assert ended == 3
    for token in tokens:
        assert resolve(db_session, token, at=NOW + timedelta(minutes=1)) is None


def test_revoking_all_leaves_another_users_sessions_alone(db_session: Session) -> None:
    first = make_user(db_session)
    second = make_user(db_session)
    kept = issue_session(db_session, second, issued_via="test", at=NOW)
    issue_session(db_session, first, issued_via="test", at=NOW)

    revoke_all_for_user(db_session, first, revoked_by="operator-1", reason="SYNTHETIC", at=NOW)

    assert resolve(db_session, kept.token, at=NOW + timedelta(minutes=1)) is not None


def test_a_session_cannot_expire_before_it_is_issued(db_session: Session) -> None:
    """The database's own check. A session that starts expired is a bug that would otherwise
    resolve to nobody and look like a mysterious sign-in failure."""
    user = make_user(db_session)

    db_session.add(
        UserSession(
            user_id=user.id,
            token_hash="a" * 64,
            issued_at=NOW,
            expires_at=NOW - timedelta(minutes=1),
            issued_via="test",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_zero_or_negative_ttl_is_refused(db_session: Session) -> None:
    user = make_user(db_session)

    with pytest.raises(SessionError):
        issue_session(db_session, user, issued_via="test", at=NOW, ttl=timedelta(0))


def test_the_default_session_is_short(db_session: Session) -> None:
    """§12.2 asks for short sessions. Pinned so lengthening it is a deliberate edit with a test
    to change, not a default that drifts."""
    assert timedelta(hours=8) == DEFAULT_SESSION_TTL


# --- criterion 4: a session is a human's ---------------------------------------------------------


def test_a_session_belongs_to_a_user_that_exists(db_session: Session) -> None:
    db_session.add(
        UserSession(
            user_id=uuid.uuid4(),
            token_hash="b" * 64,
            issued_at=NOW,
            expires_at=NOW + DEFAULT_SESSION_TTL,
            issued_via="test",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_service_identity_cannot_hold_a_session(db_session: Session) -> None:
    """Criterion 4. The foreign key is to `app_user`, and a service identity is a different
    table — so this is refused by the schema, not by a check someone could forget to call."""
    service = ServiceIdentity(name="synthetic-worker", purpose="SYNTHETIC")
    db_session.add(service)
    db_session.flush()

    db_session.add(
        UserSession(
            user_id=service.id,
            token_hash="c" * 64,
            issued_at=NOW,
            expires_at=NOW + DEFAULT_SESSION_TTL,
            issued_via="test",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_principal_carries_its_roles(db_session: Session) -> None:
    """`T-062` checks against one object rather than re-querying."""
    user = make_user(db_session)
    viewer = db_session.execute(select(Role).where(Role.key == RoleKey.VIEWER.value)).scalar_one()
    db_session.add(UserRole(user_id=user.id, role_id=viewer.id, granted_by="operator-1"))
    db_session.flush()
    issued = issue_session(db_session, user, issued_via="test", at=NOW)

    principal = resolve(db_session, issued.token, at=NOW)

    assert principal is not None
    assert principal.roles == frozenset({RoleKey.VIEWER.value})


def test_a_principal_with_no_roles_still_resolves(db_session: Session) -> None:
    """Authentication and authorization are different questions. Someone with no roles is signed
    in and permitted nothing, which is `T-062`'s answer to give, not this module's."""
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW)

    principal = resolve(db_session, issued.token, at=NOW)

    assert principal is not None
    assert principal.roles == frozenset()


def test_the_actor_is_derived_from_the_session_not_supplied(db_session: Session) -> None:
    """§12.2's immutable attribution: an `Actor` a caller could pass in is one they chose."""
    user = make_user(db_session)
    issued = issue_session(db_session, user, issued_via="test", at=NOW)
    principal = resolve(db_session, issued.token, at=NOW)

    assert principal is not None
    assert principal.actor.type is ActorType.HUMAN
    assert principal.actor.id == str(user.id)
    assert "actor" not in {field for field in Principal.__dataclass_fields__}
