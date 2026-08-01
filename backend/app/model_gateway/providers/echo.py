"""The in-process adapter that stands in for a provider (T-050; GP-06, ADR-017).

Deliberately minimal: it returns a deterministic function of the prompt and reports zero cost,
which is exactly true — nothing was bought. Its purpose is to make the gateway's own behaviour —
version resolution, budget enforcement, run recording — testable end to end without a provider.

`T-052` replaces the body with fixture-keyed outputs and the five deliberate failure modes
(schema-invalid output, refusal, timeout, unsupported claim attempt, injected-instruction echo).
The `ModelProviderAdapter` contract does not change when it does, which is the point of having
the contract.

**No I/O of any kind.** No socket, no file, no clock, no randomness — so a test that fails here
has found a real defect, not a flaky provider.
"""

import hashlib
from decimal import Decimal
from typing import Any, Final

from app.model_gateway.protocol import ProviderResponse

#: Recorded on every run this adapter serves. Not a vendor name — there is no vendor (§18.4).
MODEL_NAME: Final = "deterministic-fake"


#: A crude token estimate: whitespace-separated words. Honest about being an estimate, and only
#: ever used for the fake, whose real token count is zero because nothing was tokenized.
def _estimate_tokens(text: str) -> int:
    return len(text.split())


class EchoModelAdapter:
    """Returns a stable digest of the prompt. Same prompt in, same text out, forever."""

    model_name: str = MODEL_NAME

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        output = f"SYNTHETIC-FAKE-OUTPUT {digest[:32]}"
        return ProviderResponse(
            output_text=output,
            input_tokens=_estimate_tokens(prompt),
            output_tokens=_estimate_tokens(output),
            # Zero, and true: no provider was called, so nothing was spent (§18.7).
            cost_usd=Decimal("0"),
        )
