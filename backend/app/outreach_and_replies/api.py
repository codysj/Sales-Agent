"""The message-approval endpoint (T-067b; §11.3 step 1, §12.2, §15.1).

A router of its own rather than a handler in `drafts_and_approvals.api`, and the import graph
decided that: this endpoint calls `approve_message`, which lives here because
`outreach_and_replies` may import `drafts_and_approvals` and not the reverse
(`tests/test_module_boundaries.py::test_no_import_cycles`). Putting the handler with the rest of
the review API would have re-created the cycle `T-067a` already resolved once.

It shares the `/api/review` prefix, because the path is about where a reviewer acts rather than
about which package owns the code. Two routers on one prefix is the smaller surprise; a cycle
between two lifecycles is the larger one.
"""

import uuid
from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.lifecycles import LifecycleError
from app.drafts_and_approvals.approval import (
    Approval,
    ApprovalError,
    CandidateNotApprovable,
    InvalidationTrigger,
    approvals_needing_attention,
    require_approvable_candidate,
    revoke,
)
from app.drafts_and_approvals.models import MessageRevision
from app.identity.dependencies import db_session, requires, requires_bearer
from app.identity.rbac import Permission
from app.identity.sessions import Principal
from app.outreach_and_replies.approve_message import ApprovalTransactionRefused, approve_message
from app.prospects.models import ContactPoint

router = APIRouter(prefix="/api/review", tags=["review"])

# --- §11.3 step 1: what must be true before the transaction runs ----------------------------------
#
# `T-067a` owns steps 2-6 and refuses plenty on its own. This endpoint owns step 1, which is a
# different list and entirely about the *request*: "verify user identity, role, session, CSRF
# protection, record versions, and approval scope."
#
# Each of those maps to something already built, which is the point — step 1 is not new machinery,
# it is the machinery being *applied* to the one action §3.5 cares most about:
#
# * **identity, role, session** — `requires_bearer(Permission.APPROVE_MESSAGE)`. Tier 4 (§7.4): the
#   approval that lets an external effect happen at all, and a different permission from the tier-3
#   corrections, so a role that may tidy the queue cannot authorize outreach.
# * **CSRF** — the same refusal of cookie-only authentication every mutation here uses. `T-070`
#   replaces it with real protection; until then the exposure is removed rather than accepted.
# * **record versions** — the revision's `updated_at`, sent back by the client. §11.4 lists
#   `record_versions` on every consequential action, and `T-067a` carries whatever it is given.
# * **approval scope** — `require_approvable_candidate`: the revision's candidate must not already
#   be rejected, deferred, ineligible, or invalidated. Approving one that is would contradict a
#   decision already recorded against that prospect.


