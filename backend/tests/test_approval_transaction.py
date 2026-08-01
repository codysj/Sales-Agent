"""The §11.3 approval transaction, steps 2-6 (T-067a; §11.3, §11.4, §3.5, §7.2).

Four properties, and three of them are about what must *not* happen.

* **All three rows or none.** The approval, the send command, and the outbox event are one
  transaction. Proven by forcing a failure after the approval is written and asserting the
  database has none of them — not by reading the code and agreeing it looks atomic.
* **The recheck runs at approval time.** A reviewer read the card at some moment; §11.3 step 3
  exists because that moment has passed. Each thing that can change between reading and approving
  gets its own test, because a recheck that caught only the case somebody thought of is a recheck
  with holes in the middle.
* **Shadow mode changes nothing here, and the outbox event is still written.** This path causes no
  external effect at all — shadow mode is enforced at the adapter — and suppressing the record
  would lose the audit trail for a decision a human really made.
* **No agent callback anywhere in the path.** §11.3 ends "no agent callback is required" and §3.5
  forbids external execution authority held only by the agent runtime. Asserted by walking the
  module's transitive imports, because a callback three modules down would satisfy any test that
  only read this file.
"""

import ast
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import transition
from app.core.lifecycles import (
    ApprovalState,
    CampaignCandidateState,
    MessageRevisionState,
    OutreachThreadState,
)
from app.db.session import dispose_engines
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.approval import Approval
from app.identity.dependencies import SESSION_COOKIE, db_session
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.rbac import PERMISSION_TIERS, Permission, Tier, permission_for
from app.identity.sessions import issue_session, revoke
from app.jobs_and_outbox.outbox import OutboxEvent
from app.main import create_app
from app.outreach_and_replies.approve_message import (
    OUTBOX_EVENT_TYPE,
    ApprovalTransactionRefused,
    approve_message,
)
from app.outreach_and_replies.models import OutreachThread, SendCommand
from app.prospects.models import (
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from app.prospects.suppression import Suppression, SuppressionScope, SuppressionSource
from tests.factories import APPROVER, NOW
from tests.test_revision_validation import World as ValidWorld

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-approval-transaction-test")


class World(ValidWorld):
    """`tests/test_revision_validation.py`'s world, driven to the point of approval.

    Reused rather than rebuilt. What this task needs is "a revision that passes `T-055`", and that
    module already owns the definition — a second construction of it here would be a second thing
    to keep in step, and the copy that drifts is always the one whose suite is not about
    validation. The extension is only the two transitions: `T-055`'s world stops at `eligible`
    with a fresh revision, and step 2 of §11.3 starts from a candidate and a revision in review.
    """

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        for step in (
            CampaignCandidateState.RESEARCH_PENDING,
            CampaignCandidateState.RESEARCHED,
            CampaignCandidateState.REVIEW_PENDING,
        ):
            transition(session, self.candidate, step, actor=OPERATOR, reason="SYNTHETIC")
        revisions.transition(
            session, self.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
        )
        # `T-157`: an approval pins the claim set it was granted against, so a campaign without
        # one cannot be approved into at all. Published here rather than in the base world
        # because `T-055`'s suite is about individual claims.
        self.claim_set = self.publish_current_claim_set()


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


def counts(session: Session) -> tuple[int, int, int]:
    """`(approvals, send commands, outbox events)` — the three rows step 4 and 5 write."""
    return (
        session.execute(select(func.count()).select_from(Approval)).scalar_one(),
        session.execute(select(func.count()).select_from(SendCommand)).scalar_one(),
        session.execute(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type == OUTBOX_EVENT_TYPE)
        ).scalar_one(),
    )


def approve(world: World, **kwargs: object) -> object:
    return approve_message(
        world.session,
        world.revision,
        recipient=world.recipient,
        approver_id=APPROVER,
        actor=OPERATOR,
        **kwargs,  # type: ignore[arg-type]
    )


# --- criterion 1: one transaction, or none of it
# ---------------------------------------------------


def test_an_approval_writes_all_three_rows(db_session: Session, world: World) -> None:
    """Steps 4 and 5. The approval authorizes, the command orders, the event is what the worker
    will pick up (step 6)."""
    outcome = approve(world)

    assert counts(db_session) == (1, 1, 1)
    assert outcome.approval.state is ApprovalState.APPROVED
    assert outcome.send_command.message_revision_id == world.revision.id
    assert outcome.send_command.recipient_contact_point_id == world.recipient.id


