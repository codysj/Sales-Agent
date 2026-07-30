"""Resolving and publishing campaign policy (specification §8.1, GP-09).

Reads fail closed: a campaign with no current policy version has no rules, which is never
treated as "no restrictions".
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.campaigns.models import CampaignPolicyVersion
from app.campaigns.policy import CampaignPolicy


class CampaignPolicyError(Exception):
    """No usable campaign policy exists."""


class NoCurrentPolicy(CampaignPolicyError):
    """The campaign has no unsuperseded policy version.

    Raised rather than defaulted: an empty policy would read as "no exclusions, no geography
    limit", which is the opposite of the safe answer (§10.1).
    """


def get_current_policy_version(
    session: Session, campaign_id: uuid.UUID
) -> CampaignPolicyVersion | None:
    """The one policy version that has not been superseded, or ``None``."""
    statement = (
        select(CampaignPolicyVersion)
        .where(
            CampaignPolicyVersion.campaign_id == campaign_id,
            CampaignPolicyVersion.superseded_at.is_(None),
        )
        .order_by(CampaignPolicyVersion.version.desc())
    )
    return session.execute(statement).scalars().first()


def require_current_policy(session: Session, campaign_id: uuid.UUID) -> CampaignPolicy:
    """The typed policy in force. Raises if there is none, or if the stored body has drifted."""
    version = get_current_policy_version(session, campaign_id)
    if version is None:
        raise NoCurrentPolicy(
            f"campaign {campaign_id} has no current policy version; "
            f"eligibility cannot be evaluated without approved rules (§10.1)"
        )
    return version.as_policy()


def publish_policy_version(
    session: Session,
    *,
    campaign_id: uuid.UUID,
    policy: CampaignPolicy,
    approved_by: str,
    approved_at: datetime | None = None,
) -> CampaignPolicyVersion:
    """Supersede the current version and add a new one.

    Adds to the session without committing, so the new version, its audit event, and any
    dependent work commit together (§17.2).
    """
    moment = approved_at or datetime.now(UTC)

    previous = get_current_policy_version(session, campaign_id)
    if previous is not None:
        previous.superseded_at = moment
        next_version = previous.version + 1
    else:
        next_version = 1

    version = CampaignPolicyVersion(
        campaign_id=campaign_id,
        version=next_version,
        policy=policy.model_dump(mode="json"),
        approved_by=approved_by,
        approved_at=moment,
    )
    session.add(version)
    return version
