"""The §10.4 required structured output (T-051).

This is §10.4's JSON object as a typed model, field for field. The specification prints the exact
shape a qualification run must return, so this file is a transcription and not a design — a
reviewer should be able to read them side by side. `tests/test_output_schemas.py` asserts the
field set matches §10.4 exactly, in both directions, so a field cannot be quietly added or lost.

**Pydantic is the validator, and the JSON file is the artefact.** There is no `jsonschema`
dependency: Pydantic already validates and already emits JSON Schema, and a second library to
re-check what the model just checked would be one more thing to keep in step. The exported
`.json` file next to this module is what gets content-hashed and registered as a `SchemaVersion`
(§23) — a test fails if it drifts from what this model emits.

**`extra="forbid"`.** A model that returns an unexpected key has not answered the question asked;
accepting it silently is how an output nobody specified ends up in front of a reviewer.
"""

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: The stable key this schema is registered under. Versions share it (§14.5).
SCHEMA_KEY: Final = "qualification-output"

#: Dimension scores are bounded so an out-of-range score is a validation failure rather than a
#: number a reviewer has to interpret. §10.4 prints `0`; the range is the conservative reading.
SCORE_MIN: Final = 0
SCORE_MAX: Final = 5


class OpportunityType(StrEnum):
    """§10.4 `opportunity_type`, verbatim."""

    DIRECT_SALE = "direct_sale"
    PILOT = "pilot"
    STRATEGIC_PARTNERSHIP = "strategic_partnership"
    FUTURE_FOLLOW_UP = "future_follow_up"
    REJECT = "reject"


class EvidenceCompleteness(StrEnum):
    """§10.4 `evidence_completeness`, verbatim."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class SourceQualityRating(StrEnum):
    """§10.4 `source_quality`, verbatim.

    Deliberately a separate enum from `research_and_evidence.SourceQuality`: this one is the
    model's *assessment* of the evidence it was given, and that is not the same fact as the
    classification an adapter recorded when the evidence was captured.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FitDimensionScores(BaseModel):
    """§10.4 `fit_dimension_scores`. All four dimensions are required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_fit: int = Field(ge=SCORE_MIN, le=SCORE_MAX)
    buyer_relevance: int = Field(ge=SCORE_MIN, le=SCORE_MAX)
    timing: int = Field(ge=SCORE_MIN, le=SCORE_MAX)
    commercial_scale: int = Field(ge=SCORE_MIN, le=SCORE_MAX)


class QualificationOutput(BaseModel):
    """§10.4's object. Every field is required; none has a default.

    No defaults on purpose. A model that omits `human_review_required` has not said whether a
    human must look, and defaulting that to `False` would be the system answering its own safety
    question (§3.5). The same reasoning applies to the lists: an omitted `risks` is not the same
    claim as an empty one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: str
    campaign_candidate_id: str
    eligibility_failures: list[str]
    opportunity_type: OpportunityType
    fit_summary: str
    use_case: str
    buyer_role_assessment: str
    fit_dimension_scores: FitDimensionScores
    evidence_completeness: EvidenceCompleteness
    source_quality: SourceQualityRating
    #: Identifiers only. §10.5 makes every prospect statement resolve to a stored evidence ID and
    #: every product statement to an approved claim ID; free text here would bypass both.
    personalization_evidence_ids: list[str]
    applicable_approved_claim_ids: list[str]
    ambiguities: list[str]
    risks: list[str]
    missing_information: list[str]
    human_review_required: bool
