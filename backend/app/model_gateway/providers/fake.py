"""The deterministic fake model (T-052; GP-06, §19.2, §15.4, ADR-017).

The whole Stage 1 pipeline has to be testable with no provider, and a fake that *invents* output
would make a green pipeline meaningless. So this adapter is a lookup, not a generator: a
directory of JSON fixtures, keyed by the SHA-256 of the rendered prompt, and nothing else.

**No fixture, no output.** An unmatched prompt raises `NoFixtureForPrompt` rather than returning
something plausible. A fake that answers anything would let a test pass while exercising a prompt
nobody wrote an expectation for. A fixture set may declare one entry with `"match": "default"` —
explicitly, in the file, where a reviewer sees it — for callers that genuinely do not care which
prompt arrived.

**Determinism is structural, not promised.** Output is a pure function of the prompt bytes and
the fixture files: no clock, no randomness, no UUID, no iteration over a set, no dependence on
dictionary ordering. `tests/test_fake_model.py` asserts the module imports none of those, and
runs the adapter in two subprocesses under different `PYTHONHASHSEED` values to prove the
outputs are byte-identical across processes and not merely within one.

**Five deliberate failure modes**, because the pipeline's error paths need to be exercised as
precisely as its happy path (§19.2). Each is declared by a fixture, so triggering one is a
configuration change rather than a code change:

| Mode | What the caller sees |
|---|---|
| `schema_invalid` | Well-formed JSON that violates the §10.4 schema — `T-051` escalates it |
| `refusal` | A refusal in prose, which is also not valid output |
| `timeout` | `TimeoutError` — the gateway records `provider_error` |
| `unsupported_claim` | Schema-valid output citing a claim ID that does not exist |
| `injected_instruction_echo` | Schema-valid output echoing an instruction from its input |

The last two are the interesting ones: both are *schema-valid*, so nothing upstream of the claim
and evidence validators (`T-055`) will catch them. They exist so those validators have something
real to fail on.

This adapter replaces `EchoModelAdapter` as the fixture-driven fake; the `ModelProviderAdapter`
contract is unchanged, which is the point of having the contract.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.model_gateway.protocol import ProviderResponse

#: Fixture files above this size are refused unread. A local file is not a fetch, but an
#: unbounded parser input is an unbounded parser input (§15.3's reasoning, applied locally).
MAX_FIXTURE_BYTES: Final = 256 * 1024

#: The literal a fixture uses to say "any prompt". Spelled out in the file, never implied.
DEFAULT_MATCH: Final = "default"

#: Recorded on every run this adapter serves. Not a vendor name — there is no vendor (§18.4).
MODEL_NAME: Final = "deterministic-fake"

#: A `match` value that is already a SHA-256 digest is used as-is; anything else is prompt text.
_IS_DIGEST: Final = re.compile(r"[0-9a-f]{64}")


class FailureMode(StrEnum):
    """The five §19.2 failure paths a fixture may request."""

    SCHEMA_INVALID = "schema_invalid"
    REFUSAL = "refusal"
    TIMEOUT = "timeout"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    INJECTED_INSTRUCTION_ECHO = "injected_instruction_echo"


class FakeModelError(Exception):
    """The fake could not serve a request."""


class NoFixtureForPrompt(FakeModelError):
    """No fixture matches this prompt, and the set declares no default.

    Deliberately fatal. Returning a plausible answer here is how a test comes to pass against a
    prompt nobody wrote an expectation for.
    """


class MalformedFixture(FakeModelError):
    """A fixture file could not be read. Fatal, unlike `T-046`'s skip-and-report.

    The difference is what a bad file means: a bad *source document* is an operator's data
    problem and the other twenty documents are still evidence, but a bad *model fixture* is a
    broken expectation, and running the suite against the remaining ones would silently test
    something other than what was written.
    """


class ModelOutputFixture(BaseModel):
    """One prompt-to-output expectation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str
    #: What this fixture answers. Three accepted spellings, all resolving to one lookup key:
    #: a 64-character SHA-256 hex digest, the prompt text itself (hashed at load), or the literal
    #: `"default"`. Writing the prompt is what a fixture author usually wants — an opaque digest
    #: in a file nobody can read is how a fixture set stops being reviewable — and hashing it at
    #: load keeps the lookup itself hash-only.
    match: str
    #: The output text to return. Required unless `failure_mode` supplies it.
    output: dict[str, Any] | str | None = None
    failure_mode: FailureMode | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def lookup_key(self) -> str:
        """The key `fixture_for` matches against: always a digest, or the default literal."""
        if self.match == DEFAULT_MATCH or _IS_DIGEST.fullmatch(self.match):
            return self.match
        return prompt_key(self.match)

    @model_validator(mode="after")
    def _mode_and_output_agree(self) -> "ModelOutputFixture":
        """`unsupported_claim` is the one mode that must supply its own output.

        The other four generate what they return, because "invalid JSON" and "a refusal" have no
        interesting variations. An unsupported claim does: the whole point is that the output is
        *schema-valid*, so the fixture has to say which claim it wrongly cites.
        """
        if self.failure_mode is FailureMode.UNSUPPORTED_CLAIM and self.output is None:
            raise ValueError("unsupported_claim must declare the output that cites the claim")
        if self.failure_mode is None and self.output is None:
            raise ValueError("a fixture must declare either an output or a failure_mode")
        return self

    def rendered_output(self, prompt: str) -> str:
        """The text this fixture returns for ``prompt``."""
        if self.failure_mode is FailureMode.SCHEMA_INVALID:
            return json.dumps({"opportunity_type": "definitely_worth_a_call"})
        if self.failure_mode is FailureMode.REFUSAL:
            return "I cannot help with that request."
        if self.failure_mode is FailureMode.INJECTED_INSTRUCTION_ECHO:
            return json.dumps(_echoing_output(prompt))
        if isinstance(self.output, str):
            return self.output
        if self.output is not None:
            # Sorted keys so the bytes do not depend on dictionary ordering, which is the one
            # place cross-process determinism would quietly break.
            return json.dumps(self.output, sort_keys=True)
        raise MalformedFixture(f"fixture {self.fixture_id} declares neither output nor a mode")


