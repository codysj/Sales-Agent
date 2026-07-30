"""Evidence snapshots (specification §14.3, §9.5, GP-02).

"Qualification and personalization cite stored evidence. Missing facts remain missing" (GP-02).
Every prospect-specific statement in a draft resolves to a row here, exactly as every product
statement resolves to an approved claim — the two halves of the same rule (§10.5).

Three properties are deliberate:

* **Excerpts, not documents.** ``supporting_excerpt_or_fact`` is capped and the cap is enforced by
  rejection, never truncation. §9.5 forbids indiscriminately storing whole third-party pages, and
  a silently shortened excerpt could drop the very clause that justified the claim.
* **Snapshots are immutable.** A refresh writes a *new* snapshot (§9.5). Editing one in place
  would change what a qualification run was based on after the fact. A trigger enforces this.
* **Provenance is mandatory.** Every §14.3 field that makes evidence explainable is NOT NULL,
  including the personal-data flag — an unanswered privacy classification defaults to nothing.
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base, TimestampMixin

#: An excerpt is a sentence or two that justifies one claim, not a page. Roughly 150 words.
EXCERPT_MAX_CHARS = 1000


class SourceType(Enum):
    """Where evidence came from (§9.2).

    ``LINKEDIN_HUMAN_PROVIDED`` is the only LinkedIn value and says what it means: a human
    supplied the URL or export. Autonomous LinkedIn operation is rejected (ADR-005).
    """

    COMPANY_WEBSITE = "company_website"
    INDUSTRY_DIRECTORY = "industry_directory"
    TRADE_SHOW_LISTING = "trade_show_listing"
    PUBLIC_ANNOUNCEMENT = "public_announcement"
    PROCUREMENT_RECORD = "procurement_record"
    DATA_PROVIDER = "data_provider"
    CRM_RECORD = "crm_record"
    LINKEDIN_HUMAN_PROVIDED = "linkedin_human_provided"
    MANUAL_ENTRY = "manual_entry"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class SourceQuality(Enum):
    """§9.5 / §10.4 source-quality classification."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExtractionMethod(Enum):
    """How the excerpt was obtained from the source (§9.5).

    ``MODEL_EXTRACTION`` is recorded so a reviewer can weigh evidence a model pulled out
    differently from a structured provider field.
    """

    MANUAL = "manual"
    STRUCTURED_FIELD = "structured_field"
    TEXT_SPAN = "text_span"
    MODEL_EXTRACTION = "model_extraction"


class RetentionClass(Enum):
    """License and retention classification (§9.5, §15.5).

    `Q-019` has not set the retention policy, so these are conservative placeholders describing
    *what may be done with the evidence*, not how long it is kept.
    """

    PUBLIC_UNRESTRICTED = "public_unrestricted"
    PROVIDER_LICENSED = "provider_licensed"
    INTERNAL_ONLY = "internal_only"
    RESTRICTED = "restricted"


class EvidenceSnapshot(Base, TimestampMixin):
    """One stored fact about a candidate, with everything needed to explain it later."""

    __tablename__ = "evidence_snapshot"
    __table_args__ = (
        CheckConstraint(
            f"length(supporting_excerpt_or_fact) <= {EXCERPT_MAX_CHARS}",
            name="excerpt_within_cap",
        ),
        CheckConstraint("length(trim(supporting_excerpt_or_fact)) > 0", name="excerpt_not_blank"),
        # SHA-256 hex. Lets a refresh detect that the underlying source changed.
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_is_sha256_hex"),
        Index("ix_evidence_snapshot_candidate_id", "candidate_id"),
        Index("ix_evidence_snapshot_retrieved_at", "retrieved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: Evidence belongs to a campaign membership, not to a company: the same fact may support a
    #: candidate in one campaign and be irrelevant in another (§8.1).
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign_candidate.id", ondelete="CASCADE"), nullable=False
    )

    source_type: Mapped[SourceType] = mapped_column(nullable=False)
    source_provider_id: Mapped[str | None] = mapped_column(String(255))
    #: Only stored where provider terms permit (§9.5) — hence "if permitted" in the specification.
    source_url_if_permitted: Mapped[str | None] = mapped_column(Text)

    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    supporting_excerpt_or_fact: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    extraction_field_or_span: Mapped[str | None] = mapped_column(String(255))
    extraction_method: Mapped[ExtractionMethod] = mapped_column(nullable=False)

    source_quality: Mapped[SourceQuality] = mapped_column(nullable=False)
    license_and_retention_class: Mapped[RetentionClass] = mapped_column(nullable=False)

    #: No default on purpose. An unanswered privacy classification must not silently become
    #: "contains nothing sensitive" (§15.5, `Q-019`).
    contains_personal_or_confidential_data: Mapped[bool] = mapped_column(nullable=False)

    #: After this, the fact is stale and must be refreshed before it supports a draft (§9.5).
    #: NULL means it does not go stale on its own.
    expires_or_refresh_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @validates("supporting_excerpt_or_fact")
    def _reject_oversized_excerpt(self, _key: str, value: str | None) -> str | None:
        """Reject, never truncate.

        A silently shortened excerpt could drop the clause that actually justified the claim,
        leaving a reviewer looking at evidence that no longer says what it was cited for.

        ``None`` passes through so the NOT NULL constraint reports a missing excerpt as a missing
        excerpt, rather than this validator masking it with a TypeError.
        """
        if value is None:
            return None
        if len(value) > EXCERPT_MAX_CHARS:
            raise ValueError(
                f"evidence excerpt is {len(value)} characters, over the {EXCERPT_MAX_CHARS} cap; "
                f"store the minimum excerpt that explains the decision, not the whole document "
                f"(§14.3, §9.5)"
            )
        return value

    def is_current_at(self, moment: datetime) -> bool:
        """Retrieved by ``moment`` and not yet stale."""
        if moment < self.retrieved_at:
            return False
        return self.expires_or_refresh_by is None or moment < self.expires_or_refresh_by

    def __repr__(self) -> str:
        return f"EvidenceSnapshot({self.source_type.value} for {self.candidate_id})"
