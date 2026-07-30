"""Operational kill switches (specification §17.6, §17.1).

§17.6 lists the controls an operator must have when something is going wrong. These are the ones
that live in the database, so they can be thrown while the system is running and without a deploy:
global pause, shadow mode, outbound email disable, and per-product / per-claim-version disable.

Two switches deliberately live elsewhere and are *not* duplicated here:

* **Campaign pause** is `Campaign.paused` (T-015), which already defaults to paused. A second
  source of truth for the same question is how a paused campaign ends up sending. The checkpoint
  below takes it as a parameter instead, because `audit_and_operations` is foundation for every
  module and may not import `campaigns`.
* **Approval revocation** belongs to `drafts_and_approvals` for the same reason (`T-137`).

**Every switch is fail-closed and composes by conjunction with deploy configuration.** Shadow mode
is on if *either* the environment or a flag says so; outbound email is allowed only if *everything*
agrees. Neither layer can be used to weaken the other, so turning a switch on is always safe and
turning one off is never sufficient on its own.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor, record_audit_event
from app.core.settings import Settings
from app.db.base import Base, TimestampMixin

ENTITY_TYPE = "operational_flag"


class FlagKey(StrEnum):
    """The database-backed subset of §17.6."""

    #: Stops all new consequential work. Queued work stays queued and inspectable (§17.1).
    GLOBAL_PAUSE = "global_pause"
    #: External-effect adapters refuse to act at all.
    SHADOW_MODE = "shadow_mode"
    #: Narrower than shadow mode: email only.
    OUTBOUND_EMAIL_DISABLED = "outbound_email_disabled"
    #: Scoped to a product id.
    PRODUCT_DISABLED = "product_disabled"
    #: Scoped to a claim-version id.
    CLAIM_VERSION_DISABLED = "claim_version_disabled"


#: Keys that address a specific entity, and so require a `scope_id`.
SCOPED_KEYS = frozenset({FlagKey.PRODUCT_DISABLED, FlagKey.CLAIM_VERSION_DISABLED})


class FlagError(Exception):
    """A flag operation was refused."""


class ExternalEffectBlocked(Exception):
    """An external effect was refused by an operational switch.

    Not a failure: the system did exactly what it was told. Callers should treat it as a stop, not
    as something to retry around.
    """


class ConsequentialWorkPaused(Exception):
    """Consequential work was attempted while a pause was in force (§17.1)."""


class OperationalFlag(Base, TimestampMixin):
    """One switch, on or off, with the reason it was thrown."""

    __tablename__ = "operational_flag"
    __table_args__ = (
        # `NULLS NOT DISTINCT` so the single global row for a key collides with itself; without it,
        # PostgreSQL treats every NULL scope as unique and a key could be set twice with different
        # answers (PG 15+).
        UniqueConstraint(
            "key",
            "scope_id",
            name="uq_operational_flag_key_scope",
            postgresql_nulls_not_distinct=True,
        ),
        # §17.6 switches are read during incidents. A switch nobody can explain is a switch nobody
        # dares turn off.
        CheckConstraint("length(trim(reason)) > 0", name="flag_reason_not_blank"),
        CheckConstraint(
            "(key IN ('PRODUCT_DISABLED', 'CLAIM_VERSION_DISABLED')) = (scope_id IS NOT NULL)",
            name="scoped_keys_need_a_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    key: Mapped[FlagKey] = mapped_column(nullable=False)

    #: The product or claim version this applies to; NULL for a system-wide switch. Not a foreign
    #: key: this table is foundation and must not reference domain tables (§18.2), the same rule
    #: that keeps `outbox_event` free of one.
    scope_id: Mapped[str | None] = mapped_column(String(64))

    enabled: Mapped[bool] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    #: Who last changed it, denormalized from the audit trail so an operator reading the flag list
    #: does not have to join to find out.
    set_by: Mapped[str] = mapped_column(String(255), nullable=False)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        scope = f":{self.scope_id}" if self.scope_id else ""
        return f"OperationalFlag({self.key.value}{scope} enabled={self.enabled})"


def set_flag(
    session: Session,
    *,
    key: FlagKey,
    enabled: bool,
    actor: Actor,
    reason: str,
    scope_id: str | None = None,
) -> OperationalFlag:
    """Throw or release a switch, recording who and why (§17.6, criterion 3).

    ``reason`` is required in both directions. Turning a pause *off* is the more consequential of
    the two and is exactly the change an incident review will ask about.
    """
    if not reason.strip():
        raise FlagError(f"changing {key.value!r} needs a reason (§17.6)")
    if (key in SCOPED_KEYS) != (scope_id is not None):
        expectation = (
            "scoped and needs a scope_id"
            if key in SCOPED_KEYS
            else "system-wide and takes no scope_id"
        )
        raise FlagError(f"{key.value!r} is {expectation}")

    existing = session.execute(
        select(OperationalFlag).where(
            OperationalFlag.key == key, OperationalFlag.scope_id == scope_id
        )
    ).scalar_one_or_none()

    moment = datetime.now(UTC)
    if existing is None:
        flag = OperationalFlag(
            key=key,
            scope_id=scope_id,
            enabled=enabled,
            reason=reason,
            set_by=actor.id,
            set_at=moment,
        )
        session.add(flag)
    else:
        flag = existing
        flag.enabled = enabled
        flag.reason = reason
        flag.set_by = actor.id
        flag.set_at = moment
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="flag.enabled" if enabled else "flag.disabled",
        entity_type=ENTITY_TYPE,
        entity_id=flag.id,
        payload={"key": key.value, "scope_id": scope_id, "reason": reason},
    )
    return flag


def is_set(session: Session, key: FlagKey, *, scope_id: str | None = None) -> bool:
    """Whether a switch is currently on. A missing row means off."""
    return bool(
        session.execute(
            select(OperationalFlag.enabled).where(
                OperationalFlag.key == key, OperationalFlag.scope_id == scope_id
            )
        ).scalar_one_or_none()
    )


def shadow_mode_active(session: Session, settings: Settings) -> bool:
    """True if *either* the environment or the flag says shadow mode (criterion 1 and 4)."""
    return settings.shadow_mode or is_set(session, FlagKey.SHADOW_MODE)


def outbound_email_allowed(session: Session, settings: Settings) -> bool:
    """True only if every switch agrees. Any one of them is enough to stop email."""
    return (
        settings.outbound_email_enabled
        and not is_set(session, FlagKey.OUTBOUND_EMAIL_DISABLED)
        and not shadow_mode_active(session, settings)
        and not is_set(session, FlagKey.GLOBAL_PAUSE)
    )


def consequential_work_allowed(session: Session, *, campaign_paused: bool = False) -> bool:
    """Whether new consequential work may start (§17.1).

    ``campaign_paused`` is passed in rather than read: `Campaign.paused` is owned by `campaigns`,
    which this module may not import. The default is `False` so a caller with no campaign in play
    is not accidentally blocked, and every campaign-scoped caller passes the real value.
    """
    return not is_set(session, FlagKey.GLOBAL_PAUSE) and not campaign_paused


def assert_consequential_work_allowed(session: Session, *, campaign_paused: bool = False) -> None:
    """Raise if a pause is in force. The checkpoint every consequential path calls."""
    if not consequential_work_allowed(session, campaign_paused=campaign_paused):
        raise ConsequentialWorkPaused(
            "a pause is in force; new consequential work is refused while queued work stays "
            "queued and inspectable (§17.1, §17.6)"
        )


class GuardedAdapter[Q, R]:
    """Base class for anything that performs an external effect.

    The switch is checked *here*, in `perform`, and subclasses implement `_perform`. That is the
    whole point: a subclass cannot forget the check, because it never writes the entry point. A
    convention that each adapter must remember to call a guard is the convention that gets
    forgotten in the adapter written at 2am during an incident.

    Generic over the request and result types so the boundary stays typed: `T-035a`'s
    `ExternalEffectAdapter` is a `GuardedAdapter[EffectRequest, EffectResult]`.
    """

    #: Set by subclasses whose effect is email specifically, so the narrower switch applies too.
    is_email: bool = False

    def perform(
        self,
        session: Session,
        settings: Settings,
        request: Q,
        *,
        campaign_paused: bool = False,
    ) -> R:
        if shadow_mode_active(session, settings):
            raise ExternalEffectBlocked(
                f"{type(self).__name__} refused: shadow mode is active (§17.6)"
            )
        assert_consequential_work_allowed(session, campaign_paused=campaign_paused)
        if self.is_email and not outbound_email_allowed(session, settings):
            raise ExternalEffectBlocked(
                f"{type(self).__name__} refused: outbound email is disabled (§17.6)"
            )
        return self._perform(session, request)

    def _perform(self, session: Session, request: Q) -> R:
        raise NotImplementedError


#: Convenience for scripts and the worker, which act as the system rather than as a person.
SYSTEM_FLAG_ACTOR = Actor(type=ActorType.SERVICE, id="operations")
