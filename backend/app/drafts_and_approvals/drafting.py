"""Drafting a message from approved claims and stored evidence (T-054; §8.3 step 9, §10.5, §14.4).

§10.5 is a list of rules about what a message may say. This module is the place they become
structural rather than aspirational, and the shape is the argument:

**The model never writes a product sentence.** `DraftOutput` has no `body` field. The model
returns a subject, one personalization paragraph, and a list of claim IDs; the claim *wording* is
copied verbatim out of the approved claim record and the surrounding boilerplate is rendered from
a template. "A free-form product statement without a claim ID fails validation" (§10.5) is
therefore not a validation at all here — there is no field a free-form product statement could
arrive in.

**Claims are resolved, not trusted.** Every returned claim ID is looked up in the campaign's
*currently valid* set (`valid_claims_for_campaign`), so an expired, superseded, or wrong-campaign
claim fails closed before anything is written (§10.5, §14.4). Same for evidence IDs, against the
candidate's current snapshots.

**A draft is a revision, and revisions are immutable.** Drafting twice produces revision 2 and
retires revision 1; nothing here can rewrite a revision, because `create_revision` is the only
way in and it supersedes rather than updates (`T-020`). An approval binds to an exact revision,
so this is what keeps an approval meaning what it said.

Paraphrase is not implemented. `ApprovedClaim.allow_paraphrase` exists with constraints, but
nothing here asks the model to paraphrase and nothing checks that a paraphrase stayed inside its
constraints — so claims are reproduced exactly, which is the conservative half of §10.5. Widening
that is a task with its own tests, not a flag flipped here.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor, record_audit_event
from app.campaigns.candidate import CampaignCandidate
from app.campaigns.models import Campaign
from app.drafts_and_approvals.models import DraftPurpose, MessageDraft, MessageRevision
from app.drafts_and_approvals.revisions import create_revision

# Re-exported: `templates_registry` holds these so a module needing only the template
# name does not have to import this one, which calls the model gateway (`T-156`).
from app.drafts_and_approvals.templates_registry import PURPOSE_TEMPLATES, TEMPLATE_DIR
from app.model_gateway.gateway import DatabaseModelGateway
from app.model_gateway.protocol import ModelTaskRequest
from app.model_gateway.schemas import DRAFT_KEY, DraftOutput
from app.model_gateway.validation import run_validated_task
from app.products_and_claims.claim_models import ApprovedClaim
from app.products_and_claims.claims import valid_claims_for_campaign
from app.qualification.models import QualificationRun
from app.research_and_evidence.evidence import current_evidence
from app.research_and_evidence.models import EvidenceSnapshot

ENTITY_TYPE: Final = "message_revision"

TASK_NAME: Final = "draft"


class DraftingError(Exception):
    """The draft could not be produced."""


class CandidateNotDraftable(DraftingError):
    """The candidate has not been qualified, so there is nothing to draft from.

    §8.3 orders qualification (step 7) before drafting (step 9). Drafting an unqualified
    candidate would produce a message whose personalization rests on nothing anyone assessed.
    """


class UnknownCitation(DraftingError):
    """The draft cited a claim or evidence ID that is not currently valid for this candidate."""

    def __init__(self, unknown_claims: list[str], unknown_evidence: list[str]) -> None:
        self.unknown_claims = unknown_claims
        self.unknown_evidence = unknown_evidence
        parts = []
        if unknown_claims:
            parts.append(f"claim IDs not in the campaign's current valid set: {unknown_claims}")
        if unknown_evidence:
            parts.append(f"evidence IDs not stored for this candidate: {unknown_evidence}")
        super().__init__("; ".join(parts))


class MissingTemplate(DraftingError):
    """No approved template exists for this draft purpose."""


@dataclass(frozen=True, slots=True)
class DraftingInputs:
    """Exactly what the drafting prompt is shown. Every item is a stored row."""

    campaign_name: str
    candidate_id: uuid.UUID
    claims: list[ApprovedClaim]
    evidence: list[EvidenceSnapshot]

    def as_prompt_inputs(self) -> dict[str, str]:
        return {
            "campaign_name": self.campaign_name,
            "campaign_candidate_id": str(self.candidate_id),
            "approved_claims": "\n".join(
                f"{claim.claim_key}: {claim.text}" for claim in self.claims
            )
            or "(none)",
            "evidence": "\n".join(
                f"{snapshot.id}: {snapshot.supporting_excerpt_or_fact}"
                for snapshot in self.evidence
            )
            or "(none)",
        }


def build_inputs(session: Session, candidate: CampaignCandidate, *, at: datetime) -> DraftingInputs:
    """The campaign's currently valid claims and the candidate's current evidence."""
    campaign = session.get(Campaign, candidate.campaign_id)
    if campaign is None:  # pragma: no cover - the foreign key prevents this
        raise DraftingError(f"candidate {candidate.id} points at a missing campaign")

    return DraftingInputs(
        campaign_name=campaign.name,
        candidate_id=candidate.id,
        claims=valid_claims_for_campaign(
            session, product_id=campaign.product_id, campaign_id=campaign.id, at=at
        ),
        evidence=current_evidence(session, candidate.id, at=at),
    )


def resolve_citations(
    output: DraftOutput, inputs: DraftingInputs
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Turn the cited keys into row IDs, or raise.

    Returns `(claim_row_ids, evidence_ids)` in the order the model cited them — `T-020` hashes
    citation order, treating a reordering as a change rather than silently keeping an approval.
    """
    by_key = {claim.claim_key: claim for claim in inputs.claims}
    known_evidence = {str(snapshot.id): snapshot.id for snapshot in inputs.evidence}

    unknown_claims = [key for key in output.approved_claim_ids if key not in by_key]
    unknown_evidence = [value for value in output.evidence_ids if value not in known_evidence]
    if unknown_claims or unknown_evidence:
        raise UnknownCitation(unknown_claims, unknown_evidence)

    return (
        [by_key[key].id for key in output.approved_claim_ids],
        [known_evidence[value] for value in output.evidence_ids],
    )


