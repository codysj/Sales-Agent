"""The five independent workflow lifecycles (specification §8.2, ADR-015).

Candidate, message revision, approval, outreach thread, and background job each have their own
states and their own allowed transitions. The v0.2 single canonical state machine is
**SUPERSEDED**: one global enum cannot safely represent multiple campaigns, revisions, replies,
and concurrent jobs (§8.2). There is deliberately **no combined state enum** anywhere in this
codebase, and `tests/test_lifecycles.py` fails if one appears.

This module holds vocabulary and pure functions only — no imports from any domain module, no
persistence, no cross-entity rules (those are T-024). Living in ``core`` keeps the five tables
side by side where their separation is auditable in one place.

**Plain ``Enum``, not ``StrEnum``.** ``StrEnum`` members compare equal by string value and hash
by member name, so ``CampaignCandidateState.APPROVED`` and ``MessageRevisionState.APPROVED``
would be the *same dictionary key* — two lifecycles would silently share one transition table.
Verified, and guarded by ``test_states_from_different_lifecycles_are_distinct``.
"""

from collections.abc import Mapping
from enum import Enum
from typing import Final


class LifecycleError(Exception):
    """Base class for lifecycle rule violations."""


class IllegalTransition(LifecycleError):
    """A transition that the specification does not permit."""

    def __init__(self, current: "LifecycleState", target: object) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"illegal transition: {_label(current)} -> {_label(target)}. "
            f"Allowed from {_label(current)}: "
            f"{sorted(_label(s) for s in allowed_transitions(current)) or ['(terminal)']}"
        )


class CrossLifecycleTransition(LifecycleError):
    """An attempt to move an entity into another lifecycle's state.

    Never a typo worth tolerating: it means two independent lifecycles are being conflated,
    which is exactly what ADR-015 forbids.
    """

    def __init__(self, current: object, target: object) -> None:
        super().__init__(
            f"cross-lifecycle transition: {_label(current)} ({type(current).__name__}) -> "
            f"{_label(target)} ({type(target).__name__}); lifecycles are independent (ADR-015)"
        )


class CampaignCandidateState(Enum):
    """§8.2: imported -> eligible/ineligible -> research_pending -> researched ->
    review_pending -> approved/rejected/deferred/invalidated."""

    IMPORTED = "imported"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    RESEARCH_PENDING = "research_pending"
    RESEARCHED = "researched"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    INVALIDATED = "invalidated"