def test_the_outbox_event_carries_the_commands_idempotency_key(
    db_session: Session, world: World
) -> None:
    """Same key, so a replay publishes no second event and the worker dispatches once (§11.4)."""
    outcome = approve(world)

    event = db_session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == OUTBOX_EVENT_TYPE)
    ).scalar_one()
    assert event.idempotency_key == outcome.send_command.idempotency_key


def test_a_failure_after_the_approval_leaves_nothing(db_session: Session, world: World) -> None:
    """The atomicity claim, proven by breaking it rather than by reading the code.

    The caller owns the transaction (§7.2), so the guarantee is that a rollback takes all three
    rows together — never an approval with no command, which is a record claiming an authorization
    that ordered nothing.
    """
    before = counts(db_session)
    savepoint = db_session.begin_nested()
    approve(world)
    assert counts(db_session) == (1, 1, 1)

    savepoint.rollback()

    assert counts(db_session) == before == (0, 0, 0)


def test_a_refusal_writes_nothing_at_all(db_session: Session, world: World) -> None:
    """Refusals happen before any write, so there is nothing for the caller to undo."""
    revisions.transition(
        db_session, world.revision, MessageRevisionState.SUPERSEDED, actor=OPERATOR
    )

    with pytest.raises(ApprovalTransactionRefused, match="review_pending"):
        approve(world)

    assert counts(db_session) == (0, 0, 0)


def test_the_thread_is_created_once_per_candidate(db_session: Session, world: World) -> None:
    """§8.1 makes the candidate the identity; a second thread would split one conversation across
    two records that each look complete."""
    approve(world)

    threads = (
        db_session.execute(
            select(OutreachThread).where(OutreachThread.candidate_id == world.candidate.id)
        )
        .scalars()
        .all()
    )
    assert len(threads) == 1
    # Still `not_started`: ordering is not sending, and the worker owns what happens next.
    assert threads[0].state is OutreachThreadState.NOT_STARTED


# --- criterion 2: the step 3 recheck
# ---------------------------------------------------------------


def test_a_superseded_revision_cannot_be_approved(db_session: Session, world: World) -> None:
    """§8.2 offers `review_pending -> approved` and no other edge."""
    revisions.transition(
        db_session, world.revision, MessageRevisionState.SUPERSEDED, actor=OPERATOR
    )

    with pytest.raises(ApprovalTransactionRefused):
        approve(world)


def test_a_suppressed_recipient_is_refused(db_session: Session, world: World) -> None:
    """Suppression can arrive between the reviewer reading the card and pressing approve — which
    is the entire reason §11.3 has a step 3."""
    db_session.add(
        Suppression(
            # `EMAIL` scope keys on the address; `PERSON` keys on the contact id. Pairing the
            # address with `PERSON` stores a row that matches nothing, which is a fixture that
            # silently tests the passing path.
            scope=SuppressionScope.EMAIL,
            identity=world.recipient.value,
            source=SuppressionSource.UNSUBSCRIBE,
            reason="SYNTHETIC: unsubscribed",
            effective_at=NOW - timedelta(days=1),
        )
    )
    db_session.flush()

    with pytest.raises(ApprovalTransactionRefused):
        approve(world)

    assert counts(db_session) == (0, 0, 0)


def test_an_unverified_recipient_is_refused(db_session: Session, world: World) -> None:
    world.recipient.verification_state = VerificationState.UNVERIFIED
    db_session.flush()

    with pytest.raises(ApprovalTransactionRefused):
        approve(world)

    assert counts(db_session) == (0, 0, 0)


def test_a_recipient_the_revision_was_not_written_to_is_refused(
    db_session: Session, world: World
) -> None:
    """ADR-008 approves a recipient and a revision *together*. A mismatch means the pair being
    approved is not the pair that was reviewed."""
    other = ContactPoint(
        contact_id=world.contact.id,
        type=ContactPointType.EMAIL,
        value=f"other-{uuid.uuid4().hex[:8]}@{world.account.domain}",
        verification_state=VerificationState.VERIFIED,
    )
    db_session.add(other)
    db_session.flush()

    with pytest.raises(ApprovalTransactionRefused, match="exact recipient"):
        approve_message(
            db_session,
            world.revision,
            recipient=other,
            approver_id=APPROVER,
            actor=OPERATOR,
        )

    assert counts(db_session) == (0, 0, 0)


