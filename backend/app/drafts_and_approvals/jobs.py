"""Drafting and validation as job types (T-058b2b2a; §8.3 steps 9-11, §10.5, §17.1, §7.2).

The two steps that turn an approved candidate into a message revision a reviewer can act on.
Together they are the end of the Stage 1 pipeline: §8.3 step 11 presents the exact immutable
revision for review, and step 12's send waits on a *second* approval that Stage 1 never gives.

**Drafting refuses any candidate that is not `approved`, and that refusal is the guarantee.**
§8.3 step 9 creates a draft "on candidate approval". `campaigns.approval` is the ordinary way
that happens, but a convention about who enqueues a job protects nothing — a stray enqueue, a
replayed payload from a queue dump, a future chain someone adds without reading §8.3, and the
draft exists. So the precondition lives on the handler, where it holds whoever calls it. The
automatic cascade ends at `review_pending` (`T-058b2b1`), which is not `approved`, so the chain
*cannot* reach here even if something enqueued the job.

**Validation is a separate job, not a step inside drafting.** A revision is validated again
whenever its claims change — `T-056`'s invalidation is the push side of the same concern — so
"validate this revision" has to be a thing that can be asked for on its own. Drafting chains
into it because a draft nobody validated is a draft nobody may review (§8.3 step 10 before
step 11).

**Neither job is naturally idempotent, so both carry a guard.** `draft_message` writes a new
`MessageRevision` on every call and `apply_validation` transitions one, and §8.2 has no
self-edges (`T-010`). A replay without the guards would produce a second revision for the same
approval — two messages a reviewer must choose between, from one decision — or dead-letter a job
that had already succeeded.

**Versions are resolved, not passed**, for the reasons `qualification.jobs` records: §7.2's
cycle begins "validate policy and input version" and §14.5 requires a run to cite what it used.
"""

import uuid
from datetime import timedelta
from typing import Any, Final

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.audit_and_operations.versioning import (
    ModelConfigVersion,
    PromptVersion,
    SchemaVersion,
    VersionNotFound,
    require_effective_version,
)
from app.campaigns.candidate import CampaignCandidate
from app.core.lifecycles import CampaignCandidateState, MessageRevisionState
from app.drafts_and_approvals.drafting import TASK_NAME, draft_message
from app.drafts_and_approvals.models import MessageRevision
from app.drafts_and_approvals.validation import apply_validation
from app.jobs_and_outbox.queue import enqueue
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.registry import registry as default_registry
from app.jobs_and_outbox.retry import PermanentFailure, RetryPolicy
from app.model_gateway.gateway import DatabaseModelGateway
from app.model_gateway.schemas import DRAFT_KEY

log = structlog.get_logger(__name__)

DRAFT_JOB_TYPE: Final = "drafts.draft_message"
VALIDATE_JOB_TYPE: Final = "drafts.validate_revision"

DRAFT_ACTOR: Final = Actor(type=ActorType.SERVICE, id="drafts.draft-job")
VALIDATE_ACTOR: Final = Actor(type=ActorType.SERVICE, id="drafts.validate-job")

#: The one candidate state a draft may be written for (§8.3 step 9).
DRAFTABLE_STATE: Final = CampaignCandidateState.APPROVED

#: The one revision state validation has work to do in. §8.2 sends a `draft` to
#: `review_pending` or `validation_failed`, and offers no edge back from either (`T-010`).
VALIDATABLE_STATE: Final = MessageRevisionState.DRAFT

#: See `qualification.jobs.DEFAULT_MODEL_CONFIG_KEY` — a deployment decision, not a task one.
DEFAULT_MODEL_CONFIG_KEY: Final = "draft-model-config"


class DraftPayload(BaseModel):
    """One approved candidate, and the exact address its approval named.

    The recipient is carried rather than re-resolved: ADR-008 approves a recipient and a revision
    together, so the address the approver saw is the address the draft is for.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: uuid.UUID
    recipient_contact_point_id: uuid.UUID
    model_config_key: str = DEFAULT_MODEL_CONFIG_KEY


class ValidatePayload(BaseModel):
    """One revision to validate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: uuid.UUID


