"""Who may act (T-012; specification §14.1, §12.1, §12.2).

The subject model later authorization checks resolve against. It stores *who exists and what
they may do* and nothing about how they proved it: §12.2 rejects custom password authentication
outright, and sessions arrive with `T-061` through a managed provider. There is no password
column here and there must never be one.

**Humans and services are different tables, not a flag.** §12.2 requires service identities
separate from human identities, and a `is_service` boolean on one table is exactly the shape that
lets a query forget to filter. Separate tables mean a service identity cannot be handed to code
expecting a user by accident — the type is wrong.

**A service cannot hold a role that decides anything.** §3.5's invariant is that no external
execution authority is held only by the agent runtime, and ADR-008 requires a human approval for
every recipient and revision. So each role carries `human_only`, and the service-role join is
constrained so it can only reference roles where that is false. The enforcement is a **composite
foreign key**, not a trigger: `role` has a unique `(id, human_only)`, and `service_identity_role`
carries a `human_only` column pinned to false by a check constraint and joined to that key. A
service can therefore only ever be granted a role that the database itself agrees is not
human-only, and the day someone flips a role to human-only, the grant that depended on it fails
rather than silently widening.

**A channel identity is a mapping, never a principal.** §12.2: "messaging identities mapped to an
existing application user and role." A WhatsApp number does not authorize anything — it names a
person who is already a user. The foreign key is `NOT NULL`, so an unmapped handle cannot exist,
which is what stops an inbound message from an unknown number resolving to *someone*.
"""

import uuid
from enum import Enum
from typing import Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class RoleKey(Enum):
    """The six roles of §12.1, verbatim. Not an authorization model — a vocabulary.

    One person may hold several; §12.1 says so explicitly. What each *permits* is `T-062`'s
    matrix, deliberately not encoded here: putting permissions on the role row would put them
    somewhere a migration can change without a test noticing.
    """

    PRODUCT_CLAIM_OWNER = "product_claim_owner"
    CAMPAIGN_SALES_OWNER = "campaign_sales_owner"
    OPERATOR_REVIEWER = "operator_reviewer"
    REPLY_OWNER = "reply_owner"
    SYSTEM_ADMINISTRATOR = "system_administrator"
    VIEWER = "viewer"


#: Roles a service identity may never hold, and why each one decides something.
#:
#: Five of the six. Every one of them either approves something a person must approve (§3.5,
#: ADR-008) or changes what the system is allowed to do. `VIEWER` is the exception because
#: reading status authorizes nothing — a reporting job may legitimately hold it.
#:
#: This tuple is the *source*; the database column is the enforcement. `tests/test_identity.py`
#: asserts the seeded rows agree with it, so the two cannot drift.
HUMAN_ONLY_ROLES: Final = (
    RoleKey.PRODUCT_CLAIM_OWNER,
    RoleKey.CAMPAIGN_SALES_OWNER,
    RoleKey.OPERATOR_REVIEWER,
    RoleKey.REPLY_OWNER,
    RoleKey.SYSTEM_ADMINISTRATOR,
)

#: §12.1's responsibility column, kept with the key so a seed and a reviewer read the same words.
ROLE_RESPONSIBILITIES: Final[dict[RoleKey, str]] = {
    RoleKey.PRODUCT_CLAIM_OWNER: (
        "Approves product specifications, readiness, outbound claims, and review dates"
    ),
    RoleKey.CAMPAIGN_SALES_OWNER: (
        "Defines ICP, opportunity goals, exclusions, volume, and outreach policy"
    ),
    RoleKey.OPERATOR_REVIEWER: (
        "Reviews candidates, evidence, exact message revisions, and corrections"
    ),
    RoleKey.REPLY_OWNER: "Receives and handles positive or substantive replies",
    RoleKey.SYSTEM_ADMINISTRATOR: (
        "Manages identity, integrations, credentials, limits, pauses, and recovery"
    ),
    RoleKey.VIEWER: "Reads status and reports without making changes",
}


class ChannelType(Enum):
    """Channels a human identity can arrive on (§12.4, ADR-006, `Q-008`).

    Both are overlay channels: neither is an approval authority, which is why they map to a user
    rather than carrying permissions of their own.
    """

    WHATSAPP = "whatsapp"
    IMESSAGE = "imessage"


