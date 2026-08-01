"""Creating send commands (specification §11.3 step 4, §11.4, ADR-016).

Creating the order is not performing it. `T-035` dispatches, rechecks the §11.4 list inside the
transaction, and talks to an adapter. This module only turns a *valid approval* into an immutable
order — and refuses if the approval no longer authorizes what it authorized.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor, record_audit_event
from app.core.lifecycles import OutreachThreadState, assert_transition
from app.drafts_and_approvals.approval import Approval, require_valid
from app.outreach_and_replies.models import (
    ActionType,
    OutreachThread,
    SendAttempt,
    SendCommand,
    build_idempotency_key,
)

ENTITY_TYPE = "send_command"
THREAD_ENTITY_TYPE = "outreach_thread"


class ThreadNotStartable(Exception):
    """A thread was asked to leave `not_started` with nothing authorizing a send (§8.2, §11.4)."""


def require_send_command(session: Session, thread: OutreachThread) -> None:
    """Raise unless at least one send command exists for this thread.

    §8.2 makes `not_started` mean "nothing has been ordered yet". Any state after it asserts that a
    send *was* authorized, and thread state is what the review dashboard reads — so a thread sitting
    in `queued` with no command behind it is a record claiming an approval that does not exist.

    Nothing external happens on this transition, so this is not a §3.5 violation on its own. It is a
    truthfulness guarantee about the record, which is why the check is here rather than in the §11.4
    dispatch rechecks: by dispatch time a command exists by definition.
    """
    exists = session.execute(
        select(SendCommand.id).where(SendCommand.thread_id == thread.id).limit(1)
    ).scalar_one_or_none()
    if exists is None:
        raise ThreadNotStartable(
            f"thread {thread.id} cannot leave not_started: no send command exists for it. "
            f"Order the send first — thread state after not_started asserts that one was "
            f"authorized (§8.2)."
        )


def transition_thread(
    session: Session,
    thread: OutreachThread,
    target: OutreachThreadState,
    *,
    actor: Actor,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> OutreachThread:
    """Move a thread's state, or raise.

    There is no path from ``delivery_unknown`` back to ``sending`` or ``queued``; the lifecycle
    table refuses it, which is how "no blind retry" (§17.3) is enforced rather than remembered.

    Leaving ``not_started`` additionally requires a send command to exist (`T-141`). The lifecycle
    table cannot express that — it constrains which state may follow which, not what must be true
    about other rows — so it is checked here.
    """
    previous = thread.state
    assert_transition(previous, target)

    if previous is OutreachThreadState.NOT_STARTED:
        require_send_command(session, thread)

    thread.state = target
    thread.unresolved_since = (
        datetime.now(UTC) if target is OutreachThreadState.DELIVERY_UNKNOWN else None
    )
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="outreach_thread.transitioned",
        entity_type=THREAD_ENTITY_TYPE,
        entity_id=thread.id,
        from_state=previous,
        to_state=target,
        payload={"reason": reason} if reason else None,
        correlation_id=correlation_id,
    )
    return thread


def create_send_command(
    session: Session,
    *,
    thread: OutreachThread,
    approval: Approval,
    campaign_id: uuid.UUID,
    actor: Actor,
    record_versions: dict[str, Any] | None = None,
    now: datetime | None = None,
    correlation_id: str | None = None,
) -> SendCommand:
    """Turn a still-valid approval into one immutable send order.

    Refuses outright if the approval no longer authorizes the send — the same check `T-035`
    repeats inside the dispatch transaction. Checking twice is deliberate: time passes between
    ordering and dispatching, and §8.4's triggers can fire in the gap.

    Added to the caller's session without committing, so the command, the thread transition, and
    the audit event land together (§17.2).
    """
    require_valid(session, approval, now=now)

    command = SendCommand(
        action_type=ActionType.EMAIL_SEND,
        thread_id=thread.id,
        actor_id=actor.id,
        campaign_id=campaign_id,
        recipient_contact_point_id=approval.recipient_contact_point_id,
        message_revision_id=approval.message_revision_id,
        approval_id=approval.id,
        approval_expires_at=approval.approval_expires_at,
        record_versions=record_versions or {},
        product_status_version_id=approval.product_status_version_id,
        approved_claim_set_id=approval.approved_claim_set_id,
        idempotency_key=build_idempotency_key(
            approval_id=approval.id,
            message_revision_id=approval.message_revision_id,
            recipient_contact_point_id=approval.recipient_contact_point_id,
        ),
    )
    session.add(command)
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="send_command.created",
        entity_type=ENTITY_TYPE,
        entity_id=command.id,
        payload={
            "approval_id": str(approval.id),
            "message_revision_id": str(approval.message_revision_id),
            "idempotency_key": command.idempotency_key,
        },
        policy_decision="approval valid at order time",
        correlation_id=correlation_id,
    )
    return command


def revision_already_sent(session: Session, message_revision_id: uuid.UUID) -> bool:
    """Whether a delivery was attempted for this revision (T-056).

    Supplied to `drafts_and_approvals.invalidation` as its `AlreadySentCheck`, because §18.2
    forbids that package importing this one. An *attempt* rather than a successful delivery is
    the right test: an ambiguous result is `delivery_unknown` (§17.3), and a message that may
    have arrived must not be treated as one that never left.
    """
    return (
        session.execute(
            select(SendAttempt.id)
            .join(SendCommand, SendCommand.id == SendAttempt.send_command_id)
            .where(SendCommand.message_revision_id == message_revision_id)
            .limit(1)
        ).first()
        is not None
    )
