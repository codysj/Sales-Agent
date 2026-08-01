"""Deterministic deduplication of internal records (T-043; §8.3 step 2, §13.5 rule 2, §19.2).

Two records are the same person or they are not, and a rule an operator can read decides which.
Nothing here is probabilistic: no similarity score, no threshold, no embedding, no model
(§18.6 forbids the vector database that would be needed, and §10.1 keeps identity deterministic).
Every match names the rule that produced it, so a merge can be explained and argued with months
later — that is what `MatchReason` is for.

**Rules, in priority order.** The first that hits wins, and the caller is told which:

1. `EXACT_EMAIL` — the same normalized address. An address identifies one mailbox, so this is
   the strongest signal available and it is checked first.
2. `DOMAIN_AND_NAME` — the same account plus the same normalized personal name. Catches the
   record imported twice under two addresses, which is the ordinary shape of a duplicate.

**Why there is no role rule.** The task's scope named a third rule, "account domain + role".
It is not implemented as a *contact* match and that is a deliberate decision (ADR-019): two
different people at one company routinely share a role title, so the rule would merge distinct
humans — and a merge is the one identity operation that cannot be undone by hand once evidence
and suppression have been re-pointed. Account-level dedup already exists and is exact:
`Account.domain` is unique and normalized, so `find_account` resolves an account by domain with
no heuristic at all.

**Merging never destroys anything.** §15.6 makes suppression outrank every other consideration,
and a merge is precisely where a suppression could be lost: `PERSON`-scope suppressions store a
contact ID as text with no foreign key, so a suppression naming the losing contact would simply
stop matching once that contact is gone. `merge_contacts` therefore re-records every such
suppression against the surviving contact **before** anything moves, and never deletes the
original — the `Suppression` table blocks `DELETE` by trigger anyway.

**Campaign membership does not move, and that is the database's rule, not a simplification.**
`(campaign, account, contact)` is immutable by trigger (§8.1 — "create a new membership
instead"), so a merge cannot re-point a candidate even if it wanted to. Evidence hangs off
`CampaignCandidate`, so this is also what keeps evidence safe: a losing contact that still holds
candidates is *not* deleted, because deleting it would cascade their snapshots away. It is left
in place, stripped of the contact points that moved, and `merge_contacts` reports the stranded
candidates so `T-044` can decide whether the survivor needs its own membership.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor, record_audit_event
from app.campaigns.candidate import CampaignCandidate
from app.prospects.models import Account, Contact, ContactPoint, ContactPointType
from app.prospects.normalize import (
    NormalizationError,
    normalize_domain,
    normalize_email,
    normalize_person_name,
)
from app.prospects.suppression import (
    Suppression,
    SuppressionScope,
    record_suppression,
)

ENTITY_TYPE: Final = "contact"

#: Kept so a reader can see the whole rule set in one place; `find_contact_match` walks it in order.
__all__ = [
    "DuplicateMatch",
    "MatchReason",
    "MergeResult",
    "find_account",
    "find_contact_match",
    "merge_contacts",
]


class MatchReason(StrEnum):
    """Which rule decided two records are the same. Recorded on every merge."""

    EXACT_EMAIL = "exact_email"
    DOMAIN_AND_NAME = "domain_and_name"


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    """An existing record the incoming one is the same as, and why."""

    contact: Contact
    reason: MatchReason


@dataclass(frozen=True, slots=True)
class MergeResult:
    """What a merge moved. Empty lists are the normal case for a freshly imported duplicate."""

    kept_contact_id: uuid.UUID
    merged_contact_id: uuid.UUID
    reason: MatchReason
    moved_contact_points: list[uuid.UUID] = field(default_factory=list)
    #: Candidates left where they are, because `(campaign, account, contact)` is immutable by
    #: trigger (§8.1). They keep their evidence and their review history; creating the equivalent
    #: membership for the survivor is `T-044`'s decision, not a side effect of a merge.
    stranded_candidates: list[uuid.UUID] = field(default_factory=list)
    carried_suppressions: list[uuid.UUID] = field(default_factory=list)
    dropped_duplicate_points: list[uuid.UUID] = field(default_factory=list)
    #: False whenever the losing contact still holds candidates: deleting it would cascade their
    #: evidence away, so it stays, stripped of the contact points that moved.
    merged_contact_removed: bool = True


class DedupError(Exception):
    """A merge was refused."""


class NotMergeable(DedupError):
    """The two records cannot be merged.

    Raised rather than worked around: merging across accounts, or a record with itself, is a
    caller bug, and guessing what was meant is how two companies become one.
    """


def find_account(session: Session, domain: str) -> Account | None:
    """Account-level dedup, exact by construction: `Account.domain` is unique and normalized."""
    try:
        normalized = normalize_domain(domain)
    except NormalizationError:
        return None
    return session.execute(select(Account).where(Account.domain == normalized)).scalar_one_or_none()


def _match_by_email(session: Session, email: str) -> Contact | None:
    try:
        normalized = normalize_email(email)
    except NormalizationError:
        return None

    point = session.execute(
        select(ContactPoint).where(
            ContactPoint.type == ContactPointType.EMAIL, ContactPoint.value == normalized
        )
    ).scalar_one_or_none()
    return None if point is None else point.contact


def _match_by_account_and_name(
    session: Session, *, account_id: uuid.UUID, full_name: str
) -> Contact | None:
    """Compare normalized names, so `  Ada  Lovelace ` and `ada lovelace` are one person.

    The comparison is done in Python over one account's contacts rather than in SQL: the stored
    name keeps the operator's own spelling (§14.1), so there is no normalized column to index,
    and an account has tens of contacts, not millions.
    """
    wanted = normalize_person_name(full_name)
    if not wanted:
        return None

    contacts = (
        session.execute(select(Contact).where(Contact.account_id == account_id)).scalars().all()
    )
    for contact in contacts:
        if normalize_person_name(contact.full_name) == wanted:
            return contact
    return None


def find_contact_match(
    session: Session,
    *,
    account_id: uuid.UUID,
    full_name: str,
    email: str | None = None,
    exclude_contact_id: uuid.UUID | None = None,
) -> DuplicateMatch | None:
    """The existing contact this record duplicates, and the rule that says so.

    ``exclude_contact_id`` lets a caller ask "what does *this stored* contact duplicate", which is
    how a post-import sweep works; without it every contact would match itself.
    """
    if email:
        contact = _match_by_email(session, email)
        if contact is not None and contact.id != exclude_contact_id:
            return DuplicateMatch(contact=contact, reason=MatchReason.EXACT_EMAIL)

    contact = _match_by_account_and_name(session, account_id=account_id, full_name=full_name)
    if contact is not None and contact.id != exclude_contact_id:
        return DuplicateMatch(contact=contact, reason=MatchReason.DOMAIN_AND_NAME)

    return None


def _carry_suppressions(
    session: Session, *, keep: Contact, merged: Contact, now: datetime
) -> list[uuid.UUID]:
    """Re-record every `PERSON`-scope suppression naming ``merged`` against ``keep``.

    Done **first**, so a failure later leaves the surviving contact over-suppressed rather than
    under-suppressed. The original row is left exactly where it is: it cannot be deleted (§15.6
    trigger) and an orphaned suppression is the safe kind of orphan.
    """
    existing = (
        session.execute(
            select(Suppression).where(
                Suppression.scope == SuppressionScope.PERSON,
                Suppression.identity == str(merged.id),
            )
        )
        .scalars()
        .all()
    )

    carried: list[uuid.UUID] = []
    for suppression in existing:
        if suppression.lifted_at is not None:
            # A lifted suppression restricts nothing today, and `record_suppression` has no way
            # to create one already lifted. The original row stays where it is either way, so the
            # history is not lost — only the (absent) restriction is not copied.
            continue
        carried_row = record_suppression(
            session,
            scope=SuppressionScope.PERSON,
            identity=str(keep.id),
            source=suppression.source,
            reason=(
                f"carried from merged contact {merged.id} on dedup; "
                f"original reason: {suppression.reason}"
            ),
            effective_at=min(suppression.effective_at, now),
            jurisdiction=suppression.jurisdiction,
        )
        session.flush()
        carried.append(carried_row.id)
    return carried


def merge_contacts(
    session: Session,
    *,
    keep: Contact,
    merge: Contact,
    reason: MatchReason,
    actor: Actor,
    now: datetime | None = None,
) -> MergeResult:
    """Fold ``merge`` into ``keep``. Adds to ``session`` without committing.

    Order matters and is the safety argument: suppressions are carried first, then contact points
    and campaign candidates move, then the losing contact is removed. A crash part-way leaves the
    survivor with *more* restrictions than it needs, never fewer.
    """
    if keep.id == merge.id:
        raise NotMergeable(f"contact {keep.id} cannot be merged into itself")
    if keep.account_id != merge.account_id:
        raise NotMergeable(
            f"contacts {keep.id} and {merge.id} belong to different accounts; merging across "
            f"accounts would fold two companies together (§8.3 step 2)"
        )

    moment = now or datetime.now(UTC)
    carried = _carry_suppressions(session, keep=keep, merged=merge, now=moment)

    moved_points: list[uuid.UUID] = []
    dropped_points: list[uuid.UUID] = []
    kept_values = {
        (point.type, point.value)
        for point in session.execute(select(ContactPoint).where(ContactPoint.contact_id == keep.id))
        .scalars()
        .all()
    }
    for point in (
        session.execute(select(ContactPoint).where(ContactPoint.contact_id == merge.id))
        .scalars()
        .all()
    ):
        if (point.type, point.value) in kept_values:
            # The survivor already has this address. `(type, value)` is globally unique, so the
            # duplicate row goes; the address itself is not lost.
            dropped_points.append(point.id)
            session.delete(point)
            continue
        point.contact_id = keep.id
        kept_values.add((point.type, point.value))
        moved_points.append(point.id)

    session.flush()

    # Candidates are **not** moved. `(campaign, account, contact)` is immutable by trigger
    # (§8.1 — "create a new membership instead"), so re-pointing one is refused by the database,
    # and deleting it would cascade its evidence away. They stay, and so does the contact that
    # holds them; `T-044` decides whether the survivor needs its own membership.
    stranded = (
        session.execute(select(CampaignCandidate).where(CampaignCandidate.contact_id == merge.id))
        .scalars()
        .all()
    )
    result = MergeResult(
        kept_contact_id=keep.id,
        merged_contact_id=merge.id,
        reason=reason,
        moved_contact_points=moved_points,
        stranded_candidates=[candidate.id for candidate in stranded],
        carried_suppressions=carried,
        dropped_duplicate_points=dropped_points,
        merged_contact_removed=not stranded,
    )

    # Identifiers and counts only: a merge audit must not become where a contact's name and
    # address are quoted (§15.5).
    record_audit_event(
        session,
        actor=actor,
        action="contact.merged",
        entity_type=ENTITY_TYPE,
        entity_id=keep.id,
        policy_decision=f"dedup:{reason.value}",
        payload={
            "kept_contact_id": str(keep.id),
            "merged_contact_id": str(merge.id),
            "match_reason": reason.value,
            "moved_contact_points": len(moved_points),
            "dropped_duplicate_points": len(dropped_points),
            "stranded_candidates": len(stranded),
            "carried_suppressions": len(carried),
            "merged_contact_removed": result.merged_contact_removed,
        },
    )

    if result.merged_contact_removed:
        session.delete(merge)
    session.flush()

    return result
