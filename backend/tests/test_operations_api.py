"""The operations read view (T-069a; §17.5, §17.6, §12.1).

Every counter is asserted by **moving it**: seed a row, read the overview, see the number change.
A test that only checked the field was present would pass against an endpoint returning zeroes
for everything, which is the failure mode of a dashboard — it looks fine, and it is lying.

The authorization tests run over **every role**, not one allowed and one denied. A matrix tested
at two points has holes in the middle, and this route reports dead-job reasons and which safety
switches are thrown.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.flags import (
    FlagKey,
    is_set,
    outbound_email_allowed,
    set_flag,
)
from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor, record_audit_event
from app.core.lifecycles import JobState, OutreachThreadState
from app.core.settings import AppEnv, Settings, get_settings
from app.db.session import dispose_engines
from app.identity.dependencies import SESSION_COOKIE, db_session
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.rbac import PERMISSION_TIERS, Permission, Tier, permission_for
from app.identity.sessions import issue_session
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.outbox import RECHECK_REFUSED_ACTION, enqueue_outbox_event
from app.main import create_app
from app.outreach_and_replies.models import OutreachThread
from app.outreach_and_replies.preconditions import Recheck
from tests.test_revision_validation import World as ValidWorld

OPERATOR = Actor(type=ActorType.HUMAN, id="admin-1")
OVERVIEW = "/api/operations/overview"

#: Shadow mode off in configuration, so the *flag* half of `shadow_mode_active` is observable.
#: With the default `shadow_mode=True` the endpoint would answer `True` whatever the flag said,
#: and the test would pass against an implementation that ignored the database entirely.
FLAG_VISIBLE_SETTINGS = Settings(app_env=AppEnv.TEST, shadow_mode=False)


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-operations-test")


@pytest.fixture
def db_session_for_api(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def client(db_session_for_api: Session) -> Iterator[TestClient]:
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session_for_api
    app.dependency_overrides[get_settings] = lambda: FLAG_VISIBLE_SETTINGS
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    dispose_engines()


def a_user(session: Session, role: RoleKey) -> User:
    user = User(
        email=f"synthetic.{uuid.uuid4().hex[:8]}@example.com",
        display_name="SYNTHETIC User",
        active=True,
    )
    session.add(user)
    session.flush()
    found = session.execute(select(Role).where(Role.key == role.value)).scalar_one()
    session.add(UserRole(user_id=user.id, role_id=found.id, granted_by="synthetic-admin"))
    session.flush()
    return user


def headers_for(session: Session, role: RoleKey) -> dict[str, str]:
    token = issue_session(session, a_user(session, role), issued_via="test").token
    return {"authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(db_session: Session) -> dict[str, str]:
    return headers_for(db_session, RoleKey.SYSTEM_ADMINISTRATOR)


def overview(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    response = client.get(OVERVIEW, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def a_job(session: Session, state: JobState, **overrides: object) -> Job:
    """A job row directly, rather than through `enqueue`.

    `enqueue` validates the payload against the registered model for the job type, so seeding a
    `dead` job through it would mean registering a fake type first. What this suite needs is a row
    in a given state; the states themselves are `T-030`'s to police.
    """
    fields: dict[str, object] = {
        "job_type": "synthetic.job",
        "state": state,
        "payload": {},
        "next_run_at": datetime.now(UTC),
        "correlation_id": "corr-operations-test",
    }
    fields.update(overrides)
    job = Job(**fields)  # type: ignore[arg-type]
    session.add(job)
    session.flush()
    return job


# --- criterion 3: administrator only, checked over every role ------------------------------------


@pytest.mark.parametrize(
    "role", [role for role in RoleKey if role is not RoleKey.SYSTEM_ADMINISTRATOR], ids=str
)
def test_every_other_role_is_refused(
    client: TestClient, db_session: Session, role: RoleKey
) -> None:
    """Every role, not one of them. §7.4 tier 5 is administrator-only by construction."""
    response = client.get(OVERVIEW, headers=headers_for(db_session, role))

    assert response.status_code == 403, f"{role} was allowed: {response.text}"


def test_the_administrator_is_allowed(client: TestClient, admin_headers: dict[str, str]) -> None:
    """The other direction, so the refusals above are refusals of something that otherwise works."""
    assert client.get(OVERVIEW, headers=admin_headers).status_code == 200


def test_no_session_is_refused(client: TestClient) -> None:
    assert client.get(OVERVIEW).status_code == 401


def test_the_route_is_declared_at_tier_five_under_its_own_permission() -> None:
    """Structural. A read, and still administrative: dead-job reasons and which switches are
    thrown are the operator's map and would equally be an attacker's — so it is its own
    permission rather than `VIEW_STATUS`, which every role holds."""
    declared = permission_for("GET", OVERVIEW)

    assert declared is Permission.VIEW_OPERATIONS
    assert PERMISSION_TIERS[Permission.VIEW_OPERATIONS] is Tier.ADMINISTRATIVE
    assert declared is not Permission.VIEW_STATUS


# --- criterion 1: shadow mode and the flags in force ----------------------------------------------


def test_shadow_mode_is_reported_from_the_flag_as_well_as_configuration(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    """`shadow_mode_active` is configuration **or** the database flag. Settings say `False` here,
    so a `True` answer can only have come from the flag — an implementation reading only settings
    would fail this and pass a test that used the default."""
    assert overview(client, admin_headers)["shadow_mode"] is False

    set_flag(
        db_session,
        key=FlagKey.SHADOW_MODE,
        enabled=True,
        reason="SYNTHETIC incident",
        actor=OPERATOR,
    )
    db_session.flush()

    assert overview(client, admin_headers)["shadow_mode"] is True


def test_the_flags_in_force_are_listed(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    """An operator reading "paused" needs to know it is a switch rather than an outage."""
    assert overview(client, admin_headers)["flags_in_force"] == []

    set_flag(
        db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, reason="SYNTHETIC pause", actor=OPERATOR
    )
    db_session.flush()

    assert overview(client, admin_headers)["flags_in_force"] == ["global_pause"]


def test_a_switched_off_flag_is_not_in_force(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    """The row exists once a flag has ever been thrown. Listing it while it is off would tell an
    operator the system is paused when it is running."""
    set_flag(
        db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, reason="SYNTHETIC pause", actor=OPERATOR
    )
    set_flag(
        db_session,
        key=FlagKey.GLOBAL_PAUSE,
        enabled=False,
        reason="SYNTHETIC resume",
        actor=OPERATOR,
    )
    db_session.flush()

    assert overview(client, admin_headers)["flags_in_force"] == []


# --- criterion 2: every counter moves when a real row appears -------------------------------------


def test_queue_depth_counts_real_jobs(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    before = overview(client, admin_headers)["jobs_by_state"]
    assert isinstance(before, dict)

    a_job(db_session, JobState.QUEUED)
    a_job(db_session, JobState.QUEUED)

    after = overview(client, admin_headers)["jobs_by_state"]
    assert isinstance(after, dict)
    assert after.get("queued", 0) == before.get("queued", 0) + 2


def test_the_oldest_queued_job_age_is_reported(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    """An age, not a timestamp: the question during an incident is "how far behind", and a
    reader should not have to subtract."""
    assert overview(client, admin_headers)["oldest_queued_job_age_seconds"] is None

    a_job(db_session, JobState.QUEUED, created_at=datetime.now(UTC) - timedelta(hours=2))

    age = overview(client, admin_headers)["oldest_queued_job_age_seconds"]
    assert isinstance(age, int)
    assert age >= 7000


def test_an_empty_queue_reports_no_age_rather_than_zero(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """`None` and `0` are different answers — nothing waiting, and something that arrived this
    instant — and an operator reads them differently."""
    assert overview(client, admin_headers)["oldest_queued_job_age_seconds"] is None


def test_dead_jobs_are_named_with_their_reasons(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    """A count answers "is something wrong"; the reason answers "what". §17.1 guarantees every
    dead job carries one, and a panel that showed only the number would send an operator to the
    database."""
    a_job(
        db_session,
        JobState.DEAD,
        last_error="SYNTHETIC permanent failure",
        requires_human_review=True,
    )

    body = overview(client, admin_headers)
    assert body["dead_jobs"] == 1
    sample = body["dead_job_sample"]
    assert isinstance(sample, list)
    assert sample[0]["reason"] == "SYNTHETIC permanent failure"
    assert sample[0]["requires_human_review"] is True


def test_the_outbox_backlog_counts_pending_events(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    enqueue_outbox_event(
        db_session,
        event_type="synthetic.event",
        idempotency_key="a" * 64,
        actor=OPERATOR,
        payload={},
    )
    db_session.flush()

    body = overview(client, admin_headers)
    assert body["outbox_pending"] == 1
    assert isinstance(body["oldest_pending_outbox_age_seconds"], int)


def test_delivery_ambiguous_threads_are_counted(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    """§17.3's "may have arrived" state, which is never retried blindly and always needs a human.

    The thread is constructed in the state rather than transitioned into it: `T-141` refuses a
    thread to leave `not_started` without a send command, and that lifecycle rule is its suite's
    to police. What this one needs is a row in the state, the same reason `a_job` writes directly.
    """
    assert overview(client, admin_headers)["delivery_ambiguous_threads"] == 0

    world = ValidWorld(db_session)
    db_session.add(
        OutreachThread(candidate_id=world.candidate.id, state=OutreachThreadState.DELIVERY_UNKNOWN)
    )
    db_session.flush()

    assert overview(client, admin_headers)["delivery_ambiguous_threads"] == 1


# --- criterion 4: an unmeasured metric is not a zero, and this one is now measured ---------------


def a_refusal(session: Session, check: str, scope: str | None = None) -> None:
    """One §11.4 recheck refusal in the trail, written the way `dispatch._settle` writes it.

    Constructed rather than provoked: the *writer's* payload contract is pinned in
    `tests/test_preconditions.py::test_a_suppressed_send_records_the_scope_that_matched`, which
    runs a real dispatch. What this file needs is rows, and standing up a full send world per row
    would test that suite's subject twice and this one's not at all.
    """
    payload: dict[str, object] = {"event_type": "send.email", "refused_check": check}
    if scope is not None:
        payload["refused_scope"] = scope
    record_audit_event(
        session,
        actor=OPERATOR,
        action=RECHECK_REFUSED_ACTION,
        entity_type="outbox_event",
        entity_id=uuid.uuid4(),
        payload=payload,
    )
    session.flush()


def test_suppressed_send_attempts_is_zero_when_nothing_has_been_refused(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """`T-161` criterion 2. It was `null` because nothing recorded an attempt; now something does,
    so a zero here is a measurement rather than the claim nobody checked."""
    body = overview(client, admin_headers)

    assert body["suppressed_send_attempts"] == 0
    assert body["not_measured"] == []


def test_suppressed_send_attempts_counts_attempts_not_recipients(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    # §17.5 asks for suppressed-send *attempts*. Counting the audit trail rather than outbox rows
    # is what makes the second refusal of the same event countable at all — an outbox row carries
    # only its last outcome.
    a_refusal(db_session, Recheck.SUPPRESSION.value, scope="email")
    assert overview(client, admin_headers)["suppressed_send_attempts"] == 1

    a_refusal(db_session, Recheck.SUPPRESSION.value, scope="email")
    assert overview(client, admin_headers)["suppressed_send_attempts"] == 2


def test_another_check_refusing_is_not_a_suppressed_send(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    # A paused campaign and a revoked approval also refuse a dispatch, and counting them here
    # would report an outage as a compliance signal.
    a_refusal(db_session, Recheck.CAMPAIGN_STATUS.value)
    a_refusal(db_session, Recheck.APPROVAL_VALIDITY.value)

    assert overview(client, admin_headers)["suppressed_send_attempts"] == 0


def test_the_not_measured_list_no_longer_names_this_metric(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    # The field stays as the mechanism for the next gap. What must not survive is a response that
    # still says "not measured" about a number the same response now reports.
    body = overview(client, admin_headers)

    assert not any("T-161" in note for note in body["not_measured"])
    assert not any("suppress" in note.lower() for note in body["not_measured"])


# --- T-069b: the §17.6 controls -----------------------------------------------------------------
#
# The switches that stop the system. Two properties matter more than the happy path: nobody but
# the administrator can reach them, and **releasing one cannot start anything** — the flags are
# one half of an `and`, and configuration is the other.

#: The system-wide switches this endpoint owns. Scoped keys address one product or claim version
#: and are refused; disabling a named claim is a products-and-claims authority, not the pause
#: button's.
SYSTEM_WIDE_KEYS = [
    FlagKey.GLOBAL_PAUSE,
    FlagKey.SHADOW_MODE,
    FlagKey.OUTBOUND_EMAIL_DISABLED,
]


def flag_url(key: FlagKey) -> str:
    return f"/api/operations/flags/{key.value}"


def throw(
    client: TestClient,
    key: FlagKey,
    headers: dict[str, str],
    *,
    enabled: bool = True,
    reason: str = "SYNTHETIC incident",
):
    return client.post(flag_url(key), json={"enabled": enabled, "reason": reason}, headers=headers)


# --- criterion 2: administrator only, every control, every role ----------------------------------


@pytest.mark.parametrize("key", SYSTEM_WIDE_KEYS, ids=lambda key: key.value)
@pytest.mark.parametrize(
    "role", [role for role in RoleKey if role is not RoleKey.SYSTEM_ADMINISTRATOR], ids=str
)
def test_no_other_role_may_throw_any_switch(
    client: TestClient, db_session: Session, key: FlagKey, role: RoleKey
) -> None:
    """Every control against every role, rather than one of each: a matrix tested at two points
    has holes in the middle, and these are the switches that stop outreach."""
    response = throw(client, key, headers_for(db_session, role))

    assert response.status_code == 403, f"{role} threw {key.value}: {response.text}"


@pytest.mark.parametrize("key", SYSTEM_WIDE_KEYS, ids=lambda key: key.value)
def test_a_refused_caller_changes_nothing(
    client: TestClient, db_session: Session, key: FlagKey
) -> None:
    """A `403` that had already written the flag would be a refusal in name only."""
    throw(client, key, headers_for(db_session, RoleKey.OPERATOR_REVIEWER))

    assert not is_set(db_session, key)


@pytest.mark.parametrize("key", SYSTEM_WIDE_KEYS, ids=lambda key: key.value)
def test_the_administrator_may_throw_each_switch(
    client: TestClient, db_session: Session, key: FlagKey, admin_headers: dict[str, str]
) -> None:
    """The other direction, so the refusals above refuse something that otherwise works."""
    response = throw(client, key, admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True
    assert is_set(db_session, key)


def test_no_session_cannot_throw_a_switch(client: TestClient) -> None:
    assert throw(client, FlagKey.GLOBAL_PAUSE, {}).status_code == 401


def test_a_cookie_without_a_csrf_token_cannot_throw_a_switch(
    client: TestClient, db_session: Session
) -> None:
    """`T-070a`'s protection, on the one route where a forged request would stop the business."""
    token = issue_session(
        db_session, a_user(db_session, RoleKey.SYSTEM_ADMINISTRATOR), issued_via="test"
    ).token
    client.cookies.set(SESSION_COOKIE, token)

    response = client.post(
        flag_url(FlagKey.GLOBAL_PAUSE), json={"enabled": True, "reason": "SYNTHETIC"}
    )

    assert response.status_code == 403
    assert not is_set(db_session, FlagKey.GLOBAL_PAUSE)


