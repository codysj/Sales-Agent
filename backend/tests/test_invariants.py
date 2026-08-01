"""Cross-entity invariants (T-024; §8.2, §3.5, §19.2, ADR-015).

Every other test file checks one module. This one checks the seams *between* modules — the place
where each part is individually correct and the combination is not. ADR-015 requires the five
lifecycles to stay independent, and independence is exactly the kind of property that erodes without
anyone deciding to erode it.

`T-024` added this file and deliberately changed no production code: the two invariants that did not
hold were marked `xfail(strict=True)` naming the task that would fix them. Both have since been
closed — `T-140` (approval consults its candidate) and `T-141` (a thread needs a command to leave
`not_started`) — so no xfail remains here. Strict was the point: implementing a guard turned the
marker into a failure telling the author to delete it, which is why neither finding got lost.

If a future invariant is added that does not hold, mark it the same way rather than fixing it here.
"""

import ast
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import structlog
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.campaigns.candidate import transition as transition_candidate
from app.core.lifecycles import (
    ALLOWED_TRANSITIONS,
    ApprovalState,
    CampaignCandidateState,
    IllegalTransition,
    JobState,
    MessageRevisionState,
    OutreachThreadState,
)
from app.drafts_and_approvals.approval import (
    NON_APPROVABLE_CANDIDATE_STATES,
    CandidateNotApprovable,
    approve,
    request_approval,
    revoke,
)
from app.jobs_and_outbox.queue import enqueue, lease_jobs, mark_dead
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.retry import RetryPolicy
from app.outreach_and_replies.commands import (
    ThreadNotStartable,
    create_send_command,
    transition_thread,
)
from app.outreach_and_replies.models import SendCommand
from app.prospects.suppression import (
    SuppressionScope,
    SuppressionSource,
    is_suppressed,
    record_suppression,
)
from tests.factories import APPROVER, NOW, OPERATOR, World

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-invariant-test")


@pytest.fixture
def world(db_session: Session) -> World:
    w = World(db_session)
    w.activate()
    return w


#: The §8.2 path a candidate must actually walk. There is no shortcut from `imported` to a decision,
#: which is itself the point: a decision presupposes eligibility and research.
TO_REVIEW = (
    CampaignCandidateState.ELIGIBLE,
    CampaignCandidateState.RESEARCH_PENDING,
    CampaignCandidateState.RESEARCHED,
    CampaignCandidateState.REVIEW_PENDING,
)


def advance_candidate(
    session: Session, world: World, target: CampaignCandidateState
) -> CampaignCandidateState:
    """Walk a candidate to ``target`` one legal step at a time.

    Deliberately not a direct assignment: the whole invariant under test is that the lifecycle
    refuses shortcuts, so a test that took one would be testing nothing.

    `ineligible` is reachable only straight from `imported` — §8.2 treats "does not qualify" as a
    screening outcome, not a review outcome — so it needs its own path rather than the review one.
    """
    path = (target,) if target is CampaignCandidateState.INELIGIBLE else (*TO_REVIEW, target)
    for state in path:
        # `T-018` requires a reason for the negative outcomes: "a rejection that cannot be explained
        # is not reviewable" (§10.1). Supplied for every step, since the API ignores it elsewhere.
        transition_candidate(
            session,
            world.candidate,
            state,
            actor=OPERATOR,
            reason=f"synthetic {state.value} for an invariant test",
        )
    session.flush()
    return world.candidate.state


# --- 1. a rejected candidate cannot yield an approved revision (§8.2) --------------------------


def test_a_rejected_candidate_cannot_yield_an_approved_revision(
    db_session: Session, world: World
) -> None:
    """§8.2: rejecting a candidate is a decision about the whole prospect, not one message.

    The candidate and revision lifecycles are independent by design (ADR-015), but independence is
    not supposed to mean *ignorance*: a human who rejected the candidate has decided nobody should
    be written to, and an approval granted afterwards would contradict that decision without
    recording the contradiction anywhere.

    Fixed by `T-140`; this test carried an `xfail` marker while the gap was open.
    """
    advance_candidate(db_session, world, CampaignCandidateState.REJECTED)

    with pytest.raises(CandidateNotApprovable, match="rejected"):
        request_approval(
            db_session,
            revision=world.revision,
            approver_id=APPROVER,
            actor=OPERATOR,
            now=NOW,
        )


