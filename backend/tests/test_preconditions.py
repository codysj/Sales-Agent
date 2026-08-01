"""The §11.4 dispatch-time rechecks (T-035c; §11.4, §3.5, §8.4).

Every test here is the same shape: build a world where a send is legitimate, break exactly one
§11.4 condition, and assert the dispatch is refused *naming that condition*. The point of §11.4 is
that approval happened earlier — so what these tests really check is that nothing which became
untrue between approval and dispatch can still be acted on.

`sender_availability` has no test because it has no implementation: `Q-004` has chosen no mailbox,
provider, or sender identity, so there is nothing to check availability against. `T-035d` covers it.
"""

import uuid
from datetime import datetime, timedelta

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import AuditEvent
from app.campaigns.candidate import transition as transition_candidate
from app.campaigns.policy import CampaignPolicy
from app.campaigns.policy import SuppressionScope as SuppressionScopeConfig
from app.campaigns.service import publish_policy_version
from app.core.lifecycles import CampaignCandidateState
from app.core.settings import Settings
from app.drafts_and_approvals.approval import Approval, revoke
from app.drafts_and_approvals.models import MessageRevision
from app.jobs_and_outbox.dispatch import (
    DispatchRefused,
    dispatch_event,
    dispatch_once,
    lease_outbox_events,
)
from app.jobs_and_outbox.outbox import (
    OutboxState,
    enqueue_outbox_event,
    refused_by_check_count,
)
from app.outreach_and_replies.adapters.fake import FakeExternalEffectAdapter
from app.outreach_and_replies.commands import create_send_command
from app.outreach_and_replies.models import SendAttempt, SendCommand
from app.outreach_and_replies.preconditions import (
    MissingSendCommand,
    PreconditionFailure,
    Recheck,
    load_send_command,
    recheck_send_command,
    send_precondition_check,
)
from app.products_and_claims.models import ProductStatusVersion, ReadinessCategory
from app.prospects.models import VerificationState
from app.prospects.suppression import SuppressionScope, SuppressionSource, record_suppression
from tests.factories import APPROVER, NOW, OPERATOR, World


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-precondition-test")


def unlocked_settings() -> Settings:
    return Settings(shadow_mode=False, outbound_email_enabled=True)


@pytest.fixture
def world(db_session: Session) -> World:
    w = World(db_session)
    w.activate()
    return w


def a_command(db_session: Session, world: World) -> SendCommand:
    """A legitimate send order: active campaign, granted approval, verified recipient."""
    command = create_send_command(
        db_session,
        thread=world.thread,
        approval=world.approval(),
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        record_versions={"approver_id": APPROVER},
        now=NOW,
    )
    db_session.flush()
    return command


def refusal(db_session: Session, command: SendCommand) -> PreconditionFailure:
    """Run the rechecks and return the failure. Fails the test if nothing is refused."""
    with pytest.raises(PreconditionFailure) as caught:
        recheck_send_command(db_session, command, now=NOW)
    return caught.value


# --- the baseline: a legitimate send is not refused -------------------------------------------


def test_a_legitimate_send_passes_every_recheck(db_session: Session, world: World) -> None:
    """Without this, every test below could pass for the wrong reason."""
    recheck_send_command(db_session, a_command(db_session, world), now=NOW)


def test_the_join_from_outbox_to_command_is_the_idempotency_key(
    db_session: Session, world: World
) -> None:
    """`T-034` left no foreign key, so the shared key is what makes the lookup possible at all."""
    command = a_command(db_session, world)

    assert load_send_command(db_session, command.idempotency_key) is command
    assert load_send_command(db_session, "f" * 64) is None


# --- what the schema already guarantees --------------------------------------------------------


def test_a_send_command_cannot_be_edited_at_all(db_session: Session, world: World) -> None:
    """Why several §11.4 conditions need no runtime check.

    `send_command` is immutable by trigger (`T-022`), and every field §11.4 lists is either copied
    from the approval at order time or a `RESTRICT` foreign key. So "the command now points at a
    different recipient" and "the approval it cites has vanished" are not states the database can
    reach — they are prevented, not detected. The rechecks below cover the conditions that *can*
    drift: ones where the command is intact but the world around it changed.
    """
    command = a_command(db_session, world)

    command.campaign_id = uuid.uuid4()
    with pytest.raises(IntegrityError, match="send_command is immutable"):
        db_session.flush()


