"""Validating a stored message revision (T-055; §8.3 step 10, §10.5, §15.6, §15.7).

`T-054` checks citations at the moment a draft is written. This checks the *stored* revision, and
the difference is time: a claim expires, a recipient unsubscribes, a campaign is paused, a
product's readiness lapses — all between drafting and review. A message validated only at
creation is a message validated against a world that has moved on.

Every check is deterministic and reads only database rows. Nothing here calls a model, and
`tests/test_revision_validation.py` asserts the module imports nothing from `model_gateway` — the
boundary checker cannot, because `drafts_and_approvals` is permitted that import.

**Failures accumulate.** A reviewer needs every reason a message is not ready, not whichever one
happened to be checked first — the same rule `T-045` follows for eligibility.

**Passing is not approval.** A revision that validates moves to `review_pending`; a human still
approves it (ADR-008), and §11.4 rechecks the whole contract again inside the send transaction
(`T-035c`). This is the third of those three gates, not a replacement for either.

**"No free-form product statement" is checked structurally**, not by reading the prose. `T-054`
renders every body as `personalization + cited claim texts + boilerplate`, so a body whose claim
section is not exactly the cited claims — verbatim, in order — has had something inserted. That
is a string comparison, which is the only kind of check that can honestly claim to detect an
unapproved product sentence.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor, record_audit_event
from app.campaigns.candidate import CampaignCandidate
from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import require_current_policy
from app.core.lifecycles import MessageRevisionState

# Imported as a module, not as a bare `transition` name. `drafts_and_approvals` is a registered
# *reader* of `CampaignCandidateState` (`T-140`), and the reader compensating check in
# `test_invariants.py` forbids a reader importing an owner's transition helper. Qualifying keeps
# check meaningful — aliasing the import would evade it — and says at the call site which
# lifecycle is moving: this one moves a revision, never a candidate.
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.models import MessageDraft, MessageRevision

# The template *names*, not the drafting module: importing `drafting` would pull the model
# gateway into every path that validates, and §11.3's "no agent callback" is a property worth
# being able to assert by walking imports (`T-156`).
from app.drafts_and_approvals.templates_registry import PURPOSE_TEMPLATES, TEMPLATE_DIR
from app.products_and_claims.claim_models import ApprovedClaim
from app.products_and_claims.claims import claim_is_allowed_for_campaign
from app.products_and_claims.status import get_effective_status
from app.prospects.models import Contact, ContactPoint, ContactPointType, VerificationState
from app.prospects.suppression import find_suppression
from app.research_and_evidence.models import EvidenceSnapshot

ENTITY_TYPE: Final = "message_revision"


class Check(StrEnum):
    """The §8.3 step 10 checks, named so a failure says which one refused."""

    CLAIM_CITATIONS = "claim_citations"
    CLAIM_CURRENCY = "claim_currency"
    CAMPAIGN_SCOPE = "campaign_scope"
    PRODUCT_READINESS = "product_readiness"
    EVIDENCE_CITATIONS = "evidence_citations"
    RECIPIENT_CONTACTABLE = "recipient_contactable"
    SUPPRESSION = "suppression"
    #: The structural check that the body is template + cited claims + boilerplate and nothing
    #: else — the only tractable form of "no free-form product statement" (§10.5).
    PRODUCT_STATEMENT_GROUNDING = "product_statement_grounding"
    COMPLIANCE_ELEMENTS = "compliance_elements"
    #: The structural half of GP-02 (`T-207`): a message that says something about the prospect
    #: has to cite the stored fact it rests on. `EVIDENCE_CITATIONS` checks the citations that are
    #: there; this checks that there are any.
    EVIDENCE_FOR_PERSONALIZATION = "evidence_for_personalization"


@dataclass(frozen=True, slots=True)
class ValidationFailure:
    """One check that refused, and the identifiers that decided it.

    ``inputs`` carries IDs and classifications only — never the subject, the body, or a recipient
    address (§15.5).
    """

    check: Check
    reason: str
    inputs: dict[str, str]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """The outcome of validating one revision."""

    revision_id: uuid.UUID
    failures: list[ValidationFailure]

    @property
    def is_valid(self) -> bool:
        return not self.failures

    @property
    def summary(self) -> str:
        return "; ".join(f"{failure.check.value}: {failure.reason}" for failure in self.failures)


def _cited_claims(session: Session, revision: MessageRevision) -> list[ApprovedClaim]:
    """The claims a revision cites, in the order it cited them.

    Order is preserved because `T-020` hashes it; comparing an unordered set here would let a
    reordered body validate against a hash that says it changed.
    """
    by_id = {
        claim.id: claim
        for claim in session.execute(
            select(ApprovedClaim).where(ApprovedClaim.id.in_(revision.approved_claim_ids))
        )
        .scalars()
        .all()
    }
    return [by_id[claim_id] for claim_id in revision.approved_claim_ids if claim_id in by_id]


def _check_claim_citations(
    revision: MessageRevision, claims: Sequence[ApprovedClaim]
) -> ValidationFailure | None:
    """Every cited claim ID must still resolve to a claim row."""
    missing = [
        str(claim_id)
        for claim_id in revision.approved_claim_ids
        if claim_id not in {claim.id for claim in claims}
    ]
    if not missing:
        return None
    return ValidationFailure(
        check=Check.CLAIM_CITATIONS,
        reason=f"{len(missing)} cited claim ID(s) no longer resolve to a claim record",
        inputs={"missing_claim_ids": ",".join(missing)},
    )


def _check_claim_currency(
    claims: Sequence[ApprovedClaim], at: datetime
) -> ValidationFailure | None:
    """Expired or superseded claims fail closed (§10.5), wording unchanged or not."""
    lapsed = [claim.claim_key for claim in claims if not claim.is_valid_at(at)]
    if not lapsed:
        return None
    return ValidationFailure(
        check=Check.CLAIM_CURRENCY,
        reason=(
            f"claim(s) {lapsed} are expired or superseded at {at.isoformat()}; an approved claim "
            f"that has lapsed fails closed even if its wording is unchanged (§10.5)"
        ),
        inputs={"claim_keys": ",".join(lapsed)},
    )


def _check_campaign_scope(
    session: Session, claims: Sequence[ApprovedClaim], campaign_id: uuid.UUID
) -> ValidationFailure | None:
    """§14.4's allow-list: approval for one campaign is not approval for another."""
    outside = [
        claim.claim_key
        for claim in claims
        if not claim_is_allowed_for_campaign(session, claim_id=claim.id, campaign_id=campaign_id)
    ]
    if not outside:
        return None
    return ValidationFailure(
        check=Check.CAMPAIGN_SCOPE,
        reason=f"claim(s) {outside} are not approved for this campaign (§14.4 allow-list)",
        inputs={"claim_keys": ",".join(outside)},
    )