def test_rejecting_a_candidate_is_terminal(db_session: Session, world: World) -> None:
    """The half that does hold: a rejected candidate cannot quietly become approved again."""
    advance_candidate(db_session, world, CampaignCandidateState.REJECTED)

    with pytest.raises(IllegalTransition):
        transition_candidate(
            db_session, world.candidate, CampaignCandidateState.APPROVED, actor=OPERATOR
        )


# --- 2. an invalidated approval leaves the revision intact and immutable (§8.4) ----------------


def test_revoking_an_approval_leaves_the_revision_untouched(
    db_session: Session, world: World
) -> None:
    """§8.4 and §10.5: approval is a decision *about* a revision, never a property of it.

    If revocation could alter the revision, the audit trail would no longer show what was approved —
    and the whole point of pinning a content hash is that the record survives the decision changing.
    """
    approval = world.approval()
    before_hash = world.revision.content_hash
    before_state = world.revision.state

    revoke(db_session, approval, actor=OPERATOR, reason="claims withdrawn")
    db_session.flush()

    assert approval.state is ApprovalState.REVOKED
    assert world.revision.content_hash == before_hash
    assert world.revision.state is before_state


def test_the_revision_is_still_immutable_after_revocation(
    db_session: Session, world: World
) -> None:
    """A revoked approval must not unlock editing — that would let history be rewritten."""
    approval = world.approval()
    revoke(db_session, approval, actor=OPERATOR, reason="claims withdrawn")
    db_session.flush()

    world.revision.body = "EDITED AFTER REVOCATION"

    with pytest.raises(IntegrityError, match="message_revision content is immutable"):
        db_session.flush()


def test_no_approval_state_appears_in_the_revision_lifecycle() -> None:
    """Structural: the two lifecycles cannot even name each other's states (ADR-015)."""
    revision_states = set(MessageRevisionState)
    approval_states = set(ApprovalState)

    assert revision_states.isdisjoint(approval_states)
    for state in approval_states:
        assert state not in ALLOWED_TRANSITIONS[MessageRevisionState.DRAFT]


# --- 3. a dead job never advances candidate state (§17.1, §7.2) ---------------------------------


def test_a_dead_job_leaves_the_candidate_where_it_was(db_session: Session, world: World) -> None:
    """§7.2 puts the handler's writes and the job's state in one transaction.

    So a job that dies cannot have half-advanced a candidate: either the whole transaction committed
    or none of it did. This asserts the composition rather than trusting it.
    """

    class Payload(BaseModel):
        candidate_id: str

    registry = JobRegistry()
    registry.register(
        "synthetic.advance",
        Payload,
        lambda s, p, *, job_id: None,
        retry_policy=RetryPolicy(max_attempts=1, base_delay=timedelta(seconds=1), jitter=0.0),
        consequential=True,
    )
    before = world.candidate.state
    enqueue(
        db_session,
        job_type="synthetic.advance",
        payload={"candidate_id": str(world.candidate.id)},
        actor=OPERATOR,
        registry=registry,
    )
    db_session.flush()
    job = lease_jobs(db_session, worker_id="worker-a", limit=1)[0]

    mark_dead(db_session, job, actor=OPERATOR, error="synthetic permanent failure")
    db_session.flush()

    assert job.state is JobState.DEAD
    assert world.candidate.state is before, "a dead job must not have moved the candidate"


def test_a_dead_job_is_terminal_and_cannot_resume(db_session: Session, world: World) -> None:
    """If `dead` could be left, the "never advances" guarantee would only be about *this* moment."""
    assert ALLOWED_TRANSITIONS[JobState.DEAD] == frozenset()


