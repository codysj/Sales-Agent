"""The review queue API (T-063a; §12.3, §17.5, §15.1).

§12.3 makes the dashboard authoritative for review, and a reviewer's first question is *what is
waiting for me*. Two queues answer it: candidates awaiting a decision, and the message revisions
those decisions produced.

**Backlog age is computed, never stored.** How long a revision has been waiting is a function of
the clock, so a column would be wrong the moment after it was written and would need a job to
keep it wrong less often. It is derived from `updated_at` — which for a `review_pending`
revision is when it entered review, because the transition is the last thing that touched it —
and the reference time is a parameter, so the value is stable for a fixed clock and a test can
assert an exact number of hours rather than "roughly".

**Read-only, and that is a boundary rather than a milestone.** Approving, correcting, and editing
are `T-065` onwards. Nothing here mutates, so nothing here needs the approval permission — the
queue is `VIEW_REVIEW_QUEUE`, tier 0, and a viewer may hold it. Keeping the read and the decision
on separate permissions is what lets someone be shown the queue without being able to act on it.

**Ordering is total, not merely sensible.** Oldest-first is what a reviewer wants, but
`updated_at` ties on rows written in one transaction — and the whole seeded world is written in
one transaction. A tie-broken ordering is what makes pagination correct: without the `id`
tiebreak, two pages of a tied set can repeat a row and skip another, and the reviewer never
learns which one they missed.

**Every row carries `updated_at` as its record version.** Not a new integer column:
`T-035c`'s §11.4 recheck already compares `*_updated_at` stamps to decide whether the rows a
decision depended on have moved, and a second concurrency mechanism would be a second thing to
keep in step. What a client sends back with a later mutation is what it received here.

**It reads candidates, which `campaigns` owns.** ADR-015 permits that — `drafts_and_approvals` is
in `LIFECYCLE_READERS` for `CampaignCandidateState` — and `tests/test_invariants.py` holds it to
reading: nothing here imports `transition`.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.campaigns.approval import ApprovalRefused, approve_candidate
from app.campaigns.candidate import CampaignCandidate
from app.campaigns.decisions import (
    CandidateDecision,
    DecisionCategory,
    DecisionRefused,
    defer_candidate,
    reject_candidate,
    request_more_research,
)
from app.campaigns.models import Campaign
from app.core.lifecycles import CampaignCandidateState, MessageRevisionState
from app.drafts_and_approvals.editing import EditRefused, edit_revision
from app.drafts_and_approvals.models import MessageDraft, MessageRevision
from app.identity.dependencies import db_session, requires, requires_bearer
from app.identity.rbac import Permission
from app.identity.sessions import Principal
from app.products_and_claims.claims import valid_claims_for_campaign
from app.products_and_claims.models import Product, ReadinessCategory
from app.products_and_claims.status import get_effective_status
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from app.prospects.suppression import is_suppressed
from app.qualification.models import QualificationRun
from app.research_and_evidence.evidence import current_evidence
from app.research_and_evidence.models import SourceQuality, SourceType

router = APIRouter(prefix="/api/review", tags=["review"])

#: Rows per page. A ceiling rather than a preference: an unbounded page is a query whose cost the
#: caller chooses, and a reviewer cannot read a thousand cards anyway.
MAX_PAGE_SIZE: Final = 100
DEFAULT_PAGE_SIZE: Final = 25

#: The queue's total order: oldest first, `id` breaking the tie.
#:
#: A named constant so a test can compile it and assert both keys are there. Asserting the
#: *behaviour* is not enough — a seeded world is small, and Postgres will often return a stable
#: order for a handful of tied rows whether or not you asked for one. A control that removed the
#: tiebreak passed every pagination test, which is exactly the "reads as a pass" failure
#: `process.md` §5 warns about; the structural assertion is what actually catches it.
QUEUE_ORDER: Final = (CampaignCandidate.updated_at.asc(), CampaignCandidate.id.asc())


class CandidateRow(BaseModel):
    """One queue entry: enough to choose what to open, not enough to decide.

    §12.3's review card wants evidence, product status, claims, and the exact revision. None of
    that is here on purpose — a list endpoint that returned everything a decision needs would
    invite deciding from the list, and the card is `T-064`.
    """

    model_config = ConfigDict(frozen=True)

    candidate_id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_name: str
    account_name: str
    account_domain: str
    contact_name: str | None
    state: CampaignCandidateState
    #: The record version a later mutation sends back for optimistic concurrency. See the module
    #: docstring: `updated_at`, the same stamp §11.4's recheck compares.
    record_version: datetime


class CandidatePage(BaseModel):
    """One page, and enough to ask for the next without guessing."""

    model_config = ConfigDict(frozen=True)

    rows: list[CandidateRow]
    total: int
    limit: int
    offset: int


@router.get("/candidates", response_model=CandidatePage, summary="Candidates awaiting review")
def list_candidates(
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires(Permission.VIEW_REVIEW_QUEUE))],
    campaign_id: Annotated[uuid.UUID | None, Query()] = None,
    state: Annotated[CampaignCandidateState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CandidatePage:
    """Candidates waiting on a person, oldest first.

    ``principal`` is unused in the body and required in the signature: it is what runs the
    authorization, and naming it makes that visible at the endpoint rather than hidden in a
    decorator someone could remove without the route looking different.
    """
    filters = []
    if campaign_id is not None:
        filters.append(CampaignCandidate.campaign_id == campaign_id)
    if state is not None:
        filters.append(CampaignCandidate.state == state)
    else:
        # The queue is what is *waiting*. Without a state filter a caller would otherwise get
        # ineligible and already-approved candidates mixed in, and the count would answer a
        # question nobody asked.
        filters.append(CampaignCandidate.state == CampaignCandidateState.REVIEW_PENDING)

    base = (
        select(
            CampaignCandidate.id,
            CampaignCandidate.campaign_id,
            Campaign.name,
            Account.name,
            Account.domain,
            Contact.full_name,
            CampaignCandidate.state,
            CampaignCandidate.updated_at,
        )
        .join(Campaign, Campaign.id == CampaignCandidate.campaign_id)
        .join(Account, Account.id == CampaignCandidate.account_id)
        .outerjoin(Contact, Contact.id == CampaignCandidate.contact_id)
        .where(*filters)
    )

    total = len(session.execute(select(CampaignCandidate.id).where(*filters)).all())

    rows = session.execute(
        # `id` breaks the tie. `updated_at` alone is not a total order — a seeded world is
        # written in one transaction, so every row shares a stamp — and pagination over a
        # non-total order repeats rows and skips others silently.
        base.order_by(*QUEUE_ORDER).limit(limit).offset(offset)
    ).all()

    return CandidatePage(
        rows=[
            CandidateRow(
                candidate_id=row[0],
                campaign_id=row[1],
                campaign_name=row[2],
                account_name=row[3],
                account_domain=row[4],
                contact_name=row[5],
                state=row[6],
                record_version=row[7],
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


REVISION_ORDER: Final = (MessageRevision.updated_at.asc(), MessageRevision.id.asc())
"""The revision queue's total order. Same shape and same reason as `QUEUE_ORDER`."""


