"""Claim and readiness invalidation (T-056; §14.4, §8.4, §17.1, §19.2).

The push side of claim currency. `T-055` catches a lapsed claim when someone validates a revision;
this catches it when the *claim* changes and nobody is looking at the revision at all.

Three things are worth proving, and the third is the one that would be tempting to get wrong:
everything pending is invalidated, re-running changes nothing, and a message that has already
been delivered is flagged rather than rewritten. History is not editable.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
import structlog
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.core.lifecycles import ApprovalState, MessageRevisionState
from app.drafts_and_approvals.approval import Approval, approve, request_approval
from app.drafts_and_approvals.invalidation import (
    INVALIDATABLE_REVISION_STATES,
    INVALIDATION_JOB_TYPE,
    InvalidationPayload,
    handle_invalidation,
    invalidate_for_claim,
    invalidate_for_product_status,
    register,
    revisions_citing_claim,
)
from app.drafts_and_approvals.models import MessageRevision
from app.drafts_and_approvals.revisions import transition as transition_revision
from app.jobs_and_outbox.registry import JobRegistry
from app.outreach_and_replies.commands import revision_already_sent
from app.products_and_claims.claim_models import ApprovedClaim
from app.products_and_claims.models import ProductStatusVersion, ReadinessCategory
from tests.factories import APPROVER, NOW, OPERATOR, World

SYSTEM = Actor(type=ActorType.SYSTEM, id="invalidation-job")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-invalidation-test")


def make_claim(session: Session, world: World, key: str = "SYNTHETIC-CLAIM-one") -> ApprovedClaim:
    claim = ApprovedClaim(
        claim_key=key,
        version=1,
        product_id=world.product.id,
        text="SYNTHETIC EXAMPLE CLAIM.",
        approved_by=APPROVER,
        approved_at=NOW - timedelta(days=1),
        effective_from=NOW - timedelta(days=1),
        expires_or_review_by=NOW + timedelta(days=90),
    )
    session.add(claim)
    session.flush()
    return claim


def cite(session: Session, world: World, claim: ApprovedClaim) -> MessageRevision:
    """Point the world's revision at the claim by creating the next revision that cites it."""
    from app.drafts_and_approvals.revisions import create_revision

    return create_revision(
        session,
        draft=world.draft,
        recipient_contact_point_id=world.recipient.id,
        subject="SYNTHETIC subject",
        body="SYNTHETIC body",
        approved_claim_ids=[claim.id],
        created_by="drafting-task",
        actor=OPERATOR,
    )


def pending_revision(session: Session, world: World, claim: ApprovedClaim) -> MessageRevision:
    revision = cite(session, world, claim)
    transition_revision(session, revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR)
    return revision


def approved_revision(
    session: Session, world: World, claim: ApprovedClaim
) -> tuple[MessageRevision, Approval]:
    revision = pending_revision(session, world, claim)
    transition_revision(session, revision, MessageRevisionState.APPROVED, actor=OPERATOR)
    approval = request_approval(
        session, revision=revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    approve(session, approval, actor=OPERATOR, now=NOW)
    session.flush()
    return revision, approval


# --- criterion 1: a new version invalidates every pending revision and approval -----------------


def test_a_pending_revision_citing_the_claim_is_invalidated(db_session: Session) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)

    report = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert report.invalidated_revisions == [revision.id]
    assert revision.state is MessageRevisionState.INVALIDATED


