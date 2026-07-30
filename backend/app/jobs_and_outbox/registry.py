"""Job type registry (specification §17.1, §7.2).

A job type is a name, a typed payload, and a handler. The registry is what keeps
`jobs_and_outbox` generic: it moves work and guarantees delivery semantics, while the domain
modules that know what a candidate or a claim is register their own handlers
(``tests/test_module_boundaries.py`` forbids the reverse).

Payloads are validated against a Pydantic model **before insert**, so a malformed job never
reaches the queue to be discovered by a worker at 3am.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.jobs_and_outbox.retry import RetryPolicy


class JobHandler(Protocol):
    """What a registered handler must look like.

    Receives the caller's session so its writes land in the same transaction as the job's state
    change and audit event (§7.2 "commit state + audit + next job/outbox atomically").
    """

    def __call__(self, session: Session, payload: BaseModel, *, job_id: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class JobType:
    name: str
    payload_model: type[BaseModel]
    handler: JobHandler
    #: §17.1 requires this to be explicit per job type, so there is no default (T-031).
    retry_policy: RetryPolicy
    #: Whether a §17.6 pause must stop this job type. Required, not defaulted: guessing which
    #: work a global pause covers is exactly the guess an operator cannot afford (T-033).
    consequential: bool


class JobRegistryError(Exception):
    """A job type was registered or looked up incorrectly."""


class UnknownJobType(JobRegistryError):
    """No handler is registered for this job type.

    Raised rather than skipped: a queued job nobody can run is a silent backlog.
    """


class JobRegistry:
    """The job types this process knows how to run."""

    def __init__(self) -> None:
        self._types: dict[str, JobType] = {}

    def register(
        self,
        name: str,
        payload_model: type[BaseModel],
        handler: JobHandler,
        *,
        retry_policy: RetryPolicy,
        consequential: bool,
    ) -> None:
        """Register a job type. Both keyword arguments are required and have no default.

        ``retry_policy`` because §17.1 wants it explicit per job type; ``consequential`` because
        §17.6's pause has to know what it covers.
        """
        if not name.strip():
            raise JobRegistryError("job type name must not be blank")
        if name in self._types:
            raise JobRegistryError(
                f"job type {name!r} is already registered; two handlers for one name means the "
                f"one that runs depends on import order"
            )
        self._types[name] = JobType(
            name=name,
            payload_model=payload_model,
            handler=handler,
            retry_policy=retry_policy,
            consequential=consequential,
        )

    def get(self, name: str) -> JobType:
        try:
            return self._types[name]
        except KeyError:
            raise UnknownJobType(
                f"no handler registered for job type {name!r}; "
                f"known types: {sorted(self._types) or '(none)'}"
            ) from None

    def is_registered(self, name: str) -> bool:
        return name in self._types

    def names(self) -> list[str]:
        return sorted(self._types)

    def consequential_names(self) -> list[str]:
        """Job types a §17.6 pause must stop. The worker excludes these from leasing."""
        return sorted(name for name, job in self._types.items() if job.consequential)

    def clear(self) -> None:
        """Test helper. Never called in a running process."""
        self._types.clear()


#: The process-wide registry. Domain modules register into this at import time.
registry = JobRegistry()


def register_job_type(
    name: str,
    payload_model: type[BaseModel],
    *,
    retry_policy: RetryPolicy,
    consequential: bool,
) -> Callable[[JobHandler], JobHandler]:
    """Decorator form. Both keywords are required here too, for the same reasons."""

    def decorate(handler: JobHandler) -> JobHandler:
        registry.register(
            name, payload_model, handler, retry_policy=retry_policy, consequential=consequential
        )
        return handler

    return decorate