class RevisionRow(BaseModel):
    """One revision waiting on a reviewer.

    Carries the subject but **not** the body: a queue is for choosing what to open, and a list
    that showed the whole message would invite approving from the list. The body, its evidence,
    and its claims are the review card's (`T-064`).
    """

    model_config = ConfigDict(frozen=True)

    revision_id: uuid.UUID
    candidate_id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_name: str
    revision_number: int
    subject: str
    state: MessageRevisionState
    #: `None` when the candidate has no qualification run — possible for a revision written
    #: through a path that did not qualify first, and reported as unknown rather than guessed.
    opportunity_type: str | None
    #: Whole hours waiting. Integer because a reviewer sorts and filters on it; the exact
    #: microsecond is noise, and rounding it here keeps the API from implying a precision the
    #: number does not have.
    backlog_age_hours: int
    record_version: datetime


class RevisionPage(BaseModel):
    """One page of the revision queue."""

    model_config = ConfigDict(frozen=True)

    rows: list[RevisionRow]
    total: int
    limit: int
    offset: int


def backlog_age_hours(updated_at: datetime, *, now: datetime) -> int:
    """Whole hours ``updated_at`` has been waiting at ``now``.

    Floored at zero. A negative age would mean a row stamped in the future — clock skew between
    the database and the API — and reporting "-3 hours waiting" would be worse than reporting
    nothing at all, because a reviewer would believe it.
    """
    return max(0, int((now - updated_at).total_seconds() // 3600))


@router.get("/revisions", response_model=RevisionPage, summary="Revisions awaiting review")
def list_revisions(
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires(Permission.VIEW_REVIEW_QUEUE))],
    campaign_id: Annotated[uuid.UUID | None, Query()] = None,
    state: Annotated[MessageRevisionState | None, Query()] = None,
    opportunity_type: Annotated[str | None, Query(max_length=50)] = None,
    min_age_hours: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RevisionPage:
    """Revisions waiting on a person, longest-waiting first."""
    now = datetime.now(UTC)

    filters = [
        MessageRevision.state
        == (state if state is not None else MessageRevisionState.REVIEW_PENDING)
    ]
    if campaign_id is not None:
        filters.append(CampaignCandidate.campaign_id == campaign_id)
    if opportunity_type is not None:
        filters.append(QualificationRun.opportunity_type == opportunity_type)
    if min_age_hours is not None:
        # Expressed as a cutoff on the stamp rather than as arithmetic on every row, so the
        # database can use the index and the filter means the same thing as the reported age.
        filters.append(MessageRevision.updated_at <= now - timedelta(hours=min_age_hours))

    base = (
        select(
            MessageRevision.id,
            CampaignCandidate.id,
            CampaignCandidate.campaign_id,
            Campaign.name,
            MessageRevision.revision_number,
            MessageRevision.subject,
            MessageRevision.state,
            QualificationRun.opportunity_type,
            MessageRevision.updated_at,
        )
        .join(MessageDraft, MessageDraft.id == MessageRevision.draft_id)
        .join(CampaignCandidate, CampaignCandidate.id == MessageDraft.candidate_id)
        .join(Campaign, Campaign.id == CampaignCandidate.campaign_id)
        # Outer: a candidate may have no qualification run, and dropping the revision entirely
        # would hide work from the reviewer rather than showing it with an unknown type.
        .outerjoin(QualificationRun, QualificationRun.candidate_id == CampaignCandidate.id)
        .where(*filters)
    )

    total = len(session.execute(base).all())
    rows = session.execute(base.order_by(*REVISION_ORDER).limit(limit).offset(offset)).all()

    return RevisionPage(
        rows=[
            RevisionRow(
                revision_id=row[0],
                candidate_id=row[1],
                campaign_id=row[2],
                campaign_name=row[3],
                revision_number=row[4],
                subject=row[5],
                state=row[6],
                opportunity_type=row[7],
                backlog_age_hours=backlog_age_hours(row[8], now=now),
                record_version=row[8],
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- §12.3 items 1-5: everything the review card shows (T-149) -----------------------------------

#: Strongest evidence first. §12.3 item 2 asks for "strongest evidence", and a card that led with
#: whatever the database returned first would make a reviewer hunt for the reason to act.
#: Ordering by quality then recency, with `id` closing the tie so the order is total.
EVIDENCE_RANK: Final[dict[SourceQuality, int]] = {
    SourceQuality.HIGH: 0,
    SourceQuality.MEDIUM: 1,
    SourceQuality.LOW: 2,
}


class EvidenceRow(BaseModel):
    """One stored fact, with the provenance §14.3 requires a reviewer to see."""

    model_config = ConfigDict(frozen=True)

    evidence_id: uuid.UUID
    excerpt: str
    source_type: SourceType
    #: §12.3 item 2 names both explicitly: a fact is only as good as where it came from and when.
    source_quality: SourceQuality
    retrieved_at: datetime
    expires_or_refresh_by: datetime | None
    contains_personal_or_confidential_data: bool


class ClaimRow(BaseModel):
    """One approved claim currently usable for this campaign (§10.5)."""

    model_config = ConfigDict(frozen=True)

    claim_id: uuid.UUID
    claim_key: str
    version: int
    text: str
    expires_or_review_by: datetime | None


class RevisionDetail(BaseModel):
    """The exact revision a reviewer would act on (§12.3 item 5).

    The full body, unlike the queue row — this *is* the place a reviewer reads the message, and
    approving without seeing exactly what will be sent is the failure ADR-008 exists to prevent.
    """

    model_config = ConfigDict(frozen=True)

    revision_id: uuid.UUID
    revision_number: int
    subject: str
    body: str
    state: MessageRevisionState
    approved_claim_ids: list[uuid.UUID]
    evidence_ids: list[uuid.UUID]
    content_hash: str
    record_version: datetime


class SuppressionWarning(BaseModel):
    """§12.3 item 4. Two scopes, reported separately because they mean different things."""

    model_config = ConfigDict(frozen=True)

    contact_suppressed: bool
    account_suppressed: bool

    @property
    def any_suppressed(self) -> bool:
        return self.contact_suppressed or self.account_suppressed


#: The only verification state a candidate may be approved for. ADR-008 approves an exact
#: recipient; approving an address nobody has verified would put the reputation risk that decision
#: exists to manage onto a guess. `Rule.CONTACTABILITY` already refuses a candidate without one
#: long before review, and `T-055`'s `RECIPIENT_CONTACTABLE` refuses a revision written to one —
#: this is the third guard, at the moment of choosing.
APPROVABLE_VERIFICATION: Final = VerificationState.VERIFIED


def _is_approvable(point: ContactPoint) -> bool:
    return point.verification_state is APPROVABLE_VERIFICATION


class ContactPointRow(BaseModel):
    """One address a candidate could be approved for (§12.3 item 1, ADR-008).

    The verification state is on the row rather than filtered on: an unverified address is shown
    and refused, not hidden. A reviewer who cannot see the mailbox they expected has no way to
    tell "this address is unusable" from "the system does not know about it", and those want
    different actions.
    """

    model_config = ConfigDict(frozen=True)

    contact_point_id: uuid.UUID
    type: ContactPointType
    value: str
    verification_state: VerificationState
    #: Whether `T-154a`'s approve endpoint would accept it. Derived here so the dashboard does not
    #: have to re-implement the rule and disagree with the server about it.
    approvable: bool


class CandidateDetail(BaseModel):
    """§12.3 items 1-5, and deliberately not 6 or 7.

    Items 6 and 7 — the actions and the structured correction reason — are things a reviewer
    *does*, and this endpoint returns nothing that does anything. Approving, rejecting,
    deferring, editing, and requesting more research are `T-065` onwards; a read endpoint that
    shipped an action list would be describing authority it does not enforce.
    """

    model_config = ConfigDict(frozen=True)

    # Item 1.
    candidate_id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_name: str
    account_name: str
    account_domain: str
    contact_name: str | None
    contact_role: str | None
    #: ADR-008 approves an exact recipient, so the reviewer has to be shown the choices. Empty
    #: when the candidate has no contact, or the contact has no recorded address.
    contact_points: list[ContactPointRow]
    state: CampaignCandidateState
    opportunity_type: str | None
    # Item 2.
    evidence: list[EvidenceRow]
    # Item 3.
    product_name: str
    product_readiness: ReadinessCategory | None
    product_readiness_summary: str | None
    approved_claims: list[ClaimRow]
    # Item 4.
    suppression: SuppressionWarning
    #: §12.3 item 4 also asks for the existing CRM relationship. There is no CRM adapter: ADR-004
    #: makes HubSpot conditional on `Q-001`, and gate **G-05** is locked. `None` means *nobody
    #: asked a CRM*, which is the truth — reporting "no relationship" would be an answer this
    #: system is in no position to give, and a reviewer might act on it.
    crm_relationship: None = None
    # Item 5.
    current_revision: RevisionDetail | None
    #: What happens on approval, in words. Shadow mode sends nothing (§19.6, gate **G-07**), and
    #: a card that did not say so would let a reviewer believe they had just sent an email.
    what_happens_next: str
    record_version: datetime


#: The sentence the card shows for "what will happen next" while nothing can be sent.
SHADOW_MODE_OUTCOME: Final = (
    "Nothing is sent. This build runs in shadow mode: approving records the decision and "
    "creates no outbound message. Live sending is gated (G-07) and needs a separate, explicit "
    "authorization."
)


@router.get(
    "/candidates/{candidate_id}",
    response_model=CandidateDetail,
    summary="Everything the review card shows for one candidate",
)
def get_candidate(
    candidate_id: uuid.UUID,
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires(Permission.VIEW_REVIEW_QUEUE))],
) -> CandidateDetail:
    """§12.3 items 1-5 for one candidate. Returns nothing that acts."""
    now = datetime.now(UTC)

    candidate = session.get(CampaignCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such candidate")

    campaign = session.get(Campaign, candidate.campaign_id)
    account = session.get(Account, candidate.account_id)
    if campaign is None or account is None:  # pragma: no cover - foreign keys prevent this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such candidate")
    product = session.get(Product, campaign.product_id)
    contact = session.get(Contact, candidate.contact_id) if candidate.contact_id else None
    # Ordered so two reads of the same candidate present the choices identically — a list that
    # reordered itself would move the option under a reviewer's cursor between renders.
    points = (
        session.execute(
            select(ContactPoint)
            .where(ContactPoint.contact_id == contact.id)
            .order_by(ContactPoint.type.asc(), ContactPoint.value.asc())
        )
        .scalars()
        .all()
        if contact is not None
        else []
    )

    readiness = get_effective_status(session, campaign.product_id, at=now)
    claims = valid_claims_for_campaign(
        session, product_id=campaign.product_id, campaign_id=campaign.id, at=now
    )
    snapshots = sorted(
        current_evidence(session, candidate.id, at=now),
        key=lambda row: (EVIDENCE_RANK[row.source_quality], -row.retrieved_at.timestamp(), row.id),
    )
    opportunity_type = session.execute(
        select(QualificationRun.opportunity_type)
        .where(QualificationRun.candidate_id == candidate.id)
        .order_by(QualificationRun.qualified_at.desc(), QualificationRun.id.asc())
        .limit(1)
    ).scalar_one_or_none()

    revision = session.execute(
        select(MessageRevision)
        .join(MessageDraft, MessageDraft.id == MessageRevision.draft_id)
        .where(MessageDraft.candidate_id == candidate.id)
        # The latest revision is the one a reviewer acts on: editing supersedes (§10.5, `T-065`),
        # so an older one is history rather than a choice.
        .order_by(MessageRevision.revision_number.desc())
        .limit(1)
    ).scalar_one_or_none()

    return CandidateDetail(
        candidate_id=candidate.id,
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        account_name=account.name,
        account_domain=account.domain,
        contact_name=contact.full_name if contact else None,
        contact_role=contact.role_title if contact else None,
        contact_points=[
            ContactPointRow(
                contact_point_id=point.id,
                type=point.type,
                value=point.value,
                verification_state=point.verification_state,
                approvable=_is_approvable(point),
            )
            for point in points
        ],
        state=candidate.state,
        opportunity_type=opportunity_type,
        evidence=[
            EvidenceRow(
                evidence_id=row.id,
                excerpt=row.supporting_excerpt_or_fact,
                source_type=row.source_type,
                source_quality=row.source_quality,
                retrieved_at=row.retrieved_at,
                expires_or_refresh_by=row.expires_or_refresh_by,
                contains_personal_or_confidential_data=(row.contains_personal_or_confidential_data),
            )
            for row in snapshots
        ],
        product_name=product.name if product else "",
        product_readiness=readiness.readiness_category if readiness else None,
        product_readiness_summary=readiness.summary if readiness else None,
        approved_claims=[
            ClaimRow(
                claim_id=claim.id,
                claim_key=claim.claim_key,
                version=claim.version,
                text=claim.text,
                expires_or_review_by=claim.expires_or_review_by,
            )
            for claim in claims
        ],
        suppression=SuppressionWarning(
            contact_suppressed=(
                is_suppressed(session, contact_id=contact.id, at=now) if contact else False
            ),
            account_suppressed=is_suppressed(session, account_id=account.id, at=now),
        ),
        current_revision=(
            RevisionDetail(
                revision_id=revision.id,
                revision_number=revision.revision_number,
                subject=revision.subject,
                body=revision.body,
                state=revision.state,
                approved_claim_ids=list(revision.approved_claim_ids),
                evidence_ids=list(revision.evidence_ids),
                content_hash=revision.content_hash,
                record_version=revision.updated_at,
            )
            if revision is not None
            else None
        ),
        what_happens_next=SHADOW_MODE_OUTCOME,
        record_version=candidate.updated_at,
    )


# --- editing: revision N+1, and N left exactly as it was (T-065a) --------------------------------


class EditRequest(BaseModel):
    """What a reviewer changed, and why.

    ``correction_reason`` is required with no default: §12.3 item 7 asks for a structured reason,
    and an edit nobody can explain later is an edit nobody can review. Citations are optional and
    `None` means *unchanged* — silently dropping the claim a sentence rests on would fail
    `T-055`'s grounding check for a reason the reviewer never chose.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    correction_reason: str = Field(min_length=1, max_length=500)
    approved_claim_ids: list[uuid.UUID] | None = None
    evidence_ids: list[uuid.UUID] | None = None
    #: The `record_version` the reviewer was shown. Optimistic concurrency: if the revision moved
    #: since the card was rendered, the edit is refused rather than applied to text nobody read.
    record_version: datetime | None = None


class EditResponse(BaseModel):
    """The new revision, and what the edit did to the old one."""

    model_config = ConfigDict(frozen=True)

    revision: RevisionDetail
    superseded_revision_id: uuid.UUID
    revoked_approvals: list[uuid.UUID]
    expired_approvals: list[uuid.UUID]
    #: `False` means the edit was saved *and* failed validation — the revision exists in
    #: `validation_failed` and the reviewer needs to see why, which is what `failed_checks` is.
    is_valid: bool
    failed_checks: list[str]


@router.post(
    "/revisions/{revision_id}/edit",
    response_model=EditResponse,
    summary="Edit a draft, creating the next immutable revision",
)
def edit_revision_endpoint(
    revision_id: uuid.UUID,
    request: EditRequest,
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires_bearer(Permission.CORRECT_CANDIDATE))],
) -> EditResponse:
    """§10.5: an edit creates revision N+1 and leaves N exactly as it was.

    `requires_bearer`, not `requires`: this is a state-changing route, and a cookie is what a
    CSRF attack rides on. See `identity.dependencies` — the exposure is removed until `T-070`
    adds real protection, rather than accepted on trust.

    The actor comes from the session (§12.2), never from the request body. Committed here rather
    than by the caller: the retired approval, the superseded revision, the new one, and its
    validation are one decision, and a half-applied edit is the state this must never leave.
    """
    revision = session.get(MessageRevision, revision_id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such revision")

    if request.record_version is not None and request.record_version != revision.updated_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "this revision changed since it was loaded; reload the card before editing so "
                "you are changing the text you read"
            ),
        )

    try:
        result = edit_revision(
            session,
            revision,
            subject=request.subject,
            body=request.body,
            correction_reason=request.correction_reason,
            actor=principal.actor,
            approved_claim_ids=request.approved_claim_ids,
            evidence_ids=request.evidence_ids,
        )
    except EditRefused as refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refusal)) from refusal

    session.commit()

    created = result.revision
    return EditResponse(
        revision=RevisionDetail(
            revision_id=created.id,
            revision_number=created.revision_number,
            subject=created.subject,
            body=created.body,
            state=created.state,
            approved_claim_ids=list(created.approved_claim_ids),
            evidence_ids=list(created.evidence_ids),
            content_hash=created.content_hash,
            record_version=created.updated_at,
        ),
        superseded_revision_id=result.superseded_revision_id,
        revoked_approvals=result.revoked_approvals,
        expired_approvals=result.expired_approvals,
        is_valid=result.is_valid,
        failed_checks=[failure.check.value for failure in result.validation.failures],
    )


# --- §12.3 item 6: the decisions a reviewer takes -------------------------------------------------
#
# `T-066a` built these decisions; this is the surface they are reachable from. Three things are
# deliberate and shared by both routes:
#
# * **`requires_bearer`, not `requires`.** They change state, and a cookie is what a CSRF attack
#   rides on. Same reasoning as the edit route — the exposure is removed until `T-070` adds real
#   protection, rather than accepted on trust.
# * **The record version is checked.** The card was rendered at some moment; if the candidate moved
#   since, the answer is `409` and a reload, not a decision applied to a state nobody read. A
#   reviewer rejecting a candidate somebody else already approved is exactly the race worth losing
#   loudly.
# * **The category is a typed enum field**, so a request naming something outside §10.6's eleven is
#   refused by the schema before any handler runs — one place, not one check per route.


class RejectRequest(BaseModel):
    """Why this candidate is being rejected (§10.6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: No default. §10.6 structures the reason so the feedback is analysable, and a default would
    #: make one category the most common value in the dataset for no reason anybody chose.
    category: DecisionCategory
    notes: str | None = Field(default=None, max_length=4000)
    record_version: datetime | None = None


class DeferRequest(BaseModel):
    """What this candidate is waiting for (§10.6's eleventh category)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    until_date: date | None = None
    until_event: str | None = Field(default=None, max_length=500)
    #: Defaults to §10.6's eleventh, which is what a plain "not now" is. A reviewer deferring
    #: *because* the product is not ready may say so, and that is the more useful row.
    category: DecisionCategory = DecisionCategory.DEFER_UNTIL_DATE_OR_EVENT
    notes: str | None = Field(default=None, max_length=4000)
    record_version: datetime | None = None


class DecisionResponse(BaseModel):
    """What was recorded, so the dashboard can show it back rather than assume it."""

    model_config = ConfigDict(frozen=True)

    decision_id: uuid.UUID
    candidate_id: uuid.UUID
    kind: str
    category: DecisionCategory
    notes: str | None
    defer_until_date: date | None
    defer_until_event: str | None
    state: CampaignCandidateState
    record_version: datetime


def _candidate_for_decision(
    session: Session, candidate_id: uuid.UUID, record_version: datetime | None
) -> CampaignCandidate:
    """The candidate, or the refusal that stops a decision being applied to unread state."""
    candidate = session.get(CampaignCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such candidate")
    if record_version is not None and record_version != candidate.updated_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "this candidate changed since it was loaded; reload the card before deciding so "
                "you are deciding about the state you read"
            ),
        )
    return candidate


def _describe(decision: CandidateDecision, candidate: CampaignCandidate) -> DecisionResponse:
    return DecisionResponse(
        decision_id=decision.id,
        candidate_id=candidate.id,
        kind=decision.kind.value,
        category=decision.category,
        notes=decision.notes,
        defer_until_date=decision.defer_until_date,
        defer_until_event=decision.defer_until_event,
        state=candidate.state,
        record_version=candidate.updated_at,
    )


@router.post(
    "/candidates/{candidate_id}/reject",
    response_model=DecisionResponse,
    summary="Reject a candidate, with a structured reason",
)
def reject_candidate_endpoint(
    candidate_id: uuid.UUID,
    request: RejectRequest,
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires_bearer(Permission.CORRECT_CANDIDATE))],
) -> DecisionResponse:
    """§8.2's `review_pending -> rejected`, with §10.6's category recorded against it."""
    candidate = _candidate_for_decision(session, candidate_id, request.record_version)
    try:
        decision = reject_candidate(
            session,
            candidate,
            category=request.category,
            actor=principal.actor,
            notes=request.notes,
        )
    except DecisionRefused as refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refusal)) from refusal

    session.commit()
    return _describe(decision, candidate)


@router.post(
    "/candidates/{candidate_id}/defer",
    response_model=DecisionResponse,
    summary="Defer a candidate until a date or an event",
)
def defer_candidate_endpoint(
    candidate_id: uuid.UUID,
    request: DeferRequest,
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires_bearer(Permission.CORRECT_CANDIDATE))],
) -> DecisionResponse:
    """§8.2's `review_pending -> deferred`. A deferral with no waypoint is `409`, not a candidate
    that quietly leaves review with nothing to bring it back."""
    candidate = _candidate_for_decision(session, candidate_id, request.record_version)
    try:
        decision = defer_candidate(
            session,
            candidate,
            actor=principal.actor,
            until_date=request.until_date,
            until_event=request.until_event,
            category=request.category,
            notes=request.notes,
        )
    except DecisionRefused as refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refusal)) from refusal

    session.commit()
    return _describe(decision, candidate)


class ApproveRequest(BaseModel):
    """Which address this candidate is approved for (ADR-008)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: No default and no derivation. ADR-008 approves an *exact* recipient, so the address is part
    #: of the approver's decision — deriving it from the contact would mean the system chose and
    #: the approver ratified something they were never shown.
    recipient_contact_point_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=4000)
    record_version: datetime | None = None


class ApproveResponse(BaseModel):
    """What was approved, in the terms the approver chose it."""

    model_config = ConfigDict(frozen=True)

    candidate_id: uuid.UUID
    recipient_contact_point_id: uuid.UUID
    #: Echoed so the dashboard can show *the address* back rather than an identifier. An approval
    #: confirmed as a UUID is an approval nobody can check by reading.
    recipient: str
    state: CampaignCandidateState
    record_version: datetime


@router.post(
    "/candidates/{candidate_id}/approve",
    response_model=ApproveResponse,
    summary="Approve a candidate for outreach to an exact recipient",
)
def approve_candidate_endpoint(
    candidate_id: uuid.UUID,
    request: ApproveRequest,
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires_bearer(Permission.APPROVE_CANDIDATE))],
) -> ApproveResponse:
    """§8.3 step 9: candidate approval, which queues the drafting job.

    **`APPROVE_CANDIDATE`, not `CORRECT_CANDIDATE`.** §7.4 puts this at tier 4 — the approval that
    lets an external effect happen at all — while rejecting and deferring are tier-3 reversible
    internal changes. The two are deliberately different permissions, so a role that may tidy the
    queue cannot start outreach.

    **The recipient is checked against this candidate's contact.** A contact point id is just a
    UUID; without this, an approver could name an address belonging to somebody else entirely and
    the drafting job would write to it. §8.1 makes the candidate a `campaign + account + contact`
    membership, so "this candidate's contact" is exactly the right scope.

    **An unverified address is refused.** Approving one would put the reputation risk ADR-008
    exists to manage onto a guess about whether the mailbox is real.

    Nothing is sent. Approval queues drafting; shadow mode holds, and live sending stays behind
    **G-07**.
    """
    candidate = _candidate_for_decision(session, candidate_id, request.record_version)

    point = session.get(ContactPoint, request.recipient_contact_point_id)
    if point is None or point.contact_id != candidate.contact_id:
        # One answer for "no such address" and "not this candidate's address": distinguishing them
        # would let a caller probe which contact point ids exist.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="that recipient does not belong to this candidate's contact",
        )
    if not _is_approvable(point):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{point.value} is {point.verification_state.value}; an approval names an exact "
                f"recipient (ADR-008), and an unverified address is a guess about whether the "
                f"mailbox is real"
            ),
        )

    try:
        approve_candidate(
            session,
            candidate,
            recipient_contact_point_id=point.id,
            actor=principal.actor,
            reason=request.reason,
        )
    except ApprovalRefused as refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refusal)) from refusal

    session.commit()
    return ApproveResponse(
        candidate_id=candidate.id,
        recipient_contact_point_id=point.id,
        recipient=point.value,
        state=candidate.state,
        record_version=candidate.updated_at,
    )


