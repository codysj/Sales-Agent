"""Evidence carries its provenance or it does not exist (T-019; §14.3, §9.5, GP-02).

Three things are being held in place: every field that makes a fact explainable is mandatory,
excerpts are excerpts rather than documents, and stale evidence never comes back as current.
"""

import uuid
from datetime import timedelta

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, create_candidate
from app.campaigns.models import Campaign
from app.products_and_claims.models import Product
from app.prospects.models import Account, Contact
from app.research_and_evidence.evidence import (
    NoCurrentEvidence,
    content_hash,
    current_evidence,
    evidence_by_id,
    require_current_evidence,
)
from app.research_and_evidence.models import (
    EXCERPT_MAX_CHARS,
    EvidenceSnapshot,
    ExtractionMethod,
    RetentionClass,
    SourceQuality,
    SourceType,
)
from tests.factories import NOW

EARLIER = NOW - timedelta(days=30)
LATER = NOW + timedelta(days=30)
HASH = content_hash("SYNTHETIC source content")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-evidence-test")


@pytest.fixture
def candidate(db_session: Session) -> CampaignCandidate:
    product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
    db_session.add(product)
    db_session.flush()
    campaign = Campaign(
        slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Campaign", product_id=product.id
    )
    account = Account(domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account")
    db_session.add_all([campaign, account])
    db_session.flush()
    contact = Contact(account_id=account.id, full_name="SYNTHETIC Person")
    db_session.add(contact)
    db_session.flush()
    return create_candidate(
        db_session,
        campaign_id=campaign.id,
        account_id=account.id,
        contact_id=contact.id,
        actor=Actor(type=ActorType.HUMAN, id="operator-1"),
    )


def make_evidence(
    db_session: Session, candidate: CampaignCandidate, **overrides: object
) -> EvidenceSnapshot:
    values: dict[str, object] = {
        "candidate_id": candidate.id,
        "source_type": SourceType.SYNTHETIC_FIXTURE,
        "retrieved_at": EARLIER,
        "supporting_excerpt_or_fact": "SYNTHETIC: the company announced a depot project.",
        "content_hash": HASH,
        "extraction_method": ExtractionMethod.MANUAL,
        "source_quality": SourceQuality.MEDIUM,
        "license_and_retention_class": RetentionClass.PUBLIC_UNRESTRICTED,
        "contains_personal_or_confidential_data": False,
        "expires_or_refresh_by": None,
    }
    values.update(overrides)
    snapshot = EvidenceSnapshot(**values)  # type: ignore[arg-type]
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


# --- mandatory provenance (criterion 1) ----------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [
        "source_type",
        "retrieved_at",
        "supporting_excerpt_or_fact",
        "content_hash",
        "extraction_method",
        "source_quality",
        "license_and_retention_class",
        "contains_personal_or_confidential_data",
    ],
)
def test_every_required_provenance_field_is_mandatory(
    missing: str, db_session: Session, candidate: CampaignCandidate
) -> None:
    with pytest.raises((IntegrityError, DBAPIError)):
        make_evidence(db_session, candidate, **{missing: None})


