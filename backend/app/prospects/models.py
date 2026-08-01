"""Prospect identity (specification §14.1, §13.5, §8.3 step 2).

Accounts, contacts, and the addresses you can reach them at. Deliberately *not* a CRM: this
stores the identity needed to deduplicate, suppress, and reach someone, and nothing about the
commercial relationship (ADR-004 rejects building a second general-purpose CRM).

Identity keys are normalized on write by ``@validates`` hooks **and** checked at the database
level. Two layers because both fail differently: the validator catches ORM writes, the check
constraint catches everything else, and normalization that only happens sometimes is worse than
none — a suppression recorded against one spelling would not stop a send to the other (§15.6).
"""

import uuid
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base, TimestampMixin
from app.prospects.normalize import normalize_country, normalize_domain, normalize_email


class ContactPointType(Enum):
    EMAIL = "email"
    PHONE = "phone"
    LINKEDIN_URL = "linkedin_url"


class VerificationState(Enum):
    """Whether an address has been confirmed reachable (§15.8).

    ``UNVERIFIED`` is the default and is *not* a soft yes: campaign policy defaults to requiring
    verification before a send is considered (`T-015`).
    """

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    INVALID = "invalid"


class CRMProvider(Enum):
    """Providers an external ID may come from.

    ``FAKE`` is the test adapter. ``HUBSPOT`` exists as a value but no adapter may be built
    until `Q-001` is answered yes and gate **G-05** opens (ADR-004).
    """

    FAKE = "fake"
    HUBSPOT = "hubspot"


class MappedRecordType(Enum):
    ACCOUNT = "account"
    CONTACT = "contact"


class Account(Base, TimestampMixin):
    """A company. Identified by its normalized domain."""

    __tablename__ = "account"
    __table_args__ = (
        UniqueConstraint("domain", name="uq_account_domain"),
        CheckConstraint("domain = lower(domain)", name="domain_is_lowercase"),
        CheckConstraint("domain NOT LIKE 'www.%'", name="domain_has_no_www_prefix"),
        CheckConstraint("position('/' in domain) = 0", name="domain_has_no_path"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "country_code IS NULL OR country_code = upper(country_code)",
            name="country_code_is_uppercase",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Nullable because geography is often unknown at import. Unknown is *not* treated as
    #: domestic: campaign policy refuses a missing country (`T-015`).
    country_code: Mapped[str | None] = mapped_column(String(2))

    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    @validates("domain")
    def _normalize_domain(self, _key: str, value: str) -> str:
        return normalize_domain(value)

    @validates("country_code")
    def _normalize_country(self, _key: str, value: str | None) -> str | None:
        return normalize_country(value) if value else None

    def __repr__(self) -> str:
        return f"Account({self.domain})"


class Contact(Base, TimestampMixin):
    """A person at an account."""

    __tablename__ = "contact"
    __table_args__ = (
        CheckConstraint("length(trim(full_name)) > 0", name="full_name_not_blank"),
        Index("ix_contact_account_id", "account_id"),
        # `T-144b` reads provenance per candidate during qualification, so the lookup is hot.
        Index("ix_contact_source_import_batch_id", "source_import_batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_title: Mapped[str | None] = mapped_column(String(255))

    #: Where this identity came from (`T-144a`; §9.3, §10.1 stage 1 "approved source basis").
    #:
    #: **On the contact, not the candidate and not the account.** A candidate's source basis is
    #: inherited rather than its own, and a contact can arrive from a different source than the
    #: company it belongs to — so the identity that actually gets contacted is where provenance
    #: has to live for `T-144b`'s rule to mean anything.
    #:
    #: Nullable, and nothing refuses on it yet: rows that predate this column have no batch to
    #: name, and inventing one would be a provenance claim nobody checked. `T-144b` decides what
    #: a missing basis means for eligibility — fail closed — which is a separate, reviewable
    #: change because it can flip who may be contacted. `RESTRICT`: a batch that explains where a
    #: person came from must not be deletable out from under them (§14.2).
    #:
    #: Declared by table name rather than by importing `prospects.imports`, which imports this
    #: module — the string keeps the dependency one-way.
    source_import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batch.id", ondelete="RESTRICT")
    )

    account: Mapped[Account] = relationship(back_populates="contacts")
    contact_points: Mapped[list["ContactPoint"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Contact({self.full_name})"


class ContactPoint(Base, TimestampMixin):
    """One way to reach a contact.

    ``(type, value)`` is globally unique: an email address identifies one mailbox, so two
    contacts holding the same address would defeat both deduplication and suppression.
    """

    __tablename__ = "contact_point"
    __table_args__ = (
        UniqueConstraint("type", "value", name="uq_contact_point_type_value"),
        CheckConstraint("length(trim(value)) > 0", name="value_not_blank"),
        # Email values are normalized to lowercase; other types keep their own casing.
        CheckConstraint("type <> 'EMAIL' OR value = lower(value)", name="email_value_is_lowercase"),
        Index("ix_contact_point_contact_id", "contact_id"),
        Index("ix_contact_point_value", "value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[ContactPointType] = mapped_column(nullable=False)
    value: Mapped[str] = mapped_column(String(320), nullable=False)
    verification_state: Mapped[VerificationState] = mapped_column(
        nullable=False, default=VerificationState.UNVERIFIED
    )

    contact: Mapped[Contact] = relationship(back_populates="contact_points")

    @validates("value")
    def _normalize_value(self, _key: str, value: str) -> str:
        # `type` may not be set yet depending on attribute order, so normalize defensively:
        # an email is normalized when we know it is one, and left alone otherwise.
        if self.type is ContactPointType.EMAIL:
            return normalize_email(value)
        return value.strip()

    def __repr__(self) -> str:
        return f"ContactPoint({self.type.value}:{self.value})"


class CRMMapping(Base, TimestampMixin):
    """Internal record ↔ external CRM record (§13.5 rule 4).

    Internal IDs stay provider-independent; this table is the only place a provider's ID appears,
    so adopting or dropping a CRM does not rewrite the domain.
    """

    __tablename__ = "crm_mapping"
    __table_args__ = (
        # One external ID per internal record per provider.
        UniqueConstraint("provider", "record_type", "internal_id", name="uq_crm_mapping_internal"),
        # ...and one internal record per external ID, so two internal records cannot both claim
        # the same CRM record and fight over it on the next sync.
        UniqueConstraint("provider", "record_type", "external_id", name="uq_crm_mapping_external"),
        CheckConstraint("length(trim(external_id)) > 0", name="external_id_not_blank"),
        Index("ix_crm_mapping_internal_id", "internal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[CRMProvider] = mapped_column(nullable=False)
    record_type: Mapped[MappedRecordType] = mapped_column(nullable=False)

    #: Deliberately not a foreign key: it points at either an account or a contact depending on
    #: ``record_type``, and a polymorphic FK is not expressible. Referential integrity is the
    #: sync adapter's job (`T-093`/`T-094`).
    internal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"CRMMapping({self.provider.value}:{self.record_type.value}:{self.external_id})"
