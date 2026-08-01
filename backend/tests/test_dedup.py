"""Deterministic deduplication (T-043; §8.3 step 2, §19.2, §15.6, ADR-019).

The tests are organized around the two things that can go wrong, which are not symmetric:

* **Matching too little** leaves two records an operator merges later — recoverable.
* **Matching too much, or losing something in the merge**, is not. So most of this file is about
  what a merge must *not* destroy: a suppression that named the losing contact, evidence hanging
  off its candidates, or a contact point that was the only way to reach someone.

The duplicate cases come from `T-041`'s corpus, imported through `T-042`, so all three tasks are
exercised as one path rather than each against a fixture only it believes in.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, create_candidate
from app.campaigns.models import Campaign
from app.fixtures import PROSPECTS_CSV
from app.products_and_claims.models import Product
from app.prospects.dedup import (
    DuplicateMatch,
    MatchReason,
    NotMergeable,
    find_account,
    find_contact_match,
    merge_contacts,
)
from app.prospects.imports import import_csv
from app.prospects.models import Account, Contact, ContactPoint, ContactPointType
from app.prospects.normalize import normalize_person_name
from app.prospects.suppression import (
    Suppression,
    SuppressionScope,
    SuppressionSource,
    is_suppressed,
    record_suppression,
)
from app.research_and_evidence.models import (
    EvidenceSnapshot,
    ExtractionMethod,
    RetentionClass,
    SourceQuality,
    SourceType,
)
from tests.factories import NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-dedup-test")


def make_account(session: Session, domain: str = "alpha.example.com") -> Account:
    account = Account(domain=domain, name="SYNTHETIC-Account-Alpha", country_code="US")
    session.add(account)
    session.flush()
    return account


def make_contact(
    session: Session,
    account: Account,
    *,
    full_name: str = "SYNTHETIC Person Alpha",
    email: str | None = None,
    role_title: str | None = None,
) -> Contact:
    contact = Contact(account_id=account.id, full_name=full_name, role_title=role_title)
    session.add(contact)
    session.flush()
    if email:
        session.add(ContactPoint(contact_id=contact.id, type=ContactPointType.EMAIL, value=email))
        session.flush()
    return contact


def make_campaign(session: Session) -> Campaign:
    product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
    session.add(product)
    session.flush()
    campaign = Campaign(
        slug=f"synthetic-{uuid.uuid4().hex[:8]}",
        name="SYNTHETIC-Campaign",
        product_id=product.id,
    )
    session.add(campaign)
    session.flush()
    return campaign


# --- criterion 3: nothing probabilistic ------------------------------------------------------


def test_the_rule_set_is_exactly_two_deterministic_rules() -> None:
    """ADR-019: adding a rule is a decision someone records, not a threshold someone tunes."""
    assert {reason.value for reason in MatchReason} == {"exact_email", "domain_and_name"}


def test_name_normalization_only_folds_case_and_whitespace() -> None:
    """Anything cleverer merges people who are not the same person (ADR-019)."""
    assert normalize_person_name("  SYNTHETIC   Person  Alpha ") == "synthetic person alpha"
    assert normalize_person_name("Synthetic Person Alpha") == "synthetic person alpha"
    # Deliberately NOT equal: punctuation, ordering, and initials are left alone.
    assert normalize_person_name("Person, Synthetic") != normalize_person_name("Synthetic Person")
    assert normalize_person_name("SYNTHETIC P. Alpha") != normalize_person_name(
        "SYNTHETIC Person Alpha"
    )
    assert normalize_person_name("   ") == ""


def test_two_people_sharing_a_role_are_not_a_match(db_session: Session) -> None:
    """The rejected rule, asserted as a rule: same account, same title, different people."""
    account = make_account(db_session)
    make_contact(
        db_session, account, full_name="SYNTHETIC Person Alpha", role_title="SYNTHETIC Site Lead"
    )

    match = find_contact_match(
        db_session,
        account_id=account.id,
        full_name="SYNTHETIC Person Bravo",
        email="bravo.person@alpha.example.com",
    )

    assert match is None


def test_a_blank_name_never_matches_another_blank_name(db_session: Session) -> None:
    account = make_account(db_session)
    make_contact(db_session, account, full_name="   SYNTHETIC Person   ")

    assert find_contact_match(db_session, account_id=account.id, full_name="   ") is None


# --- the two rules, in priority order --------------------------------------------------------


def test_an_exact_address_match_wins_and_says_so(db_session: Session) -> None:
    account = make_account(db_session)
    existing = make_contact(
        db_session, account, full_name="SYNTHETIC Person Alpha", email="a.person@alpha.example.com"
    )

    match = find_contact_match(
        db_session,
        account_id=account.id,
        full_name="SYNTHETIC Someone Else",
        email="A.Person@Alpha.Example.COM",
    )

    assert match == DuplicateMatch(contact=existing, reason=MatchReason.EXACT_EMAIL)


def test_the_same_person_at_the_same_account_matches_by_name(db_session: Session) -> None:
    account = make_account(db_session)
    existing = make_contact(
        db_session, account, full_name="SYNTHETIC Person Alpha", email="a.person@alpha.example.com"
    )

    match = find_contact_match(
        db_session,
        account_id=account.id,
        full_name="  synthetic   person   alpha ",
        email="other.person@alpha.example.com",
    )

    assert match is not None
    assert match.contact.id == existing.id
    assert match.reason is MatchReason.DOMAIN_AND_NAME


def test_the_same_name_at_a_different_account_is_a_different_person(db_session: Session) -> None:
    first = make_account(db_session, "alpha.example.com")
    make_contact(db_session, first, full_name="SYNTHETIC Person Alpha")
    second = make_account(db_session, "bravo.example.org")

    assert (
        find_contact_match(db_session, account_id=second.id, full_name="SYNTHETIC Person Alpha")
        is None
    )


def test_a_stored_contact_does_not_match_itself(db_session: Session) -> None:
    account = make_account(db_session)
    contact = make_contact(db_session, account, email="a.person@alpha.example.com")

    match = find_contact_match(
        db_session,
        account_id=account.id,
        full_name=contact.full_name,
        email="a.person@alpha.example.com",
        exclude_contact_id=contact.id,
    )

    assert match is None


def test_account_lookup_is_exact_and_normalized(db_session: Session) -> None:
    account = make_account(db_session, "alpha.example.com")

    assert find_account(db_session, "https://WWW.Alpha.example.com/about") is not None
    assert find_account(db_session, "alpha.example.com") == account
    assert find_account(db_session, "notalpha.example.com") is None
    assert find_account(db_session, "not a domain") is None


# --- criterion 2: a merge destroys nothing ---------------------------------------------------


def test_a_suppression_naming_the_losing_contact_still_suppresses_after_the_merge(
    db_session: Session,
) -> None:
    """The safety case. `PERSON` suppressions hold an ID as text, so a merge could orphan one."""
    account = make_account(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(
        db_session, account, full_name="SYNTHETIC Person Alpha Dup", email="dup@alpha.example.com"
    )
    record_suppression(
        db_session,
        scope=SuppressionScope.PERSON,
        identity=str(loser.id),
        source=SuppressionSource.UNSUBSCRIBE,
        reason="SYNTHETIC opt-out",
        effective_at=NOW,
    )
    db_session.flush()

    merge_contacts(
        db_session,
        keep=keep,
        merge=loser,
        reason=MatchReason.DOMAIN_AND_NAME,
        actor=OPERATOR,
        now=NOW,
    )

    assert is_suppressed(db_session, contact_id=keep.id, at=NOW), (
        "the survivor must inherit the opt-out, or the merge would un-suppress a person"
    )


def test_the_original_suppression_row_is_never_deleted(db_session: Session) -> None:
    account = make_account(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(db_session, account, full_name="SYNTHETIC Person Alpha Dup")
    record_suppression(
        db_session,
        scope=SuppressionScope.PERSON,
        identity=str(loser.id),
        source=SuppressionSource.COMPLAINT,
        reason="SYNTHETIC complaint",
        effective_at=NOW,
    )
    db_session.flush()
    before = db_session.execute(select(func.count()).select_from(Suppression)).scalar_one()

    merge_contacts(
        db_session, keep=keep, merge=loser, reason=MatchReason.DOMAIN_AND_NAME, actor=OPERATOR
    )

    after = db_session.execute(select(func.count()).select_from(Suppression)).scalar_one()
    assert after == before + 1, "the carried suppression is added; the original stays"
    assert (
        db_session.execute(
            select(Suppression).where(Suppression.identity == str(loser.id))
        ).scalar_one()
        is not None
    )


def test_an_email_suppression_survives_because_the_address_survives(db_session: Session) -> None:
    account = make_account(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(
        db_session,
        account,
        full_name="SYNTHETIC Person Alpha Dup",
        email="dup.person@alpha.example.com",
    )
    record_suppression(
        db_session,
        scope=SuppressionScope.EMAIL,
        identity="dup.person@alpha.example.com",
        source=SuppressionSource.BOUNCE,
        reason="SYNTHETIC hard bounce",
        effective_at=NOW,
    )
    db_session.flush()

    merge_contacts(
        db_session, keep=keep, merge=loser, reason=MatchReason.DOMAIN_AND_NAME, actor=OPERATOR
    )

    assert is_suppressed(db_session, email="dup.person@alpha.example.com")


def test_a_merge_preserves_every_evidence_snapshot(db_session: Session) -> None:
    """Evidence hangs off candidates, and candidates never move: `(campaign, account, contact)`
    is immutable by trigger (§8.1). So the losing contact stays alive to hold them."""
    account = make_account(db_session)
    campaign = make_campaign(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(db_session, account, full_name="SYNTHETIC Person Alpha Dup")
    candidate = create_candidate(
        db_session,
        campaign_id=campaign.id,
        account_id=account.id,
        contact_id=loser.id,
        actor=OPERATOR,
    )
    db_session.add(
        EvidenceSnapshot(
            candidate_id=candidate.id,
            source_type=SourceType.SYNTHETIC_FIXTURE,
            retrieved_at=NOW,
            supporting_excerpt_or_fact="SYNTHETIC evidence",
            content_hash="b" * 64,
            extraction_method=ExtractionMethod.MANUAL,
            source_quality=SourceQuality.MEDIUM,
            license_and_retention_class=RetentionClass.PUBLIC_UNRESTRICTED,
            contains_personal_or_confidential_data=False,
        )
    )
    db_session.flush()
    before = db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()

    result = merge_contacts(
        db_session, keep=keep, merge=loser, reason=MatchReason.DOMAIN_AND_NAME, actor=OPERATOR
    )

    assert result.stranded_candidates == [candidate.id]
    assert not result.merged_contact_removed
    assert (
        db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()
        == before
    )
    surviving_candidate = db_session.get(CampaignCandidate, candidate.id)
    assert surviving_candidate is not None
    assert surviving_candidate.contact_id == loser.id, "membership identity is immutable (§8.1)"
    assert db_session.get(Contact, loser.id) is not None, (
        "deleting the losing contact would cascade its candidate's evidence away"
    )


def test_a_contact_point_only_the_loser_had_moves_to_the_survivor(db_session: Session) -> None:
    account = make_account(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(
        db_session,
        account,
        full_name="SYNTHETIC Person Alpha Dup",
        email="only.here@alpha.example.com",
    )

    result = merge_contacts(
        db_session, keep=keep, merge=loser, reason=MatchReason.DOMAIN_AND_NAME, actor=OPERATOR
    )

    assert len(result.moved_contact_points) == 1
    survivor_values = {
        point.value
        for point in db_session.execute(
            select(ContactPoint).where(ContactPoint.contact_id == keep.id)
        )
        .scalars()
        .all()
    }
    assert survivor_values == {"keep.person@alpha.example.com", "only.here@alpha.example.com"}


def test_the_merge_never_attempts_to_repoint_a_candidate(db_session: Session) -> None:
    """The trigger would refuse it. This asserts the merge does not try — a `RestrictViolation`
    mid-merge would abort the transaction and lose the carried suppressions with it."""
    account = make_account(db_session)
    campaign = make_campaign(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(db_session, account, full_name="SYNTHETIC Person Alpha Dup")
    stranded = create_candidate(
        db_session,
        campaign_id=campaign.id,
        account_id=account.id,
        contact_id=loser.id,
        actor=OPERATOR,
    )

    result = merge_contacts(
        db_session, keep=keep, merge=loser, reason=MatchReason.DOMAIN_AND_NAME, actor=OPERATOR
    )

    assert result.stranded_candidates == [stranded.id]
    assert not result.merged_contact_removed
    assert db_session.get(CampaignCandidate, stranded.id) is not None
    assert db_session.get(Contact, loser.id) is not None


def test_a_contact_with_no_candidates_is_removed_by_the_merge(db_session: Session) -> None:
    """The ordinary case: a freshly imported duplicate nothing else references yet."""
    account = make_account(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(db_session, account, full_name="SYNTHETIC Person Alpha Dup")

    result = merge_contacts(
        db_session, keep=keep, merge=loser, reason=MatchReason.DOMAIN_AND_NAME, actor=OPERATOR
    )

    assert result.merged_contact_removed
    assert result.stranded_candidates == []
    assert db_session.get(Contact, loser.id) is None


def test_merging_across_accounts_is_refused(db_session: Session) -> None:
    first = make_account(db_session, "alpha.example.com")
    second = make_account(db_session, "bravo.example.org")
    keep = make_contact(db_session, first)
    other = make_contact(db_session, second)

    with pytest.raises(NotMergeable, match="different accounts"):
        merge_contacts(
            db_session, keep=keep, merge=other, reason=MatchReason.EXACT_EMAIL, actor=OPERATOR
        )


def test_merging_a_contact_into_itself_is_refused(db_session: Session) -> None:
    account = make_account(db_session)
    contact = make_contact(db_session, account)

    with pytest.raises(NotMergeable, match="into itself"):
        merge_contacts(
            db_session,
            keep=contact,
            merge=contact,
            reason=MatchReason.EXACT_EMAIL,
            actor=OPERATOR,
        )


def test_the_merge_is_audited_with_its_match_reason_and_no_contact_details(
    db_session: Session,
) -> None:
    """§15.5: identifiers and counts, never the name or the address that was merged."""
    account = make_account(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(
        db_session,
        account,
        full_name="SYNTHETIC Person Alpha Dup",
        email="dup.person@alpha.example.com",
    )

    merge_contacts(
        db_session, keep=keep, merge=loser, reason=MatchReason.DOMAIN_AND_NAME, actor=OPERATOR
    )

    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "contact.merged")
    ).scalar_one()
    serialized = str(event.payload)
    assert event.payload["match_reason"] == "domain_and_name"
    assert event.policy_decision == "dedup:domain_and_name"
    assert "SYNTHETIC Person Alpha Dup" not in serialized
    assert "dup.person@alpha.example.com" not in serialized


# --- criterion 1: the T-041 duplicate edge cases resolve to one record each -------------------


def test_the_corpus_duplicate_cases_each_resolve_to_one_contact(db_session: Session) -> None:
    """The end-to-end case: `T-041`'s corpus, imported by `T-042`, deduplicated here."""
    import_csv(
        db_session,
        content=PROSPECTS_CSV.read_bytes(),
        source_name=PROSPECTS_CSV.name,
        actor=OPERATOR,
    )

    delta = db_session.execute(
        select(Account).where(Account.domain == "delta.example.com")
    ).scalar_one()
    contacts = (
        db_session.execute(select(Contact).where(Contact.account_id == delta.id)).scalars().all()
    )
    assert len(contacts) == 1, (
        "`duplicate-domain-name` shares one name, so import already lands on one contact; "
        "dedup must confirm rather than split it"
    )

    # The `duplicate-email-case` rows: two spellings, one mailbox, therefore one contact.
    charlie = db_session.execute(
        select(Account).where(Account.domain == "charlie.example.com")
    ).scalar_one()
    charlie_contacts = (
        db_session.execute(select(Contact).where(Contact.account_id == charlie.id)).scalars().all()
    )
    assert len(charlie_contacts) == 1

    match = find_contact_match(
        db_session,
        account_id=charlie.id,
        full_name="SYNTHETIC Person Charlie",
        email="Charlie.Person@Charlie.Example.com",
        exclude_contact_id=None,
    )
    assert match is not None
    assert match.reason is MatchReason.EXACT_EMAIL