class ApproveMessageRequest(BaseModel):
    """What the approver confirms (§11.3 steps 1-2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: ADR-008 approves an exact recipient and an exact revision together, so the recipient is
    #: named rather than derived — the same reason `T-154a`'s candidate approval names one.
    recipient_contact_point_id: uuid.UUID
    #: The revision's `record_version` as the approver was shown it. Optional in the schema and
    #: checked when present: `T-067b`'s criterion is that it *is* verified, and a client that omits
    #: it is choosing to race rather than being silently excused.
    record_version: datetime | None = None


class ApproveMessageResponse(BaseModel):
    """What was approved, and what it produced."""

    model_config = ConfigDict(frozen=True)

    approval_id: uuid.UUID
    message_revision_id: uuid.UUID
    send_command_id: uuid.UUID
    #: Echoed as an address, not only an id: an approval confirmed as a UUID is one nobody can
    #: check by reading.
    recipient: str
    #: A plain string, not the enum: `tests/test_invariants.py` refuses any package
    #: outside `core` and `drafts_and_approvals` to name `MessageRevisionState`, and
    #: that rule outranks a slightly richer schema. JSON carries the value either way.
    revision_state: str
    #: Stated in the response because a reviewer pressing "approve" on a *message* deserves to know
    #: that nothing leaves the building yet. Shadow mode holds and **G-07** governs live sending.
    what_happens_next: str
    record_version: datetime


APPROVAL_OUTCOME_NOTE: Final = (
    "Nothing is sent. The approval and an immutable send command are recorded, and the worker "
    "dispatches only to the fake adapter while shadow mode is on. Live sending is gated (G-07) "
    "and needs a separate, explicit authorization."
)


@router.post(
    "/revisions/{revision_id}/approve",
    response_model=ApproveMessageResponse,
    summary="Approve an exact message revision for an exact recipient",
)
def approve_message_endpoint(
    revision_id: uuid.UUID,
    request: ApproveMessageRequest,
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires_bearer(Permission.APPROVE_MESSAGE))],
) -> ApproveMessageResponse:
    """§11.3 step 1, then the transaction.

    Every refusal below happens before `approve_message` is called, so a rejected request writes
    nothing at all — there is no partial state for the caller to undo, and no audit event claiming
    an approval that did not happen.
    """
    revision = session.get(MessageRevision, revision_id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such revision")

    if request.record_version is not None and request.record_version != revision.updated_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "this revision changed since it was loaded; reload the card before approving so "
                "you are approving the text you read"
            ),
        )

    # Approval scope. A read of candidate state, never a write to it (ADR-015).
    try:
        require_approvable_candidate(session, revision)
    except CandidateNotApprovable as refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refusal)) from refusal

    recipient = session.get(ContactPoint, request.recipient_contact_point_id)
    if recipient is None:
        # One answer for "no such address" and "not this revision's address": `T-067a` refuses the
        # mismatch too, and distinguishing them here would let a caller probe which ids exist.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="that recipient does not belong to this revision",
        )

    try:
        outcome = approve_message(
            session,
            revision,
            recipient=recipient,
            approver_id=principal.user.email,
            actor=principal.actor,
            record_versions={"message_revision": revision.updated_at.isoformat()},
        )
    except ApprovalTransactionRefused as refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refusal)) from refusal

    session.commit()
    return ApproveMessageResponse(
        approval_id=outcome.approval.id,
        message_revision_id=revision.id,
        send_command_id=outcome.send_command.id,
        recipient=recipient.value,
        revision_state=revision.state.value,
        what_happens_next=APPROVAL_OUTCOME_NOTE,
        record_version=revision.updated_at,
    )


# --- §7.5: stale approvals and invalidated drafts -------------------------------------------------
#
# §7.5 asks the application to *flag* stale approvals, invalidated drafts, and expired claims.
# These two endpoints are that flag and the response to it: a list of approvals that no longer
# authorize a send, each carrying the record that made it so, and a way to close one out.
#
# They live beside the approval transaction rather than with the review API for the same reason it
# does — `outreach_and_replies` may import `drafts_and_approvals` and not the reverse.


class AttentionRow(BaseModel):
    """One approval that no longer authorizes a send (§7.5, §8.4)."""

    model_config = ConfigDict(frozen=True)

    approval_id: uuid.UUID
    message_revision_id: uuid.UUID
    recipient_contact_point_id: uuid.UUID
    approver_id: str
    approval_expires_at: datetime
    trigger: InvalidationTrigger
    reason: str
    #: The record whose change caused this — the superseded claim set, the revision whose content
    #: moved. `None` only where the trigger names no other row (expiry, or the approval's own
    #: state). A flag nobody can trace back to a version starts an investigation rather than
    #: ending one.
    triggering_id: uuid.UUID | None
    record_version: datetime


class AttentionPage(BaseModel):
    """Approvals needing attention, oldest first."""

    model_config = ConfigDict(frozen=True)

    items: list[AttentionRow]


@router.get(
    "/attention/approvals",
    response_model=AttentionPage,
    summary="Approvals that no longer authorize a send",
)
def approvals_needing_attention_endpoint(
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires(Permission.VIEW_REVIEW_QUEUE))],
    campaign_id: uuid.UUID | None = None,
) -> AttentionPage:
    """§7.5's flag. A read, so `requires` rather than `requires_bearer`.

    Only approvals still in `approved` are scanned: one already revoked or rejected is not an
    attention item — somebody dealt with it — and listing them would bury the ones nobody has
    looked at.
    """
    return AttentionPage(
        items=[
            AttentionRow(
                approval_id=approval.id,
                message_revision_id=approval.message_revision_id,
                recipient_contact_point_id=approval.recipient_contact_point_id,
                approver_id=approval.approver_id,
                approval_expires_at=approval.approval_expires_at,
                trigger=detail.trigger,
                reason=detail.reason,
                triggering_id=detail.triggering_id,
                record_version=approval.updated_at,
            )
            for approval, detail in approvals_needing_attention(session, campaign_id=campaign_id)
        ]
    )


class RevokeApprovalRequest(BaseModel):
    """Why this approval is being revoked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(min_length=1, max_length=1000)
    record_version: datetime | None = None


class RevokeApprovalResponse(BaseModel):
    """What the revocation did."""

    model_config = ConfigDict(frozen=True)

    approval_id: uuid.UUID
    state: str
    reason: str
    record_version: datetime


@router.post(
    "/approvals/{approval_id}/revoke",
    response_model=RevokeApprovalResponse,
    summary="Revoke an approval so it can never dispatch",
)
def revoke_approval_endpoint(
    approval_id: uuid.UUID,
    request: RevokeApprovalRequest,
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires_bearer(Permission.APPROVE_MESSAGE))],
) -> RevokeApprovalResponse:
    """Withdraw an approval (§8.2's `approved -> revoked`, §17.6).

    **`APPROVE_MESSAGE`, the same permission that granted it.** Withdrawing an authorization is
    the same authority as giving one — a role that could revoke but not approve could stop any
    outreach it disliked, and one that could approve but not revoke could not undo its own
    mistake.

    A reason is required with no default: §17.6 wants operational actions explicable, and a
    revocation nobody can explain later is one a reviewer cannot distinguish from a fault.
    """
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such approval")

    if request.record_version is not None and request.record_version != approval.updated_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "this approval changed since it was loaded; reload before revoking so you are "
                "acting on the state you read"
            ),
        )

    try:
        revoke(session, approval, actor=principal.actor, reason=request.reason)
    except (ApprovalError, LifecycleError) as refusal:
        # `LifecycleError` too: §8.2 makes `revoked` terminal, so revoking twice is an illegal
        # transition rather than an approval-domain refusal — and a reviewer double-clicking
        # deserves a `409` saying so, not a `500`.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refusal)) from refusal

    session.commit()
    return RevokeApprovalResponse(
        approval_id=approval.id,
        state=approval.state.value,
        reason=request.reason,
        record_version=approval.updated_at,
    )