def test_no_candidate_state_appears_in_the_job_lifecycle() -> None:
    candidate_states = set(CampaignCandidateState)

    assert candidate_states.isdisjoint(set(JobState))
    for state in candidate_states:
        assert state not in ALLOWED_TRANSITIONS[JobState.LEASED]


# --- 4. a thread cannot leave not_started without an approved send command (§8.2, §11.4) ------


def test_a_thread_cannot_be_queued_without_a_send_command(
    db_session: Session, world: World
) -> None:
    """§11.4: an outreach thread leaving `not_started` asserts that a send was authorized.

    Nothing external happens on this transition, so it is not a §3.5 violation on its own — but a
    thread in `queued` with no command behind it is a record that claims an approval exists when it
    does not, and the dashboard reads thread state.

    Fixed by `T-141`; this test carried an `xfail` marker while the gap was open.
    """
    assert (
        db_session.query(SendCommand).filter(SendCommand.thread_id == world.thread.id).count() == 0
    )

    with pytest.raises(ThreadNotStartable, match="no send command exists"):
        transition_thread(db_session, world.thread, OutreachThreadState.QUEUED, actor=OPERATOR)


@pytest.mark.parametrize(
    "target",
    sorted(ALLOWED_TRANSITIONS[OutreachThreadState.NOT_STARTED], key=lambda s: s.value),
    ids=lambda s: s.value,
)
def test_no_exit_from_not_started_works_without_a_command(
    db_session: Session, world: World, target: OutreachThreadState
) -> None:
    """Every legal exit, not just `queued`.

    Checking one target would leave the others open, and the lifecycle table may grow an exit later.
    Parametrizing over the table means a new edge is covered the day it is added.
    """
    with pytest.raises(ThreadNotStartable):
        transition_thread(db_session, world.thread, target, actor=OPERATOR)


def test_the_guard_applies_only_when_leaving_not_started(db_session: Session, world: World) -> None:
    """Later transitions must not re-run the check.

    Once a thread has left `not_started` a command demonstrably existed, so re-checking would be
    dead weight — and worse, would couple every subsequent transition to a query that can only
    succeed.
    """
    create_send_command(
        db_session,
        thread=world.thread,
        approval=world.approval(),
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        now=NOW,
    )
    db_session.flush()
    transition_thread(db_session, world.thread, OutreachThreadState.QUEUED, actor=OPERATOR)

    transition_thread(db_session, world.thread, OutreachThreadState.SENDING, actor=OPERATOR)

    assert world.thread.state is OutreachThreadState.SENDING


def test_not_started_is_the_only_state_the_guard_reads() -> None:
    """The guard is about one edge in the lifecycle, and its name says which.

    Asserted structurally so the check cannot quietly grow into a general precondition on every
    transition — which would make thread state depend on a query in states where it should not.
    """
    source = (APP / "outreach_and_replies" / "commands.py").read_text(encoding="utf-8")

    assert "if previous is OutreachThreadState.NOT_STARTED:" in source
    assert source.count("require_send_command(session, thread)") == 1


def test_a_thread_with_a_send_command_may_be_queued(db_session: Session, world: World) -> None:
    """The intended path, so the xfail above is about the missing guard and not about the flow."""
    create_send_command(
        db_session,
        thread=world.thread,
        approval=world.approval(),
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        now=NOW,
    )
    db_session.flush()

    transition_thread(db_session, world.thread, OutreachThreadState.QUEUED, actor=OPERATOR)

    assert world.thread.state is OutreachThreadState.QUEUED


def test_a_send_command_requires_a_valid_approval(db_session: Session, world: World) -> None:
    """The guard that *does* exist, and the one that matters: no command without an approval."""
    approval = world.approval()
    revoke(db_session, approval, actor=OPERATOR, reason="claims withdrawn")
    db_session.flush()

    with pytest.raises(Exception, match=r"approval|revoked"):
        create_send_command(
            db_session,
            thread=world.thread,
            approval=approval,
            campaign_id=world.campaign.id,
            actor=OPERATOR,
            now=NOW,
        )