def test_the_personal_data_flag_has_no_default(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    """An unanswered privacy classification must not become "contains nothing sensitive"."""
    snapshot = EvidenceSnapshot(
        candidate_id=candidate.id,
        source_type=SourceType.SYNTHETIC_FIXTURE,
        retrieved_at=EARLIER,
        supporting_excerpt_or_fact="SYNTHETIC fact",
        content_hash=HASH,
        extraction_method=ExtractionMethod.MANUAL,
        source_quality=SourceQuality.MEDIUM,
        license_and_retention_class=RetentionClass.PUBLIC_UNRESTRICTED,
    )
    db_session.add(snapshot)

    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.flush()


def test_a_malformed_content_hash_is_rejected(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    with pytest.raises(IntegrityError):
        make_evidence(db_session, candidate, content_hash="not-a-sha256")


def test_content_hash_detects_a_changed_source() -> None:
    assert content_hash("original") != content_hash("original ")
    assert content_hash("original") == content_hash("original")


def test_optional_provenance_stays_optional(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    """URL is stored only where provider terms permit (§9.5); span and provider ID may be absent."""
    snapshot = make_evidence(db_session, candidate)

    assert snapshot.source_url_if_permitted is None
    assert snapshot.source_provider_id is None
    assert snapshot.extraction_field_or_span is None


def test_linkedin_evidence_is_marked_human_provided() -> None:
    """ADR-005: LinkedIn is human-assisted; there is no autonomous LinkedIn source type."""
    linkedin_values = [s for s in SourceType if "linkedin" in s.value]

    assert linkedin_values == [SourceType.LINKEDIN_HUMAN_PROVIDED]


# --- excerpts, not documents (criterion 2) --------------------------------------------------


def test_an_oversized_excerpt_is_rejected_not_truncated(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    """A silently shortened excerpt could drop the clause that justified the claim."""
    oversized = "x" * (EXCERPT_MAX_CHARS + 1)

    with pytest.raises(ValueError, match="over the"):
        make_evidence(db_session, candidate, supporting_excerpt_or_fact=oversized)


def test_an_excerpt_at_the_cap_is_accepted(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    snapshot = make_evidence(
        db_session, candidate, supporting_excerpt_or_fact="x" * EXCERPT_MAX_CHARS
    )

    assert len(snapshot.supporting_excerpt_or_fact) == EXCERPT_MAX_CHARS


def test_the_database_also_caps_the_excerpt(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    """Belt and braces: the check constraint holds even if the ORM validator is bypassed."""
    make_evidence(db_session, candidate)

    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "INSERT INTO evidence_snapshot (id, candidate_id, source_type, retrieved_at, "
                "supporting_excerpt_or_fact, content_hash, extraction_method, source_quality, "
                "license_and_retention_class, contains_personal_or_confidential_data) "
                "VALUES (gen_random_uuid(), :cid, 'SYNTHETIC_FIXTURE', :ts, :excerpt, :hash, "
                "'MANUAL', 'MEDIUM', 'PUBLIC_UNRESTRICTED', false)"
            ),
            {
                "cid": candidate.id,
                "ts": EARLIER,
                "excerpt": "x" * (EXCERPT_MAX_CHARS + 1),
                "hash": HASH,
            },
        )


def test_a_blank_excerpt_is_rejected(db_session: Session, candidate: CampaignCandidate) -> None:
    with pytest.raises(IntegrityError):
        make_evidence(db_session, candidate, supporting_excerpt_or_fact="   ")


# --- staleness (criterion 3) ------------------------------------------------------------------


def test_expired_evidence_is_not_current(db_session: Session, candidate: CampaignCandidate) -> None:
    make_evidence(db_session, candidate, retrieved_at=EARLIER, expires_or_refresh_by=NOW)

    assert current_evidence(db_session, candidate.id, at=NOW + timedelta(seconds=1)) == []


def test_unexpired_evidence_is_current(db_session: Session, candidate: CampaignCandidate) -> None:
    snapshot = make_evidence(db_session, candidate, expires_or_refresh_by=LATER)

    assert [s.id for s in current_evidence(db_session, candidate.id, at=NOW)] == [snapshot.id]


def test_evidence_without_an_expiry_does_not_go_stale(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    make_evidence(db_session, candidate, expires_or_refresh_by=None)

    assert len(current_evidence(db_session, candidate.id, at=LATER)) == 1


def test_evidence_is_not_current_before_it_was_retrieved(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    make_evidence(db_session, candidate, retrieved_at=LATER)

    assert current_evidence(db_session, candidate.id, at=NOW) == []


def test_is_current_at_agrees_with_the_query(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    snapshot = make_evidence(db_session, candidate, expires_or_refresh_by=LATER)

    assert snapshot.is_current_at(NOW)
    assert not snapshot.is_current_at(LATER)
    assert not snapshot.is_current_at(EARLIER - timedelta(seconds=1))


def test_requiring_evidence_raises_when_all_of_it_is_stale(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    """With nothing current there is nothing to personalize from (GP-02)."""
    make_evidence(db_session, candidate, expires_or_refresh_by=NOW)

    with pytest.raises(NoCurrentEvidence) as exc:
        require_current_evidence(db_session, candidate.id, at=LATER)

    assert str(candidate.id) in str(exc.value)


# --- resolving specific IDs ---------------------------------------------------------------------


def test_cited_evidence_ids_resolve(db_session: Session, candidate: CampaignCandidate) -> None:
    first = make_evidence(db_session, candidate)
    second = make_evidence(db_session, candidate, supporting_excerpt_or_fact="SYNTHETIC second")

    resolved = evidence_by_id(db_session, candidate.id, [first.id, second.id], at=NOW)

    assert [s.id for s in resolved] == [first.id, second.id]


def test_a_stale_cited_id_fails_the_whole_resolution(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    """Like the claim set (`T-014`): quietly returning a subset changes what the draft says."""
    good = make_evidence(db_session, candidate)
    stale = make_evidence(db_session, candidate, expires_or_refresh_by=NOW)

    with pytest.raises(NoCurrentEvidence) as exc:
        evidence_by_id(db_session, candidate.id, [good.id, stale.id], at=LATER)

    assert str(stale.id) in str(exc.value)


def test_evidence_from_another_candidate_is_refused(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    with pytest.raises(NoCurrentEvidence, match="does not belong"):
        evidence_by_id(db_session, candidate.id, [uuid.uuid4()], at=NOW)


# --- immutability --------------------------------------------------------------------------------


def test_a_snapshot_cannot_be_edited(db_session: Session, candidate: CampaignCandidate) -> None:
    """§9.5: a refresh writes a new snapshot rather than mutating an existing one."""
    snapshot = make_evidence(db_session, candidate)

    snapshot.supporting_excerpt_or_fact = "SYNTHETIC: something else entirely"

    with pytest.raises(DBAPIError) as exc:
        db_session.flush()

    assert "immutable" in str(exc.value)


def test_a_snapshot_can_still_be_deleted(db_session: Session, candidate: CampaignCandidate) -> None:
    """Deliberate asymmetry with suppression: `Q-019` retention must be able to remove evidence."""
    snapshot = make_evidence(db_session, candidate)

    db_session.delete(snapshot)
    db_session.flush()

    assert current_evidence(db_session, candidate.id, at=NOW) == []


def test_deleting_a_candidate_removes_its_evidence(
    db_session: Session, candidate: CampaignCandidate
) -> None:
    make_evidence(db_session, candidate)

    db_session.delete(candidate)
    db_session.flush()

    assert db_session.query(EvidenceSnapshot).filter_by(candidate_id=candidate.id).count() == 0