def test_a_second_import_under_a_new_address_is_matched_and_merged(db_session: Session) -> None:
    """The duplicate an exact-key import cannot catch: same person, new address, new row."""
    import_csv(
        db_session,
        content=PROSPECTS_CSV.read_bytes(),
        source_name=PROSPECTS_CSV.name,
        actor=OPERATOR,
    )
    alpha = db_session.execute(
        select(Account).where(Account.domain == "alpha.example.com")
    ).scalar_one()
    later = import_csv(
        db_session,
        content=(
            b"account_domain,account_name,country_code,full_name,role_title,contact_type,"
            b"contact_value\nalpha.example.com,SYNTHETIC-Account-Alpha,US,"
            b"synthetic  person  alpha,SYNTHETIC Lead,email,alpha.second@alpha.example.com\n"
        ),
        source_name="later.csv",
        actor=OPERATOR,
    )
    assert not later.rejections

    duplicates = (
        db_session.execute(select(Contact).where(Contact.account_id == alpha.id)).scalars().all()
    )
    assert len(duplicates) == 2, "import matches on the exact name only, so this is two rows"

    newer = next(c for c in duplicates if c.full_name == "synthetic  person  alpha")
    older = next(c for c in duplicates if c.id != newer.id)
    match = find_contact_match(
        db_session,
        account_id=alpha.id,
        full_name=newer.full_name,
        exclude_contact_id=newer.id,
    )
    assert match is not None
    assert match.reason is MatchReason.DOMAIN_AND_NAME

    result = merge_contacts(
        db_session, keep=older, merge=newer, reason=match.reason, actor=OPERATOR
    )

    assert result.reason is MatchReason.DOMAIN_AND_NAME
    remaining = (
        db_session.execute(select(Contact).where(Contact.account_id == alpha.id)).scalars().all()
    )
    assert len(remaining) == 1
    assert {
        point.value
        for point in db_session.execute(
            select(ContactPoint).where(ContactPoint.contact_id == older.id)
        )
        .scalars()
        .all()
    } == {"alpha.person@alpha.example.com", "alpha.second@alpha.example.com"}