def _check_product_readiness(
    session: Session, campaign: Campaign, policy: CampaignPolicy, at: datetime
) -> ValidationFailure | None:
    """GP-12: the readiness that justified the message must still hold."""
    status = get_effective_status(session, campaign.product_id, at=at)
    if status is None:
        return ValidationFailure(
            check=Check.PRODUCT_READINESS,
            reason="the product has no effective readiness version; readiness must be explicit",
            inputs={"readiness": "none"},
        )
    if policy.permits_readiness(status.readiness_category):
        return None
    return ValidationFailure(
        check=Check.PRODUCT_READINESS,
        reason=f"product readiness {status.readiness_category.value} is not permitted by policy",
        inputs={"readiness": status.readiness_category.value},
    )


def _check_evidence_citations(
    session: Session, revision: MessageRevision, at: datetime
) -> ValidationFailure | None:
    """Every cited evidence snapshot must still exist and not be stale (GP-02).

    **This proves the citation resolves. It does not prove the sentence follows from it** — and
    the difference is not academic. `T-071c`'s rehearsal had three independent readers compare a
    draft against the evidence above it, and all three caught the same thing: the draft said the
    account was described *"in a public announcement"* while the excerpt it pointed at said only
    *"is described as"*. Three words of provenance nobody had recorded, and every automated check
    here passed it, because every check here can ask only whether a cited row exists and is
    fresh. Entailment — does this excerpt actually support this claim — is a model-quality
    question (§19.3, `T-082`), not something a validator resolves against a database.

    So the guarantee this file provides is narrower than "every prospect statement is supported
    by evidence", and it is worth stating which one it is: **every cited snapshot is real and
    current**. A reviewer reading both texts is what closes the gap, which is an argument for the
    human in the loop rather than a gap to be embarrassed about — but only if nobody mistakes the
    check for more than it is.

    **The wider question — whether a prospect statement needs a citation at all — is a different
    check.** It was open when this was written and `T-207` closed it: see
    `_check_personalization_is_cited`, which refuses an uncited personalization. This one stays
    about the snapshots that *are* cited, because "the citation is stale" and "there is no
    citation" want different sentences in front of a reviewer.
    """
    if not revision.evidence_ids:
        # Nothing cited, nothing to verify here. Whether nothing *may* be cited is
        # `_check_personalization_is_cited` (`T-207`).
        return None

    usable = {
        snapshot.id
        for snapshot in session.execute(
            select(EvidenceSnapshot).where(EvidenceSnapshot.id.in_(revision.evidence_ids))
        )
        .scalars()
        .all()
        if snapshot.retrieved_at <= at
        and (snapshot.expires_or_refresh_by is None or snapshot.expires_or_refresh_by > at)
    }
    missing = [str(value) for value in revision.evidence_ids if value not in usable]
    if not missing:
        return None
    return ValidationFailure(
        check=Check.EVIDENCE_CITATIONS,
        reason=f"{len(missing)} cited evidence snapshot(s) are missing or stale",
        inputs={"evidence_ids": ",".join(missing)},
    )


