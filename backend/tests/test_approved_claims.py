"""Approved claims fail closed (T-014; §10.5, §14.4, §15.7, GP-12).

The safety property under test: a claim set either resolves completely and validly, or it fails.
There is no path that quietly returns fewer claims than were approved — that is how an approved
message becomes an unapproved one.

Every claim here is synthetic. Real approved claims stay `Q-017`.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.campaigns.models import Campaign
from app.products_and_claims.claim_models import (
    ApprovedClaim,
    ApprovedClaimCampaign,
    ApprovedClaimSet,
    ApprovedClaimSetMember,
)
from app.products_and_claims.claims import (
    InvalidClaimInSet,
    NoCurrentClaimSet,
    claim_is_allowed_for_campaign,
    get_claim_set,
    get_valid_claim_set,
    publish_claim_set,
    valid_claims_for_campaign,
)
from app.products_and_claims.models import Product
from tests.factories import CLAIM_OWNER, NOW, OWNER_ONE, OWNER_TWO

EARLIER = NOW - timedelta(days=30)
LATER = NOW + timedelta(days=30)


@pytest.fixture
def product(db_session: Session) -> Product:
    item = Product(slug=f"synthetic-product-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
    db_session.add(item)
    db_session.flush()
    return item


@pytest.fixture
def campaign(db_session: Session, product: Product) -> Campaign:
    item = Campaign(
        slug=f"synthetic-campaign-{uuid.uuid4().hex[:8]}",
        name="SYNTHETIC-Campaign",
        product_id=product.id,
    )
    db_session.add(item)
    db_session.flush()
    return item


def make_claim(
    db_session: Session, product: Product, *, campaign: Campaign | None = None, **overrides: object
) -> ApprovedClaim:
    values: dict[str, object] = {
        "claim_key": f"synthetic-claim-{uuid.uuid4().hex[:8]}",
        "version": 1,
        "product_id": product.id,
        "text": "SYNTHETIC-approved sentence about a synthetic product.",
        "approved_by": CLAIM_OWNER,
        "approved_at": EARLIER,
        "effective_from": EARLIER,
        "expires_or_review_by": LATER,
        "is_synthetic": True,
    }
    values.update(overrides)
    claim = ApprovedClaim(**values)  # type: ignore[arg-type]
    db_session.add(claim)
    db_session.flush()

    if campaign is not None:
        db_session.add(ApprovedClaimCampaign(claim_id=claim.id, campaign_id=campaign.id))
        db_session.flush()
    return claim


# --- mandatory approval metadata (criterion 1) ----------------------------------------------------


def test_a_claim_without_an_approver_is_rejected(db_session: Session, product: Product) -> None:
    with pytest.raises(IntegrityError):
        make_claim(db_session, product, approved_by="   ")


def test_a_claim_without_a_review_date_is_rejected(db_session: Session, product: Product) -> None:
    """Unlike product readiness, every claim must come back for review (§15.7)."""
    with pytest.raises((IntegrityError, DBAPIError)):
        make_claim(db_session, product, expires_or_review_by=None)


def test_a_claim_without_an_effective_date_is_rejected(
    db_session: Session, product: Product
) -> None:
    with pytest.raises((IntegrityError, DBAPIError)):
        make_claim(db_session, product, effective_from=None)


def test_a_review_date_before_the_effective_date_is_rejected(
    db_session: Session, product: Product
) -> None:
    with pytest.raises(IntegrityError):
        make_claim(db_session, product, effective_from=LATER, expires_or_review_by=EARLIER)


def test_empty_claim_text_is_rejected(db_session: Session, product: Product) -> None:
    with pytest.raises(IntegrityError):
        make_claim(db_session, product, text="   ")


def test_paraphrase_permission_requires_stated_constraints(
    db_session: Session, product: Product
) -> None:
    """§10.5: allowed paraphrase must state its limits, or wording drifts from what was approved."""
    with pytest.raises(IntegrityError):
        make_claim(db_session, product, allow_paraphrase=True, paraphrase_constraints=None)


def test_paraphrase_with_constraints_is_accepted(db_session: Session, product: Product) -> None:
    claim = make_claim(
        db_session,
        product,
        allow_paraphrase=True,
        paraphrase_constraints="No numeric values may be altered.",
    )

    assert claim.allow_paraphrase is True


# --- synthetic marker (criterion 4) ---------------------------------------------------------------


def test_claims_are_synthetic_by_default(db_session: Session, product: Product) -> None:
    """Nothing is a real approved claim until `Q-017` delivers a versioned approved set."""
    claim = ApprovedClaim(
        claim_key="synthetic-default",
        version=1,
        product_id=product.id,
        text="SYNTHETIC-text",
        approved_by=OWNER_ONE,
        approved_at=EARLIER,
        effective_from=EARLIER,
        expires_or_review_by=LATER,
    )
    db_session.add(claim)
    db_session.flush()

    assert claim.is_synthetic is True


def test_no_real_claims_exist_yet(db_session: Session, product: Product) -> None:
    """A standing check: while Q-017 is open, every stored claim must be marked synthetic."""
    make_claim(db_session, product)
    db_session.flush()

    real = [c for c in db_session.query(ApprovedClaim).all() if not c.is_synthetic]

    assert real == [], f"non-synthetic claims exist before Q-017 is answered: {real}"


# --- validity window ------------------------------------------------------------------------------


def test_is_valid_at_covers_the_window(db_session: Session, product: Product) -> None:
    claim = make_claim(db_session, product)

    assert claim.is_valid_at(NOW)
    assert not claim.is_valid_at(EARLIER - timedelta(seconds=1))
    assert not claim.is_valid_at(LATER)


def test_a_superseded_claim_is_invalid_from_that_moment(
    db_session: Session, product: Product
) -> None:
    claim = make_claim(db_session, product, superseded_at=NOW)

    assert claim.is_valid_at(NOW - timedelta(seconds=1))
    assert not claim.is_valid_at(NOW)


# --- claim sets fail whole (criterion 2) ----------------------------------------------------------


def test_requesting_a_set_that_does_not_exist_raises(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    """An empty result would read as "nothing to say", letting a draft omit claim references."""
    with pytest.raises(NoCurrentClaimSet):
        get_valid_claim_set(db_session, product_id=product.id, campaign_id=campaign.id, at=NOW)


def test_a_valid_set_resolves(db_session: Session, product: Product, campaign: Campaign) -> None:
    claim = make_claim(db_session, product, campaign=campaign)
    publish_claim_set(
        db_session,
        product_id=product.id,
        campaign_id=campaign.id,
        claims=[claim],
        approved_by=OWNER_ONE,
        approved_at=NOW,
    )
    db_session.flush()

    claim_set, claims = get_valid_claim_set(
        db_session, product_id=product.id, campaign_id=campaign.id, at=NOW
    )

    assert claim_set.version == 1
    assert [c.id for c in claims] == [claim.id]


def test_an_expired_member_fails_the_whole_set(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    """No silent filtering: dropping the expired claim would change the approved content."""
    good = make_claim(db_session, product, campaign=campaign)
    expiring = make_claim(db_session, product, campaign=campaign, expires_or_review_by=NOW)
    publish_claim_set(
        db_session,
        product_id=product.id,
        campaign_id=campaign.id,
        claims=[good, expiring],
        approved_by=OWNER_ONE,
        approved_at=EARLIER,
    )
    db_session.flush()

    with pytest.raises(InvalidClaimInSet) as exc:
        get_valid_claim_set(
            db_session, product_id=product.id, campaign_id=campaign.id, at=NOW + timedelta(days=1)
        )

    assert expiring.claim_key in str(exc.value)
    assert "fails whole" in str(exc.value)


def test_a_superseded_member_fails_the_whole_set(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    claim = make_claim(db_session, product, campaign=campaign)
    publish_claim_set(
        db_session,
        product_id=product.id,
        campaign_id=campaign.id,
        claims=[claim],
        approved_by=OWNER_ONE,
        approved_at=EARLIER,
    )
    db_session.flush()

    claim.superseded_at = NOW
    db_session.flush()

    with pytest.raises(InvalidClaimInSet):
        get_valid_claim_set(
            db_session, product_id=product.id, campaign_id=campaign.id, at=NOW + timedelta(days=1)
        )


# --- campaign scoping is an allow-list (criterion 3) ----------------------------------------------


def test_a_claim_is_not_allowed_without_an_explicit_link(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    claim = make_claim(db_session, product)

    assert not claim_is_allowed_for_campaign(db_session, claim_id=claim.id, campaign_id=campaign.id)


def test_a_claim_approved_for_one_campaign_is_not_returned_for_another(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    """Positioning approved for one campaign is not thereby approved for the other (§14.4)."""
    other = Campaign(
        slug=f"synthetic-other-{uuid.uuid4().hex[:8]}",
        name="SYNTHETIC-Other",
        product_id=product.id,
    )
    db_session.add(other)
    db_session.flush()

    make_claim(db_session, product, campaign=campaign)

    assert valid_claims_for_campaign(db_session, product_id=product.id, campaign_id=other.id) == []
    assert (
        len(valid_claims_for_campaign(db_session, product_id=product.id, campaign_id=campaign.id))
        == 1
    )


def test_publishing_refuses_a_claim_not_allowed_for_the_campaign(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    unlinked = make_claim(db_session, product)

    with pytest.raises(InvalidClaimInSet) as exc:
        publish_claim_set(
            db_session,
            product_id=product.id,
            campaign_id=campaign.id,
            claims=[unlinked],
            approved_by=OWNER_ONE,
            approved_at=NOW,
        )

    assert "not approved for campaign" in str(exc.value)


def test_publishing_refuses_an_expired_claim(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    stale = make_claim(db_session, product, campaign=campaign, expires_or_review_by=NOW)

    with pytest.raises(InvalidClaimInSet):
        publish_claim_set(
            db_session,
            product_id=product.id,
            campaign_id=campaign.id,
            claims=[stale],
            approved_by=OWNER_ONE,
            approved_at=NOW + timedelta(days=1),
        )


def test_a_set_whose_member_link_was_revoked_fails(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    """Revoking campaign scope after publication must break the set, not silently narrow it."""
    claim = make_claim(db_session, product, campaign=campaign)
    publish_claim_set(
        db_session,
        product_id=product.id,
        campaign_id=campaign.id,
        claims=[claim],
        approved_by=OWNER_ONE,
        approved_at=NOW,
    )
    db_session.flush()

    link = db_session.query(ApprovedClaimCampaign).filter_by(claim_id=claim.id).one()
    db_session.delete(link)
    db_session.flush()

    with pytest.raises(InvalidClaimInSet) as exc:
        get_valid_claim_set(db_session, product_id=product.id, campaign_id=campaign.id, at=NOW)

    assert "allow-list" in str(exc.value)


# --- set versioning -------------------------------------------------------------------------------


def test_publishing_supersedes_the_previous_set(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    claim = make_claim(db_session, product, campaign=campaign)
    first = publish_claim_set(
        db_session,
        product_id=product.id,
        campaign_id=campaign.id,
        claims=[claim],
        approved_by=OWNER_ONE,
        approved_at=NOW,
    )
    db_session.flush()

    second = publish_claim_set(
        db_session,
        product_id=product.id,
        campaign_id=campaign.id,
        claims=[claim],
        approved_by=OWNER_TWO,
        approved_at=NOW + timedelta(days=1),
    )
    db_session.flush()

    assert first.superseded_at is not None
    assert second.version == 2

    current = get_claim_set(db_session, product_id=product.id, campaign_id=campaign.id)
    assert current is not None
    assert current.id == second.id


def test_set_versions_are_unique_per_product_and_campaign(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    db_session.add(
        ApprovedClaimSet(
            product_id=product.id,
            campaign_id=campaign.id,
            version=1,
            approved_by=OWNER_ONE,
            approved_at=NOW,
        )
    )
    db_session.flush()
    db_session.add(
        ApprovedClaimSet(
            product_id=product.id,
            campaign_id=campaign.id,
            version=1,
            approved_by=OWNER_TWO,
            approved_at=NOW,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- immutability ---------------------------------------------------------------------------------


def test_approved_wording_cannot_be_rewritten(db_session: Session, product: Product) -> None:
    """§10.5 stores *exact* wording; editing in place would change an approved message."""
    claim = make_claim(db_session, product)

    claim.text = "SYNTHETIC-something nobody approved"

    with pytest.raises(DBAPIError) as exc:
        db_session.flush()

    assert "immutable" in str(exc.value)


def test_the_synthetic_marker_cannot_be_flipped(db_session: Session, product: Product) -> None:
    """Promoting a synthetic claim to "real" must be a new, reviewed claim — not an UPDATE."""
    claim = make_claim(db_session, product)

    claim.is_synthetic = False

    with pytest.raises(DBAPIError):
        db_session.flush()


def test_superseding_a_claim_is_still_allowed(db_session: Session, product: Product) -> None:
    claim = make_claim(db_session, product)

    claim.superseded_at = NOW
    db_session.flush()  # must not raise

    assert claim.superseded_at == NOW


def test_set_membership_cannot_be_repointed(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    first = make_claim(db_session, product, campaign=campaign)
    second = make_claim(db_session, product, campaign=campaign)
    publish_claim_set(
        db_session,
        product_id=product.id,
        campaign_id=campaign.id,
        claims=[first],
        approved_by=OWNER_ONE,
        approved_at=NOW,
    )
    db_session.flush()

    member = db_session.query(ApprovedClaimSetMember).one()
    member.claim_id = second.id

    with pytest.raises(DBAPIError):
        db_session.flush()


def test_a_claim_cited_by_a_set_cannot_be_deleted(
    db_session: Session, product: Product, campaign: Campaign
) -> None:
    claim = make_claim(db_session, product, campaign=campaign)
    publish_claim_set(
        db_session,
        product_id=product.id,
        campaign_id=campaign.id,
        claims=[claim],
        approved_by=OWNER_ONE,
        approved_at=NOW,
    )
    db_session.flush()

    db_session.delete(claim)

    with pytest.raises(IntegrityError):
        db_session.flush()