def test_the_commands_contract_fields_are_derived_from_the_approval(
    db_session: Session, world: World
) -> None:
    """The other half: divergence is not constructible in the first place."""
    approval = world.approval()
    command = create_send_command(
        db_session,
        thread=world.thread,
        approval=approval,
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        now=NOW,
    )
    db_session.flush()

    assert command.recipient_contact_point_id == approval.recipient_contact_point_id
    assert command.message_revision_id == approval.message_revision_id
    assert command.approval_expires_at == approval.approval_expires_at


# --- 1. approver identity and authority -------------------------------------------------------


def test_a_different_approver_than_the_one_recorded_is_refused(
    db_session: Session, world: World
) -> None:
    """Recorded at order time, so a later change of hands is visible at dispatch."""
    command = create_send_command(
        db_session,
        thread=world.thread,
        approval=world.approval(),
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        record_versions={"approver_id": "someone-else"},
        now=NOW,
    )
    db_session.flush()

    assert refusal(db_session, command).check is Recheck.APPROVER_AUTHORITY


def test_a_matching_approver_is_not_refused(db_session: Session, world: World) -> None:
    command = a_command(db_session, world)

    assert command.record_versions["approver_id"] == APPROVER
    recheck_send_command(db_session, command, now=NOW)


def test_a_command_recording_no_approver_skips_that_recheck(
    db_session: Session, world: World
) -> None:
    """§11.4 does not require the stamp. Absent means nothing to compare, not assume a mismatch."""
    command = create_send_command(
        db_session,
        thread=world.thread,
        approval=world.approval(),
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        now=NOW,
    )
    db_session.flush()

    recheck_send_command(db_session, command, now=NOW)


# --- 2. approval state and expiration ---------------------------------------------------------


def test_a_revoked_approval_is_refused(db_session: Session, world: World) -> None:
    """§8.4: revocation must take effect at dispatch, not only at the next approval request."""
    command = a_command(db_session, world)
    approval = db_session.get(Approval, command.approval_id)
    assert approval is not None
    revoke(db_session, approval, actor=OPERATOR, reason="claims withdrawn")
    db_session.flush()

    assert refusal(db_session, command).check is Recheck.APPROVAL_VALIDITY


def test_an_expired_approval_is_refused(db_session: Session, world: World) -> None:
    """Nothing is mutated: time alone invalidates the send, which is the §11.4 case exactly."""
    command = a_command(db_session, world)

    with pytest.raises(PreconditionFailure) as caught:
        recheck_send_command(db_session, command, now=NOW + timedelta(days=365))

    assert caught.value.check is Recheck.APPROVAL_VALIDITY


# --- the candidate decision, rechecked at dispatch (T-140) -------------------------------------


def test_a_candidate_rejected_after_approval_blocks_dispatch(
    db_session: Session, world: World
) -> None:
    """The layer the approval-time check cannot reach (§8.2, `T-140`).

    `request_approval` and `approve` both refuse a decided-against candidate, but neither can see a
    rejection that happens *after* the approval was granted — and the gap between approval and
    dispatch is exactly where that happens. This is why §11.4 rechecks rather than trusting the
    earlier decision.
    """
    command = a_command(db_session, world)
    recheck_send_command(db_session, command, now=NOW)

    for state in (
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
        CampaignCandidateState.REVIEW_PENDING,
        CampaignCandidateState.REJECTED,
    ):
        transition_candidate(
            db_session, world.candidate, state, actor=OPERATOR, reason="synthetic rejection"
        )
    db_session.flush()

    failure = refusal(db_session, command)
    assert failure.check is Recheck.CANDIDATE_DECISION
    assert "rejected" in failure.detail


def test_the_candidate_recheck_is_its_own_reason(db_session: Session, world: World) -> None:
    """Distinct from `APPROVAL_VALIDITY`: the approval itself is still perfectly valid.

    Collapsing the two would tell an operator the approval expired when in fact a colleague
    rejected the prospect.
    """
    assert Recheck.CANDIDATE_DECISION.value == "candidate_decision"
    assert Recheck.CANDIDATE_DECISION is not Recheck.APPROVAL_VALIDITY


