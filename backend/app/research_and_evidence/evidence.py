"""Reading evidence (specification §14.3, §9.5, GP-02).

Stale evidence is not returned as current. A fact retrieved eighteen months ago that has passed
its refresh date may still be true, but nothing here will assert that it is — "missing facts
remain missing" (GP-02), and a draft that cites a stale fact is a draft nobody approved on the
basis of what it now says.
"""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.research_and_evidence.models import EvidenceSnapshot


class EvidenceError(Exception):
    """An evidence request could not be satisfied safely."""


class NoCurrentEvidence(EvidenceError):
    """A caller required evidence and none is current."""


def content_hash(content: str) -> str:
    """SHA-256 of the source content the excerpt was taken from.

    Lets a refresh tell "the page changed" from "the page is the same and our excerpt still
    stands", without keeping the page.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def current_evidence(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    at: datetime | None = None,
) -> list[EvidenceSnapshot]:
    """Every snapshot for a candidate that is retrieved and not stale at ``at``."""
    moment = at or datetime.now(UTC)

    statement = (
        select(EvidenceSnapshot)
        .where(
            EvidenceSnapshot.candidate_id == candidate_id,
            EvidenceSnapshot.retrieved_at <= moment,
        )
        .where(
            (EvidenceSnapshot.expires_or_refresh_by.is_(None))
            | (EvidenceSnapshot.expires_or_refresh_by > moment)
        )
        .order_by(EvidenceSnapshot.retrieved_at.desc())
    )
    return list(session.execute(statement).scalars().all())


def require_current_evidence(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    at: datetime | None = None,
) -> list[EvidenceSnapshot]:
    """As :func:`current_evidence`, but raises when there is none.

    Used where a personalized statement is about to be made: with no current evidence there is
    nothing to personalize *from*, and inventing the difference is exactly what GP-02 forbids.
    """
    evidence = current_evidence(session, candidate_id, at=at)
    if not evidence:
        moment = at or datetime.now(UTC)
        raise NoCurrentEvidence(
            f"candidate {candidate_id} has no current evidence at {moment.isoformat()}; "
            f"prospect statements must cite stored evidence (GP-02, §10.5)"
        )
    return evidence


def evidence_by_id(
    session: Session,
    candidate_id: uuid.UUID,
    evidence_ids: list[uuid.UUID],
    *,
    at: datetime | None = None,
) -> list[EvidenceSnapshot]:
    """Resolve specific evidence IDs, or raise if any is missing or stale.

    Fails whole, like the approved-claim set (`T-014`): a draft cited these exact IDs, so
    quietly returning a subset would change what the draft is based on.
    """
    moment = at or datetime.now(UTC)
    found = {
        snapshot.id: snapshot
        for snapshot in session.execute(
            select(EvidenceSnapshot).where(
                EvidenceSnapshot.candidate_id == candidate_id,
                EvidenceSnapshot.id.in_(evidence_ids),
            )
        )
        .scalars()
        .all()
    }

    resolved: list[EvidenceSnapshot] = []
    for evidence_id in evidence_ids:
        snapshot = found.get(evidence_id)
        if snapshot is None:
            raise NoCurrentEvidence(
                f"evidence {evidence_id} does not belong to candidate {candidate_id}"
            )
        if not snapshot.is_current_at(moment):
            refresh_by = (
                snapshot.expires_or_refresh_by.isoformat()
                if snapshot.expires_or_refresh_by
                else "never"
            )
            raise NoCurrentEvidence(
                f"evidence {evidence_id} is not current at {moment.isoformat()} "
                f"(retrieved {snapshot.retrieved_at.isoformat()}, refresh by {refresh_by})"
            )
        resolved.append(snapshot)
    return resolved
