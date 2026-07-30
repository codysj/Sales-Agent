"""Campaign membership is the unit of qualification (T-018; §8.1, §8.2, §14.2, ADR-015).

The property under test: the same account and contact evaluated for two campaigns are **two
candidates with independent states**, not one record carrying two opinions. That is what makes it
possible to approve someone for DC fast charging and reject them for sodium batteries without the
two decisions interfering.
"""

import uuid

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, create_candidate, transition
from app.campaigns.models import Campaign
from app.core.lifecycles import (
    CampaignCandidateState,
    CrossLifecycleTransition,
    IllegalTransition,
    JobState,
)
from app.products_and_claims.models import Product
from app.prospects.models import Account, Contact

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-candidate-test")


@pytest.fixture
def product(db_session: Session) -> Product:
    item = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
    db_session.add(item)
    db_session.flush()
    return item


@pytest.fixture
def account(db_session: Session) -> Account:
    item = Account(domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account")
    db_session.add(item)
    db_session.flush()
    return item


@pytest.fixture
def contact(db_session: Session, account: Account) -> Contact:
    item = Contact(account_id=account.id, full_name="SYNTHETIC Person")
    db_session.add(item)
    db_session.flush()
    return item


def make_campaign(db_session: Session, product: Product, label: str) -> Campaign:
    campaign = Campaign(
        slug=f"synthetic-{label}-{uuid.uuid4().hex[:8]}",
        name=f"SYNTHETIC-{label}",
        product_id=product.id,
    )
    db_session.add(campaign)
    db_session.flush()
    return campaign


def make_candidate(
    db_session: Session, campaign: Campaign, account: Account, contact: Contact | None
) -> CampaignCandidate:
    return create_candidate(
        db_session,
        campaign_id=campaign.id,
        account_id=account.id,
        contact_id=contact.id if contact else None,
        actor=OPERATOR,
    )


# --- identity uniqueness (criterion 1) -----------------------------------------------------


def test_a_duplicate_membership_is_rejected_by_the_database(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    campaign = make_campaign(db_session, product, "dup")
    make_candidate(db_session, campaign, account, contact)

    with pytest.raises(IntegrityError) as exc:
        make_candidate(db_session, campaign, account, contact)

    assert "uq_campaign_candidate_identity" in str(exc.value)


def test_two_account_only_candidates_also_collide(
    db_session: Session, product: Product, account: Account
) -> None:
    """`NULLS NOT DISTINCT`: without it, NULL never equals NULL and both rows would be accepted."""
    campaign = make_campaign(db_session, product, "nullcontact")
    make_candidate(db_session, campaign, account, None)

    with pytest.raises(IntegrityError) as exc:
        make_candidate(db_session, campaign, account, None)

    assert "contact_id)=" in str(exc.value), "the NULL contact must participate in the key"


def test_the_identity_triple_cannot_be_repointed(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    """Repointing would silently reassign every decision already recorded against it."""
    first = make_campaign(db_session, product, "origin")
    second = make_campaign(db_session, product, "target")
    candidate = make_candidate(db_session, first, account, contact)

    candidate.campaign_id = second.id

    with pytest.raises(DBAPIError) as exc:
        db_session.flush()

    assert "immutable" in str(exc.value)


# --- independence across campaigns (criterion 2) --------------------------------------------


def test_one_person_in_two_campaigns_is_two_candidates(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    sodium = make_campaign(db_session, product, "sodium")
    charging = make_campaign(db_session, product, "charging")

    first = make_candidate(db_session, sodium, account, contact)
    second = make_candidate(db_session, charging, account, contact)
    db_session.flush()

    assert first.id != second.id
    assert first.state is second.state is CampaignCandidateState.IMPORTED


def test_the_two_candidates_move_independently(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    """Approved for one campaign, rejected for the other — §8.1's whole point."""
    sodium = make_campaign(db_session, product, "sodium2")
    charging = make_campaign(db_session, product, "charging2")
    approved = make_candidate(db_session, sodium, account, contact)
    rejected = make_candidate(db_session, charging, account, contact)

    for state in (
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
        CampaignCandidateState.REVIEW_PENDING,
        CampaignCandidateState.APPROVED,
    ):
        transition(db_session, approved, state, actor=OPERATOR)

    transition(
        db_session,
        rejected,
        CampaignCandidateState.INELIGIBLE,
        actor=OPERATOR,
        reason="SYNTHETIC: out of scope for this campaign",
    )

    assert approved.state is CampaignCandidateState.APPROVED
    assert rejected.state is CampaignCandidateState.INELIGIBLE
    assert rejected.ineligible_reason is not None


def test_deleting_one_campaign_leaves_the_other_candidate(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    sodium = make_campaign(db_session, product, "sodium3")
    charging = make_campaign(db_session, product, "charging3")
    make_candidate(db_session, sodium, account, contact)
    survivor = make_candidate(db_session, charging, account, contact)
    db_session.flush()

    db_session.delete(sodium)
    db_session.flush()

    assert db_session.query(CampaignCandidate).filter_by(id=survivor.id).one_or_none() is not None


# --- lifecycle enforcement -------------------------------------------------------------------


def test_a_legal_transition_is_allowed(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    campaign = make_campaign(db_session, product, "legal")
    candidate = make_candidate(db_session, campaign, account, contact)

    transition(db_session, candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR)

    assert candidate.state is CampaignCandidateState.ELIGIBLE


def test_an_illegal_transition_is_refused(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    """`imported -> approved` skips eligibility, research, and review."""
    campaign = make_campaign(db_session, product, "illegal")
    candidate = make_candidate(db_session, campaign, account, contact)

    with pytest.raises(IllegalTransition):
        transition(db_session, candidate, CampaignCandidateState.APPROVED, actor=OPERATOR)

    assert candidate.state is CampaignCandidateState.IMPORTED


def test_a_cross_lifecycle_transition_is_refused(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    """ADR-015: a candidate cannot be moved into a job's state."""
    campaign = make_campaign(db_session, product, "cross")
    candidate = make_candidate(db_session, campaign, account, contact)

    with pytest.raises(CrossLifecycleTransition):
        transition(db_session, candidate, JobState.LEASED, actor=OPERATOR)  # type: ignore[arg-type]


def test_a_rejected_candidate_cannot_be_revived(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    campaign = make_campaign(db_session, product, "revive")
    candidate = make_candidate(db_session, campaign, account, contact)
    for state in (
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
        CampaignCandidateState.REVIEW_PENDING,
        CampaignCandidateState.REJECTED,
    ):
        transition(db_session, candidate, state, actor=OPERATOR)

    with pytest.raises(IllegalTransition):
        transition(db_session, candidate, CampaignCandidateState.APPROVED, actor=OPERATOR)


def test_marking_ineligible_requires_a_reason(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    """A rejection that cannot be explained is not reviewable (§10.1)."""
    campaign = make_campaign(db_session, product, "noreason")
    candidate = make_candidate(db_session, campaign, account, contact)

    with pytest.raises(ValueError, match="reason"):
        transition(db_session, candidate, CampaignCandidateState.INELIGIBLE, actor=OPERATOR)


def test_the_database_also_refuses_ineligible_without_a_reason(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    """Belt and braces: the check constraint holds even if the service is bypassed."""
    campaign = make_campaign(db_session, product, "dbreason")
    candidate = make_candidate(db_session, campaign, account, contact)
    db_session.flush()

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE campaign_candidate SET state = 'INELIGIBLE' WHERE id = :id"),
            {"id": candidate.id},
        )


# --- audit (criterion 3) ----------------------------------------------------------------------


def _events(db_session: Session, candidate: CampaignCandidate) -> list[AuditEvent]:
    return (
        db_session.query(AuditEvent)
        .filter_by(entity_type="campaign_candidate", entity_id=str(candidate.id))
        .order_by(AuditEvent.occurred_at)
        .all()
    )


def test_creation_is_audited(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    campaign = make_campaign(db_session, product, "auditcreate")
    candidate = make_candidate(db_session, campaign, account, contact)
    db_session.flush()

    events = _events(db_session, candidate)

    assert [e.action for e in events] == ["campaign_candidate.created"]
    assert events[0].to_state == "imported"
    assert events[0].actor_id == "operator-1"


def test_every_transition_records_both_ends(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    campaign = make_campaign(db_session, product, "auditmove")
    candidate = make_candidate(db_session, campaign, account, contact)

    transition(db_session, candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR)
    transition(db_session, candidate, CampaignCandidateState.RESEARCH_PENDING, actor=OPERATOR)
    db_session.flush()

    moves = [e for e in _events(db_session, candidate) if e.from_state is not None]

    assert [(e.from_state, e.to_state) for e in moves] == [
        ("imported", "eligible"),
        ("eligible", "research_pending"),
    ]


def test_a_refused_transition_writes_no_audit_event(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    """The trail must not record a change that did not happen (§3.5)."""
    campaign = make_campaign(db_session, product, "auditrefuse")
    candidate = make_candidate(db_session, campaign, account, contact)
    db_session.flush()
    before = len(_events(db_session, candidate))

    with pytest.raises(IllegalTransition):
        transition(db_session, candidate, CampaignCandidateState.APPROVED, actor=OPERATOR)

    assert len(_events(db_session, candidate)) == before


def test_the_correlation_id_flows_into_the_trail(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    campaign = make_campaign(db_session, product, "auditcorr")
    candidate = make_candidate(db_session, campaign, account, contact)
    db_session.flush()

    assert _events(db_session, candidate)[0].correlation_id == "corr-candidate-test"


def test_a_policy_decision_is_recorded_when_supplied(
    db_session: Session, product: Product, account: Account, contact: Contact
) -> None:
    campaign = make_campaign(db_session, product, "auditpolicy")
    candidate = make_candidate(db_session, campaign, account, contact)

    transition(
        db_session,
        candidate,
        CampaignCandidateState.ELIGIBLE,
        actor=OPERATOR,
        policy_decision="passed all hard eligibility rules",
    )
    db_session.flush()

    moves = [e for e in _events(db_session, candidate) if e.from_state is not None]

    assert moves[0].policy_decision == "passed all hard eligibility rules"
