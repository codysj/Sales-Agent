"""Creating and superseding message revisions (specification §10.5, §8.4).

Editing is not editing. It creates revision N+1 and retires N, because an approval binds to an
exact revision and rewriting that revision in place would leave an approval pointing at content
nobody approved (§10.5, §8.4).
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor, record_audit_event
from app.core.lifecycles import MessageRevisionState, assert_transition
from app.drafts_and_approvals.models import MessageDraft, MessageRevision

ENTITY_TYPE = "message_revision"

#: States in which a revision has left circulation.
RETIRED_STATES = frozenset({MessageRevisionState.SUPERSEDED, MessageRevisionState.INVALIDATED})


class RevisionError(Exception):
    """A revision could not be created or changed safely."""


def compute_content_hash(
    *,
    recipient_contact_point_id: uuid.UUID,
    subject: str,
    body: str,
    approved_claim_ids: list[uuid.UUID],
    evidence_ids: list[uuid.UUID],
) -> str:
    """Hash everything that makes the message what it is.

    Recipient is included because §11.4 treats "this message to this person" as the approved
    unit — the same words to a different address is a different thing entirely.

    Citation order is preserved rather than sorted: reordering is treated as a change, which errs
    toward invalidating an approval rather than silently keeping it.
    """
    canonical = json.dumps(
        {
            "recipient_contact_point_id": str(recipient_contact_point_id),
            "subject": subject,
            "body": body,
            "approved_claim_ids": [str(value) for value in approved_claim_ids],
            "evidence_ids": [str(value) for value in evidence_ids],
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reject_duplicate_citations(
    approved_claim_ids: list[uuid.UUID], evidence_ids: list[uuid.UUID]
) -> None:
    for label, values in (("claim", approved_claim_ids), ("evidence", evidence_ids)):
        if len(set(values)) != len(values):
            raise RevisionError(
                f"duplicate {label} IDs in a revision; each citation should appear once so the "
                f"reviewer sees exactly what the message rests on"
            )


def latest_revision(session: Session, draft_id: uuid.UUID) -> MessageRevision | None:
    return session.execute(
        select(MessageRevision)
        .where(MessageRevision.draft_id == draft_id)
        .order_by(MessageRevision.revision_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def live_revision(session: Session, draft_id: uuid.UUID) -> MessageRevision | None:
    """The one revision that has not been superseded or invalidated, if any."""
    return session.execute(
        select(MessageRevision)
        .where(
            MessageRevision.draft_id == draft_id,
            MessageRevision.state.not_in(RETIRED_STATES),
        )
        .order_by(MessageRevision.revision_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def create_revision(
    session: Session,
    *,
    draft: MessageDraft,
    recipient_contact_point_id: uuid.UUID,
    subject: str,
    body: str,
    approved_claim_ids: list[uuid.UUID] | None = None,
    evidence_ids: list[uuid.UUID] | None = None,
    created_by: str,
    actor: Actor,
    correlation_id: str | None = None,
) -> MessageRevision:
    """Add the next revision to a draft, retiring whichever one was live.

    Added to the caller's session without committing, so the revision, the retirement of its
    predecessor, and both audit events land together (§17.2).
    """
    claims = list(approved_claim_ids or [])
    evidence = list(evidence_ids or [])
    _reject_duplicate_citations(claims, evidence)

    previous = latest_revision(session, draft.id)
    next_number = (previous.revision_number + 1) if previous else 1

    if previous is not None and previous.state not in RETIRED_STATES:
        supersede(
            session,
            previous,
            actor=actor,
            reason=f"superseded by revision {next_number}",
            correlation_id=correlation_id,
        )

    revision = MessageRevision(
        draft_id=draft.id,
        revision_number=next_number,
        recipient_contact_point_id=recipient_contact_point_id,
        subject=subject,
        body=body,
        approved_claim_ids=claims,
        evidence_ids=evidence,
        content_hash=compute_content_hash(
            recipient_contact_point_id=recipient_contact_point_id,
            subject=subject,
            body=body,
            approved_claim_ids=claims,
            evidence_ids=evidence,
        ),
        state=MessageRevisionState.DRAFT,
        created_by=created_by,
    )
    session.add(revision)
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="message_revision.created",
        entity_type=ENTITY_TYPE,
        entity_id=revision.id,
        to_state=MessageRevisionState.DRAFT,
        payload={
            "draft_id": str(draft.id),
            "revision_number": next_number,
            "content_hash": revision.content_hash,
            "claim_count": len(claims),
            "evidence_count": len(evidence),
        },
        correlation_id=correlation_id,
    )
    return revision


def transition(
    session: Session,
    revision: MessageRevision,
    target: MessageRevisionState,
    *,
    actor: Actor,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> MessageRevision:
    """Move a revision's state, or raise. Content is never touched."""
    previous = revision.state
    assert_transition(previous, target)

    revision.state = target
    revision.retired_at = datetime.now(UTC) if target in RETIRED_STATES else None
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="message_revision.transitioned",
        entity_type=ENTITY_TYPE,
        entity_id=revision.id,
        from_state=previous,
        to_state=target,
        payload={"reason": reason} if reason else None,
        correlation_id=correlation_id,
    )
    return revision


def supersede(
    session: Session,
    revision: MessageRevision,
    *,
    actor: Actor,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> MessageRevision:
    """Retire a revision because a newer one replaces it (§10.5)."""
    return transition(
        session,
        revision,
        MessageRevisionState.SUPERSEDED,
        actor=actor,
        reason=reason,
        correlation_id=correlation_id,
    )


#: The only revision state an approval may be granted from. §8.2 offers `review_pending ->
#: approved` and no other edge into `approved`, and approving a revision nobody reviewed would
#: skip §8.3 step 8 entirely.
APPROVABLE_STATE: Final = MessageRevisionState.REVIEW_PENDING


class RevisionNotApprovable(RevisionError):
    """This revision is not in a state an approval may be granted from."""


def require_approvable(revision: MessageRevision) -> None:
    """Raise unless ``revision`` may be approved. Reads only; writes nothing.

    Separate from `mark_approved` because the caller needs to refuse *before* it writes anything
    (§11.3's transaction is all-or-nothing), and because a caller outside this package must not
    name `MessageRevisionState` at all — `tests/test_invariants.py` enforces that, and it is what
    sent this pair here rather than leaving it in the approval transaction.
    """
    if revision.state is not APPROVABLE_STATE:
        raise RevisionNotApprovable(
            f"revision {revision.id} is {revision.state.value}; §8.2 offers "
            f"`review_pending -> approved` and no other edge into approval"
        )


def mark_approved(
    session: Session,
    revision: MessageRevision,
    *,
    actor: Actor,
    correlation_id: str | None = None,
) -> MessageRevision:
    """Move ``revision`` to `approved`. Adds to ``session`` without committing.

    The approval *record* is `approval.py`'s; this is the revision's own state, and without it an
    `Approval` row would read `approved` while the revision it names still read `review_pending`.
    """
    require_approvable(revision)
    return transition(
        session,
        revision,
        MessageRevisionState.APPROVED,
        actor=actor,
        correlation_id=correlation_id,
    )


# --- operational counters (T-069a; §17.5 "review backlog and age") -------------------------------


def revisions_awaiting_review(session: Session) -> int:
    return session.execute(
        select(func.count())
        .select_from(MessageRevision)
        .where(MessageRevision.state == MessageRevisionState.REVIEW_PENDING)
    ).scalar_one()
