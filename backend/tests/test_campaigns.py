"""Campaigns, target segments, and versioned policy (T-015; §8.1, §8.6, ADR-012).

Two things matter here. A campaign always resolves to exactly one current policy, and a policy
version cannot be rewritten after a decision has been recorded against it — otherwise the audit
trail says "approved under v2" while v2 now says something else.

All fixtures are synthetic. Real ideal-customer profiles stay `Q-002`; real geography `Q-013`;
real volumes `Q-014`.
"""

import uuid
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.campaigns.models import Campaign, CampaignPolicyVersion, TargetSegment
from app.campaigns.policy import CampaignPolicy, SuppressionScope
from app.campaigns.service import (
    NoCurrentPolicy,
    get_current_policy_version,
    publish_policy_version,
    require_current_policy,
)
from app.products_and_claims.models import Product, ReadinessCategory
from tests.factories import NOW


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


# --- safe defaults ---------------------------------------------------------------------------


def test_a_new_campaign_starts_paused(campaign: Campaign) -> None:
    """A campaign that begins work on creation is an accident waiting for its first candidate."""
    assert campaign.paused is True


def test_policy_defaults_are_conservative() -> None:
    policy = CampaignPolicy()

    assert policy.allowed_countries == ("US",), "U.S.-only until Q-013 confirms jurisdictions"
    assert policy.daily_send_cap == 5, "§19.6 Stage 6 micro-pilot volume"
    assert policy.require_verified_email is True
    assert policy.suppression_scope == SuppressionScope()


def test_sellable_now_is_not_a_default_readiness() -> None:
    """No product may be positioned as generally available before Q-021/Q-022 (GP-12)."""
    assert ReadinessCategory.SELLABLE_NOW not in CampaignPolicy().required_readiness


def test_unknown_geography_is_refused_not_assumed_domestic() -> None:
    policy = CampaignPolicy()

    assert policy.permits_country("US")
    assert policy.permits_country(" us ")
    assert not policy.permits_country("DE")
    assert not policy.permits_country(None)
    assert not policy.permits_country("")


def test_an_empty_country_list_allows_nothing() -> None:
    """Empty means "nothing permitted", never "anywhere"."""
    policy = CampaignPolicy(allowed_countries=())

    assert not policy.permits_country("US")


def test_excluded_domains_are_normalized() -> None:
    policy = CampaignPolicy(excluded_domains=("  WWW.Example.COM ",))

    assert policy.excludes_domain("example.com")
    assert policy.excludes_domain("www.example.com")
    assert not policy.excludes_domain("other.example")
    assert not policy.excludes_domain(None)


def test_readiness_gate_reflects_the_policy() -> None:
    policy = CampaignPolicy(required_readiness=(ReadinessCategory.EVALUATION_OR_PILOT,))

    assert policy.permits_readiness(ReadinessCategory.EVALUATION_OR_PILOT)
    assert not policy.permits_readiness(ReadinessCategory.SELLABLE_NOW)


def test_policy_rejects_unknown_fields() -> None:
    """A typo must not become a silently ignored rule."""
    with pytest.raises(ValidationError):
        CampaignPolicy(allowed_contries=("US",))  # type: ignore[call-arg]


def test_negative_caps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CampaignPolicy(daily_send_cap=-1)


def test_policy_is_frozen() -> None:
    """Rules must not be edited in place after being loaded for a decision."""
    policy = CampaignPolicy()

    with pytest.raises(ValidationError):
        policy.daily_send_cap = 500  # type: ignore[misc]


# --- exactly one current policy ---------------------------------------------------------------


def test_a_campaign_without_policy_has_none(db_session: Session, campaign: Campaign) -> None:
    assert get_current_policy_version(db_session, campaign.id) is None


def test_requiring_a_missing_policy_raises(db_session: Session, campaign: Campaign) -> None:
    """An absent policy must never read as "no restrictions"."""
    with pytest.raises(NoCurrentPolicy) as exc:
        require_current_policy(db_session, campaign.id)

    assert str(campaign.id) in str(exc.value)


def test_publishing_gives_exactly_one_current_version(
    db_session: Session, campaign: Campaign
) -> None:
    publish_policy_version(
        db_session, campaign_id=campaign.id, policy=CampaignPolicy(), approved_by="owner-1"
    )
    db_session.flush()

    current = get_current_policy_version(db_session, campaign.id)

    assert current is not None
    assert current.version == 1
    assert current.superseded_at is None


def test_publishing_again_supersedes_the_previous(db_session: Session, campaign: Campaign) -> None:
    first = publish_policy_version(
        db_session,
        campaign_id=campaign.id,
        policy=CampaignPolicy(),
        approved_by="owner-1",
        approved_at=NOW,
    )
    db_session.flush()

    second = publish_policy_version(
        db_session,
        campaign_id=campaign.id,
        policy=CampaignPolicy(daily_send_cap=3),
        approved_by="owner-2",
        approved_at=NOW + timedelta(days=1),
    )
    db_session.flush()

    assert first.superseded_at is not None
    assert second.version == 2
    assert second.superseded_at is None

    current = get_current_policy_version(db_session, campaign.id)
    assert current is not None
    assert current.id == second.id
    assert require_current_policy(db_session, campaign.id).daily_send_cap == 3


