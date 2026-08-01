"""Output validation, bounded retry, and escalation (T-051; §10.4, §10.2, §23, GP-09, §3.5).

§10.4: "Every model output must pass a versioned JSON Schema. Invalid output is retried within a
small limit, escalated to the baseline model if applicable, or sent to human review."

The three clauses, in order:

* **Passes a schema, or it is not output.** `validate_output` parses into the registered model.
  There is no lenient mode, no partial acceptance, and no coercion of a nearly-right object.
* **Retried within a small limit.** `MAX_ATTEMPTS` is deliberately small. Each attempt is a full
  `run_task`, so every retry passes the §18.7 budgets again — a model looping on invalid output
  cannot spend past the cap that a single call would have hit.
* **Then human review.** "Escalated to the baseline model if applicable" is not applicable: one
  model exists and routing is deferred (ADR-013), so the only escalation is a person. That is
  the safe direction anyway — `Escalated` carries the attempts and the last error so a reviewer
  sees what the model actually produced.

**Invalid output is never silently accepted, and never silently dropped.** Each failed attempt
updates its `ModelRun` to `INVALID_OUTPUT` with the validation error, so the cost of a model that
cannot produce valid output is visible in the same place as the cost of one that can.
"""

from datetime import datetime
from typing import Final, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.model_gateway.gateway import DatabaseModelGateway
from app.model_gateway.models import ModelRun, ModelRunOutcome
from app.model_gateway.protocol import ModelTaskRequest
from app.model_gateway.schemas import OUTPUT_SCHEMAS

#: Attempts, not retries: 2 means one try and one more. Small on purpose — a model that cannot
#: produce valid output twice is not going to on the fifth attempt, and each try costs budget.
MAX_ATTEMPTS: Final = 2

#: How much of an invalid output is quoted in the run's failure reason. Enough to diagnose,
#: bounded so a runaway response does not become a runaway database row (§15.5).
ERROR_EXCERPT_CHARS: Final = 500

TOutput = TypeVar("TOutput", bound=BaseModel)


class OutputValidationError(Exception):
    """Model output did not satisfy its schema."""


class UnknownSchema(OutputValidationError):
    """The task named a schema key that is not registered.

    Fails closed: with no contract there is nothing to validate against, and validating against
    "whatever the model returned" is not validation.
    """


class Escalated(OutputValidationError):
    """Every attempt produced invalid output. A human must look (§10.4, GP-09)."""

    def __init__(self, schema_key: str, attempts: int, last_error: str) -> None:
        self.schema_key = schema_key
        self.attempts = attempts
        self.last_error = last_error
        self.human_review_required = True
        super().__init__(
            f"{schema_key}: {attempts} attempt(s) produced invalid output; escalated to human "
            f"review — last error: {last_error}"
        )


def validate_output(schema_key: str, text: str) -> BaseModel:
    """Parse ``text`` into the model registered under ``schema_key``, or raise.

    Raises :class:`UnknownSchema` if nothing is registered, and
    :class:`OutputValidationError` if the text is not valid JSON or does not satisfy the model.
    """
    model = OUTPUT_SCHEMAS.get(schema_key)
    if model is None:
        raise UnknownSchema(
            f"no output schema registered under {schema_key!r}; a task without a contract has "
            f"nothing to validate against (§10.4)"
        )

    try:
        return model.model_validate_json(text)
    except ValidationError as error:
        raise OutputValidationError(f"{schema_key}: {error}") from error


def _mark_invalid(session: Session, run_id: object, reason: str) -> None:
    """Record on the run that its output failed validation.

    The provider succeeded and the output did not, and the row ends up saying the second thing —
    which is what a cost report needs to show a task burning budget on unusable output.
    """
    run = session.get(ModelRun, run_id)
    if run is None:  # pragma: no cover - the run was just written in this session
        return
    run.outcome = ModelRunOutcome.INVALID_OUTPUT
    run.failure_reason = reason[:ERROR_EXCERPT_CHARS]
    session.flush()


def run_validated_task(
    gateway: DatabaseModelGateway,
    session: Session,
    request: ModelTaskRequest,
    *,
    schema_key: str,
    max_attempts: int = MAX_ATTEMPTS,
    at: datetime | None = None,
) -> BaseModel:
    """Run a task until its output validates, or escalate.

    Returns the parsed output. Raises :class:`Escalated` once ``max_attempts`` have each produced
    invalid output. Budget refusals and provider failures are **not** caught: they are not the
    model failing to answer, and retrying a call the budget just refused would be a loop.
    """
    if schema_key not in OUTPUT_SCHEMAS:
        raise UnknownSchema(f"no output schema registered under {schema_key!r}")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    last_error = ""
    for _ in range(max_attempts):
        result = gateway.run_task(session, request, at=at)
        try:
            return validate_output(schema_key, result.output_text)
        except OutputValidationError as error:
            last_error = str(error)
            _mark_invalid(session, result.run_id, last_error)

    raise Escalated(schema_key, max_attempts, last_error)
