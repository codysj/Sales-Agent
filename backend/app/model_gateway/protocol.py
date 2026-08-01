"""The typed model interfaces (T-050; specification §10.2, §10.4, §18.4, ADR-017).

Two contracts, deliberately separate:

* `ModelProviderAdapter` — what a provider can do: turn a rendered prompt into text, and report
  what that cost. It knows nothing about tasks, budgets, schemas, or candidates, which is §5.1's
  requirement that the adapter own none of the deterministic controls.
* `ModelGateway` — what the application calls. It resolves versions, enforces budgets, records
  the run, and only then invokes an adapter.

`ModelTaskRequest` carries version *identifiers*, not a model name: business logic names a
prompt, a schema, and a model configuration, and what those resolve to is configuration (§18.4).
Nothing in this package may contain a vendor string, and `test_versioning.py` greps `app/**` to
make sure.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ModelTaskRequest:
    """One bounded task invocation (§10.2 — bounded tasks, never open-ended agency)."""

    task_name: str
    prompt_version_id: uuid.UUID
    schema_version_id: uuid.UUID
    model_config_version_id: uuid.UUID
    #: The inputs the prompt renders. Treated as untrusted data throughout (§15.4).
    inputs: dict[str, Any] = field(default_factory=dict)
    policy_version_id: uuid.UUID | None = None
    #: Cost attribution (§18.7). Neither is required — a task may not belong to a campaign.
    campaign_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """What an adapter returns. Cost is reported by the adapter, never estimated by the caller."""

    output_text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class ModelTaskResult:
    """What the gateway returns: the output and the run that recorded it.

    ``output`` is the provider's raw text. Validating it against the request's schema version is
    `T-051`, which owns retry and escalation; the gateway records *which* schema applies.
    """

    run_id: uuid.UUID
    output_text: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


@runtime_checkable
class ModelProviderAdapter(Protocol):
    """A provider. Only the deterministic fake exists until gate **G-03**."""

    #: Recorded on every run so a row reports what actually produced it (§18.4).
    model_name: str

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
        """Turn a rendered prompt into text. No budgets, no schemas, no domain knowledge."""
        ...


@runtime_checkable
class ModelGateway(Protocol):
    """The single entry point for model work."""

    def run_task(self, request: ModelTaskRequest) -> ModelTaskResult:
        """Resolve versions, enforce budgets, invoke a provider, and record the run."""
        ...
