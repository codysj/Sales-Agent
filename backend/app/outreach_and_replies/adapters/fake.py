"""A fake external-effect adapter (§18.5, §19.6 Stage 1, ADR-016).

The only adapter that exists during Stage 1. It records what it was asked to do and returns whatever
outcome the test asked for, so the dispatcher's branches — including the ones §17.3 says must never
blindly retry — can be exercised without a provider account.

It is not a mock. It keeps real state: a ledger of effects it has "performed", keyed by idempotency
key, which is what makes `reconcile()` meaningful and what makes replaying one key observably
produce one effect (`T-035b`). A mock that merely records calls could not distinguish "sent twice"
from "sent once and asked twice".
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.jobs_and_outbox.dispatch import (
    EffectOutcome,
    EffectRequest,
    EffectResult,
    ExternalEffectAdapter,
)


class Scenario(StrEnum):
    """The provider behaviours a test may ask for.

    `TIMEOUT` and `AMBIGUOUS_ACCEPTANCE` are distinct *inputs* that must produce the same
    non-retryable *outcome*. Keeping them separate here and equal downstream is what lets a test
    assert that equivalence rather than assume it.
    """

    SUCCESS = "success"
    TIMEOUT = "timeout"
    AMBIGUOUS_ACCEPTANCE = "ambiguous_acceptance"
    RATE_LIMITED = "rate_limited"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """One attempt, as the adapter saw it."""

    idempotency_key: str
    event_type: str
    payload: Mapping[str, Any]
    scenario: Scenario


class FakeExternalEffectAdapter(ExternalEffectAdapter):
    """An adapter that performs nothing and remembers everything."""

    def __init__(self, scenario: Scenario = Scenario.SUCCESS, *, is_email: bool = False) -> None:
        self.scenario = scenario
        self.is_email = is_email
        #: Every attempt, in order, including ones that failed. The dispatcher's retry behaviour is
        #: only observable against a full record.
        self.calls: list[RecordedCall] = []
        #: Effects the provider would now consider real, keyed by idempotency key. `TIMEOUT` and
        #: `AMBIGUOUS_ACCEPTANCE` write here too: that is exactly why they are ambiguous rather
        #: than failed, and it is what lets `reconcile` discover the truth later.
        self.performed: dict[str, EffectResult] = {}

    def _perform(self, session: Session, request: EffectRequest) -> EffectResult:
        self.calls.append(
            RecordedCall(
                idempotency_key=request.idempotency_key,
                event_type=request.event_type,
                payload=dict(request.payload),
                scenario=self.scenario,
            )
        )

        correlation = f"fake-{request.idempotency_key[:12]}"

        if self.scenario is Scenario.SUCCESS:
            result = EffectResult(
                outcome=EffectOutcome.ACCEPTED,
                provider_correlation_id=correlation,
                detail="fake provider accepted the effect",
            )
            self.performed[request.idempotency_key] = result
            return result

        if self.scenario is Scenario.TIMEOUT:
            # The dangerous case: the effect landed, and the caller never heard so. Recorded as
            # performed precisely so a test can prove that a blind retry would duplicate it.
            self.performed[request.idempotency_key] = EffectResult(
                outcome=EffectOutcome.ACCEPTED,
                provider_correlation_id=correlation,
                detail="fake provider accepted, but the response was lost",
            )
            return EffectResult(
                outcome=EffectOutcome.AMBIGUOUS,
                detail="no response from the fake provider before the deadline",
            )

        if self.scenario is Scenario.AMBIGUOUS_ACCEPTANCE:
            self.performed[request.idempotency_key] = EffectResult(
                outcome=EffectOutcome.ACCEPTED,
                provider_correlation_id=correlation,
                detail="fake provider accepted for processing",
            )
            return EffectResult(
                outcome=EffectOutcome.AMBIGUOUS,
                provider_correlation_id=correlation,
                detail="fake provider accepted for processing without confirming delivery",
            )

        if self.scenario is Scenario.RATE_LIMITED:
            # Nothing written to `performed`: the request demonstrably never landed, which is what
            # makes this the one outcome that is safe to retry without reconciling.
            return EffectResult(
                outcome=EffectOutcome.TRANSIENT_FAILURE,
                detail="fake provider rate limit; the request was not processed",
            )

        return EffectResult(
            outcome=EffectOutcome.REJECTED,
            detail="fake provider refused the effect permanently",
        )

    def reconcile(self, idempotency_key: str) -> EffectResult | None:
        """What the fake provider believes happened. §17.3's pre-retry check."""
        return self.performed.get(idempotency_key)

    @property
    def effect_count(self) -> int:
        """Distinct effects that actually happened — what "effectively once" is measured against."""
        return len(self.performed)