def _check_recipient(
    point: ContactPoint | None, policy: CampaignPolicy
) -> ValidationFailure | None:
    if point is None:
        return ValidationFailure(
            check=Check.RECIPIENT_CONTACTABLE,
            reason="the revision's recipient contact point no longer exists",
            inputs={"recipient": "missing"},
        )
    if point.type is not ContactPointType.EMAIL:
        return ValidationFailure(
            check=Check.RECIPIENT_CONTACTABLE,
            reason=f"recipient is a {point.type.value} contact point, not an email address",
            inputs={"contact_point_type": point.type.value},
        )
    if not policy.require_verified_email:
        return None
    if point.verification_state is VerificationState.VERIFIED:
        return None
    return ValidationFailure(
        check=Check.RECIPIENT_CONTACTABLE,
        reason="campaign policy requires a verified address before review (§15.8)",
        inputs={"verification_state": point.verification_state.value},
    )


def _check_suppression(
    session: Session,
    *,
    point: ContactPoint | None,
    candidate: CampaignCandidate,
    at: datetime,
) -> ValidationFailure | None:
    """Every scope, unconditionally — policy may widen what it respects, never narrow it (§15.6)."""
    domain = point.value.rpartition("@")[2] if point and "@" in point.value else None
    match = find_suppression(
        session,
        email=point.value if point else None,
        contact_id=candidate.contact_id,
        account_id=candidate.account_id,
        domain=domain,
        at=at,
    )
    if match is None:
        return None
    return ValidationFailure(
        check=Check.SUPPRESSION,
        reason=(
            f"recipient is suppressed at {match.scope.value} scope (source {match.source.value}); "
            f"suppression outranks campaign configuration (§15.6)"
        ),
        inputs={"scope": match.scope.value, "source": match.source.value},
    )


def _boilerplate(draft: MessageDraft) -> str:
    """The fixed tail of the template this draft's purpose renders from."""
    template = (TEMPLATE_DIR / PURPOSE_TEMPLATES[draft.purpose]).read_text(encoding="utf-8")
    return template.split("{claims}")[1].strip()


