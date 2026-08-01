"""What the drafting task may return (T-054; specification §10.5, §14.4).

The shape here *is* the safety argument, so it is worth stating plainly: **the model does not
write product sentences.** It returns a subject, one personalization paragraph grounded in
evidence, and a list of approved claim IDs it believes apply. The claim wording that reaches the
message is copied verbatim from the approved claim record (§10.5 — "an approved claim stores
exact wording"), and the surrounding boilerplate is rendered from a template.

That is why there is no `body` field. A model that could return body text could return a product
sentence nobody approved, and no amount of downstream validation reliably detects a plausible
sentence about a product. Removing the field removes the failure mode.

`extra="forbid"` and no defaults, for the same reasons as `qualification.py`.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: The stable key this schema is registered under.
SCHEMA_KEY: Final = "draft-output"

#: A personalization paragraph is a paragraph. The cap is a guard against a model returning an
#: essay that a reviewer then has to read in full, not a style preference.
PERSONALIZATION_MAX_CHARS: Final = 800
SUBJECT_MAX_CHARS: Final = 200


class DraftOutput(BaseModel):
    """One drafting result: what to say about the prospect, and which claims apply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=SUBJECT_MAX_CHARS)

    #: Prospect-specific prose. Every factual statement in it must be supported by one of
    #: `evidence_ids` (§10.5); `T-055` validates that claim, and this task proves the IDs exist.
    personalization: str = Field(min_length=1, max_length=PERSONALIZATION_MAX_CHARS)

    #: Claim *keys* — the stable identifier, not the row ID. The drafting service resolves them
    #: against the campaign's current valid set and fails closed on anything unrecognised.
    approved_claim_ids: list[str]

    #: Evidence snapshot IDs backing `personalization`.
    evidence_ids: list[str]
