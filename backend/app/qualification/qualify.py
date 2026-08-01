"""The qualification task (T-053; §10.1 stage 2, §10.2, §10.3, §10.4, §8.5, GP-02, ADR-008).

Stage 2 of §10.1: the model interprets evidence and produces a typed recommendation. Everything
around that interpretation is deterministic, and the order is the design:

1. **Refuse an ineligible candidate.** Stage 1's hard rules (`T-045`) decide who may be assessed;
   qualifying someone those rules refused would be the model reopening a decision it does not get
   to make (§10.1).
2. **Build the inputs from stored records only.** The prompt is given evidence excerpts with
   their IDs and the campaign's currently valid approved claim IDs — nothing else. There is no
   path here for a fact that is not already a row.
3. **Run through the gateway.** Budgets, the run record, and schema validation with bounded retry
   all come from `T-050`/`T-051`; this module adds no second way to call a model.
4. **Check every citation against reality.** This is the part a schema cannot do: the output is
   *schema-valid* whether or not the evidence IDs it cites exist. `T-052`'s `unsupported_claim`
   fixture returns exactly such an output, and this is what catches it.
5. **Require human review, whatever the model says.** ADR-008. A model asking for no review has
   its request recorded and overruled.

**Model self-confidence controls nothing (§10.2).** There is no confidence field in the §10.4
schema, nothing here reads one, and the only model-supplied values that change what happens are
the citation lists — which are checked against the database rather than trusted. The scores are
carried through to a reviewer and gate nothing.

`Q-002` has not confirmed the ideal customer profile and `Q-020` has not set review thresholds,
so this module deliberately contains **no threshold at all**: no score is compared against a
number, and no classification is turned into an action. That is `T-080`'s and the dashboard's
work once real weights exist.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor, record_audit_event
from app.campaigns.candidate import CampaignCandidate
from app.campaigns.models import Campaign
from app.core.lifecycles import CampaignCandidateState
from app.model_gateway.gateway import DatabaseModelGateway
from app.model_gateway.models import ModelRun
from app.model_gateway.protocol import ModelTaskRequest
from app.model_gateway.schemas import QUALIFICATION_KEY
from app.model_gateway.schemas.qualification import QualificationOutput
from app.model_gateway.validation import run_validated_task
from app.products_and_claims.claims import valid_claims_for_campaign
from app.qualification.models import QualificationRun
from app.research_and_evidence.evidence import current_evidence
from app.research_and_evidence.models import EvidenceSnapshot

ENTITY_TYPE: Final = "qualification_run"

#: The task name recorded on every `ModelRun` this module produces.
TASK_NAME: Final = "qualification"

#: States a candidate may be qualified in. `imported` is excluded because hard eligibility runs
#: first (§8.3 step 4); the terminal states are excluded because the decision is already made.
QUALIFIABLE_STATES: Final = frozenset(
    {
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
    }
)

#: Recorded on every run. Phrased as the system's reason, not the model's.
REVIEW_REASON: Final = (
    "ADR-008: a human approves every candidate and every exact message in shadow mode and the "
    "first live pilot"
)


class QualificationError(Exception):
    """The candidate could not be qualified."""


class CandidateNotQualifiable(QualificationError):
    """The candidate has not passed hard eligibility, or its decision is already made."""


class UngroundedOutput(QualificationError):
    """The model cited evidence or claims that do not exist for this candidate.

    The output was schema-valid; it was simply not true about the database. GP-02 — "missing
    facts remain missing" — makes this a refusal rather than a warning.
    """

    def __init__(self, unknown_evidence: Sequence[str], unsupported_claims: Sequence[str]) -> None:
        self.unknown_evidence = list(unknown_evidence)
        self.unsupported_claims = list(unsupported_claims)
        parts = []
        if self.unknown_evidence:
            parts.append(f"evidence IDs not stored for this candidate: {self.unknown_evidence}")
        if self.unsupported_claims:
            parts.append(f"claim IDs not approved for this campaign: {self.unsupported_claims}")
        super().__init__("; ".join(parts))


@dataclass(frozen=True, slots=True)
class QualificationInputs:
    """Exactly what the prompt is given. Everything here came from a stored row."""

    campaign_id: uuid.UUID
    campaign_name: str
    candidate_id: uuid.UUID
    evidence: list[EvidenceSnapshot]
    approved_claim_ids: list[str]

    def as_prompt_inputs(self) -> dict[str, Any]:
        """The `{name}` values the template substitutes.

        Evidence is rendered as `id: excerpt` lines so the model has an ID to cite for every fact
        it is shown; there is deliberately no way to show it a fact without one.
        """
        return {
            "campaign_id": str(self.campaign_id),
            "campaign_name": self.campaign_name,
            "campaign_candidate_id": str(self.candidate_id),
            "approved_claim_ids": "\n".join(self.approved_claim_ids) or "(none)",
            "evidence": "\n".join(
                f"{snapshot.id}: {snapshot.supporting_excerpt_or_fact}"
                for snapshot in self.evidence
            )
            or "(none)",
        }


def build_inputs(
    session: Session, candidate: CampaignCandidate, *, at: datetime
) -> QualificationInputs:
    """Gather the stored evidence and currently valid claims for one candidate."""
    campaign = session.get(Campaign, candidate.campaign_id)
    if campaign is None:  # pragma: no cover - the foreign key prevents this
        raise QualificationError(f"candidate {candidate.id} points at a missing campaign")

    claims = valid_claims_for_campaign(
        session, product_id=campaign.product_id, campaign_id=campaign.id, at=at
    )
    return QualificationInputs(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        candidate_id=candidate.id,
        evidence=current_evidence(session, candidate.id, at=at),
        approved_claim_ids=[claim.claim_key for claim in claims],
    )


def check_grounding(output: QualificationOutput, inputs: QualificationInputs) -> None:
    """Raise unless every cited ID was one this candidate actually has.

    The check a JSON Schema cannot make. Both directions matter and only one is checked here: a
    citation that does not exist is a refusal, while *fewer* citations than available is simply a
    model that found less to say.
    """
    known_evidence = {str(snapshot.id) for snapshot in inputs.evidence}
    known_claims = set(inputs.approved_claim_ids)

    unknown_evidence = [
        evidence_id
        for evidence_id in output.personalization_evidence_ids
        if evidence_id not in known_evidence
    ]
    unsupported_claims = [
        claim_id
        for claim_id in output.applicable_approved_claim_ids
        if claim_id not in known_claims
    ]

    if unknown_evidence or unsupported_claims:
        raise UngroundedOutput(unknown_evidence, unsupported_claims)


def qualify_candidate(
    session: Session,
    candidate: CampaignCandidate,
    gateway: DatabaseModelGateway,
    *,
    prompt_version_id: uuid.UUID,
    schema_version_id: uuid.UUID,
    model_config_version_id: uuid.UUID,
    actor: Actor,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> QualificationRun:
    """Qualify one eligible candidate. Adds to ``session`` without committing.

    Raises :class:`CandidateNotQualifiable` before any model call, and :class:`UngroundedOutput`
    after one whose citations do not check out. Budget refusals, provider failures, and schema
    escalations propagate from the gateway unchanged — they are not this module's to reinterpret.
    """
    if candidate.state not in QUALIFIABLE_STATES:
        raise CandidateNotQualifiable(
            f"candidate {candidate.id} is {candidate.state.value}; qualification runs only after "
            f"hard eligibility has passed (§10.1 stage 1 before stage 2)"
        )

    moment = at or datetime.now(UTC)
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
    parsed = run_validated_task(gateway, session, request, schema_key=QUALIFICATION_KEY, at=moment)
    if not isinstance(parsed, QualificationOutput):  # pragma: no cover - the key fixes the type
        raise QualificationError(f"{QUALIFICATION_KEY} returned {type(parsed).__name__}")
    output = parsed

    check_grounding(output, inputs)

    # The run the gateway just wrote. Queried rather than threaded through
    # `run_validated_task`'s return value: that function returns the validated *output*, and
    # widening its contract so one caller can reach a row would put persistence in the validator.
    model_run_id = session.execute(
        select(ModelRun.id)
        .where(ModelRun.candidate_id == candidate.id, ModelRun.started_at == moment)
        .order_by(ModelRun.created_at.desc())
        .limit(1)
    ).scalar_one()

    run = QualificationRun(
        candidate_id=candidate.id,
        model_run_id=model_run_id,
        opportunity_type=output.opportunity_type.value,
        evidence_completeness=output.evidence_completeness.value,
        source_quality=output.source_quality.value,
        product_fit=output.fit_dimension_scores.product_fit,
        buyer_relevance=output.fit_dimension_scores.buyer_relevance,
        timing=output.fit_dimension_scores.timing,
        commercial_scale=output.fit_dimension_scores.commercial_scale,
        # ADR-008. Not `output.human_review_required` — the model does not get a vote.
        human_review_required=True,
        model_requested_no_review=not output.human_review_required,
        output=output.model_dump(mode="json"),
        review_reason=REVIEW_REASON,
        qualified_at=moment,
    )
    session.add(run)
    session.flush()

    # Counts and identifiers. The output body is on the row; §15.5 keeps prose out of the trail.
    record_audit_event(
        session,
        actor=actor,
        action="qualification_run.completed",
        entity_type=ENTITY_TYPE,
        entity_id=run.id,
        payload={
            "candidate_id": str(candidate.id),
            "opportunity_type": run.opportunity_type,
            "evidence_cited": len(output.personalization_evidence_ids),
            "claims_cited": len(output.applicable_approved_claim_ids),
            "human_review_required": True,
            "model_requested_no_review": run.model_requested_no_review,
        },
        correlation_id=correlation_id,
    )
    return run