# --- 5. suppression outranks an approved candidate (§15.6, §11.4) ------------------------------


def test_suppression_outranks_an_approved_candidate(db_session: Session, world: World) -> None:
    """§15.6: suppression is stronger than any approval, including a human's.

    Approving a candidate is a decision to write to someone. Suppression is that someone's decision
    not to be written to, and it wins — checked again at dispatch (`T-035c`) precisely because the
    approval may be older than the suppression.
    """
    advance_candidate(db_session, world, CampaignCandidateState.APPROVED)
    record_suppression(
        db_session,
        scope=SuppressionScope.EMAIL,
        identity=world.recipient.value,
        source=SuppressionSource.UNSUBSCRIBE,
        reason="synthetic opt-out",
        effective_at=NOW - timedelta(days=1),
    )
    db_session.flush()

    assert world.candidate.state is CampaignCandidateState.APPROVED
    assert is_suppressed(db_session, email=world.recipient.value, at=NOW) is True


def test_approving_a_candidate_does_not_clear_a_suppression(
    db_session: Session, world: World
) -> None:
    """The direction that would be catastrophic: an approval must never lift an opt-out."""
    record_suppression(
        db_session,
        scope=SuppressionScope.EMAIL,
        identity=world.recipient.value,
        source=SuppressionSource.UNSUBSCRIBE,
        reason="synthetic opt-out",
        effective_at=NOW - timedelta(days=1),
    )
    db_session.flush()

    advance_candidate(db_session, world, CampaignCandidateState.APPROVED)

    assert is_suppressed(db_session, email=world.recipient.value, at=NOW) is True


def test_suppression_has_no_lifecycle_to_be_transitioned_out_of() -> None:
    """§15.6: suppression is permanent. It is not a state machine, so it cannot be *un*-set."""
    from app.prospects.suppression import Suppression

    assert not hasattr(Suppression, "state")


# --- 6. no code path mutates two lifecycles in one unguarded step (ADR-015) ---------------------

#: Which package owns each lifecycle's transitions. A module that cannot *name* another lifecycle's
#: states cannot move them, which is a stronger guarantee than reviewing call sites.
LIFECYCLE_OWNERS: dict[str, frozenset[str]] = {
    # `qualification` is an owner, not a reader: §8.3 step 4 makes hard eligibility the thing that
    # moves a candidate out of `imported`, so `T-045` transitions it rather than merely consulting
    # it. The guarantee this map exists for is untouched — the check is that no function spans two
    # lifecycles, and `test_eligibility.py` pins that eligibility names exactly this one.
    "CampaignCandidateState": frozenset({"campaigns", "qualification", "core"}),
    "MessageRevisionState": frozenset({"drafts_and_approvals", "core"}),
    "ApprovalState": frozenset({"drafts_and_approvals", "core"}),
    "OutreachThreadState": frozenset({"outreach_and_replies", "core"}),
    "JobState": frozenset({"jobs_and_outbox", "core"}),
}

#: Packages allowed to **read** a lifecycle they do not own, and why.
#:
#: ADR-015 forbids one module *transitioning* another's entity. It does not forbid consulting one —
#: and no cross-entity invariant can be enforced without a read. `T-140` needed exactly this: an
#: approval must refuse a candidate already decided against, which means reading candidate state.
#:
#: Widening the owner set alone would have lost the guarantee, so readers are listed separately and
#: `test_a_reader_never_transitions_what_it_reads` holds them to reading only.
LIFECYCLE_READERS: dict[str, frozenset[str]] = {
    # T-140: approval refuses a rejected/deferred/invalidated candidate (§8.2).
    # T-046: evidence capture refuses a candidate that has not passed the eligibility gate, because
    # §8.3 puts step 4 before steps 5-6. It consults the state and never moves it — the compensating
    # check below holds it to that.
    "CampaignCandidateState": frozenset({"drafts_and_approvals", "research_and_evidence"}),
}


