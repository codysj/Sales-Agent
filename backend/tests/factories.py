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
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
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
from app.identity.models import User
from app.outreach_and_replies.models import OutreachThread
from app.products_and_claims.claim_models import ApprovedClaim, ApprovedClaimCampaign
from app.products_and_claims.claims import publish_claim_set
from app.products_and_claims.models import Product, ProductStatusVersion, ReadinessCategory
from app.products_and_claims.status import next_version_number
from app.prospects.imports import ImportBatch
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)

#: One deterministic hash so `a_source_batch` is get-or-create: `import_batch.content_hash`
#: is unique, and more than one test builds two worlds in the same transaction.
SOURCE_BATCH_HASH = "5" * 64

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")

#: The approver every `World` names, and an `app_user` row exists for it (`T-136a`).
#:
#: An email rather than the old opaque `approver-1`, for the same reason the seeder's approver
#: became one: `T-136b` turns these columns into foreign keys, and the value that will map to a
#: user row is the email — which is also what the production path writes (`principal.user.email`).
#: `example.invalid` is IANA-reserved (AGENTS.md rule 1).
#:
#: Individual test files still pass literal `"approver-1"` strings in about eighty places. That is
#: deliberate and left alone: nothing constrains those values until the foreign key lands, and
#: rewriting them now would be a large diff proving nothing. `T-136b` owns that sweep.
APPROVER = "synthetic-world-approver@example.invalid"

#: The other approver identities the suite names. They were `"owner-1"`, `"owner-2"`,
#: `"product-owner-1"`, and `"claim-owner-1"` — opaque strings that resolved to nothing, which is
#: what `T-136b`'s foreign key made impossible. Kept **distinct** rather than collapsed onto one
#: user: several tests turn on a *second* approver publishing the next version, and one shared
#: identity would quietly stop proving that.
OWNER_ONE = "synthetic-owner-one@example.invalid"
OWNER_TWO = "synthetic-owner-two@example.invalid"
PRODUCT_OWNER = "synthetic-product-owner@example.invalid"
CLAIM_OWNER = "synthetic-claim-owner@example.invalid"

#: Every approver identity a test may name, created once per database session. The foreign key
#: means a test cannot invent one at the call site any more, and threading a get-or-create through
#: fifty-six call sites would have put plumbing in front of what each test is actually about.
WELL_KNOWN_APPROVERS = (
    (APPROVER, "SYNTHETIC-World approver"),
    (OWNER_ONE, "SYNTHETIC-Owner one"),
    (OWNER_TWO, "SYNTHETIC-Owner two"),
    (PRODUCT_OWNER, "SYNTHETIC-Product owner"),
    (CLAIM_OWNER, "SYNTHETIC-Claim owner"),
)

#: One moment, shared by every test module, fixed for the whole run so approval expiry and
#: suppression windows are deterministic — but **anchored to the run, not written down** (T-142).
#:
#: A literal date expires. `Approval` carries `CHECK (approval_expires_at > created_at)` and
#: `created_at` comes from the server clock, so an approval built at a hard-coded `NOW` with the
#: 72-hour default TTL becomes un-insertable the moment real time passes `NOW + 72h`. That is
#: not a slow drift: 89 tests went from green to red between two runs on the same day, with no
#: code change between them.
#:
#: Truncated to the hour and pushed a day back so it is always comfortably in the past (rows may
#: be dated before it) while `NOW + DEFAULT_APPROVAL_TTL` stays comfortably in the future.
#: `tests/test_fixture_clock.py` asserts both margins, so this cannot rot back into a literal.
NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=1)


