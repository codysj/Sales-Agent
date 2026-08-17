"""Editing a draft (T-065a; §10.5, §12.3, §8.4, §8.2).

§10.5 makes a message revision immutable: a reviewer who changes a word does not change a
revision, they create the next one. This composes what that actually requires, in an order that
matters:

1. **Retire any approval the old revision held**, *before* anything else. An approval names an
   exact revision (ADR-008) — approving text and then editing it is precisely the failure the
   immutability rule exists to prevent, so the approval must stop being usable in the same
   transaction that makes the text obsolete. `§8.2` allows `approved → revoked` but not
   `pending → revoked`, so a pending approval is expired instead: the edge that exists, and the
   same outcome for a reviewer.
2. **Create revision N+1**, which `T-020`'s `create_revision` does — and which supersedes N as
   part of the same call, so the two cannot drift apart.
3. **Re-run validation** (`T-055`). An edit is new text and new citations; whatever passed for
   revision N proves nothing about N+1. It may fail, and a failing edit lands in
   `validation_failed` rather than being rejected — the reviewer needs to see *why*, and the
   revision is the record of what they wrote.

**The old revision is not touched.** Nothing here writes to it beyond its state transition, and
`tests/test_review_edit.py` asserts its body, subject, citations, and content hash field by field
afterwards. That is the guarantee an auditor needs: the text someone approved is still readable
exactly as they approved it.

**A correction reason is required.** §12.3 item 7 asks for a structured reason, and an edit
without one is a change nobody can explain later. It is not optional and there is no default.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor
from app.core.lifecycles import ApprovalState, MessageRevisionState
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.approval import Approval, expire, revoke
from app.drafts_and_approvals.models import MessageDraft, MessageRevision
from app.drafts_and_approvals.validation import ValidationResult, apply_validation

log = structlog.get_logger(__name__)

#: Revision states an edit may start from.
#:
#: `superseded` is absent and stays absent: a superseded revision has a successor by definition,
#: so editing it would take stale text as the base and retire the live revision — the branch
#: §10.5's single-line numbering assumes away.
#:
#: `invalidated` was absent for the same reason and should not have been (`T-211`). A revision a
#: reviewer refused (`T-208`) is invalidated *and* is its draft's last word, and nothing supersedes
#: it, because nothing writes a replacement automatically. Excluding it meant a refusal was a dead
#: end: the candidate is already `approved`, and §8.2 offers `approved -> invalidated` and no edge
#: to `rejected`, so there was no legal move left anywhere in the product. Editing is the route
#: back, and `require_latest` is what keeps it from being the branch above.
EDITABLE_STATES: Final = frozenset(
    {
        MessageRevisionState.DRAFT,
        MessageRevisionState.REVIEW_PENDING,
        MessageRevisionState.VALIDATION_FAILED,
        MessageRevisionState.APPROVED,
        MessageRevisionState.INVALIDATED,
    }
)


class EditRefused(Exception):
    """The edit was not permitted."""


@dataclass(frozen=True, slots=True)
class EditResult:
    """What one edit did. Returned rather than logged so a caller can report it exactly."""

    revision: MessageRevision
    superseded_revision_id: uuid.UUID
    revoked_approvals: list[uuid.UUID]
    expired_approvals: list[uuid.UUID]
    validation: ValidationResult

    @property
    def is_valid(self) -> bool:
        return self.validation.is_valid


def _retire_approvals(
    session: Session,
    revision: MessageRevision,
    *,
    actor: Actor,
    reason: str,
    moment: datetime,
    correlation_id: str | None,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Stop every approval on ``revision`` being usable. Returns `(revoked, expired)`."""
    revoked: list[uuid.UUID] = []
    expired: list[uuid.UUID] = []
    for approval in (
        session.execute(select(Approval).where(Approval.message_revision_id == revision.id))
        .scalars()
        .all()
    ):
        if approval.state is ApprovalState.APPROVED:
            revoke(
                session,
                approval,
                actor=actor,
                reason=reason,
                now=moment,
                correlation_id=correlation_id,
            )
            revoked.append(approval.id)
        elif approval.state is ApprovalState.PENDING:
            expire(session, approval, actor=actor, now=moment, correlation_id=correlation_id)
            expired.append(approval.id)
    return revoked, expired