class Role(Base, TimestampMixin):
    """One of §12.1's six. Seeded by migration, never created at runtime."""

    __tablename__ = "role"
    __table_args__ = (
        # The composite key `service_identity_role` points at. Redundant as a *key* — `id` is
        # already unique — and load-bearing as a *constraint target*: it is what lets the
        # database refuse a service grant on a human-only role with no trigger involved.
        UniqueConstraint("id", "human_only", name="uq_role_id_human_only"),
        UniqueConstraint("key", name="uq_role_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    responsibility: Mapped[str] = mapped_column(Text, nullable=False)
    #: Whether only a human may hold this role. See `HUMAN_ONLY_ROLES`.
    human_only: Mapped[bool] = mapped_column(Boolean, nullable=False)


class User(Base, TimestampMixin):
    """A human. Authenticated later by a managed provider (§12.2); never by a password here.

    ``subject`` is the provider's stable identifier, nullable until `T-061` wires one up and
    unique when present — two users sharing a subject would mean one login resolving to two
    people. ``email`` is the working identifier meanwhile, and is *not* a credential.
    """

    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("email", name="uq_app_user_email"),
        UniqueConstraint("subject", name="uq_app_user_subject"),
        CheckConstraint("email = lower(email)", name="ck_app_user_email_lowercase"),
        CheckConstraint("length(trim(display_name)) > 0", name="ck_app_user_display_name_present"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: The identity provider's subject claim. `None` until `T-061`.
    subject: Mapped[str | None] = mapped_column(String(255))
    #: Deactivation rather than deletion: §12.2 requires immutable actor attribution, and an
    #: audit event naming a user row that no longer exists is attribution nobody can follow.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    roles: Mapped[list["UserRole"]] = relationship(back_populates="user")


class UserRole(Base, TimestampMixin):
    """A human's grant of one role. One person may hold several (§12.1)."""

    __tablename__ = "user_role"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id"), nullable=False)
    #: Who granted it. A string, not a foreign key: §12.2 wants attribution that survives the
    #: granter's row being deactivated or replaced.
    granted_by: Mapped[str] = mapped_column(String(255), nullable=False)

    user: Mapped[User] = relationship(back_populates="roles")


class ServiceIdentity(Base, TimestampMixin):
    """A non-human actor: the worker, a scheduled job, a future integration.

    Holds no credential. What a service *proves* is `T-061`'s problem and will not be a password
    either; this row exists so an audit event can name a service the way it names a person, and
    so `T-062` has something to check a role against.
    """

    __tablename__ = "service_identity"
    __table_args__ = (
        UniqueConstraint("name", name="uq_service_identity_name"),
        CheckConstraint("length(trim(name)) > 0", name="ck_service_identity_name_present"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ServiceIdentityRole(Base, TimestampMixin):
    """A service's grant of one role — and only ever a role no human must hold alone.

    ``human_only`` is a stored column pinned to `false`, joined to `role(id, human_only)`. It
    looks redundant and is the entire enforcement: a grant naming a human-only role has no
    matching row in that unique key, so the insert fails. See the module docstring.
    """

    __tablename__ = "service_identity_role"
    __table_args__ = (
        UniqueConstraint("service_identity_id", "role_id", name="uq_service_identity_role"),
        CheckConstraint("human_only = false", name="ck_service_role_not_human_only"),
        ForeignKeyConstraint(
            ["role_id", "human_only"],
            ["role.id", "role.human_only"],
            name="fk_service_role_role_not_human_only",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    service_identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_identity.id"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    #: Always `false`. Carried so the composite foreign key above has something to join on.
    human_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    granted_by: Mapped[str] = mapped_column(String(255), nullable=False)


class ChannelIdentity(Base, TimestampMixin):
    """A messaging handle, mapped to a user who already exists (§12.2).

    Never a principal. An inbound WhatsApp message does not authorize anything on its own — it
    identifies a person the system already knows, and `user_id` being `NOT NULL` is what makes
    "an unmapped handle" unrepresentable rather than merely discouraged.
    """

    __tablename__ = "channel_identity"
    __table_args__ = (
        UniqueConstraint("channel", "address", name="uq_channel_identity_address"),
        CheckConstraint("length(trim(address)) > 0", name="ck_channel_identity_address_present"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    channel: Mapped[ChannelType] = mapped_column(nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Whether the mapping has been confirmed with the person it names. Defaults false: an
    #: unverified handle claiming to be someone is exactly what must not be trusted (§15.6).
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped[User] = relationship()