def test_a_candidate_still_approved_does_not_block_dispatch(
    db_session: Session, world: World
) -> None:
    """The baseline, so the test above is about the rejection and not about the fixture."""
    command = a_command(db_session, world)

    recheck_send_command(db_session, command, now=NOW)


# --- 3. exact recipient and immutable revision -------------------------------------------------


def test_a_revision_whose_content_changed_since_approval_is_refused(
    db_session: Session, world: World
) -> None:
    """Reported as an approval-validity failure, not a recipient failure — and that is correct.

    §8.4 already makes "the message content changed since approval" an approval *invalidation*, and
    `invalidation_reason` checks it. This module therefore does **not** recompute the content hash:
    a second comparison here would duplicate the designated check and report the wrong condition.
    """
    command = a_command(db_session, world)
    revision = db_session.get(MessageRevision, command.message_revision_id)
    assert revision is not None

    with db_session.no_autoflush:
        revision.content_hash = "0" * 64
        with pytest.raises(PreconditionFailure) as caught:
            recheck_send_command(db_session, command, now=NOW)
        db_session.expire(revision)

    assert caught.value.check is Recheck.APPROVAL_VALIDITY
    assert "content changed" in caught.value.detail


# --- 4. suppression at every scope -------------------------------------------------------------


@pytest.mark.parametrize(
    "scope",
    [
        SuppressionScope.PERSON,
        SuppressionScope.EMAIL,
        SuppressionScope.DOMAIN,
        SuppressionScope.ACCOUNT,
    ],
    ids=lambda s: s.value,
)
def test_suppression_at_any_scope_is_refused(
    db_session: Session, world: World, scope: SuppressionScope
) -> None:
    """§11.4 names four scopes and §15.6 makes each independently sufficient."""
    command = a_command(db_session, world)
    identity = {
        SuppressionScope.PERSON: str(world.contact.id),
        SuppressionScope.EMAIL: world.recipient.value,
        SuppressionScope.DOMAIN: world.email_domain,
        SuppressionScope.ACCOUNT: str(world.account.id),
    }[scope]
    record_suppression(
        db_session,
        scope=scope,
        identity=identity,
        source=SuppressionSource.MANUAL,
        reason="synthetic opt-out",
        # Effective *before* the moment the rechecks use. `record_suppression` otherwise defaults to
        # the real clock, which is later than NOW, and the suppression would not yet apply.
        effective_at=NOW - timedelta(days=1),
    )
    db_session.flush()

    assert refusal(db_session, command).check is Recheck.SUPPRESSION


def test_the_campaign_policy_cannot_narrow_suppression_at_send_time(
    db_session: Session, world: World
) -> None:
    """`T-015` decided this: a policy may widen what it respects, never narrow it here.

    §11.4 says "as configured", which read naively would let a campaign setting override a
    suppression record. The recheck queries every scope unconditionally instead.
    """
    publish_policy_version(
        db_session,
        campaign_id=world.campaign.id,
        policy=CampaignPolicy(
            suppression_scope=SuppressionScopeConfig(
                person=False, email=False, domain=False, account=False
            )
        ),
        approved_by=APPROVER,
    )
    db_session.flush()
    command = a_command(db_session, world)
    record_suppression(
        db_session,
        scope=SuppressionScope.EMAIL,
        identity=world.recipient.value,
        source=SuppressionSource.MANUAL,
        reason="synthetic opt-out",
        # Effective *before* the moment the rechecks use. `record_suppression` otherwise defaults to
        # the real clock, which is later than NOW, and the suppression would not yet apply.
        effective_at=NOW - timedelta(days=1),
    )
    db_session.flush()

    assert refusal(db_session, command).check is Recheck.SUPPRESSION


# --- 5. email verification (the sender half is T-035d) ----------------------------------------


def test_an_invalid_address_is_refused(db_session: Session, world: World) -> None:
    command = a_command(db_session, world)
    world.recipient.verification_state = VerificationState.INVALID
    db_session.flush()

    assert refusal(db_session, command).check is Recheck.EMAIL_VERIFICATION


