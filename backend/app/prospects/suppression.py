"""Suppression (specification §15.6, §3.5, §11.4).

"Zero sends to suppressed recipients" is a safety invariant, not a target (§3.5). Suppression is
therefore built to outlast everything around it:

* **No foreign keys.** Identities are stored as normalized strings, so deleting a contact or an
  account cannot cascade a suppression away (§15.6). An orphaned suppression is the correct
  outcome — the person still does not want to be contacted.
* **Deletion is impossible.** A trigger blocks `DELETE` outright. A suppression you can drop is
  not a suppression.
* **Opt-outs cannot be lifted.** `UNSUBSCRIBE` and `COMPLAINT` records are permanent, enforced by
  the same trigger. Other sources (a mistyped domain, a stale import) can be lifted with a
  recorded reason, because an operator error must be correctable and an opt-out must not be.
* **It outranks campaign policy.** Campaign configuration can only ever *narrow* what is
  contacted; nothing in a policy can clear a suppression.

Checked inside the final send transaction (§11.4), not only at candidate creation — a suppression
recorded after approval must still stop the send.
"""

import uuid
from contextlib import suppress
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, validates

from app.db.base import Base, TimestampMixin
from app.prospects.normalize import NormalizationError, normalize_domain, normalize_email


class SuppressionScope(Enum):
    """What the stored identity refers to (§15.6, §11.4).

    ``PERSON`` and ``ACCOUNT`` hold an internal record ID as text — deliberately not a foreign
    key, so the suppression survives deletion of the record it describes.
    """

    EMAIL = "email"
    PERSON = "person"
    DOMAIN = "domain"
    ACCOUNT = "account"


class SuppressionSource(Enum):
    """Where the suppression came from. Determines whether it can ever be lifted."""

    UNSUBSCRIBE = "unsubscribe"
    COMPLAINT = "complaint"
    BOUNCE = "bounce"
    MANUAL = "manual"
    IMPORT = "import"
    POLICY = "policy"


#: Sources that record a person's own wish not to be contacted. Permanent by design: honouring
#: an opt-out is a legal obligation under CAN-SPAM (§15.8), not an operational preference.
UNLIFTABLE_SOURCES = frozenset({SuppressionSource.UNSUBSCRIBE, SuppressionSource.COMPLAINT})


class SuppressionError(Exception):
    """A suppression rule was violated."""


class RecipientSuppressed(SuppressionError):
    """The recipient must not be contacted."""

    def __init__(self, match: "Suppression") -> None:
        self.match = match
        super().__init__(
            f"recipient is suppressed at {match.scope.value} scope "
            f"({match.identity}, source={match.source.value}); suppression overrides campaign "
            f"configuration (§15.6)"
        )


