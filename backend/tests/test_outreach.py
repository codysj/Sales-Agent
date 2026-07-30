"""Effectively-once outreach records (T-022; §11.4, §17.3, ADR-016).

Three properties: a send command carries the whole §11.4 contract or does not exist, the same
logical send cannot be ordered twice, and an ambiguous provider result lands in
``delivery_unknown`` with no way back to sending.

Nothing here sends anything — these are the records a send is made from.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import create_candidate
from app.campaigns.models import Campaign
from app.core.lifecycles import (
    IllegalTransition,
    OutreachThreadState,
    allowed_transitions,
    is_terminal,
)
from app.drafts_and_approvals.approval import Approval, ApprovalNotValid, approve, request_approval
from app.drafts_and_approvals.models import MessageDraft
from app.drafts_and_approvals.revisions import create_revision
from app.outreach_and_replies.commands import create_send_command, transition_thread
from app.outreach_and_replies.models import (
    ActionType,
    AttemptOutcome,
    DeliveryEvent,
    DeliveryEventType,
    Interaction,
    InteractionDirection,
    OutreachThread,
    SendAttempt,
    SendCommand,
    build_idempotency_key,
)
from app.products_and_claims.models import Product
from app.prospects.models import Account, Contact, ContactPoint, ContactPointType

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-outreach-test")


class World:
    def __init__(self, session: Session) -> None:
        product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
        session.add(product)
        session.flush()
        self.campaign = Campaign(
            slug=f"synthetic-{uuid.uuid4().hex[:8]}",
            name="SYNTHETIC-Campaign",
            product_id=product.id,
        )
        account = Account(domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account")
        session.add_all([self.campaign, account])
        session.flush()
        contact = Contact(account_id=account.id, full_name="SYNTHETIC Person")
        session.add(contact)
        session.flush()
        self.recipient = ContactPoint(
            contact_id=contact.id,
            type=ContactPointType.EMAIL,
            value=f"{uuid.uuid4().hex[:8]}@example.com",
        )
        session.add(self.recipient)
        session.flush()

        self.candidate = create_candidate(
            session,
            campaign_id=self.campaign.id,
            account_id=account.id,
            contact_id=contact.id,
            actor=OPERATOR,
        )
        self.draft = MessageDraft(candidate_id=self.candidate.id)
        session.add(self.draft)
        session.flush()
        self.revision = create_revision(
            session,
            draft=self.draft,
            recipient_contact_point_id=self.recipient.id,
            subject="SYNTHETIC subject",
            body="SYNTHETIC body",
            created_by="drafter-1",
            actor=OPERATOR,
        )
        self.thread = OutreachThread(candidate_id=self.candidate.id)
        session.add(self.thread)
        session.flush()

    def approval(self, session: Session) -> Approval:
        approval = request_approval(
            session,
            revision=self.revision,
            approver_id="approver-1",
            actor=OPERATOR,
            now=NOW,
        )
        approve(session, approval, actor=OPERATOR, now=NOW)
        session.flush()
        return approval


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


def make_command(db_session: Session, world: World, approval: Approval) -> SendCommand:
    return create_send_command(
        db_session,
        thread=world.thread,
        approval=approval,
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        now=NOW,
    )


# --- the §11.4 contract (criterion 1) ------------------------------------------------------


def test_a_command_carries_the_whole_contract(db_session: Session, world: World) -> None:
    approval = world.approval(db_session)

    command = make_command(db_session, world, approval)
    db_session.flush()

    assert command.action_type is ActionType.EMAIL_SEND
    assert command.actor_id == OPERATOR.id
    assert command.campaign_id == world.campaign.id
    assert command.recipient_contact_point_id == world.recipient.id
    assert command.message_revision_id == world.revision.id
    assert command.approval_id == approval.id
    assert command.approval_expires_at == approval.approval_expires_at
    assert command.idempotency_key
    assert command.record_versions == {}


@pytest.mark.parametrize(
    "missing",
    [
        "thread_id",
        "campaign_id",
        "recipient_contact_point_id",
        "message_revision_id",
        "approval_id",
        "approval_expires_at",
        "idempotency_key",
        "actor_id",
    ],
)
def test_a_command_missing_any_contract_field_is_rejected(
    missing: str, db_session: Session, world: World
) -> None:
    approval = world.approval(db_session)
    values: dict[str, object] = {
        "thread_id": world.thread.id,
        "actor_id": "operator-1",
        "campaign_id": world.campaign.id,
        "recipient_contact_point_id": world.recipient.id,
        "message_revision_id": world.revision.id,
        "approval_id": approval.id,
        "approval_expires_at": approval.approval_expires_at,
        "idempotency_key": "c" * 64,
    }
    values[missing] = None
    db_session.add(SendCommand(**values))  # type: ignore[arg-type]

    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.flush()


def test_a_command_is_immutable(db_session: Session, world: World) -> None:
    """A command has no state to progress; what happened to it lives in send_attempt."""
    approval = world.approval(db_session)
    command = make_command(db_session, world, approval)
    db_session.flush()

    with pytest.raises(DBAPIError) as exc:
        db_session.execute(
            text("UPDATE send_command SET actor_id = 'someone-else' WHERE id = :id"),
            {"id": command.id},
        )

    assert "immutable" in str(exc.value)


def test_ordering_requires_a_still_valid_approval(db_session: Session, world: World) -> None:
    """The same check T-035 repeats at dispatch — §8.4 triggers can fire in the gap."""
    approval = world.approval(db_session)
    create_revision(
        db_session,
        draft=world.draft,
        recipient_contact_point_id=world.recipient.id,
        subject="SYNTHETIC edited",
        body="SYNTHETIC body",
        created_by="drafter-1",
        actor=OPERATOR,
    )
    db_session.flush()

    with pytest.raises(ApprovalNotValid):
        make_command(db_session, world, approval)


# --- idempotency (criterion 2) ----------------------------------------------------------------


def test_the_key_is_derived_not_random() -> None:
    """A random key would make every retry look like a new send (§17.3)."""
    args = {
        "approval_id": uuid.UUID(int=1),
        "message_revision_id": uuid.UUID(int=2),
        "recipient_contact_point_id": uuid.UUID(int=3),
    }

    assert build_idempotency_key(**args) == build_idempotency_key(**args)


def test_a_different_recipient_gives_a_different_key() -> None:
    base = {
        "approval_id": uuid.UUID(int=1),
        "message_revision_id": uuid.UUID(int=2),
        "recipient_contact_point_id": uuid.UUID(int=3),
    }

    assert build_idempotency_key(**{**base, "recipient_contact_point_id": uuid.UUID(int=9)}) != (
        build_idempotency_key(**base)
    )


def test_a_duplicate_idempotency_key_is_rejected(db_session: Session, world: World) -> None:
    approval = world.approval(db_session)
    make_command(db_session, world, approval)
    db_session.flush()

    db_session.add(
        SendCommand(
            thread_id=world.thread.id,
            actor_id="operator-1",
            campaign_id=world.campaign.id,
            recipient_contact_point_id=world.recipient.id,
            message_revision_id=world.revision.id,
            approval_id=approval.id,
            approval_expires_at=approval.approval_expires_at,
            idempotency_key=build_idempotency_key(
                approval_id=approval.id,
                message_revision_id=world.revision.id,
                recipient_contact_point_id=world.recipient.id,
            ),
        )
    )

    with pytest.raises(IntegrityError) as exc:
        db_session.flush()

    assert "uq_send_command" in str(exc.value)


def test_one_approval_orders_one_send(db_session: Session, world: World) -> None:
    """An approval authorizes one send, not a stream of them (ADR-008)."""
    approval = world.approval(db_session)
    make_command(db_session, world, approval)
    db_session.flush()

    db_session.add(
        SendCommand(
            thread_id=world.thread.id,
            actor_id="operator-1",
            campaign_id=world.campaign.id,
            recipient_contact_point_id=world.recipient.id,
            message_revision_id=world.revision.id,
            approval_id=approval.id,
            approval_expires_at=approval.approval_expires_at,
            idempotency_key="d" * 64,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- delivery_unknown never retries (criterion 3) -----------------------------------------------


def test_delivery_unknown_has_no_path_back_to_sending() -> None:
    """§17.3 / ADR-016: ambiguity is resolved by reconciliation, never by resending."""
    onward = allowed_transitions(OutreachThreadState.DELIVERY_UNKNOWN)

    assert OutreachThreadState.SENDING not in onward
    assert OutreachThreadState.QUEUED not in onward
    assert not is_terminal(OutreachThreadState.DELIVERY_UNKNOWN), "it must still be resolvable"


def test_an_ambiguous_attempt_leads_to_delivery_unknown(db_session: Session, world: World) -> None:
    approval = world.approval(db_session)
    command = make_command(db_session, world, approval)
    transition_thread(db_session, world.thread, OutreachThreadState.QUEUED, actor=OPERATOR)
    transition_thread(db_session, world.thread, OutreachThreadState.SENDING, actor=OPERATOR)

    db_session.add(
        SendAttempt(
            send_command_id=command.id,
            attempt_number=1,
            started_at=NOW,
            finished_at=NOW,
            outcome=AttemptOutcome.AMBIGUOUS,
            error_summary="provider timed out after accepting the connection",
        )
    )
    transition_thread(
        db_session, world.thread, OutreachThreadState.DELIVERY_UNKNOWN, actor=OPERATOR
    )
    db_session.flush()

    assert world.thread.needs_manual_reconciliation()
    assert world.thread.unresolved_since is not None


def test_resending_from_delivery_unknown_is_refused(db_session: Session, world: World) -> None:
    # A thread may not leave `not_started` without a command behind it (`T-141`), so order one
    # first: reaching `delivery_unknown` presupposes a send was actually authorized.
    make_command(db_session, world, world.approval(db_session))
    transition_thread(db_session, world.thread, OutreachThreadState.QUEUED, actor=OPERATOR)
    transition_thread(db_session, world.thread, OutreachThreadState.SENDING, actor=OPERATOR)
    transition_thread(
        db_session, world.thread, OutreachThreadState.DELIVERY_UNKNOWN, actor=OPERATOR
    )

    with pytest.raises(IllegalTransition):
        transition_thread(db_session, world.thread, OutreachThreadState.SENDING, actor=OPERATOR)


def test_reconciliation_can_resolve_delivery_unknown(db_session: Session, world: World) -> None:
    """The way out is finding out what happened, not trying again."""
    make_command(db_session, world, world.approval(db_session))
    transition_thread(db_session, world.thread, OutreachThreadState.QUEUED, actor=OPERATOR)
    transition_thread(db_session, world.thread, OutreachThreadState.SENDING, actor=OPERATOR)
    transition_thread(
        db_session, world.thread, OutreachThreadState.DELIVERY_UNKNOWN, actor=OPERATOR
    )

    transition_thread(
        db_session,
        world.thread,
        OutreachThreadState.DELIVERED,
        actor=OPERATOR,
        reason="provider confirmed delivery on reconciliation",
    )
    db_session.flush()

    assert world.thread.state is OutreachThreadState.DELIVERED
    assert world.thread.unresolved_since is None


def test_a_thread_starts_not_started(world: World) -> None:
    assert world.thread.state is OutreachThreadState.NOT_STARTED


def test_one_thread_per_candidate(db_session: Session, world: World) -> None:
    db_session.add(OutreachThread(candidate_id=world.candidate.id))

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- attempts, events, interactions -------------------------------------------------------------


def test_attempt_numbers_are_unique_per_command(db_session: Session, world: World) -> None:
    approval = world.approval(db_session)
    command = make_command(db_session, world, approval)
    db_session.add(SendAttempt(send_command_id=command.id, attempt_number=1, started_at=NOW))
    db_session.flush()
    db_session.add(SendAttempt(send_command_id=command.id, attempt_number=1, started_at=NOW))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_redelivered_provider_event_is_counted_once(db_session: Session, world: World) -> None:
    """Providers redeliver webhooks; the same event must not be recorded twice (§15.2)."""
    for _ in range(2):
        db_session.add(
            DeliveryEvent(
                thread_id=world.thread.id,
                event_type=DeliveryEventType.DELIVERED,
                provider="fake",
                provider_event_id="evt-1",
                occurred_at=NOW,
            )
        )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_providers_may_use_the_same_event_id(db_session: Session, world: World) -> None:
    db_session.add(
        DeliveryEvent(
            thread_id=world.thread.id,
            event_type=DeliveryEventType.DELIVERED,
            provider="fake",
            provider_event_id="evt-1",
            occurred_at=NOW,
        )
    )
    db_session.add(
        DeliveryEvent(
            thread_id=world.thread.id,
            event_type=DeliveryEventType.DELIVERED,
            provider="other",
            provider_event_id="evt-1",
            occurred_at=NOW,
        )
    )

    db_session.flush()  # must not raise


def test_an_inbound_interaction_requires_a_human_by_default(
    db_session: Session, world: World
) -> None:
    """§21.2 rejects autonomous substantive reply handling."""
    interaction = Interaction(
        thread_id=world.thread.id,
        direction=InteractionDirection.INBOUND,
        occurred_at=NOW,
        summary="SYNTHETIC: prospect replied",
    )
    db_session.add(interaction)
    db_session.flush()

    assert interaction.requires_human is True
    assert interaction.handled_by is None


def test_an_attempt_may_record_refusal_by_shadow_mode() -> None:
    """Shadow mode refusing to act is a real outcome, not an error (§17.6)."""
    assert AttemptOutcome.REFUSED_BY_SHADOW_MODE in set(AttemptOutcome)


# --- audit ----------------------------------------------------------------------------------------


def test_ordering_is_audited_with_its_key(db_session: Session, world: World) -> None:
    approval = world.approval(db_session)
    command = make_command(db_session, world, approval)
    db_session.flush()

    event = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="send_command", entity_id=str(command.id))
        .one()
    )

    assert event.action == "send_command.created"
    assert event.payload["idempotency_key"] == command.idempotency_key
    assert event.policy_decision == "approval valid at order time"


def test_thread_transitions_are_audited(db_session: Session, world: World) -> None:
    make_command(db_session, world, world.approval(db_session))
    transition_thread(db_session, world.thread, OutreachThreadState.QUEUED, actor=OPERATOR)
    db_session.flush()

    event = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="outreach_thread", entity_id=str(world.thread.id))
        .one()
    )

    assert (event.from_state, event.to_state) == ("not_started", "queued")


def test_no_send_path_exists_in_this_module() -> None:
    """T-022 records; it does not act. Dispatch is T-035, behind a fake adapter and gate G-07."""
    from app.outreach_and_replies import commands, models

    for module in (models, commands):
        assert module.__file__ is not None
        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("smtplib", "httpx", "requests", "aiohttp"):
            assert forbidden not in source, f"{module.__name__} references {forbidden}"
