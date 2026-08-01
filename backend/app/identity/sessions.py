"""Sessions: what a request is authenticated by (T-061a; §12.2, §15.1).

A session is the only thing that turns a request into an actor. `T-062` will check roles against
whatever this resolves, and every audit event a human causes takes its `Actor` from here — §12.2
requires immutable actor attribution, and attribution read from a request field would be
attribution the caller chose for themselves.

**No password exists, here or anywhere.** §12.2 rejects custom password authentication outright.
There is no password column, no hash function, and no verify step; a session is *issued* by
something that already established who the person is — the local stub today (`identity.stub`), a
managed provider once `Q-026` names one (`T-061b`). `tests/test_sessions.py` asserts the absence
against the migrated schema and the source, because "we did not add one" is a claim that decays.

**The token is never stored.** The row keys on `sha256(token)`. A database dump, a backup, or a
careless log therefore contains nothing that can be replayed as a session — the same reason
`T-046` stores an evidence hash rather than the document. The plaintext exists only in the
response that issues it and in the caller's cookie.

**Expiry and revocation are separate, and both are checked.** An expiry is a fact about time; a
revocation is a decision someone made. §12.2 wants sessions "short and revocable", and collapsing
the two would mean an administrator ending a session could not tell it apart from one that simply
aged out. `resolve` refuses either, and refuses closed: anything it cannot positively confirm is
nobody.

**A session belongs to a human.** The foreign key is to `app_user`, so a `ServiceIdentity` cannot
hold one. That is not an oversight to fix later — a service authenticates as itself to do
machine work, and giving it a *session* would make it indistinguishable from a person to every
check downstream (§12.2: service identities separate from human identities).
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm import Session as DbSession

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.db.base import Base, TimestampMixin
from app.identity.models import Role, User, UserRole

log = structlog.get_logger(__name__)

#: How long a freshly issued session lasts. §12.2 asks for "short"; eight hours is one working
#: day, which is short enough that a forgotten laptop stops mattering overnight and long enough
#: that a reviewer is not re-authenticating between two approvals.
DEFAULT_SESSION_TTL: Final = timedelta(hours=8)

#: Bytes of entropy in a session token. 32 bytes is 256 bits — far beyond guessing, and the cost
#: is a slightly longer cookie.
TOKEN_BYTES: Final = 32


class SessionError(Exception):
    """A session could not be issued."""


def hash_token(token: str) -> str:
    """The stored form of a session token. One-way, so a leaked row is not a leaked session."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class UserSession(Base, TimestampMixin):
    """One authenticated period for one human.

    Named `UserSession` rather than `Session` because SQLAlchemy's `Session` is imported in every
    module that touches the database, and two things called `Session` in one file is how the
    wrong one gets passed.
    """

    __tablename__ = "user_session"
    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="ck_user_session_expiry_after_issue"),
        # A revoked session must say who ended it and why: §12.2's attribution requirement does
        # not stop at the events a person causes deliberately.
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)",
            name="ck_user_session_revocation_is_attributed",
        ),
        CheckConstraint("length(token_hash) = 64", name="ck_user_session_token_hash_is_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    #: `sha256` of the token, hex. Unique so two sessions cannot collide on one cookie.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(255))
    #: How this session came to exist — `stub` today, a provider name once `T-061b` lands. Kept
    #: so an auditor can tell a development session from a real one without reading dates.
    issued_via: Mapped[str] = mapped_column(String(50), nullable=False)
    revocation_reason: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship()

    def is_live(self, at: datetime) -> bool:
        """Whether this session authenticates anyone at ``at``. Fails closed."""
        return self.revoked_at is None and self.expires_at > at


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session and its plaintext token, which is returned exactly once.

    The token is not on `UserSession` because it is not stored. A caller that loses it cannot ask
    for it again — it re-authenticates, which is the correct outcome.
    """

    session: UserSession
    token: str


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a request is, resolved from its session.

    Roles are resolved here rather than looked up later so `T-062`'s checks read one object. The
    `Actor` is derived, never supplied: attribution a caller could pass in is attribution they
    chose.
    """

    user: User
    session: UserSession
    roles: frozenset[str]

    @property
    def actor(self) -> Actor:
        """The audit actor for anything this principal does (§12.2)."""
        return Actor(type=ActorType.HUMAN, id=str(self.user.id))


def issue_session(
    session: DbSession,
    user: User,
    *,
    issued_via: str,
    at: datetime | None = None,
    ttl: timedelta = DEFAULT_SESSION_TTL,
) -> IssuedSession:
    """Issue a session for an active user. Adds to ``session`` without committing.

    Refuses a deactivated user: §12.2 keeps the row for attribution (`T-012`), and a row kept for
    history must not be a row that can log in.
    """
    if not user.active:
        raise SessionError(
            f"user {user.id} is deactivated; the row is kept for attribution, not for access"
        )
    if ttl <= timedelta(0):
        raise SessionError("session ttl must be positive; a session that starts expired is a bug")

    moment = at or datetime.now(UTC)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    issued = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        issued_at=moment,
        expires_at=moment + ttl,
        issued_via=issued_via,
    )
    session.add(issued)
    session.flush()

    # The token is never logged. The session id is, so an operator can revoke it.
    log.info(
        "session.issued",
        session_id=str(issued.id),
        user_id=str(user.id),
        issued_via=issued_via,
        expires_at=issued.expires_at.isoformat(),
    )
    return IssuedSession(session=issued, token=token)


def resolve(session: DbSession, token: str, *, at: datetime | None = None) -> Principal | None:
    """Who this token is, or `None`.

    `None` for every failure — unknown token, expired, revoked, deactivated user. The caller gets
    no way to tell them apart, because distinguishing them is how an attacker learns which tokens
    once existed.
    """
    moment = at or datetime.now(UTC)
    found = session.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if found is None or not found.is_live(moment):
        return None

    user = session.get(User, found.user_id)
    if user is None or not user.active:
        return None

    roles = frozenset(
        session.execute(
            select(Role.key)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
        .scalars()
        .all()
    )
    return Principal(user=user, session=found, roles=roles)


def revoke(
    session: DbSession,
    user_session: UserSession,
    *,
    revoked_by: str,
    reason: str,
    at: datetime | None = None,
) -> UserSession:
    """End a session now. Idempotent: revoking twice keeps the first decision and its reason.

    Keeping the first is deliberate. The question an auditor asks is *when did this stop being
    valid and who decided*, and a second revocation overwriting the answer would move the moment
    it ended.
    """
    if user_session.revoked_at is not None:
        return user_session

    user_session.revoked_at = at or datetime.now(UTC)
    user_session.revoked_by = revoked_by
    user_session.revocation_reason = reason
    session.flush()
    log.info(
        "session.revoked",
        session_id=str(user_session.id),
        revoked_by=revoked_by,
    )
    return user_session


def revoke_all_for_user(
    session: DbSession,
    user: User,
    *,
    revoked_by: str,
    reason: str,
    at: datetime | None = None,
) -> int:
    """End every live session a user holds. Returns how many were ended.

    What "revocable" means in practice: an administrator disabling someone needs one call, not a
    list of session ids they would have to enumerate correctly.
    """
    moment = at or datetime.now(UTC)
    live = (
        session.execute(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > moment,
            )
        )
        .scalars()
        .all()
    )
    for held in live:
        revoke(session, held, revoked_by=revoked_by, reason=reason, at=moment)
    return len(live)
