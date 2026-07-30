"""Drafts and immutable message revisions (specification §10.5, §8.2, §14.2, §11.4).

A draft is a container; the **revision** is the thing that matters. An approval binds to one
exact ``message_revision_id`` (§11.4), and the final send transaction rechecks that same
revision — so a revision must mean the same thing forever. "Editing an approved message creates
a new immutable revision and invalidates the prior approval" (§10.5).

Claim and evidence references are **array columns on the revision**, not join tables. That is
deliberate: a join table could gain a row after the revision was approved, quietly changing what
the message cites. As columns they are part of the immutable row, covered by the same trigger,
and included in the content hash.

The hash proves integrity, not truth. Truth authority comes from the approved-claim record and
its approver (§10.5).
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.lifecycles import MessageRevisionState
from app.db.base import Base, TimestampMixin


class DraftPurpose(Enum):
    """§8.4 distinguishes the two, and they are governed differently.

    A follow-up may be drafted but never sent automatically; during the first live micro-pilot
    every follow-up also requires individual approval.
    """

    INITIAL_OUTREACH = "initial_outreach"
    FOLLOW_UP = "follow_up"


class MessageDraft(Base, TimestampMixin):
    """The container that groups successive revisions for one candidate."""

    __tablename__ = "message_draft"
    __table_args__ = (Index("ix_message_draft_candidate_id", "candidate_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign_candidate.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[DraftPurpose] = mapped_column(
        nullable=False, default=DraftPurpose.INITIAL_OUTREACH
    )

    revisions: Mapped[list["MessageRevision"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="MessageRevision.revision_number",
    )

    def __repr__(self) -> str:
        return f"MessageDraft({self.purpose.value} for {self.candidate_id})"


class MessageRevision(Base, TimestampMixin):
    """One exact message. Immutable in everything that defines it."""

    __tablename__ = "message_revision"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision_number", name="uq_message_revision_number"),
        CheckConstraint("revision_number > 0", name="revision_number_positive"),
        CheckConstraint("length(trim(subject)) > 0", name="subject_not_blank"),
        CheckConstraint("length(trim(body)) > 0", name="body_not_blank"),
        CheckConstraint("length(trim(created_by)) > 0", name="created_by_not_blank"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_is_sha256_hex"),
        # A superseded or invalidated revision must say when it stopped being live.
        CheckConstraint(
            "(state IN ('SUPERSEDED', 'INVALIDATED')) = (retired_at IS NOT NULL)",
            name="retired_state_needs_a_timestamp",
        ),
        Index("ix_message_revision_draft_id", "draft_id"),
        Index("ix_message_revision_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message_draft.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)

    #: The exact recipient this revision was written for. An approval binds recipient *and*
    #: revision together (§11.4); changing the recipient means a new revision.
    recipient_contact_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_point.id", ondelete="RESTRICT"), nullable=False
    )

    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    #: Every product sentence cites one of these; every prospect fact cites one of those (§10.5).
    approved_claim_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    state: Mapped[MessageRevisionState] = mapped_column(
        nullable=False, default=MessageRevisionState.DRAFT
    )
    #: Set when the revision leaves circulation, i.e. superseded or invalidated.
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Identity string until T-012's user table exists; T-136 converts it.
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)

    draft: Mapped[MessageDraft] = relationship(back_populates="revisions")

    def __repr__(self) -> str:
        return f"MessageRevision(v{self.revision_number} {self.state.value})"
