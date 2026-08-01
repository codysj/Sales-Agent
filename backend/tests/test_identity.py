"""Identity and access (T-012; §14.1, §12.1, §12.2).

Three things are worth testing here, and none of them is "the ORM can save a row":

* **The six roles exist because a migration put them there.** Reference data an authorization
  check looks up has to arrive with the schema. A role that appears only after someone remembers
  to run a seeder is a role that is missing at 3am.
* **A channel identity cannot float free.** §12.2 maps messaging identities onto an existing
  user; an unmapped handle would let an inbound WhatsApp message resolve to *someone*.
* **A service cannot hold a role that decides anything.** §3.5 and ADR-008 keep approval with
  humans, and the enforcement is a composite foreign key rather than a convention — so the test
  is an insert the database refuses, not a call the application declines.

Every test below runs against the migrated schema (`conftest.py` builds it with `alembic upgrade
head`, never `metadata.create_all`), so a constraint that exists only in the model metadata would
fail here rather than pass.
"""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
import structlog
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.identity.models import (
    HUMAN_ONLY_ROLES,
    ROLE_RESPONSIBILITIES,
    ChannelIdentity,
    ChannelType,
    Role,
    RoleKey,
    ServiceIdentity,
    ServiceIdentityRole,
    User,
    UserRole,
)


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-identity-test")


#: The migration under test. Loaded by path — see `test_role_ids_are_stable_across_a_rebuild`.
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "ba1a2b2420a4_identity_and_access_tables.py"
)


def migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("identity_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def role_named(session: Session, key: RoleKey) -> Role:
    return session.execute(select(Role).where(Role.key == key.value)).scalar_one()


def make_user(session: Session, *, email: str | None = None) -> User:
    user = User(
        email=email or f"synthetic.{uuid.uuid4().hex[:8]}@example.com",
        display_name="SYNTHETIC Person",
    )
    session.add(user)
    session.flush()
    return user


def make_service(session: Session) -> ServiceIdentity:
    service = ServiceIdentity(
        name=f"synthetic-service-{uuid.uuid4().hex[:8]}",
        purpose="SYNTHETIC service identity for tests.",
    )
    session.add(service)
    session.flush()
    return service


# --- criterion 1: the six roles are seeded by migration ------------------------------------------


def test_the_six_roles_are_seeded(db_session: Session) -> None:
    """§12.1's table, in the database, put there by `ba1a2b2420a4` and nothing else."""
    seeded = set(db_session.execute(select(Role.key)).scalars().all())

    assert seeded == {role.value for role in RoleKey}
    assert len(seeded) == 6


def test_each_seeded_role_carries_its_responsibility(db_session: Session) -> None:
    """The words are §12.1's. A role whose description drifted would be a role a reviewer
    understood differently from the specification."""
    for key, responsibility in ROLE_RESPONSIBILITIES.items():
        assert role_named(db_session, key).responsibility == responsibility


def test_the_migration_seed_agrees_with_the_module(db_session: Session) -> None:
    """The migration hard-codes the roles rather than importing `app.identity.models`.

    That is deliberate — a migration that imported application code would seed whatever the code
    says *today*, so replaying history would build a different database than it originally did.
    The cost is two copies, and this is the test that keeps them honest.
    """
    for key in RoleKey:
        expected = key in HUMAN_ONLY_ROLES
        assert role_named(db_session, key).human_only is expected, (
            f"{key.value}: the migration seed and HUMAN_ONLY_ROLES disagree"
        )


def test_exactly_one_role_may_be_held_by_a_service(db_session: Session) -> None:
    """Five of six decide something. `viewer` is the exception because reading authorizes
    nothing — a reporting job may legitimately hold it."""
    machine_assignable = (
        db_session.execute(select(Role.key).where(Role.human_only.is_(False))).scalars().all()
    )

    assert list(machine_assignable) == [RoleKey.VIEWER.value]


def test_role_ids_are_stable_across_a_rebuild(db_session: Session) -> None:
    """Deterministic `uuid5` IDs, so a `user_role` row dumped from one database and loaded into a
    freshly migrated one still points at the same role.

    The migration is loaded by path rather than imported: `alembic/versions/` is not a package,
    and making it one so a test could import it would change how alembic discovers revisions for
    the sake of one assertion.
    """
    namespace = migration_module().ROLE_NAMESPACE

    for key in RoleKey:
        assert role_named(db_session, key).id == uuid.uuid5(namespace, key.value)


def test_a_role_key_cannot_be_duplicated(db_session: Session) -> None:
    db_session.add(
        Role(key=RoleKey.VIEWER.value, responsibility="SYNTHETIC duplicate", human_only=False)
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- criterion 2: a channel identity cannot exist without a user ---------------------------------


def test_a_channel_identity_maps_to_a_user(db_session: Session) -> None:
    user = make_user(db_session)

    db_session.add(
        ChannelIdentity(
            user_id=user.id, channel=ChannelType.WHATSAPP, address="+SYNTHETIC-WHATSAPP-1"
        )
    )
    db_session.flush()

    stored = db_session.execute(select(ChannelIdentity)).scalars().one()
    assert stored.user_id == user.id
    assert stored.verified is False, "an unconfirmed handle claiming to be someone is not trusted"


def test_a_channel_identity_cannot_name_a_user_that_does_not_exist(db_session: Session) -> None:
    """The foreign key, not the application. An inbound message from an unmapped handle must
    have nobody to resolve to (§12.2)."""
    db_session.add(
        ChannelIdentity(
            user_id=uuid.uuid4(), channel=ChannelType.IMESSAGE, address="+SYNTHETIC-IMESSAGE-1"
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_channel_identity_cannot_omit_its_user(db_session: Session) -> None:
    """`NOT NULL`, so "an unmapped handle" is unrepresentable rather than merely discouraged."""
    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.execute(
            text(
                "INSERT INTO channel_identity "
                "(id, user_id, channel, address, verified, created_at, updated_at) "
                "VALUES (:id, NULL, 'WHATSAPP', '+SYNTHETIC-ORPHAN', false, now(), now())"
            ),
            {"id": uuid.uuid4()},
        )


def test_one_address_maps_to_one_user(db_session: Session) -> None:
    """Two users claiming one handle is an inbound message with an ambiguous sender."""
    first = make_user(db_session)
    second = make_user(db_session)
    db_session.add(
        ChannelIdentity(user_id=first.id, channel=ChannelType.WHATSAPP, address="+SYNTHETIC-SHARED")
    )
    db_session.flush()

    db_session.add(
        ChannelIdentity(
            user_id=second.id, channel=ChannelType.WHATSAPP, address="+SYNTHETIC-SHARED"
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_same_address_on_two_channels_is_allowed(db_session: Session) -> None:
    """A phone number is a WhatsApp handle *and* an iMessage handle. The uniqueness is per
    channel, not per string."""
    user = make_user(db_session)

    for channel in (ChannelType.WHATSAPP, ChannelType.IMESSAGE):
        db_session.add(ChannelIdentity(user_id=user.id, channel=channel, address="+SYNTHETIC-BOTH"))
    db_session.flush()

    assert db_session.execute(select(func.count()).select_from(ChannelIdentity)).scalar_one() == 2


# --- criterion 3: a service cannot hold a human-only role ----------------------------------------


def test_a_service_may_hold_the_viewer_role(db_session: Session) -> None:
    service = make_service(db_session)

    db_session.add(
        ServiceIdentityRole(
            service_identity_id=service.id,
            role_id=role_named(db_session, RoleKey.VIEWER).id,
            granted_by="operator-1",
        )
    )
    db_session.flush()

    assert (
        db_session.execute(select(func.count()).select_from(ServiceIdentityRole)).scalar_one() == 1
    )


@pytest.mark.parametrize("key", HUMAN_ONLY_ROLES, ids=lambda key: key.value)
def test_a_service_cannot_hold_a_human_only_role(db_session: Session, key: RoleKey) -> None:
    """Criterion 3, and the guarantee §3.5 and ADR-008 rest on.

    Refused by the composite foreign key `(role_id, human_only) -> role(id, human_only)`: the
    grant carries `human_only = false`, and a human-only role has no row matching that key. No
    trigger, no application check — an insert the database will not accept.
    """
    service = make_service(db_session)

    db_session.add(
        ServiceIdentityRole(
            service_identity_id=service.id,
            role_id=role_named(db_session, key).id,
            granted_by="operator-1",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_service_cannot_claim_a_human_only_role_by_lying_about_the_flag(
    db_session: Session,
) -> None:
    """The obvious way around the foreign key: set `human_only = true` so the composite key
    matches. The check constraint refuses that, so the two together leave no opening."""
    service = make_service(db_session)
    owner = role_named(db_session, RoleKey.PRODUCT_CLAIM_OWNER)

    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.execute(
            text(
                "INSERT INTO service_identity_role "
                "(id, service_identity_id, role_id, human_only, granted_by, "
                "created_at, updated_at) "
                "VALUES (:id, :service, :role, true, 'operator-1', now(), now())"
            ),
            {"id": uuid.uuid4(), "service": service.id, "role": owner.id},
        )


def test_a_human_may_hold_any_role(db_session: Session) -> None:
    """The other half: the restriction is on services, not on people. §12.1 says one person may
    hold several roles, and nothing here should make that harder."""
    user = make_user(db_session)

    for key in RoleKey:
        db_session.add(
            UserRole(
                user_id=user.id, role_id=role_named(db_session, key).id, granted_by="operator-1"
            )
        )
    db_session.flush()

    assert db_session.execute(select(func.count()).select_from(UserRole)).scalar_one() == 6


def test_a_role_cannot_be_granted_to_one_user_twice(db_session: Session) -> None:
    user = make_user(db_session)
    viewer = role_named(db_session, RoleKey.VIEWER).id
    db_session.add(UserRole(user_id=user.id, role_id=viewer, granted_by="operator-1"))
    db_session.flush()

    db_session.add(UserRole(user_id=user.id, role_id=viewer, granted_by="operator-2"))

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- §12.2: humans and services stay separate, and no password lives here -------------------------


def test_no_identity_table_has_a_password_column(db_session: Session) -> None:
    """§12.2 rejects custom password authentication outright.

    Asserted against the *migrated* schema rather than the models, because the thing that must
    not exist is a column in the database — and a future migration could add one without any
    model naming it.
    """
    columns = (
        db_session.execute(
            text(
                "SELECT table_name || '.' || column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name IN "
                "('app_user', 'service_identity', 'channel_identity', 'role', 'user_role', "
                "'service_identity_role')"
            )
        )
        .scalars()
        .all()
    )

    forbidden = [
        name
        for name in columns
        if any(word in name.lower() for word in ("password", "secret", "hash", "credential"))
    ]
    assert forbidden == [], f"§12.2 forbids password authentication; found {forbidden}"


def test_a_service_identity_is_not_a_user(db_session: Session) -> None:
    """Separate tables rather than a flag: a query that forgot to filter would return the wrong
    kind of principal, and here the type is simply wrong instead."""
    # A delta, not an absolute count: `T-136b` made the approver columns foreign keys, so the
    # `db_session` fixture now seeds the approver identities the suite names. What this test means
    # is "creating a service creates no user", and the delta says exactly that.
    before = db_session.execute(select(func.count()).select_from(User)).scalar_one()

    make_service(db_session)

    assert db_session.execute(select(func.count()).select_from(User)).scalar_one() == before
    assert not hasattr(ServiceIdentity, "roles"), (
        "a service's roles go through ServiceIdentityRole, which the database constrains"
    )


def test_a_user_is_deactivated_rather_than_deleted(db_session: Session) -> None:
    """§12.2 requires immutable actor attribution, and an audit event naming a row that no longer
    exists is attribution nobody can follow."""
    user = make_user(db_session)

    user.active = False
    db_session.flush()

    assert (
        db_session.execute(
            select(func.count()).select_from(User).where(User.id == user.id)
        ).scalar_one()
        == 1
    )


def test_an_email_must_be_stored_lowercase(db_session: Session) -> None:
    """The same rule `prospects` applies to contact addresses: a key compared in two spellings is
    a key that matches sometimes."""
    db_session.add(User(email="SYNTHETIC.Person@example.com", display_name="SYNTHETIC Person"))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_user_must_have_a_display_name(db_session: Session) -> None:
    """An audit trail naming a blank is attribution in form only."""
    db_session.add(User(email="synthetic.blank@example.com", display_name="   "))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_users_cannot_share_a_provider_subject(db_session: Session) -> None:
    """One login must resolve to one person (`T-061` will depend on this)."""
    first = make_user(db_session)
    first.subject = "synthetic-subject-1"
    db_session.flush()

    second = make_user(db_session)
    second.subject = "synthetic-subject-1"

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_subject_is_optional_until_authentication_exists(db_session: Session) -> None:
    """`T-061` fills it in. Until then a user is identified by email, and requiring a subject
    would mean no user could be created at all."""
    user = make_user(db_session)

    assert user.subject is None