def test_a_duplicate_address_row_is_dropped_rather_than_duplicated(db_session: Session) -> None:
    """`(type, value)` is globally unique, so the survivor keeps one copy and loses nothing."""
    account = make_account(db_session)
    keep = make_contact(db_session, account, email="shared.person@alpha.example.com")
    loser = make_contact(db_session, account, full_name="SYNTHETIC Person Alpha Dup")
    db_session.add(
        ContactPoint(
            contact_id=loser.id, type=ContactPointType.PHONE, value="+SYNTHETIC-PHONE-ALPHA"
        )
    )
    db_session.flush()

    result = merge_contacts(
        db_session, keep=keep, merge=loser, reason=MatchReason.DOMAIN_AND_NAME, actor=OPERATOR
    )

    assert len(result.moved_contact_points) == 1
    assert result.dropped_duplicate_points == []
    assert db_session.execute(select(func.count()).select_from(ContactPoint)).scalar_one() == 2


def test_suppression_carried_forward_keeps_the_earlier_effective_time(
    db_session: Session,
) -> None:
    """A carried suppression must not start later than the one it replaces."""
    account = make_account(db_session)
    keep = make_contact(db_session, account, email="keep.person@alpha.example.com")
    loser = make_contact(db_session, account, full_name="SYNTHETIC Person Alpha Dup")
    earlier = NOW - timedelta(days=2)
    record_suppression(
        db_session,
        scope=SuppressionScope.PERSON,
        identity=str(loser.id),
        source=SuppressionSource.UNSUBSCRIBE,
        reason="SYNTHETIC opt-out",
        effective_at=earlier,
    )
    db_session.flush()

    merge_contacts(
        db_session,
        keep=keep,
        merge=loser,
        reason=MatchReason.DOMAIN_AND_NAME,
        actor=OPERATOR,
        now=datetime.now(UTC),
    )

    carried = db_session.execute(
        select(Suppression).where(
            Suppression.scope == SuppressionScope.PERSON, Suppression.identity == str(keep.id)
        )
    ).scalar_one()
    assert carried.effective_at == earlier
    assert carried.source is SuppressionSource.UNSUBSCRIBE
