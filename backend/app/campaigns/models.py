"""Campaigns, target segments, and versioned policy (specification §8.1, §8.6, ADR-012).

A lead is not an intrinsic property of a company: qualification belongs to an account and
contact's membership in a *specific* campaign (§8.1). This module owns the campaign side of that
— the campaign itself, who it targets, and the versioned rules it judges by.

Both the sodium-battery and DC-fast-charging configurations get built; only one goes through the
first live pilot (ADR-012, §8.6). `paused` starts `True` so a newly created campaign cannot begin
work before someone deliberately starts it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.campaigns.policy import CampaignPolicy
from app.db.base import Base, TimestampMixin


class Campaign(Base, TimestampMixin):
    """One product-specific outreach configuration."""

    __tablename__ = "campaign"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_campaign_slug"),
        CheckConstraint("length(trim(slug)) > 0", name="slug_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"), nullable=False
    )

    #: Paused until deliberately started. §17.6 requires a campaign pause control, and the safe
    #: initial value is "not running" — a campaign that begins work on creation is an accident
    #: waiting for its first candidate.
    paused: Mapped[bool] = mapped_column(nullable=False, default=True)

    segments: Mapped[list["TargetSegment"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    policy_versions: Mapped[list["CampaignPolicyVersion"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Campaign({self.slug}{' paused' if self.paused else ''})"


class TargetSegment(Base, TimestampMixin):
    """An approved slice of the ideal customer profile for one campaign.

    Kept as records rather than prose so eligibility can cite which segment a candidate matched.
    Exact segments stay `Q-002` until Matrix Power confirms them; rows here are synthetic.
    """

    __tablename__ = "target_segment"
    __table_args__ = (
        UniqueConstraint("campaign_id", "key", name="uq_target_segment_campaign_key"),
        CheckConstraint("length(trim(key)) > 0", name="key_not_blank"),
        Index("ix_target_segment_campaign_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    campaign: Mapped[Campaign] = relationship(back_populates="segments")

    def __repr__(self) -> str:
        return f"TargetSegment({self.key})"


class CampaignPolicyVersion(Base, TimestampMixin):
    """One immutable version of a campaign's rules.

    Immutable *once referenced*: a qualification run, draft, or approval records the policy
    version it was judged under, and rewriting that version afterwards would make the recorded
    decision unexplainable (GP-09, §17.5). Enforced by a trigger, not by convention.
    """

    __tablename__ = "campaign_policy_version"
    __table_args__ = (
        UniqueConstraint("campaign_id", "version", name="uq_campaign_policy_version_campaign_ver"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(trim(approved_by)) > 0", name="approved_by_not_blank"),
        Index("ix_campaign_policy_version_campaign_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)

    #: Serialized :class:`app.campaigns.policy.CampaignPolicy`. Always read back through the
    #: model, never as loose JSON.
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    #: Held as an identity string until T-012's user table exists; T-136 converts it.
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Set when a later version takes over. The current version is the one with no successor.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="policy_versions")

    def as_policy(self) -> CampaignPolicy:
        """Validate and return the typed policy. Raises if the stored body has drifted."""
        return CampaignPolicy.model_validate(self.policy)

    def __repr__(self) -> str:
        return (
            f"CampaignPolicyVersion(v{self.version}{' superseded' if self.superseded_at else ''})"
        )
