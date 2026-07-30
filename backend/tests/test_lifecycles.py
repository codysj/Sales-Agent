"""The five lifecycles are separate and their transitions are exhaustively pinned (T-010).

Coverage here is the whole cross product per lifecycle: every ordered pair of states is either
asserted to be allowed or asserted to raise. A transition table with an accidental extra edge is
how a rejected candidate quietly becomes an approved one.
"""

import ast
from enum import Enum
from itertools import product
from pathlib import Path

import pytest

from app.core.lifecycles import (
    ALLOWED_TRANSITIONS,
    APPROVAL_TRANSITIONS,
    CAMPAIGN_CANDIDATE_TRANSITIONS,
    JOB_TRANSITIONS,
    LIFECYCLES,
    MESSAGE_REVISION_TRANSITIONS,
    OUTREACH_THREAD_TRANSITIONS,
    ApprovalState,
    CampaignCandidateState,
    CrossLifecycleTransition,
    IllegalTransition,
    JobState,
    MessageRevisionState,
    OutreachThreadState,
    allowed_transitions,
    assert_transition,
    can_transition,
    is_terminal,
)

APP = Path(__file__).resolve().parents[1] / "app"

TABLES = (
    CAMPAIGN_CANDIDATE_TRANSITIONS,
    MESSAGE_REVISION_TRANSITIONS,
    APPROVAL_TRANSITIONS,
    OUTREACH_THREAD_TRANSITIONS,
    JOB_TRANSITIONS,
)

# Every ordered pair within each lifecycle: (current, target, is_allowed).
ALL_PAIRS = [
    (current, target, target in ALLOWED_TRANSITIONS[current])
    for lifecycle in LIFECYCLES
    for current, target in product(lifecycle, lifecycle)
]


def test_cross_product_is_actually_exhaustive() -> None:
    """Guards the guard: if a lifecycle gained a state, the pair list must grow with it."""
    expected = sum(len(lifecycle) ** 2 for lifecycle in LIFECYCLES)

    assert len(ALL_PAIRS) == expected
    assert expected == 10**2 + 6**2 + 5**2 + 10**2 + 6**2


@pytest.mark.parametrize(("current", "target", "allowed"), ALL_PAIRS)
def test_every_pair_within_a_lifecycle(current: Enum, target: Enum, allowed: bool) -> None:
    if allowed:
        assert_transition(current, target)  # must not raise
        assert can_transition(current, target)
    else:
        with pytest.raises(IllegalTransition):
            assert_transition(current, target)
        assert not can_transition(current, target)


def test_self_transitions_are_always_rejected() -> None:
    """Re-entering the current state would log a change that did not happen (§3.5)."""
    for lifecycle in LIFECYCLES:
        for state in lifecycle:
            with pytest.raises(IllegalTransition):
                assert_transition(state, state)


# --- independence (ADR-015) --------------------------------------------------------------


def test_states_from_different_lifecycles_are_distinct() -> None:
    """The reason these are plain ``Enum`` and not ``StrEnum``.

    ``StrEnum`` members compare equal by value and hash by name, so same-named members of two
    lifecycles would collapse into one key in ``ALLOWED_TRANSITIONS`` — silently merging two
    transition tables.
    """
    assert CampaignCandidateState.APPROVED != MessageRevisionState.APPROVED
    assert CampaignCandidateState.APPROVED != ApprovalState.APPROVED
    assert MessageRevisionState.REVIEW_PENDING != CampaignCandidateState.REVIEW_PENDING
    assert OutreachThreadState.QUEUED != JobState.QUEUED

    collapsed = {CampaignCandidateState.APPROVED: 1, MessageRevisionState.APPROVED: 2}
    assert len(collapsed) == 2, "same-named states from two lifecycles collapsed into one key"


def test_flat_table_did_not_lose_entries_to_key_collisions() -> None:
    assert len(ALLOWED_TRANSITIONS) == sum(len(table) for table in TABLES)
    assert len(ALLOWED_TRANSITIONS) == sum(len(lifecycle) for lifecycle in LIFECYCLES)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CampaignCandidateState.APPROVED, MessageRevisionState.APPROVED),
        (CampaignCandidateState.REVIEW_PENDING, ApprovalState.APPROVED),
        (JobState.QUEUED, OutreachThreadState.QUEUED),
        (ApprovalState.PENDING, JobState.LEASED),
        (OutreachThreadState.SENDING, CampaignCandidateState.APPROVED),
    ],
)
def test_cross_lifecycle_transitions_are_rejected(current: Enum, target: Enum) -> None:
    with pytest.raises(CrossLifecycleTransition):
        assert_transition(current, target)


def test_no_combined_state_enum_exists() -> None:
    """ADR-015 and §21.2 reject a single global workflow enum.

    A combined enum would necessarily mix vocabulary from lifecycles that share no state names —
    job mechanics against candidate progress.
    """
    markers = {
        "candidate": {"imported", "researched", "research_pending"},
        "job": {"leased", "dead", "retry"},
        "outreach": {"provider_accepted", "delivery_unknown", "bounced"},
        "revision": {"validation_failed", "superseded"},
    }
    permitted = {lifecycle.__name__ for lifecycle in LIFECYCLES}

    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name in permitted:
                continue
            values = {
                child.value.value
                for child in node.body
                if isinstance(child, ast.Assign)
                and isinstance(child.value, ast.Constant)
                and isinstance(child.value.value, str)
            }
            groups = [name for name, marks in markers.items() if values & marks]

            assert len(groups) < 2, (
                f"{path.name}:{node.name} mixes {groups} vocabulary — "
                f"a combined workflow enum is rejected (ADR-015, §21.2)"
            )


