"""One worker cycle, composed (T-172a; ADR-027, specification §18.1, §18.2, §7.2).

**This module exists so that two entry points can run the same cycle.** It used to live in
`app/worker.py`, which nothing may import (`tests/test_module_boundaries.py`'s
`FORBIDDEN_FOR_ALL`) — so `python -m app.cli` could not drive a pass, and the CLI is the one
place allowed to install the Stage 1 fixtures (`T-040`). ADR-027 records the choice: move the
cycle rather than widen the rule that keeps fixture wiring out of production paths.

**It is still the one place that knows about both halves of §18.1's worker.** `jobs_and_outbox`
may not import `outreach_and_replies` (§18.2), so nothing inside it can hand the dispatcher a
§11.4 precondition check. This module is a composition module, not a domain module, so it may —
and passing `send_precondition_check` here is what makes the recheck run in production rather
than only in its own tests.

Free of processes, signals, and sleeps, so a whole cycle is testable. Those belong to
`app/worker.py`, which remains the production entry point and still registers no adapter and no
fake.
"""

from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.jobs_and_outbox.dispatch import ExternalEffectAdapter, dispatch_once
from app.jobs_and_outbox.recovery import (
    reclaim_expired_dispatch_leases,
    reclaim_expired_leases,
)
from app.jobs_and_outbox.runner import run_once
from app.outreach_and_replies.preconditions import send_precondition_check

#: How many jobs one pass may lease. One keeps failure blast radius small at pilot volume.
BATCH_SIZE: Final = 1


@dataclass(frozen=True, slots=True)
class PassResult:
    """What one cycle did. Returned rather than logged-and-forgotten so it can be asserted on."""

    jobs_reclaimed: int
    jobs_run: int
    dispatch_leases_reclaimed: int
    events_dispatched: int

    @property
    def did_nothing(self) -> bool:
        return not (
            self.jobs_reclaimed
            or self.jobs_run
            or self.dispatch_leases_reclaimed
            or self.events_dispatched
        )


def one_pass(
    session: Session,
    *,
    worker_id: str,
    adapter: ExternalEffectAdapter,
    settings: Settings,
) -> PassResult:
    """One full worker cycle: recover, run jobs, dispatch the outbox.

    Split out of `main` so the composition is testable without a process, a signal, or a sleep —
    which is the same reason `run_once` and `dispatch_once` exist.

    Recovery runs **before** new work in both cases: a lease nobody holds is more urgent than
    another job, and reclaiming first means one pass can both free and pick up the same item.
    """
    jobs_reclaimed = len(reclaim_expired_leases(session))
    dispatch_reclaimed = len(reclaim_expired_dispatch_leases(session))
    if jobs_reclaimed or dispatch_reclaimed:
        session.commit()

    jobs_run = run_once(session, worker_id=worker_id, limit=BATCH_SIZE)
    events_dispatched = dispatch_once(
        session,
        adapter,
        settings,
        dispatcher_id=worker_id,
        limit=BATCH_SIZE,
        precondition_check=send_precondition_check,
    )

    return PassResult(
        jobs_reclaimed=jobs_reclaimed,
        jobs_run=jobs_run,
        dispatch_leases_reclaimed=dispatch_reclaimed,
        events_dispatched=events_dispatched,
    )
