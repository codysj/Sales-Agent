"""Turning captured facts into evidence snapshots (T-046; §8.3 steps 5-6, §14.3, §15.4, GP-02).

The adapter finds facts; this decides what becomes a snapshot and what a snapshot records. That
split is the point: an adapter that wrote rows would own provenance defaults and the candidate
association, and every new source would get its own opinion about them.

Three rules hold here regardless of source:

* **A refresh writes new snapshots. Nothing is ever updated.** §9.5 requires it and a database
  trigger enforces it, so re-capturing produces a second row and the first still says what the
  earlier qualification run was based on. `capture_evidence` therefore has no "update" path to
  get wrong.
* **Provenance is copied, never invented.** Every §14.3 field comes from the `CapturedFact`. The
  one thing this module supplies is `retrieved_at`, because *when we looked* is a fact about the
  capture and not about the document.
* **Excerpt text is data (§15.4).** It is stored verbatim and nothing branches on it. The audit
  event records counts, document IDs, and hashes — never the excerpt — because §15.5 keeps
  content out of the trail.

Capture is refused for a candidate that is not eligible. §8.3 orders research *after* the
eligibility gate (step 4 before steps 5-6), and researching a candidate that hard rules already
refused spends effort on someone who must not be contacted — and, where the refusal was
suppression, builds a dossier on a person who asked not to be.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor, record_audit_event
from app.campaigns.candidate import CampaignCandidate
from app.core.lifecycles import CampaignCandidateState
from app.prospects.models import Account
from app.research_and_evidence.adapters.protocol import CapturedFact, SourceAdapter
from app.research_and_evidence.models import EvidenceSnapshot

ENTITY_TYPE: Final = "evidence_snapshot"

#: Candidate states research may run for. `imported` is excluded on purpose: eligibility (§8.3
#: step 4) comes first, and researching an unevaluated candidate would invert that order.
RESEARCHABLE_STATES: Final = frozenset(
    {CampaignCandidateState.ELIGIBLE, CampaignCandidateState.RESEARCH_PENDING}
)


class CaptureRefused(Exception):
    """Evidence capture was not permitted for this candidate."""


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """What one capture pass stored."""

    candidate_id: uuid.UUID
    snapshots: list[EvidenceSnapshot] = field(default_factory=list)
    #: Facts the adapter returned that were already stored, by `(document, hash, excerpt)`.
    duplicates: int = 0

    @property
    def captured(self) -> int:
        return len(self.snapshots)


def _existing_keys(session: Session, candidate_id: uuid.UUID) -> set[tuple[str, str]]:
    """`(content_hash, excerpt)` of what this candidate already has.

    Re-running a capture over an unchanged source must not pile up identical rows. A *changed*
    source has a different hash and so does produce a new snapshot, which is exactly the point of
    storing the hash (§9.5).
    """
    rows = (
        session.query(EvidenceSnapshot.content_hash, EvidenceSnapshot.supporting_excerpt_or_fact)
        .filter(EvidenceSnapshot.candidate_id == candidate_id)
        .all()
    )
    return {(row[0], row[1]) for row in rows}


def capture_evidence(
    session: Session,
    candidate: CampaignCandidate,
    adapter: SourceAdapter,
    *,
    actor: Actor,
    allowed_states: frozenset[CampaignCandidateState] = RESEARCHABLE_STATES,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> CaptureResult:
    """Capture evidence for one candidate. Adds to ``session`` without committing.

    Raises :class:`CaptureRefused` unless the candidate is in one of ``allowed_states``.

    **The states are an argument because there are two situations, not one.** The first research
    pass runs after the eligibility gate (§8.3 step 4 before steps 5-6), which is the default. A
    reviewer asking for *more* research (ADR-022) is asking about a candidate already in
    `review_pending`, and it passes its own set. Widening the default to serve the second would
    make the first accept a state it should never see; keeping one set per caller lets each
    refusal name exactly the situation it is refusing.
    """
    if candidate.state not in allowed_states:
        # The default set is the eligibility gate, so the refusal says so; a caller that passed
        # its own set gets the states named and no claim about why they are the right ones.
        because = (
            " — research runs after the eligibility gate (§8.3 step 4 before steps 5-6)"
            if allowed_states == RESEARCHABLE_STATES
            else ""
        )
        raise CaptureRefused(
            f"candidate {candidate.id} is {candidate.state.value}; this capture permits "
            f"{sorted(state.value for state in allowed_states)}{because}"
        )

    account = session.get(Account, candidate.account_id)
    if account is None:  # pragma: no cover - the foreign key prevents this
        raise CaptureRefused(f"candidate {candidate.id} points at a missing account")

    moment = at or datetime.now(UTC)
    facts: Sequence[CapturedFact] = adapter.refresh(account_domain=account.domain)

    seen = _existing_keys(session, candidate.id)
    stored: list[EvidenceSnapshot] = []
    duplicates = 0

    for fact in facts:
        key = (fact.content_hash, fact.excerpt)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)

        snapshot = EvidenceSnapshot(
            candidate_id=candidate.id,
            source_type=fact.source_type,
            source_provider_id=fact.source_document_id,
            source_url_if_permitted=fact.source_url_if_permitted,
            retrieved_at=moment,
            supporting_excerpt_or_fact=fact.excerpt,
            content_hash=fact.content_hash,
            extraction_field_or_span=fact.extraction_field_or_span,
            extraction_method=fact.extraction_method,
            source_quality=fact.source_quality,
            license_and_retention_class=fact.retention_class,
            contains_personal_or_confidential_data=(fact.contains_personal_or_confidential_data),
            expires_or_refresh_by=fact.expires_or_refresh_by,
        )
        session.add(snapshot)
        stored.append(snapshot)

    session.flush()

    # Identifiers, counts, and hashes. Never an excerpt: the audit trail must not become the
    # place a document's text is quoted (§15.5).
    record_audit_event(
        session,
        actor=actor,
        action="evidence_snapshot.captured",
        entity_type=ENTITY_TYPE,
        entity_id=candidate.id,
        payload={
            "candidate_id": str(candidate.id),
            "adapter": adapter.name,
            "captured": len(stored),
            "duplicates": duplicates,
            "source_documents": sorted({fact.source_document_id for fact in facts}),
        },
        correlation_id=correlation_id,
    )

    return CaptureResult(candidate_id=candidate.id, snapshots=stored, duplicates=duplicates)