def test_an_unverified_address_is_refused_when_the_policy_requires_verification(
    db_session: Session, world: World
) -> None:
    """`require_verified_email` defaults to True (§15.8), and unverified is not a soft yes."""
    command = a_command(db_session, world)
    world.recipient.verification_state = VerificationState.UNVERIFIED
    db_session.flush()

    assert refusal(db_session, command).check is Recheck.EMAIL_VERIFICATION


def test_sender_availability_is_declared_but_not_implemented() -> None:
    """Honesty in code, not just in the ledger.

    §11.4's bullet is "email verification **and** sender availability". `Q-004` has chosen no
    mailbox, provider, or sender identity, so there is nothing to check. The name exists so the gap
    is visible where someone would look for it; `T-035d` fills it.
    """
    assert Recheck.SENDER_AVAILABILITY.value == "sender_availability"


# --- 6. campaign active status and volume limit ------------------------------------------------


def test_a_paused_campaign_is_refused(db_session: Session, world: World) -> None:
    command = a_command(db_session, world)
    world.campaign.paused = True
    db_session.flush()

    failure = refusal(db_session, command)
    assert failure.check is Recheck.CAMPAIGN_STATUS
    assert failure.is_recoverable, "an unpause is expected, so the work must be held not failed"


def test_reaching_the_total_send_cap_is_refused(db_session: Session, world: World) -> None:
    """§17.1 and `Q-014`: the pilot caps are deliberately small and deliberately hard."""
    command = a_command(db_session, world)
    publish_policy_version(
        db_session,
        campaign_id=world.campaign.id,
        policy=CampaignPolicy(total_send_cap=0),
        approved_by=APPROVER,
    )
    db_session.flush()

    assert refusal(db_session, command).check is Recheck.CAMPAIGN_STATUS


def test_a_campaign_cannot_vanish_from_under_a_command() -> None:
    """The reason there is no "vanished campaign" refusal test.

    `send_command.campaign_id` is a `RESTRICT` foreign key, so the row cannot be deleted while a
    command cites it, and the command itself is immutable. The recheck still handles `None`
    defensively, but the state is unreachable — prevented, not detected.
    """
    column = SendCommand.__table__.c.campaign_id
    foreign_key = next(iter(column.foreign_keys))

    assert column.nullable is False
    assert foreign_key.ondelete == "RESTRICT"


# --- 7. product-status and approved-claim versions ---------------------------------------------


def a_status_version(
    world: World, *, version: int, effective_from: datetime
) -> ProductStatusVersion:
    return ProductStatusVersion(
        product_id=world.product.id,
        version=version,
        readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
        approved_by=APPROVER,
        approved_at=effective_from,
        effective_from=effective_from,
        expires_or_review_by=None,
    )


def test_a_product_status_version_no_longer_in_force_is_refused(
    db_session: Session, world: World
) -> None:
    """§10.5: a product statement may only rest on the status currently in force.

    Reported as an approval-validity failure, because §8.4's `invalidation_reason` pins the status
    version and is the designated check. This module deliberately does not re-check it — see the
    delegation table in `preconditions.py`. The condition is enforced; only the reporting label
    differs from §11.4's wording.
    """
    old = a_status_version(world, version=1, effective_from=NOW - timedelta(days=30))
    db_session.add(old)
    db_session.flush()

    approval = world.approval(product_status_version_id=old.id)
    command = create_send_command(
        db_session,
        thread=world.thread,
        approval=approval,
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        record_versions={"approver_id": APPROVER},
        now=NOW,
    )
    db_session.flush()
    # The pinned version is still in force, so the send is legitimate...
    recheck_send_command(db_session, command, now=NOW)

    # ...until readiness moves on. The old window must be closed first: `T-013`'s exclusion
    # constraint refuses two versions in force for one product at the same moment.
    old.expires_or_review_by = NOW - timedelta(days=1)
    db_session.flush()
    db_session.add(a_status_version(world, version=2, effective_from=NOW - timedelta(days=1)))
    db_session.flush()

    failure = refusal(db_session, command)
    assert failure.check is Recheck.APPROVAL_VALIDITY
    assert "product status version is no longer effective" in failure.detail