def test_the_route_is_declared_under_the_pause_permission() -> None:
    """Structural, and it pins the tier: §7.4 tier 5 is never delegated, and reusing a lower-tier
    permission here would put the stop switches behind an authority somebody else holds."""
    declared = permission_for("POST", "/api/operations/flags/{key}")

    assert declared is Permission.PAUSE_SYSTEM
    assert PERMISSION_TIERS[Permission.PAUSE_SYSTEM] is Tier.ADMINISTRATIVE


# --- criterion 1: the audit event ----------------------------------------------------------------


@pytest.mark.parametrize("enabled", [True, False], ids=["thrown", "released"])
def test_throwing_a_switch_writes_an_audit_event(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], enabled: bool
) -> None:
    """Both directions. Releasing a pause is the more consequential half and is exactly what an
    incident review asks about, so it is audited on the same terms."""
    response = throw(
        client, FlagKey.GLOBAL_PAUSE, admin_headers, enabled=enabled, reason="SYNTHETIC reason"
    )
    assert response.status_code == 200, response.text

    event = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="operational_flag")
        .order_by(AuditEvent.occurred_at.desc())
        .first()
    )
    assert event is not None
    assert event.action == ("flag.enabled" if enabled else "flag.disabled")
    assert event.payload["reason"] == "SYNTHETIC reason"
    assert event.payload["key"] == FlagKey.GLOBAL_PAUSE.value


