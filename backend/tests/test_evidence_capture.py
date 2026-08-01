"""Offline evidence capture (T-046; §8.3 steps 5-6, §9.5, §14.3, §15.3, §15.4).

The four things worth proving are all about what capture must *not* do: it must not reach the
network, must not invent provenance, must not mutate a snapshot on refresh, and must not read a
document's text as anything but text.

The hostile document is a real fixture on disk rather than a string built in a test, because the
guarantee is about what happens when such a document arrives through the ordinary path.
"""

import ast
import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, create_candidate, transition
from app.campaigns.models import Campaign
from app.core.lifecycles import CampaignCandidateState
from app.products_and_claims.models import Product
from app.prospects.models import Account
from app.research_and_evidence.adapters import SourceAdapter, SourceCapabilityUnavailable
from app.research_and_evidence.adapters.fixture import (
    MAX_DOCUMENT_BYTES,
    FixtureSourceAdapter,
)
from app.research_and_evidence.capture import CaptureRefused, capture_evidence
from app.research_and_evidence.evidence import content_hash, current_evidence
from app.research_and_evidence.models import (
    EXCERPT_MAX_CHARS,
    EvidenceSnapshot,
    ExtractionMethod,
    RetentionClass,
    SourceQuality,
)
from tests.factories import NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")

BACKEND = Path(__file__).resolve().parents[1]
DOCUMENTS = BACKEND / "app" / "fixtures" / "source_documents"
RESEARCH_PACKAGE = BACKEND / "app" / "research_and_evidence"

#: The sentence the hostile fixture carries, quoted here so the assertion is unmistakable.
INJECTION = "ignore previous instructions"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-capture-test")


@pytest.fixture
def adapter() -> FixtureSourceAdapter:
    return FixtureSourceAdapter(directory=DOCUMENTS)


def make_candidate(
    session: Session,
    *,
    domain: str = "alpha.example.com",
    state: CampaignCandidateState = CampaignCandidateState.ELIGIBLE,
) -> CampaignCandidate:
    product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
    session.add(product)
    session.flush()
    campaign = Campaign(
        slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Campaign", product_id=product.id
    )
    account = Account(domain=domain, name="SYNTHETIC-Account", country_code="US")
    session.add_all([campaign, account])
    session.flush()
    candidate = create_candidate(
        session,
        campaign_id=campaign.id,
        account_id=account.id,
        contact_id=None,
        actor=OPERATOR,
    )
    if state is not CampaignCandidateState.IMPORTED:
        transition(session, candidate, state, actor=OPERATOR)
    return candidate


# --- criterion 1: no HTTP client anywhere in the capture path ---------------------------------