def test_a_paused_campaign_is_refused(db_session: Session, world: World) -> None:
    """§11.3 step 3 rechecks the campaign. A campaign paused after review must stop the approval,
    not discover it at dispatch."""
    world.campaign.paused = True
    db_session.flush()

    with pytest.raises(ApprovalTransactionRefused):
        approve(world)

    assert counts(db_session) == (0, 0, 0)


def test_the_recheck_runs_at_approval_time_not_review_time(
    db_session: Session, world: World
) -> None:
    """The property behind every case above, stated once: a revision that passed when the reviewer
    opened the card is re-examined when they approve it."""
    assert approve(world) is not None

    # The same revision, approved a second time, is refused *as a decision* — the revision moved
    # to `approved`, so §8.2 offers no edge. Before the transaction transitioned the revision this
    # reached `uq_approval_live_per_revision` and failed as an integrity error instead, which is a
    # crash rather than a refusal and leaves the caller nothing to show a reviewer.
    with pytest.raises(ApprovalTransactionRefused, match="review_pending"):
        approve(world)


# --- criterion 3: shadow mode
# ----------------------------------------------------------------------


def test_shadow_mode_leaves_this_path_unchanged(db_session: Session, world: World) -> None:
    """Nothing here causes an external effect, so nothing here consults shadow mode.

    The guarantee is not "this function checks a flag" — it is that this function *cannot* send.
    Asserted as the absence of any send attempt or provider result, which is what an external
    effect would leave behind.
    """
    from app.outreach_and_replies.models import SendAttempt

    approve(world)

    attempts = db_session.execute(select(func.count()).select_from(SendAttempt)).scalar_one()
    assert attempts == 0


def test_the_outbox_event_is_written_under_shadow_mode(db_session: Session, world: World) -> None:
    """Suppressing the record would lose the audit trail for a decision a human really made. The
    event is the order; whether it is ever dispatched is the adapter's business."""
    approve(world)

    events = db_session.execute(
        select(func.count())
        .select_from(OutboxEvent)
        .where(OutboxEvent.event_type == OUTBOX_EVENT_TYPE)
    ).scalar_one()
    assert events == 1


def test_the_thread_never_leaves_not_started_here(db_session: Session, world: World) -> None:
    """Ordering is not sending. `T-141` refuses a thread to leave `not_started` without a send
    command; this leaves it there even though a command now exists, because dispatch is step 6."""
    outcome = approve(world)

    assert outcome.thread.state is OutreachThreadState.NOT_STARTED


# --- criterion 4: no agent callback anywhere in the path
# -------------------------------------------


def _module_path(dotted: str) -> Path:
    return APP.joinpath(*dotted.split(".")).with_suffix(".py")