class Suppression(Base, TimestampMixin):
    """One reason not to contact an identity."""

    __tablename__ = "suppression"
    __table_args__ = (
        CheckConstraint("length(trim(identity)) > 0", name="identity_not_blank"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint(
            "(lifted_at IS NULL) = (lifted_reason IS NULL)", name="lift_needs_a_reason"
        ),
        # Lookups happen inside the send transaction, so they must be cheap.
        Index("ix_suppression_scope_identity", "scope", "identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[SuppressionScope] = mapped_column(nullable=False)

    #: Normalized on write: an email suppression recorded as ``Sales@Example.COM`` must stop a
    #: send to ``sales@example.com``.
    identity: Mapped[str] = mapped_column(String(320), nullable=False)

    source: Mapped[SuppressionSource] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    #: When it starts applying. Suppressions apply immediately across active campaigns (§15.6).
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Which jurisdiction or policy this was recorded under (§15.6). `Q-013` decides the real
    #: values; until then it is free text.
    jurisdiction: Mapped[str | None] = mapped_column(String(100))

    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: An `Actor` id, not a user (ADR-025). Human-only today; §15.6 lets a policy source lift
    #: one, and this column must not have to change on the day that happens.
    lifted_by: Mapped[str | None] = mapped_column(String(255))
    lifted_reason: Mapped[str | None] = mapped_column(Text)

    @validates("identity")
    def _normalize_identity(self, _key: str, value: str) -> str:
        if self.scope is SuppressionScope.EMAIL:
            return normalize_email(value)
        if self.scope is SuppressionScope.DOMAIN:
            return normalize_domain(value)
        return value.strip()

    def is_active_at(self, moment: datetime) -> bool:
        if moment < self.effective_at:
            return False
        return self.lifted_at is None or moment < self.lifted_at

    def __repr__(self) -> str:
        return f"Suppression({self.scope.value}:{self.identity})"


def _candidate_identities(
    *,
    email: str | None,
    contact_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
    domain: str | None,
) -> list[tuple[SuppressionScope, str]]:
    """Every (scope, identity) pair that could suppress this recipient.

    Ordered narrowest first, so the reported match is the most specific one. Any match
    suppresses — the order only decides which reason an operator is shown.
    """
    pairs: list[tuple[SuppressionScope, str]] = []

    normalized_email: str | None = None
    if email:
        try:
            normalized_email = normalize_email(email)
        except NormalizationError:
            normalized_email = email.strip().lower()
        pairs.append((SuppressionScope.EMAIL, normalized_email))

    if contact_id is not None:
        pairs.append((SuppressionScope.PERSON, str(contact_id)))

    # A domain suppression must catch a *new* contact at that domain with no extra write, so the
    # domain is derived from the address when one is not supplied explicitly (§15.6).
    # An unnormalizable domain simply yields no domain-scope candidate; the other scopes still
    # apply, and a junk value must not abort a suppression check inside a send transaction.
    domains: list[str] = []
    if domain:
        with suppress(NormalizationError):
            domains.append(normalize_domain(domain))
    if normalized_email and "@" in normalized_email:
        with suppress(NormalizationError):
            domains.append(normalize_domain(normalized_email.rpartition("@")[2]))
    for value in dict.fromkeys(domains):
        pairs.append((SuppressionScope.DOMAIN, value))

    if account_id is not None:
        pairs.append((SuppressionScope.ACCOUNT, str(account_id)))

    return pairs


def find_suppression(
    session: Session,
    *,
    email: str | None = None,
    contact_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    domain: str | None = None,
    at: datetime | None = None,
) -> Suppression | None:
    """The narrowest active suppression covering this recipient, or ``None``."""
    moment = at or datetime.now(UTC)
    pairs = _candidate_identities(
        email=email, contact_id=contact_id, account_id=account_id, domain=domain
    )
    if not pairs:
        return None

    rows = (
        session.execute(
            select(Suppression).where(
                Suppression.effective_at <= moment,
                (Suppression.lifted_at.is_(None)) | (Suppression.lifted_at > moment),
            )
        )
        .scalars()
        .all()
    )
    by_key = {(row.scope, row.identity): row for row in rows}

    for scope, identity in pairs:
        match = by_key.get((scope, identity))
        if match is not None:
            return match
    return None


def is_suppressed(
    session: Session,
    *,
    email: str | None = None,
    contact_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    domain: str | None = None,
    at: datetime | None = None,
) -> bool:
    return (
        find_suppression(
            session,
            email=email,
            contact_id=contact_id,
            account_id=account_id,
            domain=domain,
            at=at,
        )
        is not None
    )


def require_not_suppressed(
    session: Session,
    *,
    email: str | None = None,
    contact_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    domain: str | None = None,
    at: datetime | None = None,
) -> None:
    """Raise :class:`RecipientSuppressed` if any scope matches.

    This is the form the final send transaction calls (§11.4). It takes no campaign argument on
    purpose: there is no configuration under which a suppressed recipient may be contacted.
    """
    match = find_suppression(
        session, email=email, contact_id=contact_id, account_id=account_id, domain=domain, at=at
    )
    if match is not None:
        raise RecipientSuppressed(match)


def record_suppression(
    session: Session,
    *,
    scope: SuppressionScope,
    identity: str,
    source: SuppressionSource,
    reason: str,
    effective_at: datetime | None = None,
    jurisdiction: str | None = None,
) -> Suppression:
    """Add a suppression. Effective immediately unless a later time is given."""
    suppression = Suppression(
        scope=scope,
        identity=identity,
        source=source,
        reason=reason,
        effective_at=effective_at or datetime.now(UTC),
        jurisdiction=jurisdiction,
    )
    session.add(suppression)
    return suppression


def _existing_opt_out(
    session: Session, *, scope: SuppressionScope, identity: str, at: datetime
) -> Suppression | None:
    """An opt-out already on file for this exact identity, or ``None``.

    Only :data:`UNLIFTABLE_SOURCES` count. A `MANUAL` or `IMPORT` suppression on the same identity
    is *not* the same thing and must not stand in for one: it can be lifted with a reason, and the
    whole point of the opt-out record is that it cannot.
    """
    rows = (
        session.execute(
            select(Suppression).where(Suppression.scope == scope, Suppression.identity == identity)
        )
        .scalars()
        .all()
    )
    for row in rows:
        if row.source in UNLIFTABLE_SOURCES and row.is_active_at(at):
            return row
    return None


def record_opt_out(
    session: Session,
    *,
    email: str,
    reason: str,
    source: SuppressionSource = SuppressionSource.UNSUBSCRIBE,
    contact_id: uuid.UUID | None = None,
    jurisdiction: str | None = None,
    at: datetime | None = None,
) -> list[Suppression]:
    """Honour an opt-out (§15.8 "clear opt-out handling and immediate suppression", §15.6).

    This is the one entry point for "this person asked not to be contacted", and it is deliberately
    narrower than :func:`record_suppression` in every direction that could lose an opt-out:

    * **Permanent.** ``source`` must be one of :data:`UNLIFTABLE_SOURCES`. Recording an opt-out as
      `MANUAL` would leave it liftable, which is the one property it must never have, so a liftable
      source is refused rather than quietly downgraded.
    * **Immediate, and never future-dated.** ``effective_at`` is clamped to now. A caller passing a
      future timestamp — a provider clock running ahead, a replayed event — would otherwise open a
      window in which the send transaction still lets the message through. A past ``at`` is honoured
      as given, because suppressing *earlier* is the safe direction.
    * **Idempotent.** The same unsubscribe delivered twice records one suppression. Suppressions
      cannot be deleted (§15.6), so duplicates are permanent noise in the one table an operator
      reads to answer "why was this person not contacted".
    * **The person, not just the mailbox.** When the contact is known, a `PERSON`-scope record goes
      in alongside the `EMAIL` one, so opting out of one address is not undone by a second address
      on the same contact.

    "Immediately across active campaigns" needs no fan-out: eligibility (§10.1) and the final send
    transaction (§11.4) both read suppression live, so the next evaluation of an already-approved
    candidate refuses it. Returns every suppression now covering the opt-out, newly written or
    already on file.

    Raises :class:`NormalizationError` if the address cannot be parsed. That is deliberate — a
    suppression stored under an unparseable key would never match a check, and failing loudly is
    better than a record that only looks like protection.
    """
    if source not in UNLIFTABLE_SOURCES:
        permanent = ", ".join(sorted(item.value for item in UNLIFTABLE_SOURCES))
        raise SuppressionError(
            f"an opt-out may not be recorded under source {source.value!r}: only {permanent} "
            f"cannot be lifted, and an opt-out that can be lifted is not an opt-out (§15.6)"
        )

    now = datetime.now(UTC)
    moment = min(at, now) if at is not None else now

    targets = [(SuppressionScope.EMAIL, normalize_email(email))]
    if contact_id is not None:
        targets.append((SuppressionScope.PERSON, str(contact_id)))

    recorded: list[Suppression] = []
    for scope, identity in targets:
        existing = _existing_opt_out(session, scope=scope, identity=identity, at=moment)
        if existing is not None:
            recorded.append(existing)
            continue
        recorded.append(
            record_suppression(
                session,
                scope=scope,
                identity=identity,
                source=source,
                reason=reason,
                effective_at=moment,
                jurisdiction=jurisdiction,
            )
        )
    return recorded