def readers_of(lifecycle: str) -> frozenset[str]:
    return LIFECYCLE_OWNERS[lifecycle] | LIFECYCLE_READERS.get(lifecycle, frozenset())


def imported_lifecycle_names(path: Path) -> set[str]:
    """Lifecycle enum names a module imports, from its AST rather than a text search."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.core.lifecycles":
            names.update(alias.name for alias in node.names)
    return names


def owning_package(path: Path) -> str:
    relative = path.relative_to(APP)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


@pytest.mark.parametrize("lifecycle", sorted(LIFECYCLE_OWNERS), ids=lambda name: name)
def test_only_the_owning_package_names_a_lifecycle(lifecycle: str) -> None:
    """ADR-015, enforced structurally.

    A function that moves two lifecycles in one step has to name both. Checking *imports* catches
    that at the module level, which is where the coupling would first appear — and unlike a review
    convention, it cannot be forgotten.

    `worker.py` and `main.py` are leaves that compose everything and are exempt: composition across
    modules is their entire job, and nothing imports them (`test_module_boundaries.py`).
    """
    allowed = readers_of(lifecycle)
    offenders = {
        str(path.relative_to(APP))
        for path in sorted(APP.rglob("*.py"))
        if path.stem not in {"worker", "main"}
        and lifecycle in imported_lifecycle_names(path)
        and owning_package(path) not in allowed
    }

    assert not offenders, f"{lifecycle} is named outside {sorted(allowed)}: {sorted(offenders)}"


@pytest.mark.parametrize("lifecycle", sorted(LIFECYCLE_READERS), ids=lambda name: name)
def test_a_reader_never_transitions_what_it_reads(lifecycle: str) -> None:
    """The compensating check for `LIFECYCLE_READERS`.

    An allowed reader must consult and nothing more, so it may not import the owning package's
    transition helper and may not assign to the entity's `.state`. Without this, the reader list
    would just be a hole in the guard above — which is what a bare widening would have been.
    """
    owner_helpers = {"transition", "transition_candidate", "transition_thread"}
    entity_hint = lifecycle.removesuffix("State").lower()
    offenders: list[str] = []

    for package in LIFECYCLE_READERS[lifecycle]:
        for path in sorted((APP / package).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported = {
                alias.asname or alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            if imported & owner_helpers or f"{entity_hint}.state = " in source:
                offenders.append(str(path.relative_to(APP)))

    assert not offenders, f"{lifecycle} readers must not transition it: {sorted(offenders)}"


def test_the_lifecycle_owner_map_covers_every_lifecycle() -> None:
    """A guard on the guard: a new lifecycle with no owner would be silently unchecked."""
    from app.core.lifecycles import LIFECYCLES

    assert {lifecycle.__name__ for lifecycle in LIFECYCLES} == set(LIFECYCLE_OWNERS)


def test_every_lifecycle_transition_goes_through_one_guard() -> None:
    """`assert_transition` is the only way to move any of the five (§8.2).

    Asserted by inspection: every module that assigns to a `.state` attribute of a lifecycle-owning
    entity also imports `assert_transition`. A module that mutated state without it would be making
    an unchecked transition, which is the "unguarded step" this invariant is about.
    """
    unguarded: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path.stem in {"worker", "main"}:
            continue
        source = path.read_text(encoding="utf-8")
        names = imported_lifecycle_names(path)
        moves_state = ".state = " in source
        lifecycle_names = names & set(LIFECYCLE_OWNERS)
        if moves_state and lifecycle_names and "assert_transition" not in names:
            unguarded.append(str(path.relative_to(APP)))

    assert not unguarded, f"these modules assign lifecycle state without a guard: {unguarded}"


def test_the_state_scan_is_not_vacuous() -> None:
    """If nothing in `app/` assigned lifecycle state, the test above would prove nothing."""
    movers = [
        str(path.relative_to(APP))
        for path in sorted(APP.rglob("*.py"))
        if ".state = " in path.read_text(encoding="utf-8")
    ]

    assert len(movers) >= 4, f"expected several state-moving modules, found {movers}"


def test_a_uuid_is_not_a_lifecycle() -> None:
    """Sanity anchor for the import scan: it looks for enum names, not arbitrary identifiers."""
    assert "uuid" not in LIFECYCLE_OWNERS
    assert isinstance(uuid.uuid4(), uuid.UUID)


# --- T-140: the fix, at both layers ------------------------------------------------------------


def test_the_non_approvable_set_is_exactly_the_decided_against_states() -> None:
    """A guard on the guard, and it was needed.

    The parametrized test below draws its cases *from* `NON_APPROVABLE_CANDIDATE_STATES`, so
    shrinking that set removes a case rather than failing one — a negative control that deleted
    `DEFERRED` passed. Naming the four states explicitly is what makes the set itself testable.

    The complement matters too: the pre-decision states must stay approvable, or drafting during
    research would break.
    """
    assert (
        frozenset(
            {
                CampaignCandidateState.INELIGIBLE,
                CampaignCandidateState.REJECTED,
                CampaignCandidateState.DEFERRED,
                CampaignCandidateState.INVALIDATED,
            }
        )
        == NON_APPROVABLE_CANDIDATE_STATES
    )
    still_approvable = set(CampaignCandidateState) - NON_APPROVABLE_CANDIDATE_STATES
    assert still_approvable == {
        CampaignCandidateState.IMPORTED,
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
        CampaignCandidateState.REVIEW_PENDING,
        CampaignCandidateState.APPROVED,
    }


@pytest.mark.parametrize(
    "state",
    sorted(NON_APPROVABLE_CANDIDATE_STATES, key=lambda s: s.value),
    ids=lambda s: s.value,
)
def test_every_decided_against_candidate_state_blocks_approval(
    db_session: Session, world: World, state: CampaignCandidateState
) -> None:
    """§8.2: all four are decisions that a send should not happen.

    `deferred` is included because §10.6 makes it "not now" rather than "no" — approving during a
    deferral would silently override it.
    """
    advance_candidate(db_session, world, state)

    with pytest.raises(CandidateNotApprovable, match=state.value):
        request_approval(
            db_session,
            revision=world.revision,
            approver_id=APPROVER,
            actor=OPERATOR,
            now=NOW,
        )


def test_a_candidate_still_under_review_may_be_approved(db_session: Session, world: World) -> None:
    """The states before a decision are deliberately allowed.

    A draft can legitimately exist while research and review are in progress; refusing there would
    break the drafting flow rather than protect anyone.
    """
    advance_candidate(db_session, world, CampaignCandidateState.APPROVED)

    approval = request_approval(
        db_session, revision=world.revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    approve(db_session, approval, actor=OPERATOR, now=NOW)

    assert approval.state is ApprovalState.APPROVED


def test_a_candidate_rejected_between_request_and_grant_is_caught(
    db_session: Session, world: World
) -> None:
    """The window a reviewer actually sits in.

    Checking only at `request_approval` would let a candidate be rejected while the reviewer reads
    the message, and the grant would still succeed. `approve` re-reads for exactly that reason.
    """
    approval = request_approval(
        db_session, revision=world.revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    advance_candidate(db_session, world, CampaignCandidateState.REJECTED)

    with pytest.raises(CandidateNotApprovable, match="rejected"):
        approve(db_session, approval, actor=OPERATOR, now=NOW)


def test_the_approval_module_reads_candidate_state_and_never_writes_it() -> None:
    """ADR-015 independence, criterion 3.

    Consulting another lifecycle is required by any cross-entity invariant; *transitioning* it is
    what independence forbids. Asserted at the source, because the difference is one line of code.
    """
    source = (APP / "drafts_and_approvals" / "approval.py").read_text(encoding="utf-8")

    assert "candidate_refusal" in source
    assert "CampaignCandidateState" in source
    # The two ways this module could move a candidate: calling the transition helper, or assigning
    # to the attribute directly.
    assert "transition_candidate" not in source
    assert "candidate.state =" not in source


# --- minting an opt-out (T-178; §15.6, §15.8) -----------------------------------------------------
#
# `record_opt_out()` enforces four things `record_suppression()` does not: the source must be
# permanent, `effective_at` is clamped so an opt-out can never be future-dated, the same unsubscribe
# twice records one row, and the person is suppressed as well as the mailbox. Calling
# `record_suppression(source=SuppressionSource.UNSUBSCRIBE)` directly gets none of them, and because
# a suppression cannot be deleted (§15.6) the resulting row is permanent and looks correct.
#
# The rule is about *minting*, not carrying. `prospects/dedup.py` passes `source=suppression.source`
# — a variable — when it copies an existing suppression onto a surviving contact. That is a decision
# already made, so it is deliberately not flagged, and the guard below proves the walk sees that
# call and lets it through rather than never having found it.

MINTING_FUNCTION = "record_suppression"

#: Matched by attribute name, so `from ... import SuppressionSource as SS` then `SS.UNSUBSCRIBE`
#: does not evade the check. Spelled as strings because this walk reads source, not objects.
UNLIFTABLE_SOURCE_NAMES = frozenset({"UNSUBSCRIBE", "COMPLAINT"})


def called_name(node: ast.Call) -> str | None:
    """The bare function name of a call, whether written `f()` or `pkg.mod.f()`."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def local_names_for(tree: ast.AST, target: str) -> set[str]:
    """Every local name bound to ``target``, so `import record_suppression as rs` is caught too."""
    names = {target}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(
                alias.asname for alias in node.names if alias.name == target and alias.asname
            )
    return names