def _app_imports(source: str) -> set[str]:
    """Every `app.*` module a source file imports, dotted and relative to `app`.

    `from app.pkg import submodule` is recorded as **both** `pkg` and `pkg.submodule`. Only
    recording the module named after `from` misses it entirely: `pkg` is a directory, so the walk
    finds no file and stops — and a control proved the walk could be evaded by writing the import
    that way. Names that turn out to be classes rather than modules resolve to no file and are
    skipped, so the over-collection costs nothing.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            module = node.module.removeprefix("app.")
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    found.add(alias.name.removeprefix("app."))
    return found


def transitive_imports(entry: str) -> set[str]:
    """Every `app` module reachable from ``entry`` by imports."""
    seen: set[str] = set()
    pending = [entry]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        path = _module_path(current)
        if not path.exists():
            continue
        seen.add(current)
        pending.extend(_app_imports(path.read_text(encoding="utf-8")))
    return seen


def test_the_approval_path_reaches_no_model_gateway() -> None:
    """§11.3: "No agent callback is required." §3.5: no external execution authority held only by
    the agent runtime.

    The **whole transitive walk**, not a hand-listed set. This assertion was scoped to five named
    modules when `T-067a` wrote it, because `validation` imported `drafting` for two template
    constants and `drafting` calls the model — so the honest broad claim was false for a reason
    that had nothing to do with approval. `T-156` moved those constants to a registry that imports
    only the draft purpose, and this is the guarantee the specification's sentence actually
    deserves: nothing anywhere in the approval path can reach the model.
    """
    reachable = transitive_imports("outreach_and_replies.approve_message")

    assert "outreach_and_replies.approve_message" in reachable, "the walk found nothing"
    offenders = sorted(module for module in reachable if module.split(".")[0] == "model_gateway")
    assert not offenders, f"the approval path reaches the model gateway: {offenders}"


def test_validation_reaches_no_model_gateway() -> None:
    """The same for `validation` on its own, because it is imported by more than this path — the
    edge would come back for every other caller too, and only this test would notice."""
    offenders = sorted(
        module
        for module in transitive_imports("drafts_and_approvals.validation")
        if module.split(".")[0] == "model_gateway"
    )

    assert not offenders, f"validation reaches the model gateway: {offenders}"


def test_the_template_registry_stays_a_registry() -> None:
    """The property that keeps the edge gone. `templates_registry` exists to hold two constants;
    the moment it imports a provider, a client, or a session it has stopped being a registry and
    the whole chain is back — which no other test here would catch, because the walk above would
    simply start reporting a different module."""
    reachable = transitive_imports("drafts_and_approvals.templates_registry")

    assert "drafts_and_approvals.templates_registry" in reachable, "the walk found nothing"
    # Stated as "reaches nothing that talks outward" rather than as an exact module set: an exact
    # set would break on any unrelated import `models` acquires, and would be edited rather than
    # read the first time it did.
    forbidden = {"model_gateway", "outreach_and_replies", "crm", "messaging", "jobs_and_outbox"}
    offenders = sorted(module for module in reachable if module.split(".")[0] in forbidden)
    assert not offenders, f"the template registry reaches {offenders}"


def test_the_approval_path_names_no_agent_runtime(db_session: Session) -> None:
    """The other half: not only no import, but no mention. OpenClaw is optional and isolated
    (§6), and a string reference would be the first step toward a callback."""
    forbidden = ("openclaw", "nemoclaw", "agent_callback")
    guilty: dict[str, list[str]] = {}
    for module in sorted(transitive_imports("outreach_and_replies.approve_message")):
        path = _module_path(module)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        hits = [word for word in forbidden if word in text]
        if hits:
            guilty[module] = hits

    assert not guilty, f"the approval path names an agent runtime: {guilty}"


def test_the_walk_would_catch_an_agent_import() -> None:
    """A guard on the guard: the walk must actually traverse, or both tests above pass vacuously
    by finding one module and stopping."""
    reachable = transitive_imports("outreach_and_replies.approve_message")

    # It reaches its direct dependencies and their dependencies.
    assert "drafts_and_approvals.approval" in reachable
    assert "audit_and_operations.service" in reachable
    assert len(reachable) > 10, f"the walk only reached {len(reachable)} modules"


def test_a_module_that_imports_the_gateway_is_detected() -> None:
    """And the detector itself: run against a module that genuinely reaches `model_gateway`, it
    has to say so — otherwise "no offenders" means "the check does not work"."""
    reachable = transitive_imports("qualification.jobs")

    assert {module for module in reachable if module.split(".")[0] == "model_gateway"}


# --- §11.4's field set
# -----------------------------------------------------------------------------


def test_the_send_command_carries_the_consequential_action_fields(
    db_session: Session, world: World
) -> None:
    """§11.4 lists what every external action contains. Missing one is not visible until dispatch
    needs it, which is after the human decision has been made."""
    outcome = approve(world)
    command = outcome.send_command

    assert command.action_type is not None
    assert command.actor_id == OPERATOR.id
    assert command.campaign_id == world.campaign.id
    assert command.recipient_contact_point_id == world.recipient.id
    assert command.message_revision_id == world.revision.id
    assert command.approval_id == outcome.approval.id
    assert command.approval_expires_at is not None
    assert command.idempotency_key
    assert command.created_at is not None


def test_record_versions_are_carried_when_given(db_session: Session, world: World) -> None:
    """§11.4 lists `record_versions`, and §11.3 step 1 is where they are captured — so this only
    has to carry what the endpoint passes it (`T-067b`)."""
    versions = {"campaign_candidate": datetime.now(UTC).isoformat()}

    outcome = approve_message(
        db_session,
        world.revision,
        recipient=world.recipient,
        approver_id=APPROVER,
        actor=OPERATOR,
        record_versions=versions,
    )

    assert outcome.send_command.record_versions == versions


# --- T-067b: §11.3 step 1, the checks in front of the transaction ---------------------------------
#
# `T-067a` proved what the transaction does. This proves what must be true before it is allowed to
# run, and the tests are deliberately one-per-check: step 1 lists six things, and a test that
# exercised them together would pass with five of them missing.


@pytest.fixture
def db_session_for_api(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def client(db_session_for_api: Session) -> Iterator[TestClient]:
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session_for_api
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


@pytest.fixture
def approver_headers(db_session: Session) -> dict[str, str]:
    """A session holding `APPROVE_MESSAGE` — §12.1 gives message review to the operator/reviewer."""
    token = issue_session(
        db_session, a_user(db_session, RoleKey.OPERATOR_REVIEWER), issued_via="test"
    ).token
    return {"authorization": f"Bearer {token}"}


def approve_url(world: World) -> str:
    return f"/api/review/revisions/{world.revision.id}/approve"


def payload(world: World, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"recipient_contact_point_id": str(world.recipient.id)}
    body.update(overrides)
    return body


# --- criterion 1: identity, role, session, and record version, each on its own --------------------


def test_an_approved_message_writes_the_transaction(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """The happy path, so the refusals below are refusals of something that otherwise works."""
    response = client.post(approve_url(world), json=payload(world), headers=approver_headers)

    assert response.status_code == 200, response.text
    assert counts(db_session) == (1, 1, 1)
    body = response.json()
    assert body["recipient"] == world.recipient.value
    assert body["revision_state"] == "approved"


def test_the_response_says_nothing_is_sent(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    """A reviewer pressing approve on a *message* deserves to know what leaves the building."""
    body = client.post(approve_url(world), json=payload(world), headers=approver_headers).json()

    assert "Nothing is sent" in body["what_happens_next"]
    assert "G-07" in body["what_happens_next"]


def test_no_session_is_refused(client: TestClient, db_session: Session, world: World) -> None:
    """Identity. §11.3 step 1's first word."""
    response = client.post(approve_url(world), json=payload(world))

    assert response.status_code == 401
    assert counts(db_session) == (0, 0, 0)


