"""Writing to the audit trail.

The single way every other module records that something consequential happened (§3.5). It
refuses to write an event that could not later be trusted: no actor, no correlation, or a
payload carrying material §15.5 says must never reach a log.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app import APP_VERSION
from app.audit_and_operations.models import ActorType, AuditEvent

#: Payload keys that would put a credential or message body into the audit trail (§15.5).
#: Substring match, case-insensitive — `api_key`, `Authorization`, `refresh_token` all hit.
FORBIDDEN_PAYLOAD_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
)


class AuditError(Exception):
    """The audit trail refused a write."""


class MissingCorrelationId(AuditError):
    """No correlation ID was supplied or bound to the logging context.

    Not defaulted on purpose: an event that cannot be joined to the request or job that caused
    it is much weaker evidence, and the fix (bind the context) belongs at the call site.
    """


class UnsafePayload(AuditError):
    """The payload carries something §15.5 forbids recording."""


@dataclass(frozen=True, slots=True)
class Actor:
    """Who did it. Required on every event — there is no anonymous default."""

    type: ActorType
    id: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise AuditError("actor id must not be blank")


SYSTEM_ACTOR = Actor(type=ActorType.SYSTEM, id="system")


def current_correlation_id() -> str | None:
    """The correlation ID bound by the request middleware or the worker's job context."""
    bound = structlog.contextvars.get_contextvars().get("correlation_id")
    return bound if isinstance(bound, str) else None


def _check_payload(payload: Mapping[str, Any]) -> None:
    for key in payload:
        lowered = key.lower()
        if any(fragment in lowered for fragment in FORBIDDEN_PAYLOAD_KEY_FRAGMENTS):
            raise UnsafePayload(
                f"payload key {key!r} looks like a credential; the audit trail must not "
                f"record secrets (specification §15.5)"
            )


def record_audit_event(
    session: Session,
    *,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    from_state: Enum | None = None,
    to_state: Enum | None = None,
    policy_decision: str | None = None,
    payload: Mapping[str, Any] | None = None,
    correlation_id: str | None = None,
    prompt_version: str | None = None,
    schema_version: str | None = None,
    policy_version: str | None = None,
    model_config_version: str | None = None,
) -> AuditEvent:
    """Append one audit event. Adds it to ``session`` without committing.

    The caller's transaction decides whether the event survives, so state, effect, and audit
    commit together or not at all (§17.2).

    Never pass contact details, prompts, message bodies, or credentials in ``payload``.
    """
    resolved_correlation = correlation_id or current_correlation_id()
    if not resolved_correlation:
        raise MissingCorrelationId(
            f"no correlation_id for {action!r} on {entity_type}:{entity_id}; "
            f"pass one explicitly or bind it with structlog.contextvars"
        )

    body = dict(payload or {})
    _check_payload(body)

    event = AuditEvent(
        correlation_id=resolved_correlation,
        actor_type=actor.type,
        actor_id=actor.id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        from_state=from_state.value if from_state else None,
        to_state=to_state.value if to_state else None,
        policy_decision=policy_decision,
        payload=body,
        app_version=APP_VERSION,
        prompt_version=prompt_version,
        schema_version=schema_version,
        policy_version=policy_version,
        model_config_version=model_config_version,
    )
    session.add(event)
    return event