def synthetic_slug(prefix: str = "synthetic") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def a_source_batch(session: Session) -> ImportBatch:
    """A synthetic CSV import batch, created once per session (`T-144a`).

    Every `World` contact names one, so `T-144b` — which refuses a candidate with no approved
    source basis — does not arrive to a suite full of unattributed identities and a sweep that
    hides whether the rule works.
    """
    existing = session.execute(
        select(ImportBatch).where(ImportBatch.content_hash == SOURCE_BATCH_HASH)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    batch = ImportBatch(
        source_type="csv",
        source_name="SYNTHETIC-world-import.csv",
        content_hash=SOURCE_BATCH_HASH,
    )
    session.add(batch)
    session.flush()
    return batch


def a_user(session: Session, email: str, display_name: str = "SYNTHETIC-Approver") -> User:
    """Get-or-create by email (`T-136a`).

    Get-or-*create*: `app_user.email` is unique, and more than one test builds two `World`s in the
    same transaction.
    """
    existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        return existing
    user = User(email=email, display_name=display_name, subject=None, active=True)
    session.add(user)
    session.flush()
    return user


def approver_user(session: Session) -> User:
    """The `app_user` behind :data:`APPROVER`."""
    return a_user(session, APPROVER, "SYNTHETIC-World approver")


def create_well_known_approvers(session: Session) -> None:
    """Put every identity in :data:`WELL_KNOWN_APPROVERS` in the database (`T-136b`).

    Called by the `db_session` fixture, so it costs nothing to the offline half of the suite —
    a test that never touches PostgreSQL never reaches it.
    """
    for email, display_name in WELL_KNOWN_APPROVERS:
        a_user(session, email, display_name)


def a_status_pin(session: Session, product_id: uuid.UUID, *, now: datetime = NOW) -> uuid.UUID:
    """A product readiness version to pin an approval to (`T-193b`).

    Module-level because `tests/test_outreach.py` builds its own world and needs the same
    thing; a second copy of this would be a second thing to keep correct. Separate from
    `a_claim_set_pin` because a caller may supply either pin — building both together hits
    `T-013`'s exclusion constraint when the caller brought its own readiness version.
    """
    status = ProductStatusVersion(
        product_id=product_id,
        version=next_version_number(session, product_id),
        readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
        summary="SYNTHETIC readiness for a factory world",
        approved_by=APPROVER,
        approved_at=now,
        effective_from=now,
        expires_or_review_by=None,
    )
    session.add(status)
    session.flush()
    return status.id


def a_claim_set_pin(
    session: Session,
    product_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    now: datetime = NOW,
) -> uuid.UUID:
    """An approved claim set to pin an approval to (`T-193b`)."""
    claim = ApprovedClaim(
        claim_key=f"SYNTHETIC-CLAIM-{uuid.uuid4().hex[:8]}",
        version=1,
        product_id=product_id,
        text="SYNTHETIC claim text for a factory world.",
        presumes_readiness=ReadinessCategory.EVALUATION_OR_PILOT,
        approved_by=APPROVER,
        approved_at=now,
        effective_from=now,
        expires_or_review_by=now + timedelta(days=180),
        is_synthetic=True,
    )
    session.add(claim)
    session.flush()
    session.add(ApprovedClaimCampaign(claim_id=claim.id, campaign_id=campaign_id))
    session.flush()
    claim_set = publish_claim_set(
        session,
        product_id=product_id,
        campaign_id=campaign_id,
        claims=[claim],
        approved_by=APPROVER,
        approved_at=now,
    )
    session.flush()
    return claim_set.id


class World:
    """One coherent synthetic world: a campaign, a prospect, a draft, and a thread.

    Deliberately eager rather than lazy. A half-built world is the source of test failures that
    look like product bugs.
    """

    def __init__(self, session: Session, *, policy: CampaignPolicy | None = None) -> None:
        self.session = session

        # First, because everything below that records an approver names this one (`T-136a`).
        self.approver = approver_user(session)

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

        self.contact = Contact(
            account_id=self.account.id,
            full_name="SYNTHETIC Person",
            # Provenance, so this world survives `T-144b` (`T-144a`).
            source_import_batch_id=a_source_batch(session).id,
        )
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
        #: Built on demand by `pins()`; see there for why not eagerly (`T-193b`).
        self._status_pin: uuid.UUID | None = None
        self._claim_set_pin: uuid.UUID | None = None
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

    def status_pin(self, *, now: datetime = NOW) -> uuid.UUID:
        """This world's readiness version, created once (`T-193b`)."""
        if self._status_pin is None:
            self._status_pin = a_status_pin(self.session, self.product.id, now=now)
        return self._status_pin

    def claim_set_pin(self, *, now: datetime = NOW) -> uuid.UUID:
        """This world's approved claim set, created once (`T-193b`).

        Cached because `publish_claim_set` supersedes the current set and adds a new one:
        calling it twice would leave the first superseded, which is precisely the state
        `invalidation_detail` refuses.
        """
        if self._claim_set_pin is None:
            self._claim_set_pin = a_claim_set_pin(
                self.session, self.product.id, self.campaign.id, now=now
            )
        return self._claim_set_pin

    def approval(
        self,
        session: Session | None = None,
        *,
        now: datetime = NOW,
        product_status_version_id: uuid.UUID | None = None,
        approved_claim_set_id: uuid.UUID | None = None,
        pinned: bool = True,
    ) -> Approval:
        """A granted approval for this world's revision.

        ``product_status_version_id`` must be passed here rather than set afterwards: an approval's
        pins are immutable by trigger (§8.4 — "request a new approval instead").

        **Pinned by default** (`T-193b`). An approval missing either pin cannot be shown to
        be current, so `invalidation_detail` refuses it — which means an unpinned approval
        is not a simpler approval, it is an invalid one. Pass ``pinned=False`` to build
        that state deliberately; the tests for the refusal itself do.
        """
        active = session or self.session
        if pinned and product_status_version_id is None:
            product_status_version_id = self.status_pin(now=now)
        if pinned and approved_claim_set_id is None:
            approved_claim_set_id = self.claim_set_pin(now=now)
        approval = request_approval(
            active,
            revision=self.revision,
            approver_id=APPROVER,
            actor=OPERATOR,
            product_status_version_id=product_status_version_id,
            approved_claim_set_id=approved_claim_set_id,
            now=now,
        )
        approve(active, approval, actor=OPERATOR, now=now)
        active.flush()
        return approval

    @property
    def email_domain(self) -> str:
        return self.recipient.value.rpartition("@")[2]
