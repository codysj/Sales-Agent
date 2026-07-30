"""The §11.4 dispatch-time rechecks.

§11.4 requires the *final dispatch transaction* to re-evaluate every condition the decision rested
on. Approval happened earlier — possibly much earlier — and in between an approval can be revoked,
a recipient can unsubscribe, a campaign can be paused, a product's claims can be withdrawn. A
system that checks at approval time and sends at dispatch time is a system that eventually sends
something nobody would approve now.

**These rechecks live here, not in the dispatcher.** `jobs_and_outbox` must not know what an
approval is (§18.2, and `docs/architecture/modules.md` says so explicitly: "Domain modules register
handlers and perform their own §11.4 rechecks inside the dispatch transaction"). The dispatcher
takes an injected `PreconditionCheck` and this module supplies one.

The join from a generic outbox event back to its `SendCommand` is the **idempotency key** — unique
in both tables by design (`T-034`), which is what makes it possible to look up the domain contract
without the outbox holding a foreign key into the domain.

**Six of §11.4's nine conditions are already enforced by `invalidation_reason` (§8.4), and this
module delegates to it rather than checking them again.** That function is the designated place, and
a second comparison here would report the wrong condition when both could fire — which is exactly
what happened while this module was being written. The split:

| §11.4 condition                      | Enforced by                                    |
|--------------------------------------|------------------------------------------------|
| Approval state and expiration        | `invalidation_reason` (§8.4)                   |
| Exact recipient                      | `invalidation_reason` — pinned recipient       |
| Exact immutable revision             | `invalidation_reason` — pinned content hash    |
| Product-status version               | `invalidation_reason` — pinned version         |
| Approved-claim-set version           | `invalidation_reason` — pinned claim set       |
| Candidate decision after approval    | here (§8.2, `T-140`) — the layer approval cannot see |
| Approver identity and authority      | here, against the command's recorded stamp     |
| Suppression at every scope           | here                                           |
| Email verification                   | here                                           |
| Campaign active status and volume    | here                                           |
| Current record versions              | here                                           |
| Existing result for the key          | here                                           |
| **Sender availability**              | **nothing — `Q-004`, `T-035d`**                |

Several §11.4 conditions additionally cannot drift at all: `send_command` is immutable by trigger
and its contract fields are `RESTRICT` foreign keys copied from the approval, so "the command now
points somewhere else" is prevented rather than detected.

`SENDER_AVAILABILITY` is named in `Recheck` so the one real gap is visible where someone would look
for it, rather than implied by absence. `Q-004` has chosen no mailbox, provider, or sender identity,
so there is nothing to check availability against; `T-035d` implements it once that is answered.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import require_current_policy
from app.drafts_and_approvals.approval import (
    Approval,
    candidate_refusal,
    invalidation_reason,
)
from app.drafts_and_approvals.models import MessageRevision
from app.outreach_and_replies.models import SendAttempt, SendCommand
from app.prospects.models import ContactPoint, VerificationState
from app.prospects.suppression import find_suppression


class Recheck(StrEnum):
    """The §11.4 conditions, named so a refusal can say which one failed (criterion 2)."""

    APPROVER_AUTHORITY = "approver_authority"
    APPROVAL_VALIDITY = "approval_validity"
    #: The candidate behind the message was decided against after the approval was granted
    #: (§8.2, `T-140`). Distinct from `APPROVAL_VALIDITY` because the approval itself is still fine.
    CANDIDATE_DECISION = "candidate_decision"
    RECIPIENT_AND_REVISION = "recipient_and_revision"
    SUPPRESSION = "suppression"
    EMAIL_VERIFICATION = "email_verification"
    #: Not implemented — `Q-004` has chosen no mailbox or sender identity. See `T-035d`.
    SENDER_AVAILABILITY = "sender_availability"
    CAMPAIGN_STATUS = "campaign_status"
    PRODUCT_AND_CLAIM_VERSIONS = "product_and_claim_versions"
    RECORD_VERSIONS = "record_versions"
    EXISTING_RESULT = "existing_result"


#: Rechecks whose failure may become valid again, so refusing must not spend the retry budget
#: (criterion 3). A paused campaign gets unpaused; a revoked approval does not get un-revoked.
RECOVERABLE = frozenset({Recheck.CAMPAIGN_STATUS})


class PreconditionFailure(Exception):
    """A §11.4 recheck refused the dispatch.

    Carries *which* check failed rather than only a message, so the dispatcher can record it
    structurally and decide whether the condition may later become valid.
    """

    def __init__(self, check: Recheck, detail: str) -> None:
        self.check = check
        self.detail = detail
        super().__init__(f"{check.value}: {detail}")

    @property
    def is_recoverable(self) -> bool:
        return self.check in RECOVERABLE


class MissingSendCommand(PreconditionFailure):
    """No send command carries this outbox event's idempotency key."""

    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            Recheck.EXISTING_RESULT,
            f"no send command carries key {idempotency_key[:12]}…; an external effect with no "
            f"§11.4 contract behind it must never be performed",
        )