def test_an_approved_but_unsent_revision_is_invalidated_and_its_approval_revoked(
    db_session: Session,
) -> None:
    """The case the task singles out: approved, and the basis has since been withdrawn."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision, approval = approved_revision(db_session, world, claim)

    report = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert revision.state is MessageRevisionState.INVALIDATED
    assert approval.state is ApprovalState.REVOKED
    assert report.revoked_approvals == [approval.id]


def test_a_pending_approval_is_expired_rather_than_revoked(db_session: Session) -> None:
    """§8.2 has no `pending -> revoked` edge; expiry is the edge that exists (`T-021`)."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)
    approval = request_approval(
        db_session, revision=revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    db_session.flush()

    report = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert approval.state is ApprovalState.EXPIRED
    assert report.expired_approvals == [approval.id]


def test_a_revision_citing_a_different_claim_is_untouched(db_session: Session) -> None:
    world = World(db_session)
    target = make_claim(db_session, world, "SYNTHETIC-CLAIM-target")
    other = make_claim(db_session, world, "SYNTHETIC-CLAIM-other")
    untouched = pending_revision(db_session, world, other)

    invalidate_for_claim(db_session, target, actor=SYSTEM, at=NOW)

    assert untouched.state is MessageRevisionState.REVIEW_PENDING


def test_a_draft_revision_is_left_alone(db_session: Session) -> None:
    """§8.2 has no `draft -> invalidated` edge (`R-005`). `T-055` refuses it at validation instead,
    so it can never reach a reviewer — the safety outcome without widening the lifecycle."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    draft_revision = cite(db_session, world, claim)

    report = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert draft_revision.state is MessageRevisionState.DRAFT
    assert report.invalidated_revisions == []


def test_the_invalidatable_states_are_exactly_the_two_with_an_edge() -> None:
    assert {
        MessageRevisionState.REVIEW_PENDING,
        MessageRevisionState.APPROVED,
    } == INVALIDATABLE_REVISION_STATES


def test_a_readiness_change_reaches_revisions_through_the_products_claims(
    db_session: Session,
) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)
    status = ProductStatusVersion(
        product_id=world.product.id,
        version=1,
        readiness_category=ReadinessCategory.PAUSED_OR_UNAVAILABLE,
        approved_by=APPROVER,
        approved_at=NOW,
        effective_from=NOW,
    )
    db_session.add(status)
    db_session.flush()

    report = invalidate_for_product_status(db_session, status, actor=SYSTEM, at=NOW)

    assert revision.state is MessageRevisionState.INVALIDATED
    assert report.invalidated_revisions == [revision.id]


def test_the_query_finds_only_invalidatable_revisions(db_session: Session) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    cite(db_session, world, claim)  # stays in `draft`
    pending = pending_revision(db_session, world, claim)

    assert [revision.id for revision in revisions_citing_claim(db_session, claim.id)] == [
        pending.id
    ]


# --- criterion 2: idempotent, one audit event per affected entity --------------------------------


def test_running_twice_changes_nothing_the_second_time(db_session: Session) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision, approval = approved_revision(db_session, world, claim)
    first = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    second = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert first.changed_anything
    assert not second.changed_anything
    assert second.invalidated_revisions == []
    assert revision.state is MessageRevisionState.INVALIDATED
    assert approval.state is ApprovalState.REVOKED


def test_each_affected_revision_gets_one_transition_event(db_session: Session) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)

    invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)
    invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    events = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.entity_id == str(revision.id),
            AuditEvent.to_state == MessageRevisionState.INVALIDATED.value,
        )
    ).scalar_one()
    assert events == 1


def test_the_run_records_an_audit_event_naming_the_triggering_version(
    db_session: Session,
) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    pending_revision(db_session, world, claim)

    invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "approved_claim.invalidation_run")
    ).scalar_one()
    assert event.payload["claim_key"] == claim.claim_key
    assert event.payload["claim_version"] == "1"
    assert event.payload["invalidated_revisions"] == 1


def test_the_invalidation_reason_names_the_claim(db_session: Session) -> None:
    """A reviewer opening the record must see *why*, not just that it happened."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)

    invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    event = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(revision.id),
            AuditEvent.to_state == MessageRevisionState.INVALIDATED.value,
        )
    ).scalar_one()
    assert claim.claim_key in str(event.payload)


def test_a_run_that_changes_nothing_still_records_that_it_ran(db_session: Session) -> None:
    """Evidence the job executed. "Nothing was affected" is a result, not an absence."""
    world = World(db_session)
    claim = make_claim(db_session, world)

    report = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert not report.changed_anything
    assert (
        db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "approved_claim.invalidation_run")
        ).scalar_one()
        == 1
    )


# --- criterion 3: a delivered message is flagged, never altered ----------------------------------


def test_an_already_sent_revision_is_not_altered(db_session: Session) -> None:
    """Rewriting a delivered message's record would be a lie about what was sent."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision, approval = approved_revision(db_session, world, claim)

    report = invalidate_for_claim(
        db_session,
        claim,
        actor=SYSTEM,
        at=NOW,
        already_sent=lambda _session, _revision_id: True,
    )

    assert revision.state is MessageRevisionState.APPROVED, "history is not editable"
    assert approval.state is ApprovalState.APPROVED
    assert report.invalidated_revisions == []
    assert report.skipped_already_sent == [revision.id]


def test_an_already_sent_revision_is_flagged(db_session: Session) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision, _ = approved_revision(db_session, world, claim)

    invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW, already_sent=lambda _s, _r: True)

    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "message_revision.claim_withdrawn_after_send")
    ).scalar_one()
    assert event.entity_id == str(revision.id)
    assert event.payload["claim_key"] == claim.claim_key


def test_the_sent_check_is_injected_because_the_import_is_forbidden() -> None:
    """§18.2: `drafts_and_approvals` may not import `outreach_and_replies`, so the fact is passed
    in — the same shape `T-035c` uses for the §11.4 rechecks."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[1] / "app" / "drafts_and_approvals" / "invalidation.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not [name for name in imported if "outreach_and_replies" in name]


def test_the_real_sent_check_reports_no_send_when_none_happened(db_session: Session) -> None:
    world = World(db_session)

    assert revision_already_sent(db_session, world.revision.id) is False