def test_version_numbers_are_unique_per_campaign(db_session: Session, campaign: Campaign) -> None:
    db_session.add(
        CampaignPolicyVersion(
            campaign_id=campaign.id,
            version=1,
            policy=CampaignPolicy().model_dump(mode="json"),
            approved_by="owner-1",
            approved_at=NOW,
        )
    )
    db_session.flush()
    db_session.add(
        CampaignPolicyVersion(
            campaign_id=campaign.id,
            version=1,
            policy=CampaignPolicy().model_dump(mode="json"),
            approved_by="owner-2",
            approved_at=NOW,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- immutability once written -----------------------------------------------------------------


def test_a_published_policy_body_cannot_be_rewritten(
    db_session: Session, campaign: Campaign
) -> None:
    """GP-09: a decision recorded against v2 must still be explainable by reading v2."""
    version = publish_policy_version(
        db_session, campaign_id=campaign.id, policy=CampaignPolicy(), approved_by="owner-1"
    )
    db_session.flush()

    version.policy = CampaignPolicy(daily_send_cap=9999).model_dump(mode="json")

    with pytest.raises(DBAPIError) as exc:
        db_session.flush()

    assert "immutable" in str(exc.value)


def test_the_approver_cannot_be_rewritten(db_session: Session, campaign: Campaign) -> None:
    version = publish_policy_version(
        db_session, campaign_id=campaign.id, policy=CampaignPolicy(), approved_by="owner-1"
    )
    db_session.flush()

    version.approved_by = "someone-else"

    with pytest.raises(DBAPIError):
        db_session.flush()


def test_superseding_is_still_allowed(db_session: Session, campaign: Campaign) -> None:
    """Retiring a version is how the next one takes over; it changes no rule."""
    version = publish_policy_version(
        db_session, campaign_id=campaign.id, policy=CampaignPolicy(), approved_by="owner-1"
    )
    db_session.flush()

    version.superseded_at = NOW
    db_session.flush()  # must not raise

    assert version.superseded_at == NOW


# --- stored bodies stay typed --------------------------------------------------------------------


def test_a_stored_policy_round_trips_through_the_model(
    db_session: Session, campaign: Campaign
) -> None:
    original = CampaignPolicy(
        allowed_countries=("US",),
        excluded_domains=("blocked.example",),
        excluded_segments=("consultancies",),
        daily_send_cap=2,
        total_send_cap=10,
        required_readiness=(ReadinessCategory.EVALUATION_OR_PILOT,),
    )
    version = publish_policy_version(
        db_session, campaign_id=campaign.id, policy=original, approved_by="owner-1"
    )
    db_session.flush()
    db_session.expire(version)

    assert version.as_policy() == original


def test_a_drifted_policy_body_fails_loudly(db_session: Session, campaign: Campaign) -> None:
    """Loose JSON must not quietly become permissive rules."""
    db_session.add(
        CampaignPolicyVersion(
            campaign_id=campaign.id,
            version=1,
            policy={"allowed_countries": ["US"], "unexpected_rule": True},
            approved_by="owner-1",
            approved_at=NOW,
        )
    )
    db_session.flush()

    version = get_current_policy_version(db_session, campaign.id)
    assert version is not None

    with pytest.raises(ValidationError):
        version.as_policy()


# --- campaign structure ---------------------------------------------------------------------------


def test_campaign_slugs_are_unique(
    db_session: Session, campaign: Campaign, product: Product
) -> None:
    db_session.add(Campaign(slug=campaign.slug, name="Duplicate", product_id=product.id))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_product_in_use_by_a_campaign_cannot_be_deleted(
    db_session: Session, campaign: Campaign, product: Product
) -> None:
    db_session.delete(product)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_segment_keys_are_unique_within_a_campaign(db_session: Session, campaign: Campaign) -> None:
    db_session.add(TargetSegment(campaign_id=campaign.id, key="depot-charging"))
    db_session.flush()
    db_session.add(TargetSegment(campaign_id=campaign.id, key="depot-charging"))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_campaigns_can_target_the_same_product(
    db_session: Session, campaign: Campaign, product: Product
) -> None:
    """ADR-012: both configurations get built even though only one pilots first."""
    other = Campaign(
        slug=f"synthetic-second-{uuid.uuid4().hex[:8]}",
        name="SYNTHETIC-Second",
        product_id=product.id,
    )
    db_session.add(other)

    db_session.flush()  # must not raise


def test_deleting_a_campaign_removes_its_policy_versions(
    db_session: Session, campaign: Campaign
) -> None:
    publish_policy_version(
        db_session, campaign_id=campaign.id, policy=CampaignPolicy(), approved_by="owner-1"
    )
    db_session.flush()

    db_session.delete(campaign)
    db_session.flush()

    assert get_current_policy_version(db_session, campaign.id) is None
