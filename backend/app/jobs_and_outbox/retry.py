"""Retry policy, backoff, and failure classification (specification §17.1, §7.2).

§17.1 requires retry policy to be **explicit per job type**, so there is no default policy here and
no fallback: `JobRegistry.register` takes one as a required argument. A job type whose author never
thought about failure is a job type that will retry a permanent error a thousand times, or give up
on a transient one after a single blip.

§7.2 lists four outcomes — `SUCCEED | RETRY | DEAD-LETTER | REQUIRE HUMAN REVIEW`. The first is not
a failure; the other three are what `classify` returns.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum


class RetryPolicyError(Exception):
    """A retry policy is internally inconsistent."""


class PermanentFailure(Exception):
    """Raise from a handler when retrying cannot possibly help.

    A malformed record, a rejected-by-rule input, a resource that is gone. Short-circuits the
    attempt budget: there is no point spending five attempts proving the same thing.
    """


class NeedsHumanReview(Exception):
    """Raise from a handler when the decision is not the machine's to make (§7.2, §11.4).

    Distinct from `PermanentFailure`: nothing is broken, but a human must look. Kept separate so
    "we gave up" and "we are waiting for a person" are never counted as the same thing.
    """


class FailureOutcome(Enum):
    """What to do with a failed attempt."""

    RETRY = "retry"
    DEAD = "dead"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How one job type handles failure.

    ``retryable`` is a whitelist, not a blacklist. Anything not listed is treated as permanent —
    the safer default, because an unrecognized exception is more likely a bug we would retry
    forever than a network hiccup.
    """

    #: Total attempts including the first. 1 means "never retry".
    max_attempts: int
    base_delay: timedelta
    #: Ceiling on the exponential growth, applied before jitter.
    max_delay: timedelta = timedelta(hours=1)
    #: Fraction of the delay to randomize, ±. 0.0 disables jitter entirely.
    jitter: float = 0.2
    #: Exception classes worth retrying.
    retryable: Sequence[type[BaseException]] = field(default=(Exception,))

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise RetryPolicyError("max_attempts must be at least 1 (the first attempt)")
        if self.base_delay < timedelta(0) or self.max_delay < timedelta(0):
            raise RetryPolicyError("delays must not be negative")
        if self.max_delay < self.base_delay:
            raise RetryPolicyError("max_delay must not be below base_delay")
        if not 0.0 <= self.jitter <= 1.0:
            raise RetryPolicyError("jitter must be a fraction between 0.0 and 1.0")


def classify(
    policy: RetryPolicy, exc: BaseException, *, attempt_count: int
) -> tuple[FailureOutcome, str]:
    """Decide the outcome of a failed attempt, with the reason to record.

    §17.1: a job that stops being retried must carry a human-readable reason, so the reason is
    returned alongside the outcome rather than left to the caller to invent.
    """
    if isinstance(exc, NeedsHumanReview):
        return FailureOutcome.HUMAN_REVIEW, f"handler requested human review: {exc}"

    if isinstance(exc, PermanentFailure):
        return FailureOutcome.DEAD, f"permanent failure: {exc}"

    if not isinstance(exc, tuple(policy.retryable)):
        # Deliberately names the type and not the message: an exception message can quote payload
        # contents, and `last_error` is read by humans in the dashboard (§15.5).
        return FailureOutcome.DEAD, (
            f"{type(exc).__name__} is not retryable under this job type's policy"
        )

    if attempt_count >= policy.max_attempts:
        return FailureOutcome.DEAD, (
            f"exhausted {policy.max_attempts} attempts; last failure was {type(exc).__name__}"
        )

    return FailureOutcome.RETRY, type(exc).__name__


def compute_backoff(
    policy: RetryPolicy, *, attempt_count: int, rng: random.Random | None = None
) -> timedelta:
    """Exponential backoff with symmetric jitter (§17.1).

    Deterministic for a seeded ``rng``, which is what makes the progression testable. Jitter
    exists so that a hundred jobs failing on the same downstream outage do not come back in
    lockstep and repeat the stampede.
    """
    if attempt_count < 1:
        raise RetryPolicyError("attempt_count starts at 1 (the attempt that just failed)")

    # Attempt 1 waits base_delay, attempt 2 waits 2x, attempt 3 waits 4x. Computed in seconds
    # because timedelta has no __pow__, and capped before jitter so the cap is a real ceiling on
    # the growth rather than a ceiling on the random draw.
    growth = min(
        policy.base_delay.total_seconds() * 2 ** (attempt_count - 1),
        policy.max_delay.total_seconds(),
    )
    if policy.jitter == 0.0:
        return timedelta(seconds=growth)

    source = rng or random.Random()
    jittered = growth * (1 + policy.jitter * (2 * source.random() - 1))
    return timedelta(seconds=max(0.0, jittered))