# --- citing evidence from a file written in advance (T-207) --------------------------------------
#
# `T-207` made an uncited prospect statement fail validation, which left this adapter unable to
# produce a valid personalized draft at all: evidence is keyed by a **runtime UUID**, so no fixture
# written in advance can name one. A fixture that cannot cite is a fixture that can only produce
# drafts a reviewer must refuse.
#
# Resolved here and never in `drafting.py`. `resolve_citations` must keep raising on a citation it
# was not given — that is what catches a real model inventing an id — so teaching it a
# development-only spelling would put a hole in the check that matters most. Substituting before
# the output leaves the adapter means the draft path only ever sees an ordinary UUID that came out
# of this candidate's own inputs.
#
# In the adapter rather than in `app/fixtures/model_routing.py`, where it was written first: two
# routers wrap this class — that one and the test double in `tests/test_pipeline_jobs.py` — and a
# substitution living in one of them is a substitution the other silently lacks. That is not
# hypothetical either; it is how this moved.
#
# **Fewer snapshots than the sentinel asks for is not an error.** The sentinel resolves to nothing,
# the draft personalizes with no citation, and `T-207`'s check refuses it — the honest outcome for
# a candidate nobody found evidence for, and one a reviewer sees on `/attention` rather than
# approves. Raising here would dead-letter the job instead, and a dead job is the failure nobody
# reads.

#: `SYNTHETIC-EVIDENCE-1` is the first evidence line in the prompt, `-2` the second, and so on.
#: One-based because it is read by people writing fixtures, not by an index.
SENTINEL_PREFIX: Final = "SYNTHETIC-EVIDENCE-"
EVIDENCE_SENTINEL: Final = re.compile(rf"^{SENTINEL_PREFIX}(\d+)$")

#: Every evidence line a drafting prompt carries is `"<uuid>: <excerpt>"` (`as_prompt_inputs`).
#: Matched on the shape of a UUID at the start of a line, so a change to the prompt's wording
#: around it cannot silently break the resolution.
_PROMPT_EVIDENCE_ID: Final = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):", re.MULTILINE
)


def evidence_ids_in(prompt: str) -> list[str]:
    """The evidence snapshot ids this prompt was given, in the order it lists them."""
    return _PROMPT_EVIDENCE_ID.findall(prompt)


def resolve_evidence_sentinels(output: str, prompt: str) -> str:
    """Replace `SYNTHETIC-EVIDENCE-N` in fixture output with the prompt's own snapshot ids.

    Returns the output unchanged when it carries no sentinel — every qualification fixture, and
    every draft fixture that cites nothing.
    """
    if SENTINEL_PREFIX not in output:
        return output

    available = evidence_ids_in(prompt)
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        # A failure-mode fixture returns prose on purpose. Nothing to substitute into.
        return output
    if not isinstance(parsed, dict) or "evidence_ids" not in parsed:
        return output

    resolved: list[str] = []
    for value in parsed["evidence_ids"]:
        match = EVIDENCE_SENTINEL.match(str(value))
        if match is None:
            resolved.append(str(value))
            continue
        index = int(match.group(1)) - 1
        if 0 <= index < len(available):
            resolved.append(available[index])
        # else: dropped. See the note above.
    parsed["evidence_ids"] = resolved
    # Sorted for the same reason `rendered_output` sorts: the bytes must not depend on dictionary
    # ordering, which is where cross-process determinism would quietly break.
    return json.dumps(parsed, sort_keys=True)