def _existing_revision(session: Session, candidate_id: uuid.UUID) -> MessageRevision | None:
    """Any revision already written for this candidate's draft.

    The idempotency key. `T-054` creates one `MessageDraft` per candidate and revisions under it,
    so "this candidate already has a revision" is the question a replay must answer.
    """
    return (
        session.execute(
            select(MessageRevision)
            .join(MessageRevision.draft)
            .where(MessageRevision.draft.has(candidate_id=candidate_id))
            .order_by(MessageRevision.revision_number)
        )
        .scalars()
        .first()
    )


def handle_draft(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Draft one message for an approved candidate, then queue its validation."""
    if not isinstance(payload, DraftPayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected DraftPayload, got {type(payload).__name__}")

    candidate = session.get(CampaignCandidate, payload.candidate_id)
    if candidate is None:
        raise PermanentFailure(f"no campaign candidate {payload.candidate_id}")

    existing = _existing_revision(session, candidate.id)
    if existing is not None:
        # A replay. Re-queue the validation rather than returning silently: if the crash happened
        # between writing the revision and enqueueing, the revision would otherwise sit in
        # `draft` forever, and a duplicate validation job is harmless because it is idempotent.
        log.info("draft.already_written", candidate_id=str(candidate.id))
        enqueue(
            session,
            job_type=VALIDATE_JOB_TYPE,
            payload={"revision_id": str(existing.id)},
            actor=DRAFT_ACTOR,
        )
        return

    if candidate.state is not DRAFTABLE_STATE:
        # Permanent, and deliberately not a quiet return. Something asked for a draft that §8.3
        # step 9 does not allow, and that is worth a dead job an operator can see rather than a
        # log line nobody reads.
        raise PermanentFailure(
            f"candidate {candidate.id} is {candidate.state.value}, not {DRAFTABLE_STATE.value}; "
            f"§8.3 step 9 creates a draft on candidate approval"
        )

    try:
        prompt = require_effective_version(session, PromptVersion, TASK_NAME)
        schema = require_effective_version(session, SchemaVersion, DRAFT_KEY)
        config = require_effective_version(session, ModelConfigVersion, payload.model_config_key)
    except VersionNotFound as exc:
        raise PermanentFailure(str(exc)) from exc

    revision = draft_message(
        session,
        candidate,
        DatabaseModelGateway(),
        recipient_contact_point_id=payload.recipient_contact_point_id,
        prompt_version_id=prompt.id,
        schema_version_id=schema.id,
        model_config_version_id=config.id,
        actor=DRAFT_ACTOR,
    )
    # Same transaction as the revision (§7.2). A draft nobody validated is a draft nobody may
    # review (§8.3 step 10 before step 11).
    enqueue(
        session,
        job_type=VALIDATE_JOB_TYPE,
        payload={"revision_id": str(revision.id)},
        actor=DRAFT_ACTOR,
    )
    log.info("draft.written", candidate_id=str(candidate.id), revision_id=str(revision.id))


def handle_validate(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Validate one revision, sending it to review or to `validation_failed`."""
    if not isinstance(payload, ValidatePayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected ValidatePayload, got {type(payload).__name__}")

    revision = session.get(MessageRevision, payload.revision_id)
    if revision is None:
        raise PermanentFailure(f"no message revision {payload.revision_id}")

    if revision.state is not VALIDATABLE_STATE:
        log.info(
            "validate.already_done",
            revision_id=str(revision.id),
            state=revision.state.value,
        )
        return

    result = apply_validation(session, revision, actor=VALIDATE_ACTOR)
    # Nothing is enqueued either way. A valid revision waits on a person (§8.3 step 11); an
    # invalid one waits on someone deciding what to do about it. Neither is the queue's business.
    log.info(
        "validate.done",
        revision_id=str(revision.id),
        valid=result.is_valid,
        # Check names, never the values that failed them (§15.5).
        failed_checks=[failure.check.value for failure in result.failures],
    )


def register(registry: JobRegistry | None = None) -> None:
    """Register both job types.

    Neither is consequential in §17.6's sense. Writing a draft and validating it produce no
    external effect — the send is step 12, behind a second approval and gate **G-07** — and a
    pause that stopped a reviewer's queue from filling would hide the work it was called to
    inspect.
    """
    target = registry or default_registry
    for name, model, handler in (
        (DRAFT_JOB_TYPE, DraftPayload, handle_draft),
        (VALIDATE_JOB_TYPE, ValidatePayload, handle_validate),
    ):
        if target.is_registered(name):
            continue
        target.register(
            name,
            model,
            handler,
            retry_policy=RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10)),
            consequential=False,
        )