def test_without_a_sent_check_nothing_is_treated_as_sent(db_session: Session) -> None:
    """Correct in shadow mode, where nothing sends at all; the worker wires the real check."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)

    report = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert report.skipped_already_sent == []
    assert revision.state is MessageRevisionState.INVALIDATED


# --- the job type ---------------------------------------------------------------------------------


def test_the_job_type_registers_with_an_explicit_retry_policy() -> None:
    registry = JobRegistry()

    register(registry)

    job = registry.get(INVALIDATION_JOB_TYPE)
    assert job.payload_model is InvalidationPayload
    assert job.retry_policy.max_attempts >= 1


def test_the_job_type_is_not_consequential() -> None:
    """§17.6: a pause stops work going *out*. Withdrawing work is on the same side as the pause."""
    registry = JobRegistry()

    register(registry)

    assert INVALIDATION_JOB_TYPE not in registry.consequential_names()


def test_registering_twice_is_harmless() -> None:
    registry = JobRegistry()

    register(registry)
    register(registry)

    assert registry.is_registered(INVALIDATION_JOB_TYPE)


def test_the_handler_invalidates_by_claim(db_session: Session) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)

    handle_invalidation(
        db_session,
        InvalidationPayload(trigger_kind="claim", trigger_id=claim.id),
        job_id=uuid.uuid4(),
    )

    assert revision.state is MessageRevisionState.INVALIDATED


def test_the_handler_refuses_an_unknown_trigger_kind(db_session: Session) -> None:
    with pytest.raises(ValueError, match="unknown trigger kind"):
        handle_invalidation(
            db_session,
            InvalidationPayload(trigger_kind="something-else", trigger_id=uuid.uuid4()),
            job_id=uuid.uuid4(),
        )


def test_the_handler_refuses_a_missing_claim(db_session: Session) -> None:
    with pytest.raises(ValueError, match="no approved claim"):
        handle_invalidation(
            db_session,
            InvalidationPayload(trigger_kind="claim", trigger_id=uuid.uuid4()),
            job_id=uuid.uuid4(),
        )


def test_the_handler_records_a_system_actor(db_session: Session) -> None:
    """§17.5: attributable. Pretending a person withdrew an approval would be worse than useless."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    pending_revision(db_session, world, claim)

    handle_invalidation(
        db_session,
        InvalidationPayload(trigger_kind="claim", trigger_id=claim.id),
        job_id=uuid.uuid4(),
    )

    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "approved_claim.invalidation_run")
    ).scalar_one()
    assert event.actor_type is ActorType.SYSTEM


def test_the_payload_rejects_an_unexpected_field() -> None:
    with pytest.raises(ValidationError):
        InvalidationPayload.model_validate(
            {"trigger_kind": "claim", "trigger_id": str(uuid.uuid4()), "force": True}
        )


def test_the_report_is_empty_for_a_claim_nothing_cites(db_session: Session) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)

    report = invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert report.invalidated_revisions == []
    assert report.revoked_approvals == []
    assert not report.changed_anything


def test_invalidation_never_deletes_anything(db_session: Session) -> None:
    """State changes only: the revision, its approval, and the audit trail all survive."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision, approval = approved_revision(db_session, world, claim)
    before = db_session.execute(select(func.count()).select_from(MessageRevision)).scalar_one()

    invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert (
        db_session.execute(select(func.count()).select_from(MessageRevision)).scalar_one() == before
    )
    assert db_session.get(MessageRevision, revision.id) is not None
    assert db_session.get(Approval, approval.id) is not None


def test_the_revision_content_is_unchanged_by_invalidation(db_session: Session) -> None:
    """Only the state moves. `T-020`'s trigger would refuse anything else, and nothing tries."""
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)
    body, content_hash = revision.body, revision.content_hash

    invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    assert (revision.body, revision.content_hash) == (body, content_hash)


def test_the_audit_payload_carries_no_message_content(db_session: Session) -> None:
    world = World(db_session)
    claim = make_claim(db_session, world)
    revision = pending_revision(db_session, world, claim)

    invalidate_for_claim(db_session, claim, actor=SYSTEM, at=NOW)

    events = db_session.execute(select(AuditEvent)).scalars().all()
    serialized = " ".join(str(event.payload) for event in events)
    assert revision.body not in serialized


def test_a_second_claim_on_the_same_revision_still_finds_it_invalidated(
    db_session: Session,
) -> None:
    """Two claims withdrawn in sequence; the second must not fail on an already-moved row."""
    world = World(db_session)
    first = make_claim(db_session, world, "SYNTHETIC-CLAIM-a")
    second = make_claim(db_session, world, "SYNTHETIC-CLAIM-b")
    from app.drafts_and_approvals.revisions import create_revision

    revision = create_revision(
        db_session,
        draft=world.draft,
        recipient_contact_point_id=world.recipient.id,
        subject="SYNTHETIC subject",
        body="SYNTHETIC body",
        approved_claim_ids=[first.id, second.id],
        created_by="drafting-task",
        actor=OPERATOR,
    )
    transition_revision(db_session, revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR)

    invalidate_for_claim(db_session, first, actor=SYSTEM, at=NOW)
    report = invalidate_for_claim(db_session, second, actor=SYSTEM, at=NOW)

    assert revision.state is MessageRevisionState.INVALIDATED
    assert report.invalidated_revisions == []


def test_the_default_registry_can_register_the_job(monkeypatch: Any) -> None:
    """The process-wide registry is what the worker reads; registration must reach it."""
    from app.jobs_and_outbox.registry import registry as process_registry

    register()

    assert process_registry.is_registered(INVALIDATION_JOB_TYPE)