def test_the_audit_actor_is_the_signed_in_administrator(
    client: TestClient, db_session: Session
) -> None:
    """§15.1: attribution comes from the session, never from the request."""
    user = a_user(db_session, RoleKey.SYSTEM_ADMINISTRATOR)
    token = issue_session(db_session, user, issued_via="test").token

    throw(client, FlagKey.GLOBAL_PAUSE, {"authorization": f"Bearer {token}"})

    event = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="operational_flag")
        .order_by(AuditEvent.occurred_at.desc())
        .first()
    )
    assert event is not None
    assert event.actor_id == str(user.id)


# --- criterion 3: a switch thrown for no stated reason is refused --------------------------------


@pytest.mark.parametrize("reason", ["", "   "], ids=["empty", "whitespace"])
def test_a_switch_with_no_reason_is_refused(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], reason: str
) -> None:
    """§17.6 wants operational actions explicable. A whitespace reason satisfies a `min_length`
    schema and explains nothing, which is why `set_flag` strips before checking — both shapes are
    refused, and nothing is written."""
    response = throw(client, FlagKey.GLOBAL_PAUSE, admin_headers, reason=reason)

    assert response.status_code in {400, 422}, response.text
    assert not is_set(db_session, FlagKey.GLOBAL_PAUSE)


