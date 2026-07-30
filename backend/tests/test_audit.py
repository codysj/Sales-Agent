"""The audit trail is append-only and always attributable (T-011; specification §3.5, §17.5).

"Every consequential action has an actor, revision, policy decision, and audit event" is listed
as a safety invariant, not a target. These tests treat it as one.
"""

import uuid

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app import APP_VERSION
from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import (
    SYSTEM_ACTOR,
    Actor,
    AuditError,
    MissingCorrelationId,
    UnsafePayload,
    record_audit_event,
)
from app.core.lifecycles import CampaignCandidateState

HUMAN = Actor(type=ActorType.HUMAN, id="reviewer-1")


@pytest.fixture(autouse=True)
def _clear_log_context() -> None:
    """Correlation IDs must not leak between tests through structlog contextvars."""
    structlog.contextvars.clear_contextvars()


def _record(session: Session, **overrides: object) -> AuditEvent:
    kwargs: dict[str, object] = {
        "actor": HUMAN,
        "action": "candidate.approved",
        "entity_type": "campaign_candidate",
        "entity_id": str(uuid.uuid4()),
        "correlation_id": "corr-test-1",
    }
    kwargs.update(overrides)
    return record_audit_event(session, **kwargs)  # type: ignore[arg-type]


# --- attribution ---------------------------------------------------------------------------


def test_an_event_records_its_actor(db_session: Session) -> None:
    event = _record(db_session)
    db_session.flush()

    assert event.actor_type is ActorType.HUMAN
    assert event.actor_id == "reviewer-1"
    assert event.app_version == APP_VERSION


def test_an_actor_cannot_be_blank() -> None:
    with pytest.raises(AuditError):
        Actor(type=ActorType.HUMAN, id="   ")


def test_the_database_rejects_a_blank_actor_id(db_session: Session) -> None:
    """Belt and braces: the check constraint holds even if the service is bypassed."""
    db_session.add(
        AuditEvent(
            correlation_id="corr-1",
            actor_type=ActorType.SYSTEM,
            actor_id="  ",
            action="x",
            entity_type="y",
            entity_id="z",
            app_version=APP_VERSION,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_actor_is_a_required_argument(db_session: Session) -> None:
    """There is no anonymous default; omitting the actor is a TypeError, not a silent 'system'."""
    with pytest.raises(TypeError):
        record_audit_event(  # type: ignore[call-arg]
            db_session, action="a", entity_type="b", entity_id="c", correlation_id="d"
        )


# --- correlation ---------------------------------------------------------------------------


def test_correlation_id_is_taken_from_the_log_context(db_session: Session) -> None:
    """The ID bound by the request middleware (T-004) or a job flows into the trail (§17.5)."""
    structlog.contextvars.bind_contextvars(correlation_id="corr-from-request")

    event = record_audit_event(
        db_session,
        actor=HUMAN,
        action="candidate.reviewed",
        entity_type="campaign_candidate",
        entity_id=uuid.uuid4(),
    )
    db_session.flush()

    assert event.correlation_id == "corr-from-request"


def test_an_explicit_correlation_id_wins(db_session: Session) -> None:
    structlog.contextvars.bind_contextvars(correlation_id="corr-ambient")

    event = _record(db_session, correlation_id="corr-explicit")

    assert event.correlation_id == "corr-explicit"


def test_writing_without_any_correlation_id_is_refused(db_session: Session) -> None:
    """An event that cannot be joined to its cause is much weaker evidence."""
    with pytest.raises(MissingCorrelationId) as exc:
        record_audit_event(
            db_session,
            actor=SYSTEM_ACTOR,
            action="sweep.ran",
            entity_type="job",
            entity_id="job-1",
        )

    assert "sweep.ran" in str(exc.value)


# --- append-only ---------------------------------------------------------------------------


def test_update_is_rejected_by_the_database(db_session: Session) -> None:
    event = _record(db_session)
    db_session.flush()

    with pytest.raises(DBAPIError) as exc:
        db_session.execute(
            text("UPDATE audit_event SET action = 'tampered' WHERE id = :id"), {"id": event.id}
        )

    assert "append-only" in str(exc.value)


def test_delete_is_rejected_by_the_database(db_session: Session) -> None:
    event = _record(db_session)
    db_session.flush()

    with pytest.raises(DBAPIError) as exc:
        db_session.execute(text("DELETE FROM audit_event WHERE id = :id"), {"id": event.id})

    assert "append-only" in str(exc.value)


def test_truncate_is_rejected_by_the_database(db_session: Session) -> None:
    """TRUNCATE bypasses row-level triggers, so it needs its own statement-level guard."""
    _record(db_session)
    db_session.flush()

    with pytest.raises(DBAPIError) as exc:
        db_session.execute(text("TRUNCATE audit_event"))

    assert "append-only" in str(exc.value)


def test_the_orm_cannot_edit_a_persisted_event(db_session: Session) -> None:
    """Not just raw SQL: an ORM mutation hits the same wall."""
    event = _record(db_session)
    db_session.flush()

    event.action = "tampered"

    with pytest.raises(DBAPIError):
        db_session.flush()


# --- payload safety (§15.5) ------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "api_key",
        "apiKey",
        "Authorization",
        "refresh_token",
        "client_secret",
        "aws_credential",
        "private_key",
    ],
)
def test_credential_shaped_payload_keys_are_refused(key: str, db_session: Session) -> None:
    with pytest.raises(UnsafePayload) as exc:
        _record(db_session, payload={key: "value"})

    assert "15.5" in str(exc.value)


def test_ordinary_payload_keys_are_accepted(db_session: Session) -> None:
    event = _record(db_session, payload={"campaign_id": "c-1", "reason": "weak evidence"})
    db_session.flush()

    assert event.payload == {"campaign_id": "c-1", "reason": "weak evidence"}


def test_payload_defaults_to_an_empty_object(db_session: Session) -> None:
    event = _record(db_session)
    db_session.flush()

    assert event.payload == {}


# --- lifecycle transitions ------------------------------------------------------------------


def test_a_state_transition_records_both_ends(db_session: Session) -> None:
    """§8.2 movement is recorded as enum *values*, so later renames cannot rewrite history."""
    event = _record(
        db_session,
        from_state=CampaignCandidateState.REVIEW_PENDING,
        to_state=CampaignCandidateState.APPROVED,
    )
    db_session.flush()

    assert event.from_state == "review_pending"
    assert event.to_state == "approved"


def test_states_are_optional_for_non_transition_events(db_session: Session) -> None:
    event = _record(db_session, action="report.generated")
    db_session.flush()

    assert event.from_state is None
    assert event.to_state is None


# --- transactionality -----------------------------------------------------------------------


def test_the_event_is_not_committed_by_the_service(db_session: Session) -> None:
    """State, effect, and audit must commit together or not at all (§17.2)."""
    _record(db_session)

    assert db_session.new, "record_audit_event must leave the event pending in the caller's tx"


def test_versions_are_recorded_when_supplied(db_session: Session) -> None:
    event = _record(
        db_session,
        prompt_version="p-1",
        schema_version="s-1",
        policy_version="pol-1",
        model_config_version="m-1",
    )
    db_session.flush()

    assert (event.prompt_version, event.schema_version) == ("p-1", "s-1")
    assert (event.policy_version, event.model_config_version) == ("pol-1", "m-1")
