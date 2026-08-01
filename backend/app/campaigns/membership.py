"""Creating campaign memberships (T-044; specification §8.1, §8.3 step 3).

§8.1 is a decision about modelling, and this module is where it becomes code: **a lead is not a
property of a company.** An account and contact relevant to both the sodium-battery and the
DC-fast-charging campaign get *two* memberships, with independent state, evidence, scores, and
review decisions — never one record carrying two opinions. Nothing here merges those opinions,
and there is deliberately no function that returns "the candidate" for an account.

What this module is not: a judgement about whether outreach *should* happen. Applicability comes
from the caller — the `campaigns` column of an import file, or an operator's selection — and hard
eligibility (geography, suppression, readiness, contactability) is `T-045`, evaluated per
membership after it exists. Creating a membership only says "this pairing is worth evaluating
for this campaign", which is exactly what the `imported` state means (§8.2).

Two conservative choices, both of which report rather than raise:

* **A paused campaign gets no new memberships.** §17.6 makes the pause an operational control,
  and a paused campaign quietly accumulating candidates is work someone stopped on purpose.
  `Campaign.paused` defaults to `True` (T-015), so a freshly seeded world produces nothing until
  someone starts a campaign — which is the safe direction to be wrong in.
* **An unknown campaign slug is reported, not fatal.** A typo in one row of an import must not
  cost the other rows their memberships, the same way `T-042` reports a bad row and carries on.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, create_candidate
from app.campaigns.models import Campaign


@dataclass(frozen=True, slots=True)
class MembershipResult:
    """One membership pass. Every campaign asked for appears in exactly one of these lists."""

    created: list[uuid.UUID] = field(default_factory=list)
    #: Memberships that already existed. Re-running is expected — an import re-run, a corrected
    #: file — so this is the ordinary case, not a warning.
    existing: list[uuid.UUID] = field(default_factory=list)
    #: Campaign IDs skipped because the campaign is paused (§17.6).
    skipped_paused: list[uuid.UUID] = field(default_factory=list)
    #: Slugs that name no campaign. Reported so an operator can fix the file.
    unknown_slugs: list[str] = field(default_factory=list)

    @property
    def candidate_ids(self) -> list[uuid.UUID]:
        """Every membership this pairing now has, whether this pass made it or found it."""
        return [*self.created, *self.existing]


def find_membership(
    session: Session,
    *,
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    contact_id: uuid.UUID | None,
) -> CampaignCandidate | None:
    """The membership for the §8.1 identity triple, if it exists.

    ``contact_id`` of ``None`` is matched with ``IS NULL`` rather than ``= NULL``, matching the
    `NULLS NOT DISTINCT` unique constraint: two account-level candidates for one campaign are one
    candidate, not two.
    """
    contact_match = (
        CampaignCandidate.contact_id.is_(None)
        if contact_id is None
        else CampaignCandidate.contact_id == contact_id
    )
    return session.execute(
        select(CampaignCandidate).where(
            CampaignCandidate.campaign_id == campaign_id,
            CampaignCandidate.account_id == account_id,
            contact_match,
        )
    ).scalar_one_or_none()


def create_memberships(
    session: Session,
    *,
    account_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    campaign_slugs: Sequence[str],
    actor: Actor,
    correlation_id: str | None = None,
) -> MembershipResult:
    """Create one membership per named campaign. Adds to ``session`` without committing.

    Duplicate slugs in ``campaign_slugs`` collapse: the second occurrence finds the membership
    the first created, so a malformed `a|a` cell cannot produce two candidates where the database
    would in any case refuse the second.
    """
    result = MembershipResult()

    for slug in campaign_slugs:
        cleaned = slug.strip()
        if not cleaned:
            continue

        campaign = session.execute(
            select(Campaign).where(Campaign.slug == cleaned)
        ).scalar_one_or_none()
        if campaign is None:
            if cleaned not in result.unknown_slugs:
                result.unknown_slugs.append(cleaned)
            continue

        existing = find_membership(
            session, campaign_id=campaign.id, account_id=account_id, contact_id=contact_id
        )
        if existing is not None:
            if existing.id not in result.existing:
                result.existing.append(existing.id)
            continue

        if campaign.paused:
            # Checked *after* the existing-membership lookup on purpose: pausing a campaign stops
            # new work, it does not hide the work already in it.
            if campaign.id not in result.skipped_paused:
                result.skipped_paused.append(campaign.id)
            continue

        # `create_candidate` writes the audit event naming the campaign (T-018). Constructing a
        # `CampaignCandidate` here instead would create a membership nobody could explain.
        candidate = create_candidate(
            session,
            campaign_id=campaign.id,
            account_id=account_id,
            contact_id=contact_id,
            actor=actor,
            correlation_id=correlation_id,
        )
        result.created.append(candidate.id)

    return result
