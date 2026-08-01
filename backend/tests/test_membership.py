"""Campaign membership creation (T-044; specification §8.1, §8.3 step 3, §17.6).

The §8.1 decision under test is that **two campaigns mean two memberships**, and the way that
claim fails is not by producing the wrong count on the first pass — it is by the two records
turning out to share something. So the dual-relevance test moves one candidate's state and
asserts the other did not follow, rather than only counting rows.

The end-to-end case runs the whole identity chain built so far: `T-040`'s seeded campaigns,
`T-041`'s corpus, `T-042`'s importer, and this module reading the corpus's own `campaigns`
column.
"""

import csv
import io
import uuid

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, transition
from app.campaigns.membership import create_memberships, find_membership
from app.campaigns.models import Campaign
from app.core.lifecycles import CampaignCandidateState
from app.core.settings import AppEnv, Settings
from app.fixtures import PROSPECTS_CSV
from app.fixtures.synthetic import seed_synthetic
from app.products_and_claims.models import Product
from app.prospects.imports import import_csv
from app.prospects.models import Account, Contact
from app.prospects.normalize import normalize_domain

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
TEST_SETTINGS = Settings(app_env=AppEnv.TEST)

SODIUM = "synthetic-sodium-battery"
CHARGING = "synthetic-dc-fast-charging"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-membership-test")


def make_campaign(session: Session, slug: str, *, paused: bool = False) -> Campaign:
    product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
    session.add(product)
    session.flush()
    campaign = Campaign(slug=slug, name=f"SYNTHETIC-{slug}", product_id=product.id, paused=paused)
    session.add(campaign)
    session.flush()
    return campaign


def make_prospect(session: Session, domain: str = "juliett.example.com") -> tuple[Account, Contact]:
    account = Account(domain=domain, name="SYNTHETIC-Account-Juliett", country_code="US")
    session.add(account)
    session.flush()
    contact = Contact(account_id=account.id, full_name="SYNTHETIC Person Juliett")
    session.add(contact)
    session.flush()
    return account, contact


# --- criterion 1: two campaigns, two independent memberships ---------------------------------


def test_the_dual_relevance_account_produces_exactly_two_candidates(db_session: Session) -> None:
    make_campaign(db_session, SODIUM)
    make_campaign(db_session, CHARGING)
    account, contact = make_prospect(db_session)

    result = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM, CHARGING],
        actor=OPERATOR,
    )

    assert len(result.created) == 2
    campaigns = {
        db_session.get(CampaignCandidate, candidate_id).campaign_id
        for candidate_id in result.created
    }
    assert len(campaigns) == 2, "two memberships must name two different campaigns"


def test_the_two_memberships_have_genuinely_independent_state(db_session: Session) -> None:
    """The §8.1 claim that matters: one review decision must not become the other's."""
    make_campaign(db_session, SODIUM)
    make_campaign(db_session, CHARGING)
    account, contact = make_prospect(db_session)
    result = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM, CHARGING],
        actor=OPERATOR,
    )
    first, second = (db_session.get(CampaignCandidate, cid) for cid in result.created)

    transition(db_session, first, CampaignCandidateState.INELIGIBLE, actor=OPERATOR, reason="test")

    assert first.state is CampaignCandidateState.INELIGIBLE
    assert second.state is CampaignCandidateState.IMPORTED, (
        "a decision in one campaign must not move the other campaign's candidate"
    )


def test_the_same_contact_in_one_campaign_is_one_membership(db_session: Session) -> None:
    """The other half of §8.1: two campaigns split, one campaign does not."""
    make_campaign(db_session, SODIUM)
    account, contact = make_prospect(db_session)

    result = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM, SODIUM],
        actor=OPERATOR,
    )

    assert len(result.created) == 1
    assert db_session.execute(select(func.count()).select_from(CampaignCandidate)).scalar_one() == 1


# --- criterion 2: re-running creates no duplicates -------------------------------------------