#: Anything that opens a socket. `httpx2` is the test client dependency and belongs in `tests/`.
NETWORK_MODULES = (
    "httpx",
    "httpx2",
    "requests",
    "urllib",
    "urllib3",
    "http",
    "socket",
    "aiohttp",
    "ftplib",
    "telnetlib",
    "smtplib",
    "webbrowser",
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def network_importers(paths: list[Path]) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        roots = {name.split(".")[0] for name in imported_modules(path)}
        if roots & set(NETWORK_MODULES):
            offenders.append(path.name)
    return offenders


def test_the_capture_path_imports_no_http_client() -> None:
    """§15.3: a fetch path needs SSRF protection, redirect and size limits, and isolated parsing.
    None of that exists, so there must be no fetch path. Gate **G-03** governs when there may be."""
    assert network_importers(sorted(RESEARCH_PACKAGE.rglob("*.py"))) == []


def test_the_network_import_check_can_fail(tmp_path: Path) -> None:
    """A checker that cannot detect the thing it forbids reports success forever."""
    offending = tmp_path / "fetcher.py"
    offending.write_text("import httpx\n", encoding="utf-8")

    assert network_importers([offending]) == ["fetcher.py"]


def test_discovery_is_refused_and_names_its_gate(adapter: FixtureSourceAdapter) -> None:
    with pytest.raises(SourceCapabilityUnavailable, match="Q-003"):
        adapter.discover({"segment": "SYNTHETIC"})


def test_import_is_refused_and_points_at_the_module_that_owns_it(
    adapter: FixtureSourceAdapter,
) -> None:
    with pytest.raises(SourceCapabilityUnavailable, match="T-042"):
        adapter.import_records("some-file.csv")


def test_the_fixture_adapter_satisfies_the_source_contract(adapter: FixtureSourceAdapter) -> None:
    assert isinstance(adapter, SourceAdapter)


# --- criterion 2: every snapshot carries full §14.3 provenance --------------------------------


def test_every_captured_snapshot_has_complete_provenance(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    candidate = make_candidate(db_session)

    result = capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    assert result.captured >= 1
    for snapshot in result.snapshots:
        assert snapshot.source_type is not None
        assert snapshot.source_provider_id.startswith("SYNTHETIC-DOC-")
        assert snapshot.retrieved_at == NOW
        assert snapshot.supporting_excerpt_or_fact.strip()
        assert len(snapshot.content_hash) == 64
        assert snapshot.extraction_method is ExtractionMethod.STRUCTURED_FIELD
        assert isinstance(snapshot.source_quality, SourceQuality)
        assert isinstance(snapshot.license_and_retention_class, RetentionClass)
        assert snapshot.contains_personal_or_confidential_data in (True, False)


def test_the_content_hash_is_over_the_whole_source_not_the_excerpt(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    """A hash of the excerpt could not tell a reader that the underlying document changed."""
    candidate = make_candidate(db_session)
    document = json.loads(
        (DOCUMENTS / "alpha-microgrid-announcement.json").read_text(encoding="utf-8")
    )

    capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    snapshot = (
        db_session.execute(
            select(EvidenceSnapshot).where(
                EvidenceSnapshot.source_provider_id == "SYNTHETIC-DOC-alpha-microgrid"
            )
        )
        .scalars()
        .first()
    )
    assert snapshot.content_hash == content_hash(document["text"])
    assert snapshot.content_hash != content_hash(snapshot.supporting_excerpt_or_fact)


def test_the_privacy_flag_is_carried_from_the_document_not_defaulted(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    """§15.5 / `Q-019`: an unanswered classification must not become "contains nothing"."""
    candidate = make_candidate(db_session, domain="bravo.example.org")

    result = capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    assert result.captured == 1
    assert result.snapshots[0].contains_personal_or_confidential_data is True


def test_a_document_missing_its_privacy_flag_is_skipped_not_defaulted(
    adapter: FixtureSourceAdapter,
) -> None:
    documents = adapter.documents()

    assert "SYNTHETIC-DOC-malformed" not in {document.document_id for document in documents}
    assert any("malformed" in skipped.path for skipped in adapter.skipped)


def test_one_malformed_document_does_not_cost_the_others(
    adapter: FixtureSourceAdapter,
) -> None:
    """The same rule `T-042` applies to CSV rows: report and carry on."""
    documents = adapter.documents()

    assert len(documents) >= 3
    assert adapter.skipped


def test_an_oversized_document_is_refused_unread(tmp_path: Path) -> None:
    """§15.3's size limit, applied to the local equivalent of a response body."""
    oversized = tmp_path / "huge.json"
    oversized.write_text("x" * (MAX_DOCUMENT_BYTES + 1), encoding="utf-8")

    adapter = FixtureSourceAdapter(directory=tmp_path)
    documents = adapter.documents()

    assert documents == []
    assert adapter.skipped[0].reason == "larger than the document size limit"


def test_an_over_long_excerpt_is_skipped_rather_than_truncated(tmp_path: Path) -> None:
    """Truncation could drop the clause that justified the claim (`T-019`'s rule)."""
    (tmp_path / "long.json").write_text(
        json.dumps(
            {
                "document_id": "SYNTHETIC-DOC-long",
                "account_domain": "alpha.example.com",
                "contains_personal_or_confidential_data": False,
                "text": "SYNTHETIC source text.",
                "facts": [{"excerpt": "S" * (EXCERPT_MAX_CHARS + 1)}],
            }
        ),
        encoding="utf-8",
    )
    adapter = FixtureSourceAdapter(directory=tmp_path)

    facts = adapter.refresh(account_domain="alpha.example.com")

    assert facts == []
    assert adapter.skipped[0].reason == "excerpt exceeds the cap"


def test_capture_is_refused_before_the_eligibility_gate(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    """§8.3 puts step 4 before steps 5-6: researching a candidate hard rules refused would build
    a dossier on someone who must not be contacted."""
    candidate = make_candidate(db_session, state=CampaignCandidateState.IMPORTED)

    with pytest.raises(CaptureRefused, match="eligibility gate"):
        capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)


def test_capture_is_refused_for_an_ineligible_candidate(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    candidate = make_candidate(db_session, state=CampaignCandidateState.IMPORTED)
    transition(
        db_session,
        candidate,
        CampaignCandidateState.INELIGIBLE,
        actor=OPERATOR,
        reason="SYNTHETIC: refused by a hard rule",
    )

    with pytest.raises(CaptureRefused):
        capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)


# --- criterion 3: refresh writes a new snapshot, never mutates one -----------------------------


def test_a_changed_source_produces_a_second_snapshot_and_leaves_the_first(
    db_session: Session, tmp_path: Path
) -> None:
    """The §9.5 rule: a refresh is an addition. What an earlier run cited still says the same."""
    document = {
        "document_id": "SYNTHETIC-DOC-changing",
        "account_domain": "alpha.example.com",
        "contains_personal_or_confidential_data": False,
        "text": "SYNTHETIC source text, first version.",
        "facts": [{"excerpt": "SYNTHETIC: the first version of the fact."}],
    }
    path = tmp_path / "changing.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    adapter = FixtureSourceAdapter(directory=tmp_path)
    candidate = make_candidate(db_session)
    first = capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)
    first_id = first.snapshots[0].id
    first_hash = first.snapshots[0].content_hash

    document["text"] = "SYNTHETIC source text, second version."
    document["facts"] = [{"excerpt": "SYNTHETIC: the second version of the fact."}]
    path.write_text(json.dumps(document), encoding="utf-8")
    second = capture_evidence(
        db_session, candidate, adapter, actor=OPERATOR, at=NOW + timedelta(hours=1)
    )

    assert second.captured == 1
    assert second.snapshots[0].id != first_id
    surviving = db_session.get(EvidenceSnapshot, first_id)
    assert surviving is not None
    assert surviving.content_hash == first_hash
    assert surviving.supporting_excerpt_or_fact == "SYNTHETIC: the first version of the fact."


def test_recapturing_an_unchanged_source_stores_nothing_new(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    candidate = make_candidate(db_session)
    first = capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    second = capture_evidence(
        db_session, candidate, adapter, actor=OPERATOR, at=NOW + timedelta(hours=1)
    )

    assert second.captured == 0
    assert second.duplicates == first.captured
    assert (
        db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()
        == first.captured
    )


def test_the_database_refuses_an_update_to_a_stored_snapshot(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    """`T-019`'s immutability trigger — the reason capture has no update path to get wrong."""
    candidate = make_candidate(db_session)
    result = capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)
    snapshot = result.snapshots[0]

    snapshot.supporting_excerpt_or_fact = "SYNTHETIC: rewritten after the fact"

    with pytest.raises(Exception, match="immutable"):
        db_session.flush()


def test_captured_evidence_is_visible_to_the_reader_used_by_drafting(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    candidate = make_candidate(db_session)

    capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    assert current_evidence(db_session, candidate.id, at=NOW) != []


# --- criterion 4: document text is data, never instruction (§15.4) -----------------------------


def test_the_hostile_document_is_captured_as_ordinary_evidence(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    candidate = make_candidate(db_session)

    result = capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    hostile = [
        snapshot
        for snapshot in result.snapshots
        if snapshot.source_provider_id == "SYNTHETIC-DOC-alpha-hostile"
    ]
    assert len(hostile) == 1
    assert INJECTION in hostile[0].supporting_excerpt_or_fact
    # Stored exactly as written: not sanitized, not rewritten, not obeyed.
    assert hostile[0].supporting_excerpt_or_fact.startswith("SYNTHETIC:")


def test_the_hostile_document_changes_nothing_about_the_candidate(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    """It asks for approval, unsuppression, and a readiness change. It gets a row in a table."""
    candidate = make_candidate(db_session)
    state_before = candidate.state

    capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    assert candidate.state is state_before
    assert candidate.ineligible_reason is None


def test_its_classification_is_taken_from_the_document_metadata_not_its_prose(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    """The hostile text claims maintenance mode; the fields say low quality, internal only."""
    candidate = make_candidate(db_session)

    result = capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    hostile = next(
        snapshot
        for snapshot in result.snapshots
        if snapshot.source_provider_id == "SYNTHETIC-DOC-alpha-hostile"
    )
    assert hostile.source_quality is SourceQuality.LOW
    assert hostile.license_and_retention_class is RetentionClass.INTERNAL_ONLY


def test_the_audit_event_records_documents_and_counts_but_no_excerpt(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    """§15.5: the trail must not become where a hostile document's text is quoted."""
    candidate = make_candidate(db_session)

    capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "evidence_snapshot.captured")
    ).scalar_one()
    serialized = str(event.payload)
    assert INJECTION not in serialized
    assert "SYNTHETIC-DOC-alpha-hostile" in serialized
    assert event.payload["captured"] >= 1


def test_no_module_in_the_capture_path_branches_on_excerpt_text(
    adapter: FixtureSourceAdapter,
) -> None:
    """Nothing may read a document's content and decide something. The adapter's only interest in
    `text` is its hash and its length, and `capture.py` never inspects an excerpt at all."""
    capture_source = (RESEARCH_PACKAGE / "capture.py").read_text(encoding="utf-8")

    assert "fact.excerpt" in capture_source, "the excerpt is stored"
    for suspicious in ("in fact.excerpt", "fact.excerpt ==", "fact.excerpt.lower()", "eval("):
        assert suspicious not in capture_source


def test_documents_are_returned_in_a_stable_order(adapter: FixtureSourceAdapter) -> None:
    """Two runs over one directory must produce the same evidence in the same order."""
    first = [document.document_id for document in adapter.documents()]
    second = [document.document_id for document in adapter.documents()]

    assert first == second


def test_an_absent_directory_yields_nothing_rather_than_raising(tmp_path: Path) -> None:
    adapter = FixtureSourceAdapter(directory=tmp_path / "does-not-exist")

    assert adapter.documents() == []
    assert adapter.refresh(account_domain="alpha.example.com") == []


def test_a_domain_with_no_documents_captures_nothing(
    db_session: Session, adapter: FixtureSourceAdapter
) -> None:
    """ "Missing facts remain missing" (GP-02) — absence must not become an invented fact."""
    candidate = make_candidate(db_session, domain="zulu.example.com")

    result = capture_evidence(db_session, candidate, adapter, actor=OPERATOR, at=NOW)

    assert result.captured == 0
    assert current_evidence(db_session, candidate.id, at=NOW) == []
