"""The operations read view (T-069a; §17.5, §17.6, §12.1).

**What the system is doing right now, for somebody holding a pager.** §17.5 asks operational
dashboards to expose queue depth and oldest job, dead-job rates, outbox backlog, delivery
ambiguity, and review backlog and age. Each number here is a count of real rows; none is derived,
smoothed, or cached.

**It lives in `outreach_and_replies`, and the import graph decided that rather than taste.**
`T-069`'s own file hint said `audit_and_operations`, which is where an operations panel obviously
belongs — and it is impossible. That package is the platform module *nine* domain packages
already import, so importing `jobs_and_outbox`, `drafts_and_approvals`, or this one back is a
package cycle, and `tests/test_module_boundaries.py::test_no_import_cycles` refuses it. This
package is the top of the domain graph — nothing but `main` and `worker` imports it, and it
already imports everything the counters need. Exactly the reasoning that put `approve_message`
here (`T-067a`), reached by measuring the graph rather than by finding out from the suite.

**Shadow mode is the first field, and it is the *effective* answer.** `shadow_mode_active` is
`settings.shadow_mode or the database flag` — two switches, either of which is enough. Reporting
one of them would be a panel that says outreach is live while a flag says otherwise, which is the
sentence an operator would act on at 3am.

**A metric with no data source is `null`, never `0`.** Suppressed-send attempts were reported that
way until `T-161`: `0` would read as "nothing is being suppressed", which is a claim nobody
checked, and a campaign whose every send is being refused looks identical to one with nothing to
send. They are now counted from the audit trail — the §11.4 recheck writes the refusal with the
scope that matched, and `refused_by_check_count` counts those rows. `not_measured` stays as the
mechanism for the next gap; it is empty today.

**Administrator-only, and that is a deliberate declaration.** `VIEW_OPERATIONS` is tier 5 rather
than folded into `VIEW_STATUS`, which every role holds: dead-job reasons, backlog depths, and
which safety switches are thrown are the operator's map and would equally be an attacker's.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Final

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.flags import (
    FlagError,
    FlagKey,
    OperationalFlag,
    set_flag,
    shadow_mode_active,
)
from app.campaigns.candidate import (
    candidates_awaiting_review,
    oldest_candidate_awaiting_review_at,
)
from app.core.lifecycles import OutreachThreadState
from app.core.settings import Settings, get_settings
from app.drafts_and_approvals.approval import InvalidationTrigger, approvals_needing_attention
from app.drafts_and_approvals.revisions import revisions_awaiting_review
from app.identity.dependencies import db_session, requires, requires_mutation
from app.identity.rbac import Permission
from app.identity.sessions import Principal
from app.jobs_and_outbox.outbox import (
    oldest_pending_outbox_at,
    pending_outbox_count,
    refused_by_check_count,
)
from app.jobs_and_outbox.queue import (
    dead_job_count,
    dead_jobs,
    job_counts_by_state,
    oldest_runnable_job_at,
)
from app.outreach_and_replies.models import OutreachThread
from app.outreach_and_replies.preconditions import Recheck

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/operations", tags=["operations"])

#: How many dead jobs to name. A count answers "is something wrong"; the reasons answer "what",
#: and §17.1 already guarantees every dead job carries one. Bounded because a panel that renders
#: ten thousand rows is a panel nobody opens during an incident.
DEAD_JOB_SAMPLE: Final = 20


class DeadJob(BaseModel):
    """One job that will not be retried, and why (§17.1)."""

    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID
    job_type: str
    #: Never null: `dead_job_must_carry_a_reason` is a database constraint, not a convention.
    reason: str
    attempt_count: int
    requires_human_review: bool


class OperationsOverview(BaseModel):
    """§17.5's dashboard, as far as this repository has data for it."""

    model_config = ConfigDict(frozen=True)

    #: First, and effective: configuration *or* the database flag. See the module docstring.
    shadow_mode: bool
    #: Every flag currently switched on, by key. An operator reading "paused" needs to know it is
    #: the flag rather than an outage.
    flags_in_force: list[str]

    #: Jobs by state (§17.5 "queue depth"), and how long the oldest runnable one has waited.
    jobs_by_state: dict[str, int]
    oldest_queued_job_age_seconds: int | None
    dead_jobs: int
    dead_job_sample: list[DeadJob]

    #: The transactional outbox (§17.3): work decided but not yet performed.
    outbox_pending: int
    oldest_pending_outbox_age_seconds: int | None

    #: §17.3's "may have arrived" state. Never retried blindly, so it needs a human.
    delivery_ambiguous_threads: int

    #: §17.5 "review backlog and age" — the two queues `T-063a`/`T-063b` serve.
    candidates_awaiting_review: int
    revisions_awaiting_review: int
    oldest_review_item_age_seconds: int | None

    #: Approvals no longer valid because the claim set they pinned was superseded (§8.4).
    claim_invalidations: int

    #: §17.5's last item, measurable since `T-161`: dispatches the §11.4 suppression recheck
    #: refused. Attempts, not recipients — the same address refused three times is three.
    suppressed_send_attempts: int

    #: Numbers §17.5 asks for that this repository has no data source for. Empty today, and kept
    #: rather than deleted: it is the mechanism by which an unmeasured number is *stated* instead
    #: of shown as a zero an operator would act on, and the next gap should use it rather than
    #: reinvent it. `operations-panel.test.tsx::states an unmeasured number rather than implying a
    #: zero` keeps the panel's rendering path alive against a placeholder.
    not_measured: list[str]