#: The instruction the echo mode looks for. Matching a fixed marker rather than trying to detect
#: "an instruction" keeps the fake deterministic and honest about what it is doing (§15.4).
INJECTION_MARKER: Final = "ignore previous instructions"


def _echoing_output(prompt: str) -> dict[str, Any]:
    """Schema-valid §10.4 output whose prose repeats an instruction found in the prompt.

    Nothing here *obeys* the instruction — it copies it into a text field, which is exactly what
    a compromised model would do and exactly what the downstream validators must catch.
    """
    lowered = prompt.lower()
    start = lowered.find(INJECTION_MARKER)
    echoed = prompt[start : start + 120] if start >= 0 else "no instruction found in the prompt"
    return {
        "campaign_id": "SYNTHETIC-campaign",
        "campaign_candidate_id": "SYNTHETIC-candidate",
        "eligibility_failures": [],
        "opportunity_type": "pilot",
        "fit_summary": f"SYNTHETIC echo: {echoed}",
        "use_case": "SYNTHETIC use case.",
        "buyer_role_assessment": "SYNTHETIC buyer role assessment.",
        "fit_dimension_scores": {
            "product_fit": 1,
            "buyer_relevance": 1,
            "timing": 1,
            "commercial_scale": 1,
        },
        "evidence_completeness": "insufficient",
        "source_quality": "low",
        "personalization_evidence_ids": [],
        "applicable_approved_claim_ids": [],
        "ambiguities": [],
        "risks": ["SYNTHETIC: the source text contained an instruction"],
        "missing_information": [],
        "human_review_required": True,
    }


def prompt_key(prompt: str) -> str:
    """The fixture key for a rendered prompt: SHA-256 of its UTF-8 bytes."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


@dataclass
class FakeModelAdapter:
    """Serves fixture-defined outputs from ``directory``. No network, no clock, no randomness."""

    directory: Path
    model_name: str = MODEL_NAME
    #: Prompts served, in order. Lets a test assert what the pipeline actually asked.
    served: list[str] = field(default_factory=list)

    def fixtures(self) -> dict[str, ModelOutputFixture]:
        """Every fixture in the directory, keyed by `match`. Sorted for a stable read order."""
        loaded: dict[str, ModelOutputFixture] = {}

        if not self.directory.is_dir():
            return loaded

        for path in sorted(self.directory.glob("*.json")):
            if path.stat().st_size > MAX_FIXTURE_BYTES:
                raise MalformedFixture(f"{path.name} is larger than the fixture size limit")
            try:
                fixture = ModelOutputFixture.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, json.JSONDecodeError, UnicodeDecodeError) as error:
                raise MalformedFixture(f"{path.name}: {error}") from error

            if fixture.lookup_key in loaded:
                raise MalformedFixture(
                    f"{path.name}: two fixtures claim match {fixture.match!r}; which one answers "
                    f"would depend on file order, and a fake that depends on file order is not "
                    f"deterministic"
                )
            loaded[fixture.lookup_key] = fixture
        return loaded

    def fixture_for(self, prompt: str) -> ModelOutputFixture:
        """The fixture serving ``prompt``, or raise."""
        available = self.fixtures()
        exact = available.get(prompt_key(prompt))
        if exact is not None:
            return exact

        fallback = available.get(DEFAULT_MATCH)
        if fallback is not None:
            return fallback

        raise NoFixtureForPrompt(
            f"no fixture matches prompt {prompt_key(prompt)} and the set declares no "
            f'"{DEFAULT_MATCH}" entry; write the expectation rather than letting the fake invent '
            f"one (T-052)"
        )

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
        """Return the fixture's output for ``prompt``.

        ``parameters`` is accepted and ignored: temperature and token limits change what a real
        provider does, and a fake that pretended to honour them would be modelling nothing.
        """
        fixture = self.fixture_for(prompt)
        self.served.append(prompt)

        if fixture.failure_mode is FailureMode.TIMEOUT:
            raise TimeoutError(
                f"SYNTHETIC timeout from fixture {fixture.fixture_id}; the gateway records this "
                f"as provider_error (T-050)"
            )

        output = resolve_evidence_sentinels(fixture.rendered_output(prompt), prompt)
        return ProviderResponse(
            output_text=output,
            input_tokens=fixture.input_tokens,
            output_tokens=fixture.output_tokens,
            # Zero, and true: nothing was bought (§18.7).
            cost_usd=Decimal("0"),
        )