def test_rerunning_creates_no_duplicates(db_session: Session) -> None:
    make_campaign(db_session, SODIUM)
    make_campaign(db_session, CHARGING)
    account, contact = make_prospect(db_session)
    first = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM, CHARGING],
        actor=OPERATOR,
    )

    second = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM, CHARGING],
        actor=OPERATOR,
    )

    assert second.created == []
    assert sorted(second.existing) == sorted(first.created)
    assert db_session.execute(select(func.count()).select_from(CampaignCandidate)).scalar_one() == 2


def test_rerunning_does_not_reset_a_candidate_that_has_moved_on(db_session: Session) -> None:
    """Finding an existing membership must return it untouched, not re-import it."""
    make_campaign(db_session, SODIUM)
    account, contact = make_prospect(db_session)
    created = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )
    candidate = db_session.get(CampaignCandidate, created.created[0])
    transition(db_session, candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR)

    create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )

    assert candidate.state is CampaignCandidateState.ELIGIBLE


def test_an_account_level_membership_is_matched_on_its_null_contact(db_session: Session) -> None:
    """`NULLS NOT DISTINCT` (T-018): two account-level candidates would both be "the" one."""
    make_campaign(db_session, SODIUM)
    account, _ = make_prospect(db_session)
    first = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=None,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )

    second = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=None,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )

    assert second.created == []
    assert second.existing == first.created
    assert (
        find_membership(
            db_session,
            campaign_id=db_session.get(CampaignCandidate, first.created[0]).campaign_id,
            account_id=account.id,
            contact_id=None,
        )
        is not None
    )


def test_an_account_level_membership_is_not_the_contact_level_one(db_session: Session) -> None:
    make_campaign(db_session, SODIUM)
    account, contact = make_prospect(db_session)
    create_memberships(
        db_session,
        account_id=account.id,
        contact_id=None,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )

    with_contact = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )

    assert len(with_contact.created) == 1
    assert db_session.execute(select(func.count()).select_from(CampaignCandidate)).scalar_one() == 2


# --- criterion 3: every creation is audited, naming the campaign -----------------------------


def test_each_creation_writes_an_audit_event_naming_the_campaign(db_session: Session) -> None:
    sodium = make_campaign(db_session, SODIUM)
    charging = make_campaign(db_session, CHARGING)
    account, contact = make_prospect(db_session)

    create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM, CHARGING],
        actor=OPERATOR,
    )

    events = (
        db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "campaign_candidate.created")
        )
        .scalars()
        .all()
    )
    assert len(events) == 2
    assert {event.payload["campaign_id"] for event in events} == {
        str(sodium.id),
        str(charging.id),
    }
    assert all(event.to_state == CampaignCandidateState.IMPORTED.value for event in events)


def test_a_reused_membership_writes_no_second_creation_event(db_session: Session) -> None:
    make_campaign(db_session, SODIUM)
    account, contact = make_prospect(db_session)
    for _ in range(2):
        create_memberships(
            db_session,
            account_id=account.id,
            contact_id=contact.id,
            campaign_slugs=[SODIUM],
            actor=OPERATOR,
        )

    events = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "campaign_candidate.created")
    ).scalar_one()

    assert events == 1, "an audit trail that logs a creation that did not happen is not evidence"


# --- fail-closed handling: paused campaigns and unknown slugs --------------------------------


def test_a_paused_campaign_receives_no_new_membership(db_session: Session) -> None:
    """§17.6: pausing stops new work. A campaign quietly filling up is not paused."""
    paused = make_campaign(db_session, SODIUM, paused=True)
    account, contact = make_prospect(db_session)

    result = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )

    assert result.created == []
    assert result.skipped_paused == [paused.id]
    assert db_session.execute(select(func.count()).select_from(CampaignCandidate)).scalar_one() == 0