def _check_product_statement_grounding(
    revision: MessageRevision, draft: MessageDraft, claims: Sequence[ApprovedClaim]
) -> ValidationFailure | None:
    """The body's claim section must be exactly the cited claims, verbatim and in order.

    This is what makes "a free-form product statement fails validation" (§10.5) a check rather
    than a hope: `T-054` renders `personalization + claims + boilerplate`, so if the text between
    the personalization and the boilerplate is not the cited claim texts joined, something was
    inserted that no approver saw.
    """
    if draft.purpose not in PURPOSE_TEMPLATES:
        return ValidationFailure(
            check=Check.PRODUCT_STATEMENT_GROUNDING,
            reason=f"no approved template for {draft.purpose.value}; the body cannot be verified",
            inputs={"purpose": draft.purpose.value},
        )

    expected_tail = "\n\n".join(claim.text for claim in claims)
    boilerplate = _boilerplate(draft)
    if f"{expected_tail}\n\n{boilerplate}" in revision.body:
        return None
    return ValidationFailure(
        check=Check.PRODUCT_STATEMENT_GROUNDING,
        reason=(
            "the body's claim section is not exactly the cited approved claims; a product "
            "statement nobody approved has been introduced (§10.5)"
        ),
        inputs={"claims_cited": str(len(claims))},
    )


def _personalization(
    revision: MessageRevision, draft: MessageDraft, claims: Sequence[ApprovedClaim]
) -> str | None:
    """What the model wrote *about the prospect*, or `None` if the body is not template-shaped.

    `T-054` renders `personalization + claims + boilerplate`, so everything before the claim
    section is the prospect statement. Recovered by partitioning rather than by parsing: the same
    string the grounding check looks for, used from the other side.
    """
    if draft.purpose not in PURPOSE_TEMPLATES:
        return None
    tail = f"{'\n\n'.join(claim.text for claim in claims)}\n\n{_boilerplate(draft)}"
    head, separator, _ = revision.body.partition(tail)
    if not separator:
        return None
    return head.strip()


def _check_personalization_is_cited(
    revision: MessageRevision, draft: MessageDraft, claims: Sequence[ApprovedClaim]
) -> ValidationFailure | None:
    """A message that says something about the prospect must cite stored evidence (§10.5, GP-02).

    **This is the check `T-207` found missing, and the decision it records.** `_check_evidence_
    citations` returns early on an empty list, so until now a draft could assert something about
    an account while citing *nothing* and pass every check — which is a strictly weaker guarantee
    than "evidence before persuasion", and weaker than what §10.5 and the README both describe.
    Both default draft fixtures did exactly that, and one reached a reviewer in `T-071c`.

    The specification leaves *how* to a local decision, not *whether*: §10.5 requires prospect
    statements to cite stored evidence, GP-02 is "evidence before persuasion", and `process.md`
    §4 says a new validator defaults to reject. So an uncited prospect statement is refused, and
    the alternative — permitting it and documenting the weaker promise — was not taken.

    **It refuses the absence of a citation, never the quality of one.** Whether the excerpt
    actually supports the sentence is entailment, which is §19.3 and `T-082` and is not resolvable
    against a database.

    **A body that is not template-shaped is left alone.** `_check_product_statement_grounding`
    already refuses it, and deciding which part of free-form prose is a prospect statement would
    be a guess — a second failure derived from a guess is worse than one failure derived from a
    string comparison.
    """
    if revision.evidence_ids:
        return None
    personalization = _personalization(revision, draft, claims)
    if not personalization:
        return None
    return ValidationFailure(
        check=Check.EVIDENCE_FOR_PERSONALIZATION,
        reason=(
            "this message says something about the prospect and cites no stored evidence; every "
            "prospect statement rests on a recorded fact (§10.5, GP-02)"
        ),
        # The length, never the sentence: §15.5 keeps message content out of `inputs`, and the
        # reviewer can read the body on the card.
        inputs={"personalization_characters": str(len(personalization))},
    )


