"""Resolving approved claims (specification §10.5, §15.7, GP-12).

Everything here fails closed. An expired, superseded, or wrong-campaign claim does not get
filtered out quietly — the request fails, because the caller asked for a claim set and silently
getting a *different* claim set is how an approved message turns into an unapproved one.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.products_and_claims.claim_models import (
    ApprovedClaim,
    ApprovedClaimCampaign,
    ApprovedClaimSet,
    ApprovedClaimSetMember,
)


class ClaimError(Exception):
    """A claim request could not be satisfied safely."""


class NoCurrentClaimSet(ClaimError):
    """No unsuperseded claim set exists for this product and campaign.

    Raised rather than returning an empty set: "no claims" reads as "nothing to say about the
    product", which would let a draft omit the claim references §10.5 requires.
    """


class InvalidClaimInSet(ClaimError):
    """A claim in the requested set is not usable at the requested instant.

    The whole set fails. Dropping the offending claim and returning the rest would change the
    approved content without an approval (§10.5, §8.4).
    """


def get_claim_set(
    session: Session, *, product_id: uuid.UUID, campaign_id: uuid.UUID
) -> ApprovedClaimSet | None:
    """The current (unsuperseded) claim set for a product and campaign."""
    statement = (
        select(ApprovedClaimSet)
        .where(
            ApprovedClaimSet.product_id == product_id,
            ApprovedClaimSet.campaign_id == campaign_id,
            ApprovedClaimSet.superseded_at.is_(None),
        )
        .order_by(ApprovedClaimSet.version.desc())
    )
    return session.execute(statement).scalars().first()


def claim_is_allowed_for_campaign(
    session: Session, *, claim_id: uuid.UUID, campaign_id: uuid.UUID
) -> bool:
    """Allow-list check. Absence of a link means *not permitted*, never "unrestricted"."""
    statement = select(ApprovedClaimCampaign.id).where(
        ApprovedClaimCampaign.claim_id == claim_id,
        ApprovedClaimCampaign.campaign_id == campaign_id,
    )
    return session.execute(statement).first() is not None


def get_valid_claim_set(
    session: Session,
    *,
    product_id: uuid.UUID,
    campaign_id: uuid.UUID,
    at: datetime | None = None,
) -> tuple[ApprovedClaimSet, list[ApprovedClaim]]:
    """The current claim set and its claims, or raise.

    Raises :class:`NoCurrentClaimSet` if there is none, and :class:`InvalidClaimInSet` if **any**
    member is expired, superseded, not yet effective, or not allowed for this campaign. There is
    deliberately no "skip the bad ones" mode.
    """
    moment = at or datetime.now(UTC)

    claim_set = get_claim_set(session, product_id=product_id, campaign_id=campaign_id)
    if claim_set is None:
        raise NoCurrentClaimSet(
            f"no approved claim set for product {product_id} and campaign {campaign_id}; "
            f"outbound product statements require approved claim IDs (§10.5)"
        )

    members = (
        session.execute(
            select(ApprovedClaim)
            .join(ApprovedClaimSetMember, ApprovedClaimSetMember.claim_id == ApprovedClaim.id)
            .where(ApprovedClaimSetMember.claim_set_id == claim_set.id)
            .order_by(ApprovedClaim.claim_key)
        )
        .scalars()
        .all()
    )

    for claim in members:
        if not claim.is_valid_at(moment):
            raise InvalidClaimInSet(
                f"claim {claim.claim_key} v{claim.version} in set v{claim_set.version} is not "
                f"valid at {moment.isoformat()} "
                f"(effective {claim.effective_from.isoformat()}, "
                f"review by {claim.expires_or_review_by.isoformat()}"
                f"{', superseded' if claim.superseded_at else ''}); "
                f"the claim set fails whole rather than dropping it (§10.5)"
            )
        if not claim_is_allowed_for_campaign(session, claim_id=claim.id, campaign_id=campaign_id):
            raise InvalidClaimInSet(
                f"claim {claim.claim_key} v{claim.version} is not approved for campaign "
                f"{campaign_id}; claim scope is an allow-list (§14.4)"
            )

    return claim_set, list(members)


def valid_claims_for_campaign(
    session: Session,
    *,
    product_id: uuid.UUID,
    campaign_id: uuid.UUID,
    at: datetime | None = None,
) -> list[ApprovedClaim]:
    """Claims currently usable for a campaign — the candidates for a *new* set.

    Filtering is correct here because nothing has been approved yet: this assembles a proposal,
    it does not reinterpret an existing approval.
    """
    moment = at or datetime.now(UTC)

    statement = (
        select(ApprovedClaim)
        .join(ApprovedClaimCampaign, ApprovedClaimCampaign.claim_id == ApprovedClaim.id)
        .where(
            ApprovedClaim.product_id == product_id,
            ApprovedClaimCampaign.campaign_id == campaign_id,
            ApprovedClaim.effective_from <= moment,
            ApprovedClaim.expires_or_review_by > moment,
        )
        .where((ApprovedClaim.superseded_at.is_(None)) | (ApprovedClaim.superseded_at > moment))
        .order_by(ApprovedClaim.claim_key)
    )
    return list(session.execute(statement).scalars().all())


def publish_claim_set(
    session: Session,
    *,
    product_id: uuid.UUID,
    campaign_id: uuid.UUID,
    claims: list[ApprovedClaim],
    approved_by: str,
    approved_at: datetime | None = None,
) -> ApprovedClaimSet:
    """Supersede the current set and publish a new one.

    Refuses to include a claim that is not valid or not allowed for the campaign, so an invalid
    set cannot be created in the first place.
    """
    moment = approved_at or datetime.now(UTC)

    for claim in claims:
        if not claim.is_valid_at(moment):
            raise InvalidClaimInSet(
                f"cannot publish a set containing {claim.claim_key} v{claim.version}: "
                f"not valid at {moment.isoformat()}"
            )
        if not claim_is_allowed_for_campaign(session, claim_id=claim.id, campaign_id=campaign_id):
            raise InvalidClaimInSet(
                f"cannot publish a set containing {claim.claim_key} v{claim.version}: "
                f"not approved for campaign {campaign_id}"
            )

    previous = get_claim_set(session, product_id=product_id, campaign_id=campaign_id)
    if previous is not None:
        previous.superseded_at = moment
        next_version = previous.version + 1
    else:
        next_version = 1

    claim_set = ApprovedClaimSet(
        product_id=product_id,
        campaign_id=campaign_id,
        version=next_version,
        approved_by=approved_by,
        approved_at=moment,
    )
    session.add(claim_set)
    session.flush()

    for claim in claims:
        session.add(ApprovedClaimSetMember(claim_set_id=claim_set.id, claim_id=claim.id))

    return claim_set