def _age_seconds(moment: datetime | None, now: datetime) -> int | None:
    """Whole seconds since ``moment``, or `None` if there is nothing waiting.

    `None` and `0` are different answers — an empty queue and a queue whose oldest item arrived
    this instant — and an operator reads them differently.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:  # pragma: no cover - every column is timezone-aware
        moment = moment.replace(tzinfo=UTC)
    return max(0, int((now - moment).total_seconds()))


@router.get(
    "/overview",
    response_model=OperationsOverview,
    summary="What the system is doing right now (administrator only)",
)
def operations_overview(
    session: Annotated[Session, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[Principal, Depends(requires(Permission.VIEW_OPERATIONS))],
) -> OperationsOverview:
    """Every §17.5 counter this repository has rows for, plus the switches in force.

    `principal` is unused in the body and required in the signature: it is what runs the
    authorization, and naming it keeps that visible at the endpoint rather than hidden in a
    decorator somebody could remove without the route looking different (`T-063a`'s reasoning).
    """
    now = datetime.now(UTC)

    # Each count comes from the package that owns the lifecycle it reads.
    # `tests/test_invariants.py::test_only_the_owning_package_names_a_lifecycle` refuses this
    # module to name `JobState`, `CampaignCandidateState`, or `MessageRevisionState` — the state
    # vocabulary belongs to its owner, and a counter spelling it here would be a second place to
    # update when a state is added. Found by the suite, which is what it is for.
    jobs_by_state = job_counts_by_state(session)
    oldest_queued = oldest_runnable_job_at(session)
    dead = dead_jobs(session, limit=DEAD_JOB_SAMPLE)
    oldest_outbox = oldest_pending_outbox_at(session)
    oldest_review = oldest_candidate_awaiting_review_at(session)

    claim_invalidations = sum(
        1
        for _, detail in approvals_needing_attention(session)
        if detail.trigger is InvalidationTrigger.CLAIM_SET_SUPERSEDED
    )

    return OperationsOverview(
        shadow_mode=shadow_mode_active(session, settings),
        flags_in_force=sorted(
            key.value
            for key in session.execute(
                select(OperationalFlag.key).where(OperationalFlag.enabled.is_(True))
            )
            .scalars()
            .all()
            if isinstance(key, FlagKey)
        ),
        jobs_by_state=jobs_by_state,
        oldest_queued_job_age_seconds=_age_seconds(oldest_queued, now),
        dead_jobs=dead_job_count(session),
        dead_job_sample=[
            DeadJob(
                job_id=job.id,
                job_type=job.job_type,
                # The constraint guarantees a reason on a dead job; the fallback exists so a
                # panel never renders `None` if that ever ceases to be true.
                reason=job.last_error or "no reason recorded",
                attempt_count=job.attempt_count,
                requires_human_review=job.requires_human_review,
            )
            for job in dead
        ],
        outbox_pending=pending_outbox_count(session),
        oldest_pending_outbox_age_seconds=_age_seconds(oldest_outbox, now),
        delivery_ambiguous_threads=session.execute(
            select(func.count())
            .select_from(OutreachThread)
            .where(OutreachThread.state == OutreachThreadState.DELIVERY_UNKNOWN)
        ).scalar_one(),
        candidates_awaiting_review=candidates_awaiting_review(session),
        revisions_awaiting_review=revisions_awaiting_review(session),
        oldest_review_item_age_seconds=_age_seconds(oldest_review, now),
        claim_invalidations=claim_invalidations,
        suppressed_send_attempts=refused_by_check_count(session, Recheck.SUPPRESSION.value),
        not_measured=[],
    )


# --- §17.6 operational controls (T-069b) --------------------------------------------------------
#
# **These switches can only ever stop things.** `shadow_mode_active` is `settings.shadow_mode or
# the flag`, and `outbound_email_allowed` requires *every* switch to agree — so releasing a flag
# here cannot enable an external effect that configuration has not already enabled, and gate
# **G-07** still governs live sending. A test asserts exactly that, because "the pause button
# cannot become a start button" is the property an operator is trusting when they throw it.
#
# **Only the system-wide keys.** `PRODUCT_DISABLED` and `CLAIM_VERSION_DISABLED` address a
# specific row and need a `scope_id`; disabling a named product or claim version is a
# products-and-claims action with its own authority, not a global operational switch, and
# accepting it here would put that decision behind the pause button's permission.


class FlagChangeRequest(BaseModel):
    """Throw or release one switch, and say why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    #: Required in both directions. `set_flag` refuses a blank one too — this bound is the schema
    #: saying so early, and §17.6 wants the operational action explicable either way. Releasing a
    #: pause is the more consequential half and is exactly what an incident review asks about.
    reason: str = Field(min_length=1, max_length=1000)


class FlagChangeResponse(BaseModel):
    """What the switch now says."""

    model_config = ConfigDict(frozen=True)

    key: str
    enabled: bool
    reason: str
    set_by: str
    set_at: datetime
    #: Stated back because a flag is not the whole answer: shadow mode is configuration *or* the
    #: flag, so an administrator releasing the flag needs to see whether anything changed.
    shadow_mode: bool
    what_happens_next: str


CONTROL_OUTCOME_NOTE: Final = (
    "The switch is recorded and takes effect on the next check. Releasing a switch cannot enable "
    "an external effect that configuration has not already enabled, and live sending stays gated "
    "(G-07)."
)


@router.post(
    "/flags/{key}",
    response_model=FlagChangeResponse,
    summary="Throw or release a system-wide operational switch (administrator only)",
)
def set_operational_flag(
    key: FlagKey,
    request: FlagChangeRequest,
    session: Annotated[Session, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[Principal, Depends(requires_mutation(Permission.PAUSE_SYSTEM))],
) -> FlagChangeResponse:
    """§17.6's global pause, shadow-mode switch, and outbound-email disable.

    `PAUSE_SYSTEM` is tier 5 and administrator-only (§7.4): these are the switches that stop the
    system, and §12.1 gives them to nobody else. The actor comes from the session, never from the
    request (§15.1, `T-070c`), and `set_flag` writes the audit event.

    **A scoped key is refused by `set_flag`, not by a check here.** This route first carried its
    own `key in SCOPED_KEYS` guard, and a negative control proved it dead: deleting it changed
    nothing, because `PRODUCT_DISABLED` with no `scope_id` is already a `FlagError` one layer
    down. A rule enforced twice is a rule that can disagree with itself, and the copy nobody
    exercises is the one that drifts — the same reasoning that removed the duplicate
    verification check from `approve_message._recheck`.
    """
    try:
        flag = set_flag(
            session,
            key=key,
            enabled=request.enabled,
            actor=principal.actor,
            reason=request.reason,
        )
    except FlagError as refusal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(refusal)
        ) from refusal

    session.commit()

    # The switch is logged as an event, never the reason: §17.5 wants the actor and the action,
    # and a reason is free text an operator typed.
    log.info(
        "operational_flag.changed",
        key=key.value,
        enabled=request.enabled,
        actor_id=principal.actor.id,
    )
    return FlagChangeResponse(
        key=flag.key.value,
        enabled=flag.enabled,
        reason=flag.reason,
        set_by=flag.set_by,
        set_at=flag.set_at,
        shadow_mode=shadow_mode_active(session, settings),
        what_happens_next=CONTROL_OUTCOME_NOTE,
    )