class MessageRevisionState(Enum):
    """§8.2: draft -> validation_failed/review_pending -> approved/superseded/invalidated."""

    DRAFT = "draft"
    VALIDATION_FAILED = "validation_failed"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class ApprovalState(Enum):
    """§8.2: pending -> approved/rejected/expired/revoked."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class OutreachThreadState(Enum):
    """§8.2: not_started -> queued -> sending -> provider_accepted/delivery_unknown ->
    delivered/bounced/replied/unsubscribed/failed."""

    NOT_STARTED = "not_started"
    QUEUED = "queued"
    SENDING = "sending"
    PROVIDER_ACCEPTED = "provider_accepted"
    DELIVERY_UNKNOWN = "delivery_unknown"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    REPLIED = "replied"
    UNSUBSCRIBED = "unsubscribed"
    FAILED = "failed"


class JobState(Enum):
    """§8.2: queued -> leased -> succeeded/retry/dead/cancelled."""

    QUEUED = "queued"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    DEAD = "dead"
    CANCELLED = "cancelled"


LifecycleState = (
    CampaignCandidateState | MessageRevisionState | ApprovalState | OutreachThreadState | JobState
)

# Keys are widened to the union so the five tables can merge into one lookup: `Mapping` is
# invariant in its key type, so per-lifecycle key types will not combine. The precision that
# gives up — "this table contains only its own lifecycle's states" — is recovered at runtime by
# `test_each_table_contains_only_its_own_lifecycle`.
LifecycleTable = Mapping[LifecycleState, frozenset[LifecycleState]]

_C = CampaignCandidateState
_M = MessageRevisionState
_A = ApprovalState
_O = OutreachThreadState
_J = JobState

# --- transition tables -------------------------------------------------------------------
# §8.2 gives the happy path; the edges below are the conservative reading of it. Each
# non-obvious edge carries the clause it comes from. An empty set means terminal.

CAMPAIGN_CANDIDATE_TRANSITIONS: Final[LifecycleTable] = {
    _C.IMPORTED: frozenset({_C.ELIGIBLE, _C.INELIGIBLE}),
    _C.ELIGIBLE: frozenset({_C.RESEARCH_PENDING, _C.INVALIDATED}),
    # Terminal. Re-evaluating a rejected candidate after a policy change is not specified;
    # a new membership is created rather than resurrecting this one.
    _C.INELIGIBLE: frozenset(),
    _C.RESEARCH_PENDING: frozenset({_C.RESEARCHED, _C.INVALIDATED}),
    _C.RESEARCHED: frozenset({_C.REVIEW_PENDING, _C.INVALIDATED}),
    _C.REVIEW_PENDING: frozenset({_C.APPROVED, _C.REJECTED, _C.DEFERRED, _C.INVALIDATED}),
    # A claim or product-status version change invalidates dependent work (§14.4, T-056).
    _C.APPROVED: frozenset({_C.INVALIDATED}),
    _C.REJECTED: frozenset(),
    # §10.6 offers "defer until a specific date/event", so a deferred candidate returns to
    # review when that date or event arrives.
    _C.DEFERRED: frozenset({_C.REVIEW_PENDING, _C.INVALIDATED}),
    _C.INVALIDATED: frozenset(),
}

MESSAGE_REVISION_TRANSITIONS: Final[LifecycleTable] = {
    _M.DRAFT: frozenset({_M.VALIDATION_FAILED, _M.REVIEW_PENDING, _M.SUPERSEDED}),
    # Editing after a failed validation creates revision N+1 and supersedes this one (§10.5).
    _M.VALIDATION_FAILED: frozenset({_M.SUPERSEDED, _M.INVALIDATED}),
    _M.REVIEW_PENDING: frozenset({_M.APPROVED, _M.SUPERSEDED, _M.INVALIDATED}),
    _M.APPROVED: frozenset({_M.SUPERSEDED, _M.INVALIDATED}),
    # Revisions are immutable; both ends are final (§10.5, §8.4).
    _M.SUPERSEDED: frozenset(),
    _M.INVALIDATED: frozenset(),
}

APPROVAL_TRANSITIONS: Final[LifecycleTable] = {
    _A.PENDING: frozenset({_A.APPROVED, _A.REJECTED, _A.EXPIRED}),
    _A.APPROVED: frozenset({_A.REVOKED, _A.EXPIRED}),
    # "An expired or revoked approval can never transition back to approved" (T-021, §11.4).
    _A.REJECTED: frozenset(),
    _A.EXPIRED: frozenset(),
    _A.REVOKED: frozenset(),
}

OUTREACH_THREAD_TRANSITIONS: Final[LifecycleTable] = {
    _O.NOT_STARTED: frozenset({_O.QUEUED}),
    _O.QUEUED: frozenset({_O.SENDING, _O.FAILED}),
    _O.SENDING: frozenset({_O.PROVIDER_ACCEPTED, _O.DELIVERY_UNKNOWN, _O.FAILED}),
    _O.PROVIDER_ACCEPTED: frozenset(
        {_O.DELIVERED, _O.BOUNCED, _O.REPLIED, _O.UNSUBSCRIBED, _O.FAILED, _O.DELIVERY_UNKNOWN}
    ),
    # ADR-016: an ambiguous provider result is resolved by *reconciliation*, never by a blind
    # retry — hence no edge back to SENDING or QUEUED from here.
    _O.DELIVERY_UNKNOWN: frozenset({_O.DELIVERED, _O.BOUNCED, _O.REPLIED, _O.FAILED}),
    _O.DELIVERED: frozenset({_O.REPLIED, _O.BOUNCED, _O.UNSUBSCRIBED}),
    _O.BOUNCED: frozenset(),
    # A reply can itself be an opt-out request (§15.6).
    _O.REPLIED: frozenset({_O.UNSUBSCRIBED}),
    _O.UNSUBSCRIBED: frozenset(),
    _O.FAILED: frozenset(),
}

JOB_TRANSITIONS: Final[LifecycleTable] = {
    _J.QUEUED: frozenset({_J.LEASED, _J.CANCELLED}),
    # LEASED -> QUEUED is lease-expiry reclaim after a worker crash (§17.1, T-032).
    _J.LEASED: frozenset({_J.SUCCEEDED, _J.RETRY, _J.DEAD, _J.CANCELLED, _J.QUEUED}),
    _J.RETRY: frozenset({_J.QUEUED, _J.DEAD, _J.CANCELLED}),
    _J.SUCCEEDED: frozenset(),
    _J.DEAD: frozenset(),
    _J.CANCELLED: frozenset(),
}

#: Flat lookup. Safe only because these are plain ``Enum`` members — see the module docstring.
ALLOWED_TRANSITIONS: Final[Mapping[LifecycleState, frozenset[LifecycleState]]] = {
    **CAMPAIGN_CANDIDATE_TRANSITIONS,
    **MESSAGE_REVISION_TRANSITIONS,
    **APPROVAL_TRANSITIONS,
    **OUTREACH_THREAD_TRANSITIONS,
    **JOB_TRANSITIONS,
}

LIFECYCLES: Final[tuple[type[Enum], ...]] = (
    CampaignCandidateState,
    MessageRevisionState,
    ApprovalState,
    OutreachThreadState,
    JobState,
)


def _label(state: object) -> str:
    return state.value if isinstance(state, Enum) else repr(state)


def allowed_transitions(state: LifecycleState) -> frozenset[LifecycleState]:
    """States reachable from ``state`` in one step. Empty means terminal."""
    return ALLOWED_TRANSITIONS[state]


def is_terminal(state: LifecycleState) -> bool:
    return not ALLOWED_TRANSITIONS[state]


def can_transition(current: LifecycleState, target: LifecycleState) -> bool:
    return type(current) is type(target) and target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: LifecycleState, target: LifecycleState) -> None:
    """Raise unless the specification permits ``current -> target``.

    Fails closed on everything not explicitly allowed, including a self-transition: re-entering
    the state an entity is already in would produce a duplicate audit event describing a change
    that did not happen (§3.5).
    """
    if type(current) is not type(target):
        raise CrossLifecycleTransition(current, target)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise IllegalTransition(current, target)