def test_pausing_a_campaign_does_not_hide_the_membership_already_in_it(
    db_session: Session,
) -> None:
    campaign = make_campaign(db_session, SODIUM)
    account, contact = make_prospect(db_session)
    first = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )
    campaign.paused = True
    db_session.flush()

    again = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM],
        actor=OPERATOR,
    )

    assert again.existing == first.created
    assert again.skipped_paused == []


def test_an_unknown_slug_is_reported_and_the_others_still_land(db_session: Session) -> None:
    make_campaign(db_session, SODIUM)
    account, contact = make_prospect(db_session)

    result = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM, "synthetic-campaign-that-does-not-exist"],
        actor=OPERATOR,
    )

    assert result.unknown_slugs == ["synthetic-campaign-that-does-not-exist"]
    assert len(result.created) == 1


def test_a_blank_slug_is_ignored_rather_than_reported(db_session: Session) -> None:
    """An empty `campaigns` cell means "no campaign named", not "a campaign called ''"."""
    account, contact = make_prospect(db_session)

    result = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=["", "   "],
        actor=OPERATOR,
    )

    assert result == type(result)()


# --- the whole identity chain: T-040 + T-041 + T-042 + this ----------------------------------


def activate_seeded_campaigns(session: Session) -> None:
    """Seeded campaigns start paused (T-015/T-040); starting them is a deliberate act."""
    for campaign in session.execute(select(Campaign)).scalars().all():
        campaign.paused = False
    session.flush()


def test_the_corpus_both_campaigns_account_gets_two_memberships_per_contact(
    db_session: Session,
) -> None:
    seed_synthetic(db_session, settings=TEST_SETTINGS)
    activate_seeded_campaigns(db_session)
    import_csv(
        db_session,
        content=PROSPECTS_CSV.read_bytes(),
        source_name=PROSPECTS_CSV.name,
        actor=OPERATOR,
    )

    rows = list(csv.DictReader(io.StringIO(PROSPECTS_CSV.read_text(encoding="utf-8"))))
    for row in rows:
        # Resolve through the same normalizer the importer used, so `www.Delta.example.com`
        # finds the account its sibling row created rather than looking like a missing one.
        account = db_session.execute(
            select(Account).where(Account.domain == normalize_domain(row["account_domain"]))
        ).scalar_one()
        contact = db_session.execute(
            select(Contact).where(
                Contact.account_id == account.id, Contact.full_name == row["full_name"]
            )
        ).scalar_one_or_none()
        if contact is None:
            continue
        result = create_memberships(
            db_session,
            account_id=account.id,
            contact_id=contact.id,
            campaign_slugs=row["campaigns"].split("|"),
            actor=OPERATOR,
        )
        if row["case_label"] == "both-campaigns":
            assert len(result.candidate_ids) == 2, (
                "the dual-relevance rows must each hold two memberships (§8.1)"
            )

    juliett = db_session.execute(
        select(Account).where(Account.domain == "juliett.example.com")
    ).scalar_one()
    juliett_candidates = (
        db_session.execute(
            select(CampaignCandidate).where(CampaignCandidate.account_id == juliett.id)
        )
        .scalars()
        .all()
    )
    assert len(juliett_candidates) == 4, "two contacts x two campaigns"
    assert len({candidate.contact_id for candidate in juliett_candidates}) == 2
    assert len({candidate.campaign_id for candidate in juliett_candidates}) == 2


def test_no_membership_is_created_while_the_seeded_campaigns_are_still_paused(
    db_session: Session,
) -> None:
    """The shipped default: a seeded world does no work until someone starts a campaign."""
    seed_synthetic(db_session, settings=TEST_SETTINGS)
    account, contact = make_prospect(db_session)

    result = create_memberships(
        db_session,
        account_id=account.id,
        contact_id=contact.id,
        campaign_slugs=[SODIUM, CHARGING],
        actor=OPERATOR,
    )

    assert result.created == []
    assert len(result.skipped_paused) == 2