def test_a_command_citing_no_product_status_is_not_refused_for_it(
    db_session: Session, world: World
) -> None:
    """Not every effect makes a product claim, and §11.4 allows the field's absence."""
    command = a_command(db_session, world)

    assert command.product_status_version_id is None
    recheck_send_command(db_session, command, now=NOW)


# --- 8. current record versions ----------------------------------------------------------------


def command_with_versions(
    db_session: Session, world: World, versions: dict[str, str]
) -> SendCommand:
    """`record_versions` is set at order time — the command is immutable afterwards."""
    command = create_send_command(
        db_session,
        thread=world.thread,
        approval=world.approval(),
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        record_versions=versions,
        now=NOW,
    )
    db_session.flush()
    return command


def test_a_record_that_changed_since_approval_is_refused(db_session: Session, world: World) -> None:
    """§11.4 ``record_versions``: the rows the decision rested on must not have moved."""
    command = command_with_versions(
        db_session,
        world,
        {"approver_id": APPROVER, "campaign_updated_at": "1999-01-01T00:00:00+00:00"},
    )

    failure = refusal(db_session, command)
    assert failure.check is Recheck.RECORD_VERSIONS
    assert "campaign" in failure.detail


def test_an_unrecognised_record_key_is_ignored_rather_than_guessed(
    db_session: Session, world: World
) -> None:
    """A stamp for a table we cannot resolve must not silently pass *or* silently fail.

    Refusing on an unknown key would make adding a stamp a breaking change; passing it off as
    verified would be a lie. Skipping it and saying so here is the honest third option.
    """
    command = command_with_versions(
        db_session,
        world,
        {"approver_id": APPROVER, "something_else_updated_at": "1999-01-01T00:00:00+00:00"},
    )

    recheck_send_command(db_session, command, now=NOW)


# --- 9. existing result for the idempotency key ------------------------------------------------


def test_a_command_with_a_recorded_attempt_is_refused(db_session: Session, world: World) -> None:
    """§17.3's duplicate guard, at dispatch time."""
    command = a_command(db_session, world)
    db_session.add(SendAttempt(send_command_id=command.id, attempt_number=1, started_at=NOW))
    db_session.flush()

    assert refusal(db_session, command).check is Recheck.EXISTING_RESULT


def test_an_outbox_event_with_no_command_behind_it_is_refused(db_session: Session) -> None:
    """An external effect with no §11.4 contract must never be performed."""
    with pytest.raises(MissingSendCommand) as caught:
        send_precondition_check(db_session, "b" * 64)

    assert caught.value.check is Recheck.EXISTING_RESULT


# --- the dispatcher applies them ---------------------------------------------------------------


def outbox_for(db_session: Session, command: SendCommand) -> None:
    enqueue_outbox_event(
        db_session,
        event_type="send.email",
        idempotency_key=command.idempotency_key,
        actor=OPERATOR,
        payload={"channel": "email"},
    )
    db_session.flush()


def test_the_dispatcher_sends_when_every_recheck_passes(db_session: Session, world: World) -> None:
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    adapter = FakeExternalEffectAdapter()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]

    dispatch_event(
        db_session,
        event,
        adapter,
        unlocked_settings(),
        precondition_check=send_precondition_check,
    )

    assert event.state is OutboxState.DISPATCHED
    assert adapter.effect_count == 1


def test_a_refused_recheck_never_reaches_the_adapter(db_session: Session, world: World) -> None:
    """The placement §11.4 cares about: inside the transaction, before anything is sent."""
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    approval = db_session.get(Approval, command.approval_id)
    assert approval is not None
    revoke(db_session, approval, actor=OPERATOR, reason="claims withdrawn")
    db_session.flush()
    adapter = FakeExternalEffectAdapter()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]

    with pytest.raises(DispatchRefused) as caught:
        dispatch_event(
            db_session,
            event,
            adapter,
            unlocked_settings(),
            precondition_check=send_precondition_check,
        )

    assert caught.value.check == Recheck.APPROVAL_VALIDITY.value
    assert adapter.calls == [], "nothing may have been sent"
    assert adapter.effect_count == 0
    assert event.state is OutboxState.FAILED