# --- the property an operator is trusting: a switch can only ever stop things --------------------


def test_releasing_every_switch_cannot_enable_outbound_email(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    """The flags are one half of an `and`; configuration is the other. An administrator releasing
    every switch must not thereby start anything — live sending is gated (**G-07**) and
    `outbound_email_enabled` is `False`. This is the pause button not being a start button."""
    for key in SYSTEM_WIDE_KEYS:
        assert throw(client, key, admin_headers, enabled=False).status_code == 200

    assert not outbound_email_allowed(db_session, FLAG_VISIBLE_SETTINGS)


def test_a_scoped_key_is_refused(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
) -> None:
    """A scoped key addresses one product or claim version and needs a  this route does
    not take, so it cannot be thrown here.

    The refusal comes from , and the endpoint deliberately carries no second check of
    its own: a control proved that check dead — deleting it changed nothing — and the store is the
    authority on flag shape. Asserted on the store's own wording so that if the refusal is ever
    removed, this notices."""
    response = throw(client, FlagKey.PRODUCT_DISABLED, admin_headers)

    assert response.status_code == 400
    assert "scope" in response.json()["detail"]
    assert not is_set(db_session, FlagKey.PRODUCT_DISABLED)


def test_the_response_says_what_happens_next(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """An administrator throwing a switch during an incident deserves to know when it bites and
    what it cannot do."""
    body = throw(client, FlagKey.SHADOW_MODE, admin_headers).json()

    assert "G-07" in body["what_happens_next"]
    assert body["shadow_mode"] is True