# --- specific invariants the specification calls out --------------------------------------


def test_delivery_unknown_never_retries_blindly() -> None:
    """ADR-016: ambiguity is resolved by reconciliation, never by resending."""
    onward = allowed_transitions(OutreachThreadState.DELIVERY_UNKNOWN)

    assert OutreachThreadState.SENDING not in onward
    assert OutreachThreadState.QUEUED not in onward
    assert OutreachThreadState.PROVIDER_ACCEPTED not in onward


def test_expired_or_revoked_approval_can_never_become_approved_again() -> None:
    """T-021 / §11.4."""
    for dead_end in (ApprovalState.EXPIRED, ApprovalState.REVOKED, ApprovalState.REJECTED):
        assert is_terminal(dead_end)
        assert ApprovalState.APPROVED not in allowed_transitions(dead_end)


def test_an_immutable_revision_cannot_be_resurrected() -> None:
    """§10.5: editing creates a new revision; the old one is finished."""
    assert is_terminal(MessageRevisionState.SUPERSEDED)
    assert is_terminal(MessageRevisionState.INVALIDATED)


def test_a_rejected_candidate_is_terminal() -> None:
    assert is_terminal(CampaignCandidateState.REJECTED)
    assert CampaignCandidateState.APPROVED not in allowed_transitions(
        CampaignCandidateState.REJECTED
    )


def test_a_deferred_candidate_can_return_to_review() -> None:
    """§10.6 allows "defer until a specific date or event"."""
    assert CampaignCandidateState.REVIEW_PENDING in allowed_transitions(
        CampaignCandidateState.DEFERRED
    )


def test_a_crashed_job_lease_can_be_reclaimed() -> None:
    """§17.1 / T-032: an expired lease returns the job to the queue."""
    assert JobState.QUEUED in allowed_transitions(JobState.LEASED)


def test_terminal_states_are_the_expected_ones() -> None:
    terminal = {state for state in ALLOWED_TRANSITIONS if is_terminal(state)}

    assert terminal == {
        CampaignCandidateState.INELIGIBLE,
        CampaignCandidateState.REJECTED,
        CampaignCandidateState.INVALIDATED,
        MessageRevisionState.SUPERSEDED,
        MessageRevisionState.INVALIDATED,
        ApprovalState.REJECTED,
        ApprovalState.EXPIRED,
        ApprovalState.REVOKED,
        OutreachThreadState.BOUNCED,
        OutreachThreadState.UNSUBSCRIBED,
        OutreachThreadState.FAILED,
        JobState.SUCCEEDED,
        JobState.DEAD,
        JobState.CANCELLED,
    }


# --- table well-formedness ----------------------------------------------------------------


def test_every_state_has_a_transition_entry() -> None:
    """A state missing from the table would raise KeyError at runtime, not a clean refusal."""
    for lifecycle in LIFECYCLES:
        for state in lifecycle:
            assert state in ALLOWED_TRANSITIONS, f"{lifecycle.__name__}.{state.name} has no entry"


def test_each_table_contains_only_its_own_lifecycle() -> None:
    """Recovers at runtime what the widened key type gives up statically (see lifecycles.py)."""
    for lifecycle, table in zip(LIFECYCLES, TABLES, strict=True):
        for current, targets in table.items():
            assert type(current) is lifecycle, (
                f"{_name(current)} is a key in the {lifecycle.__name__} table"
            )
            for target in targets:
                assert type(target) is lifecycle, (
                    f"{_name(current)} -> {_name(target)} crosses lifecycles inside a table"
                )


def test_every_non_initial_state_is_reachable() -> None:
    """An unreachable state is dead vocabulary that will mislead the next reader."""
    initial = {
        CampaignCandidateState.IMPORTED,
        MessageRevisionState.DRAFT,
        ApprovalState.PENDING,
        OutreachThreadState.NOT_STARTED,
        JobState.QUEUED,
    }
    reachable = {target for targets in ALLOWED_TRANSITIONS.values() for target in targets}

    for lifecycle in LIFECYCLES:
        for state in lifecycle:
            if state not in initial:
                assert state in reachable, f"{_name(state)} is unreachable"


def test_error_messages_name_both_states() -> None:
    """A bare 'illegal transition' in a log is useless at 3am."""
    with pytest.raises(IllegalTransition) as illegal:
        assert_transition(CampaignCandidateState.REJECTED, CampaignCandidateState.APPROVED)
    assert "rejected" in str(illegal.value)
    assert "approved" in str(illegal.value)

    with pytest.raises(CrossLifecycleTransition) as crossed:
        assert_transition(JobState.QUEUED, OutreachThreadState.QUEUED)
    assert "JobState" in str(crossed.value)
    assert "OutreachThreadState" in str(crossed.value)


def _name(state: Enum) -> str:
    return f"{type(state).__name__}.{state.name}"