def test_a_role_without_the_permission_is_refused(
    client: TestClient, db_session: Session, world: World
) -> None:
    """Role. `APPROVE_MESSAGE` is tier 4 (§7.4) and the campaign/sales owner does not hold it."""
    token = issue_session(
        db_session, a_user(db_session, RoleKey.CAMPAIGN_SALES_OWNER), issued_via="test"
    ).token

    response = client.post(
        approve_url(world), json=payload(world), headers={"authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403
    assert "approve_message" in response.json()["detail"]
    assert counts(db_session) == (0, 0, 0)


def test_a_revoked_session_is_refused(
    client: TestClient, db_session: Session, world: World
) -> None:
    """Session. A token that was valid is not a token that is valid — `T-061a` revokes, and the
    dependency resolves against the row rather than trusting the string."""
    issued = issue_session(
        db_session, a_user(db_session, RoleKey.OPERATOR_REVIEWER), issued_via="test"
    )
    revoke(db_session, issued.session, revoked_by="test", reason="SYNTHETIC")

    response = client.post(
        approve_url(world),
        json=payload(world),
        headers={"authorization": f"Bearer {issued.token}"},
    )

    assert response.status_code == 401
    assert counts(db_session) == (0, 0, 0)


def test_a_stale_record_version_is_refused(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """Record version. Approving text that moved since it was read is the race §11.3 step 1 names,
    and losing it loudly is the whole point."""
    response = client.post(
        approve_url(world),
        json=payload(world, record_version="2020-01-01T00:00:00Z"),
        headers=approver_headers,
    )

    assert response.status_code == 409
    assert "reload" in response.json()["detail"]
    assert counts(db_session) == (0, 0, 0)


def test_the_current_record_version_is_accepted(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """The other direction: a client that sends the version it was shown is not penalised for
    sending it. Without this, the check above would pass against a version nobody could ever
    satisfy."""
    current = world.revision.updated_at.isoformat()

    response = client.post(
        approve_url(world), json=payload(world, record_version=current), headers=approver_headers
    )

    assert response.status_code == 200, response.text


def test_an_unknown_revision_is_404(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    response = client.post(
        f"/api/review/revisions/{uuid.uuid4()}/approve",
        json=payload(world),
        headers=approver_headers,
    )

    assert response.status_code == 404


def test_an_extra_field_is_refused(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    """`extra="forbid"`. A request supplying `approver_id` or `actor` must fail loudly rather than
    have it ignored — the silence is what makes someone believe it was honoured (§12.2)."""
    response = client.post(
        approve_url(world),
        json=payload(world, approver_id="somebody-else"),
        headers=approver_headers,
    )

    assert response.status_code == 422


def test_the_approver_comes_from_the_session(
    client: TestClient, db_session: Session, world: World
) -> None:
    """§12.2: immutable actor attribution, taken from the session and not from the request."""
    user = a_user(db_session, RoleKey.OPERATOR_REVIEWER)
    token = issue_session(db_session, user, issued_via="test").token

    client.post(
        approve_url(world), json=payload(world), headers={"authorization": f"Bearer {token}"}
    )

    approval = db_session.execute(select(Approval)).scalars().one()
    assert approval.approver_id == user.email


# --- criterion 2: cookie authentication is refused ------------------------------------------------


def test_a_cookie_cannot_authenticate_an_approval(
    client: TestClient, db_session: Session, world: World
) -> None:
    """The CSRF answer until `T-070`. A CSRF attack rides on credentials the browser attaches by
    itself; a bearer token it never sends unprompted, so the exposure is removed rather than
    mitigated — and this is the single action where that matters most (§3.5)."""
    token = issue_session(
        db_session, a_user(db_session, RoleKey.OPERATOR_REVIEWER), issued_via="test"
    ).token
    client.cookies.set(SESSION_COOKIE, token)

    response = client.post(approve_url(world), json=payload(world), headers={})

    # `403`, not `401`, since `T-070a`: the caller *is* authenticated, and the missing thing
    # is the CSRF token. Telling them to sign in again would send them round a loop that
    # cannot fix it. The property this test protects is unchanged — a cookie alone still
    # cannot mutate anything.
    assert response.status_code == 403
    assert counts(db_session) == (0, 0, 0)


def test_the_route_is_declared_at_tier_four_under_its_own_permission() -> None:
    """Structural, and it pins the distinction §12.1 draws: approving a *candidate* for outreach
    and approving the exact words that go out are different authorities, so they are different
    permissions even though one role holds both today."""
    declared = permission_for("POST", "/api/review/revisions/{revision_id}/approve")

    assert declared is Permission.APPROVE_MESSAGE
    assert PERMISSION_TIERS[Permission.APPROVE_MESSAGE] is Tier.EXTERNAL_COMMUNICATION
    assert (
        permission_for("POST", "/api/review/candidates/{candidate_id}/approve")
        is Permission.APPROVE_CANDIDATE
    )


# --- criterion 3: a revision outside the approver's scope -----------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        CampaignCandidateState.REJECTED,
        CampaignCandidateState.DEFERRED,
        CampaignCandidateState.INVALIDATED,
    ],
    ids=lambda state: state.value,
)
def test_a_revision_whose_candidate_was_already_decided_is_refused(
    client: TestClient,
    db_session: Session,
    world: World,
    approver_headers: dict[str, str],
    state: CampaignCandidateState,
) -> None:
    """Approval scope. Every already-decided state, not one of them: approving here would
    contradict a decision already recorded against this prospect (§8.2)."""
    transition(db_session, world.candidate, state, actor=OPERATOR, reason="SYNTHETIC")

    response = client.post(approve_url(world), json=payload(world), headers=approver_headers)

    assert response.status_code == 409
    assert counts(db_session) == (0, 0, 0)


def test_a_recipient_belonging_to_another_contact_is_refused(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """ADR-008's exact recipient, enforced at the edge as well as in the transaction."""
    stranger = Contact(account_id=world.account.id, full_name="SYNTHETIC Other")
    db_session.add(stranger)
    db_session.flush()
    theirs = ContactPoint(
        contact_id=stranger.id,
        type=ContactPointType.EMAIL,
        value=f"other-{uuid.uuid4().hex[:8]}@{world.account.domain}",
        verification_state=VerificationState.VERIFIED,
    )
    db_session.add(theirs)
    db_session.flush()

    response = client.post(
        approve_url(world),
        json=payload(world, recipient_contact_point_id=str(theirs.id)),
        headers=approver_headers,
    )

    assert response.status_code == 409
    assert counts(db_session) == (0, 0, 0)


def test_an_unknown_recipient_is_refused(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    response = client.post(
        approve_url(world),
        json=payload(world, recipient_contact_point_id=str(uuid.uuid4())),
        headers=approver_headers,
    )

    assert response.status_code == 404
    assert counts(db_session) == (0, 0, 0)


def test_a_second_approval_is_refused(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """The revision moved to `approved`, so §8.2 offers no edge — a refusal, not a crash."""
    assert (
        client.post(approve_url(world), json=payload(world), headers=approver_headers).status_code
        == 200
    )

    again = client.post(approve_url(world), json=payload(world), headers=approver_headers)

    assert again.status_code == 409
    assert counts(db_session) == (1, 1, 1)


# --- T-157: the approval pins the versions §11.4 requires -----------------------------------------
#
# The defect was silent by construction. `invalidation_detail` checks the pinned product status and
# the pinned claim set only `if ... is not None`, and nothing on the production path ever set
# either — so the two §8.4 triggers passed vacuously on every approval a reviewer ever granted.
# `T-068a`'s suite missed it because it built approvals through `request_approval` directly, with
# the pins supplied by hand: the tests reached the triggers by constructing exactly the row the
# production path could not produce.
#
# These tests therefore all start at the endpoint. A pin asserted on an approval the test built
# itself proves nothing about the transaction that a reviewer actually drives.


def approve_via_endpoint(
    client: TestClient, world: World, headers: dict[str, str]
) -> dict[str, object]:
    response = client.post(approve_url(world), json=payload(world), headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def test_an_approval_from_the_endpoint_pins_both_versions(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """Criterion 1. Both pins non-null, and each the row that was actually in force."""
    approve_via_endpoint(client, world, approver_headers)

    approval = db_session.execute(select(Approval)).scalars().one()
    assert approval.product_status_version_id == world.status.id
    assert approval.approved_claim_set_id == world.claim_set.id


def test_the_send_command_carries_both_versions(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """Criterion 3. §11.4 lists both on every external action, and the command is the action."""
    approve_via_endpoint(client, world, approver_headers)

    command = db_session.execute(select(SendCommand)).scalars().one()
    assert command.product_status_version_id == world.status.id
    assert command.approved_claim_set_id == world.claim_set.id


def test_superseding_the_pinned_claim_set_invalidates_the_approval(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """Criterion 2, and the §8.4 trigger that could never fire before.

    End to end from the endpoint on both sides: the approval is granted through `/approve` and the
    staleness is read back through `/attention/approvals`, which is what a reviewer sees. Nothing
    here constructs an approval or calls `invalidation_detail` directly.
    """
    approval_id = approve_via_endpoint(client, world, approver_headers)["approval_id"]

    world.publish_current_claim_set()  # supersedes the pinned set, publishing v2
    db_session.commit()

    rows = client.get("/api/review/attention/approvals", headers=approver_headers).json()["items"]

    assert [row["approval_id"] for row in rows] == [approval_id]
    assert rows[0]["trigger"] == "claim_set_superseded"
    assert rows[0]["triggering_id"] == str(world.claim_set.id)


def test_expiring_the_pinned_product_status_invalidates_the_approval(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """The other §8.4 trigger, equally dead before this task: a readiness version that stopped
    being effective while an approval still pointed at it."""
    approval_id = approve_via_endpoint(client, world, approver_headers)["approval_id"]

    # `NOW` rather than an offset: the fixture clock is in the past, so this readiness has lapsed
    # by the time the attention endpoint reads it, and it still sits after `effective_from` —
    # `ck_product_status_version_effective_window_ordered` refuses a window that closes first.
    world.status.expires_or_review_by = NOW
    db_session.commit()

    rows = client.get("/api/review/attention/approvals", headers=approver_headers).json()["items"]

    assert [row["approval_id"] for row in rows] == [approval_id]
    assert rows[0]["trigger"] == "product_status_superseded"
    assert rows[0]["triggering_id"] == str(world.status.id)


def test_a_campaign_with_no_current_claim_set_cannot_be_approved_into(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """Fails closed rather than pinning null. An approval with no claim set pinned is exactly the
    approval §8.4 can never invalidate, so the transaction refuses to create one — and refusing
    writes nothing, the same as every other step-1 refusal above."""
    world.claim_set.superseded_at = NOW - timedelta(hours=1)
    db_session.flush()

    response = client.post(approve_url(world), json=payload(world), headers=approver_headers)

    assert response.status_code == 409
    assert "claim set" in response.json()["detail"]
    assert counts(db_session) == (0, 0, 0)