def load_send_command(session: Session, idempotency_key: str) -> SendCommand | None:
    """Find the §11.4 contract behind an outbox event, by the key the two share (`T-034`)."""
    return session.execute(
        select(SendCommand).where(SendCommand.idempotency_key == idempotency_key)
    ).scalar_one_or_none()


def _check_approval(session: Session, command: SendCommand, now: datetime) -> None:
    approval = session.get(Approval, command.approval_id)
    if approval is None:
        raise PreconditionFailure(
            Recheck.APPROVAL_VALIDITY, "the approval this command cites no longer exists"
        )

    # §11.4 lists approver identity/authority separately from approval state. The command records
    # the approver it relied on; if the approval now names someone else, the authority behind this
    # send is not the authority that was checked.
    recorded_approver = (command.record_versions or {}).get("approver_id")
    if recorded_approver is not None and recorded_approver != approval.approver_id:
        raise PreconditionFailure(
            Recheck.APPROVER_AUTHORITY,
            f"the approval is now held by {approval.approver_id!r}, not the "
            f"{recorded_approver!r} this command relied on",
        )

    reason = invalidation_reason(session, approval, now=now)
    if reason is not None:
        raise PreconditionFailure(Recheck.APPROVAL_VALIDITY, reason)

    # §8.2 and `T-140`: the approval-time check cannot see a candidate rejected *afterwards*, and
    # the gap between approval and dispatch is exactly where that happens. Same read, second layer —
    # which is the whole reason §11.4 rechecks rather than trusting the earlier decision.
    revision = session.get(MessageRevision, command.message_revision_id)
    if revision is not None:
        candidate_block = candidate_refusal(session, revision)
        if candidate_block is not None:
            raise PreconditionFailure(Recheck.CANDIDATE_DECISION, candidate_block)

    # The command copied `approval_expires_at` at order time deliberately (§11.4). If the stored
    # expiry has passed, the command is stale even should the approval row say otherwise.
    if command.approval_expires_at <= now:
        raise PreconditionFailure(
            Recheck.APPROVAL_VALIDITY,
            f"the command's recorded approval expiry ({command.approval_expires_at.isoformat()}) "
            f"has passed",
        )


def _check_recipient_and_revision(session: Session, command: SendCommand) -> ContactPoint:
    revision = session.get(MessageRevision, command.message_revision_id)
    if revision is None:
        raise PreconditionFailure(
            Recheck.RECIPIENT_AND_REVISION, "the message revision no longer exists"
        )

    if revision.recipient_contact_point_id != command.recipient_contact_point_id:
        raise PreconditionFailure(
            Recheck.RECIPIENT_AND_REVISION,
            "the revision's recipient differs from the command's recipient",
        )

    # Deliberately *not* recomputing the content hash here. `invalidation_reason` (called above,
    # via `_check_approval`) already refuses when the message content no longer matches what was
    # approved — that is §8.4's invalidation path, and it is the check the specification designates.
    # A second hash comparison in this module would duplicate it and report the wrong condition.

    recipient = session.get(ContactPoint, command.recipient_contact_point_id)
    if recipient is None:
        raise PreconditionFailure(
            Recheck.RECIPIENT_AND_REVISION, "the recipient contact point no longer exists"
        )
    return recipient


def _check_suppression(session: Session, recipient: ContactPoint, now: datetime) -> None:
    """§11.4: person, email, domain, and account scope (§15.6).

    **Every scope is queried unconditionally, and `CampaignPolicy.suppression_scope` is deliberately
    not consulted here.** §11.4 says "as configured", but `T-015` already resolved that ambiguity in
    the direction safety requires: a policy may *widen* what it respects and never narrow it at send
    time. Reading the policy here to skip a scope would turn a suppression record into something a
    campaign setting can override, which is the one thing §15.6 does not allow.
    """
    contact = recipient.contact
    suppression = find_suppression(
        session,
        email=recipient.value,
        contact_id=recipient.contact_id,
        account_id=contact.account_id if contact else None,
        domain=recipient.value.rpartition("@")[2] or None,
        at=now,
    )
    if suppression is not None:
        raise PreconditionFailure(
            Recheck.SUPPRESSION, f"suppressed at {suppression.scope.value} scope"
        )