class RequestResearchRequest(BaseModel):
    """Why more evidence is wanted (§10.6, ADR-022)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: No default. Every other reviewer decision carries a structured reason, and "why did somebody
    #: want more evidence here" is exactly the evaluation data §10.6 exists to collect — a campaign
    #: whose candidates repeatedly need more is telling you about its research configuration.
    category: DecisionCategory
    notes: str | None = Field(default=None, max_length=4000)
    record_version: datetime | None = None


@router.post(
    "/candidates/{candidate_id}/request-research",
    response_model=DecisionResponse,
    summary="Ask for more evidence about a candidate that stays in review",
)
def request_more_research_endpoint(
    candidate_id: uuid.UUID,
    request: RequestResearchRequest,
    session: Annotated[Session, Depends(db_session)],
    principal: Annotated[Principal, Depends(requires_bearer(Permission.CORRECT_CANDIDATE))],
) -> DecisionResponse:
    """ADR-022: this queues an evidence pass and moves the candidate nowhere.

    §8.2 offers no edge from `review_pending` back to `research_pending`, so unlike reject and
    defer this decision leaves the candidate exactly where the reviewer is looking at it — the
    response still carries `state` so a dashboard can show that rather than assume it.

    A pass already in flight is `409` with the reason, not a second queued pass: a reviewer who
    clicks twice wants one more pass, not two.
    """
    candidate = _candidate_for_decision(session, candidate_id, request.record_version)
    try:
        decision = request_more_research(
            session,
            candidate,
            category=request.category,
            actor=principal.actor,
            notes=request.notes,
        )
    except DecisionRefused as refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refusal)) from refusal

    session.commit()
    return _describe(decision, candidate)