def test_a_refusal_writes_an_audit_event_naming_the_check(
    db_session: Session, world: World
) -> None:
    """Criterion 2. A reviewer must be able to tell a revoked approval from a paused campaign."""
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    world.campaign.paused = True
    db_session.flush()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]

    with pytest.raises(DispatchRefused):
        dispatch_event(
            db_session,
            event,
            FakeExternalEffectAdapter(),
            unlocked_settings(),
            precondition_check=send_precondition_check,
        )
    db_session.flush()

    audit = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(event.id),
            AuditEvent.action == "outbox.recheck_refused",
        )
    ).scalar_one()
    assert audit.payload["refused_check"] == Recheck.CAMPAIGN_STATUS.value


@pytest.mark.parametrize(
    "scope",
    [
        SuppressionScope.PERSON,
        SuppressionScope.EMAIL,
        SuppressionScope.DOMAIN,
        SuppressionScope.ACCOUNT,
    ],
    ids=lambda s: s.value,
)
def test_a_suppressed_send_records_the_scope_that_matched(
    db_session: Session, world: World, scope: SuppressionScope
) -> None:
    """`T-161` criterion 1. Refusing was never in doubt; leaving a countable trace was.

    Before this the trail said only `refused_check: suppression`, and the scope lived in a
    sentence inside `last_detail` — greppable, not countable, and overwritten by the next attempt.
    """
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    record_suppression(
        db_session,
        scope=scope,
        identity={
            SuppressionScope.PERSON: str(world.contact.id),
            SuppressionScope.EMAIL: world.recipient.value,
            SuppressionScope.DOMAIN: world.email_domain,
            SuppressionScope.ACCOUNT: str(world.account.id),
        }[scope],
        source=SuppressionSource.MANUAL,
        reason="synthetic opt-out",
        effective_at=NOW - timedelta(days=1),
    )
    db_session.flush()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]

    with pytest.raises(DispatchRefused):
        dispatch_event(
            db_session,
            event,
            FakeExternalEffectAdapter(),
            unlocked_settings(),
            precondition_check=send_precondition_check,
        )
    db_session.flush()

    audit = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(event.id),
            AuditEvent.action == "outbox.recheck_refused",
        )
    ).scalar_one()
    assert audit.payload["refused_check"] == Recheck.SUPPRESSION.value
    assert audit.payload["refused_scope"] == scope.value


def test_a_suppressed_send_becomes_a_countable_attempt(db_session: Session, world: World) -> None:
    """`T-161` criterion 2, from the writing end: the count the dashboard reads moves.

    One real dispatch, end to end. That two *attempts* count two rather than one recipient is
    proven where rows are cheap — `tests/test_operations_api.py::test_suppressed_send_attempts
    _counts_attempts_not_recipients` — because a second command here would need a second revision:
    `uq_approval_live_per_revision` allows one live approval per revision, and building a whole
    second world to re-prove the counter's arithmetic would test the fixtures, not the count.
    """
    assert refused_by_check_count(db_session, Recheck.SUPPRESSION.value) == 0

    command = a_command(db_session, world)
    outbox_for(db_session, command)
    record_suppression(
        db_session,
        scope=SuppressionScope.EMAIL,
        identity=world.recipient.value,
        source=SuppressionSource.MANUAL,
        reason="synthetic opt-out",
        effective_at=NOW - timedelta(days=1),
    )
    db_session.flush()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]
    with pytest.raises(DispatchRefused):
        dispatch_event(
            db_session,
            event,
            FakeExternalEffectAdapter(),
            unlocked_settings(),
            precondition_check=send_precondition_check,
        )
    db_session.flush()

    assert refused_by_check_count(db_session, Recheck.SUPPRESSION.value) == 1
    # A refusal by another check is not a suppressed send; counting it would report an outage as
    # a compliance signal.
    assert refused_by_check_count(db_session, Recheck.CAMPAIGN_STATUS.value) == 0