def _check_email_verification(recipient: ContactPoint, policy: CampaignPolicy) -> None:
    """The implementable half of §11.4's verification bullet. Sender availability is `T-035d`."""
    if recipient.verification_state is VerificationState.INVALID:
        raise PreconditionFailure(
            Recheck.EMAIL_VERIFICATION, "the recipient address is known to be invalid"
        )
    if policy.require_verified_email and recipient.verification_state is not (
        VerificationState.VERIFIED
    ):
        raise PreconditionFailure(
            Recheck.EMAIL_VERIFICATION,
            f"the campaign requires a verified address and this one is "
            f"{recipient.verification_state.value}",
        )


def _check_campaign(campaign: Campaign, policy: CampaignPolicy, sent_total: int) -> None:
    """§11.4: campaign active status **and volume limit**."""
    if campaign.paused:
        # Recoverable: a paused campaign is a decision that gets reversed, and §17.1 requires the
        # held work to stay intact rather than be failed.
        raise PreconditionFailure(Recheck.CAMPAIGN_STATUS, "the campaign is paused")
    if sent_total >= policy.total_send_cap:
        raise PreconditionFailure(
            Recheck.CAMPAIGN_STATUS,
            f"the campaign has reached its total send cap ({policy.total_send_cap})",
        )


def _check_record_versions(session: Session, command: SendCommand) -> None:
    """§11.4 ``record_versions``: the rows the decision depended on must not have moved."""
    for key, recorded in (command.record_versions or {}).items():
        if not key.endswith("_updated_at"):
            continue
        table, _, _ = key.rpartition("_updated_at")
        current = _current_updated_at(session, table, command)
        if current is not None and current != recorded:
            raise PreconditionFailure(
                Recheck.RECORD_VERSIONS,
                f"{table} changed since approval (recorded {recorded}, now {current})",
            )


def _current_updated_at(session: Session, table: str, command: SendCommand) -> str | None:
    """The current version stamp for a recorded table, or `None` if we cannot resolve it."""
    lookups: dict[str, tuple[type[object], uuid.UUID | None]] = {
        "message_revision": (MessageRevision, command.message_revision_id),
        "approval": (Approval, command.approval_id),
        "contact_point": (ContactPoint, command.recipient_contact_point_id),
        "campaign": (Campaign, command.campaign_id),
    }
    entry = lookups.get(table)
    if entry is None:
        return None
    model, row_id = entry
    if row_id is None:
        return None
    row = session.get(model, row_id)
    stamp = getattr(row, "updated_at", None)
    return stamp.isoformat() if stamp is not None else None


def _check_existing_result(session: Session, command: SendCommand) -> None:
    """§11.4's last item, and §17.3's duplicate guard.

    A command with a recorded attempt has already reached the provider. Sending again would be the
    duplicate the whole idempotency-key design exists to prevent.
    """
    already = session.execute(
        select(SendAttempt.id).where(SendAttempt.send_command_id == command.id).limit(1)
    ).scalar_one_or_none()
    if already is not None:
        raise PreconditionFailure(
            Recheck.EXISTING_RESULT,
            "this command already has a recorded send attempt; sending again would duplicate it",
        )


def recheck_send_command(
    session: Session, command: SendCommand, *, now: datetime | None = None
) -> None:
    """Re-evaluate every implementable §11.4 condition. Raises `PreconditionFailure` to refuse.

    Order matters only for which failure is reported first, and it is deliberate: the cheapest and
    most consequential checks come first, so a revoked approval or a suppressed recipient is
    reported before anything more speculative.
    """
    moment = now or datetime.now(UTC)

    campaign = session.get(Campaign, command.campaign_id)
    if campaign is None:
        raise PreconditionFailure(Recheck.CAMPAIGN_STATUS, "the campaign no longer exists")
    policy = require_current_policy(session, campaign.id)
    sent_total = session.execute(
        select(func.count(SendAttempt.id))
        .join(SendCommand, SendAttempt.send_command_id == SendCommand.id)
        .where(SendCommand.campaign_id == campaign.id)
    ).scalar_one()

    _check_approval(session, command, moment)
    recipient = _check_recipient_and_revision(session, command)
    _check_suppression(session, recipient, moment)
    _check_email_verification(recipient, policy)
    _check_campaign(campaign, policy, sent_total)
    _check_record_versions(session, command)
    _check_existing_result(session, command)


def send_precondition_check(session: Session, idempotency_key: str) -> None:
    """The `PreconditionCheck` the dispatcher injects for send effects.

    Signature matches `app.jobs_and_outbox.dispatch.PreconditionCheck`. Takes the key rather than
    the outbox event so the dispatcher never has to hand a domain module one of its own rows.
    """
    command = load_send_command(session, idempotency_key)
    if command is None:
        raise MissingSendCommand(idempotency_key)
    recheck_send_command(session, command)
