"""Approved claims and claim sets (specification §10.5, §14.4, §15.7, GP-12).

The rule this exists to enforce: **every product sentence in outreach references an approved
claim ID**, and a free-form product statement fails validation (§10.5). Internal decks, notes,
roadmap dates, pricing, certifications, and customer names are *not* approved claims — they
become claims only by appearing here, with an approver and a review date (§15.7).

Two additional properties matter more than they look:

* **Claim sets are pinned, not recomputed.** A send command records the exact
  ``approved_claim_set_version`` it was built from (§11.4). If any claim in that set has since
  expired, the set fails *whole* — silently dropping the expired claim and rendering the rest
  would change the message without anyone approving the change.
* **Every claim carries a review date.** Unlike product readiness, ``expires_or_review_by`` is
  NOT NULL here: a claim nobody ever has to look at again is how a stale certification or
  roadmap date survives into a live send.

Until `Q-017` delivers a written, versioned approved-claim set, every row is synthetic and
``is_synthetic`` must be ``True``.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.products_and_claims.models import ReadinessCategory


class ApprovedClaim(Base, TimestampMixin):
    """One externally usable statement about a product, with its exact approved wording."""

    __tablename__ = "approved_claim"
    __table_args__ = (
        UniqueConstraint("claim_key", "version", name="uq_approved_claim_key_version"),
        CheckConstraint("length(trim(claim_key)) > 0", name="claim_key_not_blank"),
        CheckConstraint("length(trim(text)) > 0", name="text_not_blank"),
        CheckConstraint("length(trim(approved_by)) > 0", name="approved_by_not_blank"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "expires_or_review_by > effective_from", name="review_date_after_effective_from"
        ),
        # A paraphrase permission without stated constraints is an invitation to drift from the
        # wording that was actually approved (§10.5).
        CheckConstraint(
            "allow_paraphrase = false OR paraphrase_constraints IS NOT NULL",
            name="paraphrase_requires_constraints",
        ),
        Index("ix_approved_claim_product_id", "product_id"),
        Index("ix_approved_claim_effective_from", "effective_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: Stable across versions: v1 and v2 of the same claim share a key.
    claim_key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"), nullable=False
    )

    #: The exact approved wording. Rendered verbatim unless paraphrase is explicitly permitted.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    allow_paraphrase: Mapped[bool] = mapped_column(nullable=False, default=False)
    paraphrase_constraints: Mapped[str | None] = mapped_column(Text)

    #: The readiness this claim presumes. A claim asserting availability must not outlive the
    #: readiness that justified it (§14.4, GP-12).
    presumes_readiness: Mapped[ReadinessCategory | None] = mapped_column()

    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_document.id", ondelete="RESTRICT")
    )
    source_date: Mapped[date | None] = mapped_column(Date)

    #: A foreign key to `app_user.email` with `RESTRICT` (`T-136b`, ADR-024).
    approved_by: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("app_user.email", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: NOT NULL on purpose — every claim must come back for review.
    expires_or_review_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approved_claim.id", ondelete="SET NULL")
    )

    #: False is only legitimate once `Q-017` has delivered an approved claim set. Nothing in the
    #: pipeline may treat a synthetic claim as approved for a real recipient.
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=True)

    campaign_links: Mapped[list["ApprovedClaimCampaign"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )

    def is_valid_at(self, moment: datetime) -> bool:
        """Effective, not yet expired, and not superseded."""
        if moment < self.effective_from or moment >= self.expires_or_review_by:
            return False
        return self.superseded_at is None or moment < self.superseded_at

    def __repr__(self) -> str:
        return f"ApprovedClaim({self.claim_key} v{self.version})"


class ApprovedClaimCampaign(Base):
    """Which campaigns a claim may be used for (§14.4 ``allowed_campaigns``).

    An allow-list, not a deny-list: a claim is usable for a campaign only if a row exists here.
    A positioning statement approved for the sodium-battery campaign is not thereby approved for
    DC fast charging.
    """

    __tablename__ = "approved_claim_campaign"
    __table_args__ = (
        UniqueConstraint("claim_id", "campaign_id", name="uq_approved_claim_campaign"),
        Index("ix_approved_claim_campaign_campaign_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approved_claim.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False
    )

    claim: Mapped[ApprovedClaim] = relationship(back_populates="campaign_links")


class ApprovedClaimSet(Base, TimestampMixin):
    """An immutable, versioned bundle of claims for one product and campaign.

    A draft records the set version it was built from, and the final send transaction rechecks
    that version (§11.4). The set is the unit of approval, so its membership cannot change after
    the fact — a new version is published instead.
    """

    __tablename__ = "approved_claim_set"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "campaign_id", "version", name="uq_approved_claim_set_scope_version"
        ),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(trim(approved_by)) > 0", name="approved_by_not_blank"),
        Index("ix_approved_claim_set_scope", "product_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)

    #: A foreign key to `app_user.email` with `RESTRICT` (`T-136b`, ADR-024).
    approved_by: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("app_user.email", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    members: Mapped[list["ApprovedClaimSetMember"]] = relationship(
        back_populates="claim_set", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"ApprovedClaimSet(v{self.version})"


class ApprovedClaimSetMember(Base):
    """One claim's membership in one set."""

    __tablename__ = "approved_claim_set_member"
    __table_args__ = (
        UniqueConstraint("claim_set_id", "claim_id", name="uq_approved_claim_set_member"),
        Index("ix_approved_claim_set_member_claim_id", "claim_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    claim_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approved_claim_set.id", ondelete="CASCADE"), nullable=False
    )
    #: RESTRICT: a claim cited by a published set cannot be deleted out from under it.
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approved_claim.id", ondelete="RESTRICT"), nullable=False
    )

    claim_set: Mapped[ApprovedClaimSet] = relationship(back_populates="members")
    claim: Mapped[ApprovedClaim] = relationship()