def render_body(purpose: DraftPurpose, *, personalization: str, claims: list[ApprovedClaim]) -> str:
    """Assemble the message: template + the model's prose + verbatim approved wording.

    The claim text is inserted exactly as approved. Nothing here reformats, truncates, joins with
    connective prose, or otherwise touches it — a claim that reads awkwardly next to another is a
    problem for the person who approves the message, not something to smooth over silently.
    """
    template_name = PURPOSE_TEMPLATES.get(purpose)
    if template_name is None:
        raise MissingTemplate(
            f"no approved template for {purpose.value}; boilerplate is rendered from a template, "
            f"never generated (§10.5)"
        )

    template = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    return template.replace("{personalization}", personalization.strip()).replace(
        "{claims}", "\n\n".join(claim.text for claim in claims)
    )


def draft_message(
    session: Session,
    candidate: CampaignCandidate,
    gateway: DatabaseModelGateway,
    *,
    recipient_contact_point_id: uuid.UUID,
    prompt_version_id: uuid.UUID,
    schema_version_id: uuid.UUID,
    model_config_version_id: uuid.UUID,
    actor: Actor,
    created_by: str = "drafting-task",
    purpose: DraftPurpose = DraftPurpose.INITIAL_OUTREACH,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> MessageRevision:
    """Draft one message for a qualified candidate, as a new immutable revision.

    Raises :class:`CandidateNotDraftable` before any model call, and :class:`UnknownCitation`
    after one whose citations do not resolve. Nothing is written in either case beyond the
    `ModelRun` the gateway records.
    """
    moment = at or datetime.now(UTC)

    qualified = session.execute(
        select(QualificationRun.id).where(QualificationRun.candidate_id == candidate.id).limit(1)
    ).scalar_one_or_none()
    if qualified is None:
        raise CandidateNotDraftable(
            f"candidate {candidate.id} has no qualification run; §8.3 qualifies (step 7) before "
            f"it drafts (step 9)"
        )

    # Fail before spending a model call if the boilerplate cannot be rendered afterwards.
    if purpose not in PURPOSE_TEMPLATES:
        raise MissingTemplate(f"no approved template for {purpose.value} (§10.5)")

    inputs = build_inputs(session, candidate, at=moment)

    request = ModelTaskRequest(
        task_name=TASK_NAME,
        prompt_version_id=prompt_version_id,
        schema_version_id=schema_version_id,
        model_config_version_id=model_config_version_id,
        inputs=inputs.as_prompt_inputs(),
        campaign_id=candidate.campaign_id,
        candidate_id=candidate.id,
    )
    parsed = run_validated_task(gateway, session, request, schema_key=DRAFT_KEY, at=moment)
    if not isinstance(parsed, DraftOutput):  # pragma: no cover - the key fixes the type
        raise DraftingError(f"{DRAFT_KEY} returned {type(parsed).__name__}")

    claim_ids, evidence_ids = resolve_citations(parsed, inputs)
    cited_claims = [claim for claim in inputs.claims if claim.id in set(claim_ids)]

    draft = session.execute(
        select(MessageDraft).where(
            MessageDraft.candidate_id == candidate.id, MessageDraft.purpose == purpose
        )
    ).scalar_one_or_none()
    if draft is None:
        draft = MessageDraft(candidate_id=candidate.id, purpose=purpose)
        session.add(draft)
        session.flush()

    revision = create_revision(
        session,
        draft=draft,
        recipient_contact_point_id=recipient_contact_point_id,
        subject=parsed.subject,
        body=render_body(purpose, personalization=parsed.personalization, claims=cited_claims),
        approved_claim_ids=claim_ids,
        evidence_ids=evidence_ids,
        created_by=created_by,
        actor=actor,
        correlation_id=correlation_id,
    )

    # Counts and identifiers. The subject and body are on the revision; §15.5 keeps message
    # content out of the audit trail.
    record_audit_event(
        session,
        actor=actor,
        action="message_revision.drafted",
        entity_type=ENTITY_TYPE,
        entity_id=revision.id,
        payload={
            "candidate_id": str(candidate.id),
            "revision_number": revision.revision_number,
            "claims_cited": len(claim_ids),
            "evidence_cited": len(evidence_ids),
            "template": PURPOSE_TEMPLATES[purpose],
        },
        correlation_id=correlation_id,
    )
    return revision