def test_the_recorded_scope_carries_no_address_and_no_identifier(
    db_session: Session, world: World
) -> None:
    """§15.5. The scope is a category; the identity that matched must not travel with it.

    A trail that named the address would put a person's email in a table an operator reads over
    somebody's shoulder during an incident — and the category is the operationally useful half
    anyway: a run of `domain` matches is a different incident from a run of `person` ones.
    """
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    record_suppression(
        db_session,
        scope=SuppressionScope.EMAIL,
        identity=world.recipient.value,
        source=SuppressionSource.MANUAL,
        reason="synthetic opt-out",
        effective_at=NOW - timedelta(days=1),
    )
    db_session.flush()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]

    with pytest.raises(DispatchRefused):
        dispatch_event(
            db_session,
            event,
            FakeExternalEffectAdapter(),
            unlocked_settings(),
            precondition_check=send_precondition_check,
        )
    db_session.flush()

    audit = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(event.id),
            AuditEvent.action == "outbox.recheck_refused",
        )
    ).scalar_one()
    rendered = str(audit.payload)
    assert world.recipient.value not in rendered
    assert str(world.contact.id) not in rendered
    assert world.email_domain not in rendered


def test_a_refusal_with_no_scope_records_none(db_session: Session, world: World) -> None:
    """Only suppression has a scope. A paused campaign must not invent an empty one.

    The count reads `refused_check`, so a stray `refused_scope: ""` on every other refusal would
    not corrupt it — but it would make the payload lie about what was known.
    """
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    world.campaign.paused = True
    db_session.flush()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]

    with pytest.raises(DispatchRefused):
        dispatch_event(
            db_session,
            event,
            FakeExternalEffectAdapter(),
            unlocked_settings(),
            precondition_check=send_precondition_check,
        )
    db_session.flush()

    audit = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(event.id),
            AuditEvent.action == "outbox.recheck_refused",
        )
    ).scalar_one()
    assert "refused_scope" not in audit.payload


def test_a_recoverable_refusal_holds_the_work_without_spending_the_budget(
    db_session: Session, world: World
) -> None:
    """Criterion 3. A pause gets reversed; burning attempts would dead-letter live work."""
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    world.campaign.paused = True
    db_session.flush()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]
    assert event.attempt_count == 1, "the lease spent one"

    with pytest.raises(DispatchRefused):
        dispatch_event(
            db_session,
            event,
            FakeExternalEffectAdapter(),
            unlocked_settings(),
            precondition_check=send_precondition_check,
        )

    assert event.state is OutboxState.PENDING, "held, not failed"
    assert event.attempt_count == 0, "the attempt was refunded"


def test_a_permanent_refusal_does_fail_the_event(db_session: Session, world: World) -> None:
    """The other side of criterion 3: a revoked approval will refuse identically forever."""
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    approval = db_session.get(Approval, command.approval_id)
    assert approval is not None
    revoke(db_session, approval, actor=OPERATOR, reason="claims withdrawn")
    db_session.flush()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]

    with pytest.raises(DispatchRefused):
        dispatch_event(
            db_session,
            event,
            FakeExternalEffectAdapter(),
            unlocked_settings(),
            precondition_check=send_precondition_check,
        )

    assert event.state is OutboxState.FAILED
    assert lease_outbox_events(db_session, dispatcher_id="d2", limit=5) == []


def test_one_refused_event_does_not_stop_the_batch(db_session: Session, world: World) -> None:
    """`dispatch_once` must survive a refusal, or one bad approval stalls every other send."""
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    world.campaign.paused = True
    db_session.flush()

    attempted = dispatch_once(
        db_session,
        FakeExternalEffectAdapter(),
        unlocked_settings(),
        dispatcher_id="d1",
        limit=5,
        precondition_check=send_precondition_check,
    )

    assert attempted == 1


def test_dispatching_with_no_check_does_not_recheck(db_session: Session, world: World) -> None:
    """Explicitly pinned, because it is the unsafe path and should stay hard to reach by accident.

    An effect with no §11.4 contract behind it has nothing to recheck. A send always has one, so
    the send path always passes `send_precondition_check`.
    """
    command = a_command(db_session, world)
    outbox_for(db_session, command)
    world.campaign.paused = True
    db_session.flush()
    adapter = FakeExternalEffectAdapter()
    event = lease_outbox_events(db_session, dispatcher_id="d1", limit=1)[0]

    dispatch_event(db_session, event, adapter, unlocked_settings())

    assert event.state is OutboxState.DISPATCHED
    assert adapter.effect_count == 1
