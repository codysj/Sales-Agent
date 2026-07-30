"""Synthetic fixture builders shared across test modules.

The §11.4 contract touches seven modules, so a test that needs one send command needs a product, a
campaign with a policy, an account, a contact, a contact point, a candidate, a draft, a revision, an
approval, and a thread. Building that chain twice is how two test files come to disagree about what
a valid send looks like.

Everything here is **synthetic**: names are prefixed `SYNTHETIC`, domains end in `.example.com` or
`.invalid`, and identifiers are random. Nothing resembles real prospect data (§19.6 Stage 1).

Extracted from `test_outreach.py` when `T-035c` needed the same chain.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import create_candidate
from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import publish_policy_version
from app.drafts_and_approvals.approval import Approval, approve, request_approval
from app.drafts_and_approvals.models import MessageDraft, MessageRevision
from app.drafts_and_approvals.revisions import create_revision
from app.outreach_and_replies.models import OutreachThread
from app.products_and_claims.models import Product
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
APPROVER = "approver-1"

#: A fixed moment, so approval expiry and suppression windows are deterministic.
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def synthetic_slug(prefix: str = "synthetic") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class World:
    """One coherent synthetic world: a campaign, a prospect, a draft, and a thread.

    Deliberately eager rather than lazy. A half-built world is the source of test failures that
    look like product bugs.
    """

    def __init__(self, session: Session, *, policy: CampaignPolicy | None = None) -> None:
        self.session = session

        self.product = Product(slug=synthetic_slug(), name="SYNTHETIC-Product")
        session.add(self.product)
        session.flush()

        self.campaign = Campaign(
            slug=synthetic_slug(),
            name="SYNTHETIC-Campaign",
            product_id=self.product.id,
        )
        self.account = Account(
            domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account"
        )
        session.add_all([self.campaign, self.account])
        session.flush()

        # A campaign with no published policy has no rules to recheck against, so every world gets
        # one. `require_verified_email` defaults to True, so the recipient below is verified.
        self.policy_version = publish_policy_version(
            session,
            campaign_id=self.campaign.id,
            policy=policy or CampaignPolicy(),
            approved_by=APPROVER,
        )

        self.contact = Contact(account_id=self.account.id, full_name="SYNTHETIC Person")
        session.add(self.contact)
        session.flush()

        self.recipient = ContactPoint(
            contact_id=self.contact.id,
            type=ContactPointType.EMAIL,
            value=f"{uuid.uuid4().hex[:8]}@{self.account.domain}",
            verification_state=VerificationState.VERIFIED,
        )
        session.add(self.recipient)
        session.flush()

        self.candidate = create_candidate(
            session,
            campaign_id=self.campaign.id,
            account_id=self.account.id,
            contact_id=self.contact.id,
            actor=OPERATOR,
        )
        self.draft = MessageDraft(candidate_id=self.candidate.id)
        session.add(self.draft)
        session.flush()

        self.revision: MessageRevision = create_revision(
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

    def activate(self) -> None:
        """Start the campaign.

        Not done in the constructor on purpose. `Campaign.paused` defaults to True (`T-015`) and a
        test that forgets to start its campaign *should* see a refusal — that is the fail-closed
        behaviour, and hiding it behind a helpful default would make the pause recheck untestable.
        """
        self.campaign.paused = False
        self.session.flush()

    def approval(
        self,
        session: Session | None = None,
        *,
        now: datetime = NOW,
        product_status_version_id: uuid.UUID | None = None,
    ) -> Approval:
        """A granted approval for this world's revision.

        ``product_status_version_id`` must be passed here rather than set afterwards: an approval's
        pins are immutable by trigger (§8.4 — "request a new approval instead").
        """
        active = session or self.session
        approval = request_approval(
            active,
            revision=self.revision,
            approver_id=APPROVER,
            actor=OPERATOR,
            product_status_version_id=product_status_version_id,
            now=now,
        )
        approve(active, approval, actor=OPERATOR, now=now)
        active.flush()
        return approval

    @property
    def email_domain(self) -> str:
        return self.recipient.value.rpartition("@")[2]
