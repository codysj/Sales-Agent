"""Products, versioned readiness, and source provenance (specification §2.3, §14.4, GP-12).

"Product readiness is part of truthfulness": technical relevance does not imply availability,
certification, or approval to say anything about it (GP-12). Readiness is therefore explicit,
versioned, time-bounded, and traceable to the document it came from.

A ``SourceDocument`` records **where a status came from**. It is not permission to repeat it:
internal decks, notes, and roadmaps are never approved outbound claims until they appear in the
approved-claim store (§15.7, T-014).

Until `Q-021` and `Q-022` deliver approved product briefs, every row here is synthetic (T-040).
"""

import uuid
from datetime import date, datetime
from enum import Enum

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


class ReadinessCategory(Enum):
    """The five states §2.3 requires the system to distinguish.

    A database enum, not free text: "roughly available" is exactly the ambiguity that produces a
    premature certification or availability claim.
    """

    SELLABLE_NOW = "sellable_now"
    EVALUATION_OR_PILOT = "evaluation_or_pilot"
    IN_DEVELOPMENT = "in_development"
    STRATEGIC_OR_ROADMAP = "strategic_or_roadmap"
    PAUSED_OR_UNAVAILABLE = "paused_or_unavailable"


class SourceDocument(Base, TimestampMixin):
    """Where a recorded fact came from, with its own date preserved (§0.3 item 4).

    Internal material is a *source record*, never an approved external claim (§15.7).
    """

    __tablename__ = "source_document"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
        Index("ix_source_document_source_date", "source_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)

    #: The document's own date, preserved rather than the date it was ingested.
    source_date: Mapped[date] = mapped_column(Date, nullable=False)

    #: Where the document lives. Deliberately not the document itself: this store keeps
    #: pointers and provenance, not copies of internal material.
    location: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))

    #: Internal material carries a higher bar before anything from it may be said externally.
    is_internal: Mapped[bool] = mapped_column(nullable=False, default=True)

    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"SourceDocument({self.title!r} {self.source_date})"


class Product(Base, TimestampMixin):
    """A Matrix Power product or capability that outreach might reference."""

    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_product_slug"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("length(trim(slug)) > 0", name="slug_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    status_versions: Mapped[list["ProductStatusVersion"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Product({self.slug})"


class ProductStatusVersion(Base, TimestampMixin):
    """One product's readiness over one time window.

    Windows for a product may not overlap — enforced by a PostgreSQL exclusion constraint, not by
    application logic, so two concurrent writers cannot produce two "current" readiness answers.
    An open-ended window (``expires_or_review_by`` NULL) runs until something supersedes it.
    """

    __tablename__ = "product_status_version"
    __table_args__ = (
        UniqueConstraint("product_id", "version", name="uq_product_status_version_product_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(trim(approved_by)) > 0", name="approved_by_not_blank"),
        CheckConstraint(
            "expires_or_review_by IS NULL OR expires_or_review_by > effective_from",
            name="effective_window_ordered",
        ),
        Index("ix_product_status_version_product_id", "product_id"),
        Index("ix_product_status_version_effective_from", "effective_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)

    readiness_category: Mapped[ReadinessCategory] = mapped_column(nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)

    #: Provenance. Restricted, not cascaded: deleting the document that justified a readiness
    #: claim must not silently delete the justification.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_document.id", ondelete="RESTRICT")
    )
    source_date: Mapped[date | None] = mapped_column(Date)

    #: Who approved this readiness and when (§14.4).
    #:
    #: A foreign key to `app_user.email`, not to `app_user.id` (`T-136b`, ADR-024). The email is
    #: what the production path already records (`principal.user.email`), and keeping it in the
    #: column means the row still says *who* without a join — the same reason `audit_event.actor_id`
    #: stays readable. `RESTRICT` is the point: an approver with history cannot be deleted.
    approved_by: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("app_user.email", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Treated as a hard expiry, not a soft reminder: past this instant the status is not
    #: current, and callers get nothing rather than something stale (GP-12).
    expires_or_review_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_status_version.id", ondelete="SET NULL")
    )

    product: Mapped[Product] = relationship(back_populates="status_versions")

    def is_effective_at(self, moment: datetime) -> bool:
        if moment < self.effective_from:
            return False
        return self.expires_or_review_by is None or moment < self.expires_or_review_by

    def __repr__(self) -> str:
        return (
            f"ProductStatusVersion(v{self.version} {self.readiness_category.value} "
            f"from {self.effective_from:%Y-%m-%d})"
        )