def opt_out_minting_lines(tree: ast.AST) -> list[int]:
    """Lines where a *literal* unliftable source is handed to `record_suppression`."""
    names = local_names_for(tree, MINTING_FUNCTION)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and called_name(node) in names
        for keyword in node.keywords
        if keyword.arg == "source"
        and isinstance(keyword.value, ast.Attribute)
        and keyword.value.attr in UNLIFTABLE_SOURCE_NAMES
    ]


def test_no_module_mints_an_opt_out_around_record_opt_out() -> None:
    """`T-178`. The bypass `T-102b` and `T-103` are the natural authors of.

    **Known limit:** a source held in a variable (`src = SuppressionSource.UNSUBSCRIBE`) or splatted
    through `**kwargs` reads as a `Name`, not an `Attribute`, and is out of this walk's reach. It
    catches the way the bypass would actually be written, which is why the message names the
    sanctioned function rather than only refusing.
    """
    offenders = {
        str(path.relative_to(APP)): lines
        for path in sorted(APP.rglob("*.py"))
        if (lines := opt_out_minting_lines(ast.parse(path.read_text(encoding="utf-8"))))
    }

    assert offenders == {}, (
        f"{offenders} mint an opt-out through {MINTING_FUNCTION}(), which does not clamp "
        f"effective_at, refuse a liftable source, or deduplicate. Use record_opt_out()."
    )


def test_the_opt_out_walk_sees_the_call_it_is_required_not_to_flag() -> None:
    """The guard on the guard.

    A walk that found nothing would pass the test above forever. `dedup.py` holds the one
    legitimate `record_suppression` call that carries an unliftable source, so it is the exact
    place to prove the detector both fires and discriminates.
    """
    tree = ast.parse((APP / "prospects" / "dedup.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and called_name(node) == MINTING_FUNCTION
    ]

    assert calls, f"the walk no longer finds {MINTING_FUNCTION} in dedup.py; it is misreading"
    assert opt_out_minting_lines(tree) == [], (
        "dedup carries an already-recorded source rather than minting one, and must not be flagged"
    )
