"""Hard eligibility — stage 1 of §10.1 (T-045; §8.3 step 4, §10.1, §15.6, GP-12).

"Deterministic rules own eligibility. The model interprets contextual evidence and produces a
typed recommendation; it does not override a failed hard rule" (§10.1). This module is that
sentence as code, and the shape of it is the argument:

* **Nothing here can call a model.** `qualification` may import `model_gateway`, so the guarantee
  cannot come from the module boundary checker — it comes from this file taking no adapter, no
  gateway, no client, and no callable. Every input is a database row or a `CampaignPolicy` field.
  `tests/test_eligibility.py` asserts the module imports nothing from `app.model_gateway` and that
  the same candidate evaluated twice produces the identical failure list.
* **There is no override parameter, because a parameter is a door.** `apply_eligibility` takes no
  `force`, no `override`, no `reason_to_ignore`. A caller holding a glowing model recommendation
  has nothing to pass it to.
* **Every rule runs.** Failures accumulate rather than short-circuiting, so a reviewer sees all
  the reasons a candidate was refused, not whichever one happened to be checked first (criterion
  2). It also means an operator who fixes one reason is not surprised by the next.

**Conservative where the specification leaves discretion** (`Q-002` has not confirmed segments,
`Q-013` has not confirmed jurisdictions): unknown geography is refused rather than assumed
domestic, a campaign with no published policy has no rules and therefore refuses everything
(`NoCurrentPolicy`), a product with no effective readiness version refuses (GP-12), and an
unverified address is refused whenever policy asks for verification.

**Three of §10.1's eight checks are named but cannot fire yet, and that is deliberate.** They
appear in `Rule` so the gap is visible where someone would look for it rather than implied by
absence — the same reason `Recheck.SENDER_AVAILABILITY` exists in `outreach_and_replies`:

| §10.1 check | Status |
|---|---|
| Geography | `Rule.GEOGRAPHY` |
| Campaign exclusions | `Rule.CAMPAIGN_EXCLUSION` |
| Suppression | `Rule.SUPPRESSION` |
| Product readiness | `Rule.PRODUCT_READINESS` |
| Contactability | `Rule.CONTACTABILITY` |
| Existing relationship conflict | **not implemented** — CRM (`Q-001`, **G-05**); `T-143` |
| Approved source basis | **not implemented** — needs import provenance on the candidate; `T-144` |
| Obvious non-fit | **not implemented** — needs a confirmed ICP (`Q-002`); `T-145` |

A rule that always passes would be worse than an absent one: it would read as coverage.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, transition
from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import require_current_policy
from app.core.lifecycles import CampaignCandidateState
from app.products_and_claims.status import get_effective_status
from app.prospects.models import Account, Contact, ContactPoint, ContactPointType, VerificationState
from app.prospects.suppression import find_suppression


class Rule(StrEnum):
    """The §10.1 stage-1 checks, named so a refusal can say which one failed."""

    GEOGRAPHY = "geography"
    CAMPAIGN_EXCLUSION = "campaign_exclusion"
    SUPPRESSION = "suppression"
    PRODUCT_READINESS = "product_readiness"
    CONTACTABILITY = "contactability"
    #: Not implemented — the CRM is gated behind `Q-001` and **G-05**. See `T-143`.
    EXISTING_RELATIONSHIP = "existing_relationship"
    #: Not implemented — a candidate carries no link to the import batch it came from. See `T-144`.
    APPROVED_SOURCE_BASIS = "approved_source_basis"
    #: Not implemented — `Q-002` has not confirmed the ideal customer profile. See `T-145`.
    OBVIOUS_NON_FIT = "obvious_non_fit"


#: Rules that actually run today. The difference between this and `Rule` is the honest measure of
#: how much of §10.1 stage 1 is enforced, and `tests/test_eligibility.py` pins both.
IMPLEMENTED_RULES: Final = (
    Rule.GEOGRAPHY,
    Rule.CAMPAIGN_EXCLUSION,
    Rule.SUPPRESSION,
    Rule.PRODUCT_READINESS,
    Rule.CONTACTABILITY,
)

#: Rule -> why it cannot run yet. Every `Rule` is in exactly one of these two collections.
DEFERRED_RULES: Final = {
    Rule.EXISTING_RELATIONSHIP: "no CRM adapter exists; Q-001 unanswered, gate G-05 locked (T-143)",
    Rule.APPROVED_SOURCE_BASIS: "a candidate records no import provenance yet (T-144)",
    Rule.OBVIOUS_NON_FIT: "Q-002 has not confirmed the ideal customer profile (T-145)",
}


@dataclass(frozen=True, slots=True)
class EligibilityFailure:
    """One hard rule that refused, and the inputs that decided it.

    ``inputs`` carries identifiers and classifications only — a country code, a readiness
    category, a suppression scope — never an address or a person's name (§15.5). The reviewer
    needs to know *which* rule fired and on what basis; the record itself is one query away.
    """

    rule: Rule
    reason: str
    inputs: dict[str, str]


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """The outcome of one evaluation."""

    candidate_id: uuid.UUID
    failures: list[EligibilityFailure]

    @property
    def is_eligible(self) -> bool:
        return not self.failures

    @property
    def summary(self) -> str:
        """Every reason, in rule order — what `ineligible_reason` records (criterion 2)."""
        return "; ".join(f"{failure.rule.value}: {failure.reason}" for failure in self.failures)


def _check_geography(account: Account, policy: CampaignPolicy) -> EligibilityFailure | None:
    """Unknown geography is refused, not assumed domestic (`Q-013`, §15.8)."""
    if policy.permits_country(account.country_code):
        return None
    return EligibilityFailure(
        rule=Rule.GEOGRAPHY,
        reason=(
            f"country {account.country_code or 'unknown'} is not in the campaign's allowed set "
            f"{list(policy.allowed_countries)}"
        ),
        inputs={
            "country_code": account.country_code or "unknown",
            "allowed": ",".join(policy.allowed_countries),
        },
    )


def _check_campaign_exclusion(
    account: Account, policy: CampaignPolicy
) -> EligibilityFailure | None:
    if not policy.excludes_domain(account.domain):
        return None
    return EligibilityFailure(
        rule=Rule.CAMPAIGN_EXCLUSION,
        reason=f"account domain {account.domain} is on the campaign's exclusion list",
        inputs={"domain": account.domain},
    )


def _check_suppression(
    session: Session,
    *,
    account: Account,
    contact: Contact | None,
    email: str | None,
    at: datetime,
) -> EligibilityFailure | None:
    """Every scope, unconditionally.

    `CampaignPolicy.suppression_scope` is deliberately **not** consulted: §15.6 lets a policy
    widen what it respects and never narrow it, so reading it here could only ever skip a scope.
    """
    match = find_suppression(
        session,
        email=email,
        contact_id=contact.id if contact else None,
        account_id=account.id,
        domain=account.domain,
        at=at,
    )
    if match is None:
        return None
    return EligibilityFailure(
        rule=Rule.SUPPRESSION,
        reason=(
            f"suppressed at {match.scope.value} scope (source {match.source.value}); "
            f"suppression outranks campaign configuration (§15.6)"
        ),
        inputs={"scope": match.scope.value, "source": match.source.value},
    )


def _check_product_readiness(
    session: Session, *, campaign: Campaign, policy: CampaignPolicy, at: datetime
) -> EligibilityFailure | None:
    """Technical relevance is not availability (GP-12). No effective status means no readiness."""
    status = get_effective_status(session, campaign.product_id, at=at)
    if status is None:
        return EligibilityFailure(
            rule=Rule.PRODUCT_READINESS,
            reason=(
                "the campaign's product has no effective readiness version; readiness must be "
                "explicit before the product may be referenced (GP-12)"
            ),
            inputs={"readiness": "none"},
        )
    if policy.permits_readiness(status.readiness_category):
        return None
    return EligibilityFailure(
        rule=Rule.PRODUCT_READINESS,
        reason=(
            f"product readiness {status.readiness_category.value} is not permitted by the "
            f"campaign policy"
        ),
        inputs={
            "readiness": status.readiness_category.value,
            "permitted": ",".join(category.value for category in policy.required_readiness),
        },
    )


def _check_contactability(
    contact: Contact | None, points: Sequence[ContactPoint], policy: CampaignPolicy
) -> EligibilityFailure | None:
    if contact is None:
        return EligibilityFailure(
            rule=Rule.CONTACTABILITY,
            reason="account-level candidate has no contact to reach",
            inputs={"contact": "none"},
        )

    emails = [point for point in points if point.type is ContactPointType.EMAIL]
    if not emails:
        return EligibilityFailure(
            rule=Rule.CONTACTABILITY,
            reason="contact has no email contact point",
            inputs={"email_points": "0"},
        )
    if not policy.require_verified_email:
        return None
    if any(point.verification_state is VerificationState.VERIFIED for point in emails):
        return None
    return EligibilityFailure(
        rule=Rule.CONTACTABILITY,
        reason=(
            "no verified email address; campaign policy requires verification before a send is "
            "considered (§15.8)"
        ),
        inputs={
            "email_points": str(len(emails)),
            "states": ",".join(sorted({point.verification_state.value for point in emails})),
        },
    )


def evaluate(
    session: Session, candidate: CampaignCandidate, *, at: datetime | None = None
) -> EligibilityDecision:
    """Run every implemented hard rule and return all failures. Reads only; changes nothing.

    Raises `NoCurrentPolicy` if the campaign has no published policy: a campaign with no approved
    rules cannot produce an eligibility answer, and defaulting to "no restrictions" is the
    opposite of the safe direction (§10.1).
    """
    moment = at or datetime.now(UTC)

    campaign = session.get(Campaign, candidate.campaign_id)
    account = session.get(Account, candidate.account_id)
    if campaign is None or account is None:  # pragma: no cover - foreign keys prevent this
        raise ValueError(f"candidate {candidate.id} points at a missing campaign or account")

    policy = require_current_policy(session, candidate.campaign_id)

    contact = session.get(Contact, candidate.contact_id) if candidate.contact_id else None
    points: list[ContactPoint] = []
    if contact is not None:
        points = list(
            session.execute(select(ContactPoint).where(ContactPoint.contact_id == contact.id))
            .scalars()
            .all()
        )
    primary_email = next(
        (point.value for point in points if point.type is ContactPointType.EMAIL), None
    )

    # Ordered by `IMPLEMENTED_RULES`, and every one runs: a reviewer needs all the reasons.
    failures = [
        failure
        for failure in (
            _check_geography(account, policy),
            _check_campaign_exclusion(account, policy),
            _check_suppression(
                session, account=account, contact=contact, email=primary_email, at=moment
            ),
            _check_product_readiness(session, campaign=campaign, policy=policy, at=moment),
            _check_contactability(contact, points, policy),
        )
        if failure is not None
    ]

    return EligibilityDecision(candidate_id=candidate.id, failures=failures)


def apply_eligibility(
    session: Session,
    candidate: CampaignCandidate,
    *,
    actor: Actor,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> EligibilityDecision:
    """Evaluate and move the candidate to `eligible` or `ineligible`.

    There is deliberately no override argument. A model recommendation, however confident, has
    nowhere to enter this function (§10.1, §3.5).
    """
    decision = evaluate(session, candidate, at=at)

    target = (
        CampaignCandidateState.ELIGIBLE
        if decision.is_eligible
        else CampaignCandidateState.INELIGIBLE
    )
    transition(
        session,
        candidate,
        target,
        actor=actor,
        reason=decision.summary or None,
        policy_decision=(
            "eligibility:pass"
            if decision.is_eligible
            else "eligibility:fail:" + ",".join(f.rule.value for f in decision.failures)
        ),
        correlation_id=correlation_id,
    )
    return decision