def edit_revision(
    session: Session,
    revision: MessageRevision,
    *,
    subject: str,
    body: str,
    correction_reason: str,
    actor: Actor,
    approved_claim_ids: list[uuid.UUID] | None = None,
    evidence_ids: list[uuid.UUID] | None = None,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> EditResult:
    """Create revision N+1 from an edit of ``revision``. Adds to ``session`` without committing.

    Everything lands in the caller's transaction: the retired approval, the superseded revision,
    the new one, and its validation outcome. A partial edit — new text with the old approval
    still live — is the one state this must never leave behind.
    """
    if not correction_reason.strip():
        raise EditRefused(
            "an edit needs a correction reason (§12.3 item 7); a change nobody can explain later "
            "is a change nobody can review"
        )
    if revision.state not in EDITABLE_STATES:
        raise EditRefused(
            f"revision {revision.id} is {revision.state.value}; editing history would branch the "
            f"revision chain, and §10.5's numbering assumes one line"
        )

    moment = at or datetime.now(UTC)
    draft = session.get(MessageDraft, revision.draft_id)
    if draft is None:  # pragma: no cover - the foreign key prevents this
        raise EditRefused(f"revision {revision.id} points at a missing draft")

    # The state check above is not sufficient on its own once `invalidated` is editable
    # (`T-211`). Every other editable state implies "latest" — a revision that has been replaced
    # is `superseded` — but nothing supersedes an invalidated one, so a draft can hold an
    # invalidated revision *and* a later live one at the same time. Editing the older of those
    # would base the new text on what a reviewer already refused and retire the current wording
    # to do it. Checked here rather than in the state table because it is a fact about the draft,
    # not about the revision.
    latest = revisions.latest_revision(session, draft.id)
    if latest is not None and latest.id != revision.id:
        raise EditRefused(
            f"revision {revision.id} is not the latest revision of its draft (revision "
            f"{latest.revision_number} is); edit that one, or the chain would branch"
        )

    # First, and deliberately: an approval must stop being usable in the same transaction that
    # makes the text it names obsolete.
    revoked, expired = _retire_approvals(
        session,
        revision,
        actor=actor,
        reason=f"superseded by an edit: {correction_reason}",
        moment=moment,
        correlation_id=correlation_id,
    )

    superseded_id = revision.id
    created = revisions.create_revision(
        session,
        draft=draft,
        recipient_contact_point_id=revision.recipient_contact_point_id,
        subject=subject,
        body=body,
        # Citations carry over unless the caller changes them: an edit is usually wording, and
        # silently dropping the claim a sentence rests on would make the new revision fail
        # `T-055`'s grounding check for a reason the reviewer never chose.
        approved_claim_ids=(
            approved_claim_ids
            if approved_claim_ids is not None
            else list(revision.approved_claim_ids)
        ),
        evidence_ids=(evidence_ids if evidence_ids is not None else list(revision.evidence_ids)),
        created_by=actor.id,
        actor=actor,
        correlation_id=correlation_id,
    )

    # Whatever passed for revision N proves nothing about N+1.
    validation = apply_validation(
        session, created, actor=actor, at=moment, correlation_id=correlation_id
    )

    log.info(
        "revision.edited",
        superseded_revision_id=str(superseded_id),
        revision_id=str(created.id),
        revision_number=created.revision_number,
        revoked_approvals=len(revoked),
        expired_approvals=len(expired),
        valid=validation.is_valid,
        # The reason, not the text: §15.5 keeps content out of the log line.
        failed_checks=[failure.check.value for failure in validation.failures],
    )
    return EditResult(
        revision=created,
        superseded_revision_id=superseded_id,
        revoked_approvals=revoked,
        expired_approvals=expired,
        validation=validation,
    )