def _check_compliance_elements(
    revision: MessageRevision, draft: MessageDraft
) -> ValidationFailure | None:
    """The approved boilerplate for this stage must be present, verbatim.

    What counts as compliant wording for a live send is `Q-017` and a legal owner's decision, not
    this module's. What is checkable now is that the template's text is there and unedited.
    """
    if draft.purpose not in PURPOSE_TEMPLATES:
        return ValidationFailure(
            check=Check.COMPLIANCE_ELEMENTS,
            reason=f"no approved template for {draft.purpose.value}",
            inputs={"purpose": draft.purpose.value},
        )
    if _boilerplate(draft) in revision.body:
        return None
    return ValidationFailure(
        check=Check.COMPLIANCE_ELEMENTS,
        reason="the approved boilerplate for this draft purpose is missing or altered",
        inputs={"template": PURPOSE_TEMPLATES[draft.purpose]},
    )


def validate_revision(
    session: Session, revision: MessageRevision, *, at: datetime | None = None
) -> ValidationResult:
    """Run every check and return all failures. Reads only; changes nothing.

    Raises `NoCurrentPolicy` if the campaign has no published policy — with no approved rules
    there is no basis on which to call a message valid (§10.1's reasoning, applied here).
    """
    moment = at or datetime.now(UTC)

    draft = session.get(MessageDraft, revision.draft_id)
    if draft is None:  # pragma: no cover - the foreign key prevents this
        raise ValueError(f"revision {revision.id} points at a missing draft")
    candidate = session.get(CampaignCandidate, draft.candidate_id)
    if candidate is None:  # pragma: no cover - the foreign key prevents this
        raise ValueError(f"draft {draft.id} points at a missing candidate")
    campaign = session.get(Campaign, candidate.campaign_id)
    if campaign is None:  # pragma: no cover - the foreign key prevents this
        raise ValueError(f"candidate {candidate.id} points at a missing campaign")

    policy = require_current_policy(session, campaign.id)
    claims = _cited_claims(session, revision)
    point = session.get(ContactPoint, revision.recipient_contact_point_id)

    failures = [
        failure
        for failure in (
            _check_claim_citations(revision, claims),
            _check_claim_currency(claims, moment),
            _check_campaign_scope(session, claims, campaign.id),
            _check_product_readiness(session, campaign, policy, moment),
            _check_evidence_citations(session, revision, moment),
            _check_recipient(point, policy),
            _check_suppression(session, point=point, candidate=candidate, at=moment),
            _check_product_statement_grounding(revision, draft, claims),
            _check_personalization_is_cited(revision, draft, claims),
            _check_compliance_elements(revision, draft),
        )
        if failure is not None
    ]
    return ValidationResult(revision_id=revision.id, failures=failures)


def apply_validation(
    session: Session,
    revision: MessageRevision,
    *,
    actor: Actor,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> ValidationResult:
    """Validate and move the revision to `review_pending` or `validation_failed`.

    There is no argument that skips a check and no way to force the passing transition — a
    revision reaches a reviewer because every check passed, or it does not reach one.
    """
    result = validate_revision(session, revision, at=at)

    target = (
        MessageRevisionState.REVIEW_PENDING
        if result.is_valid
        else MessageRevisionState.VALIDATION_FAILED
    )
    revisions.transition(
        session,
        revision,
        target,
        actor=actor,
        reason=result.summary or None,
        correlation_id=correlation_id,
    )

    record_audit_event(
        session,
        actor=actor,
        action="message_revision.validated",
        entity_type=ENTITY_TYPE,
        entity_id=revision.id,
        policy_decision=(
            "validation:pass"
            if result.is_valid
            else "validation:fail:" + ",".join(f.check.value for f in result.failures)
        ),
        payload={
            "revision_id": str(revision.id),
            "failed_checks": [failure.check.value for failure in result.failures],
        },
        correlation_id=correlation_id,
    )
    return result


def contact_for(session: Session, point: ContactPoint) -> Contact | None:
    """The contact behind a contact point. Small helper, kept for the dashboard's later use."""
    return session.get(Contact, point.contact_id)
