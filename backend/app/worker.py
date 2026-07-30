"""The worker process (specification §18.1, §7.2).

One of the two processes the backend runs. It owns scheduling, jobs, state transitions, and
outbox dispatch — never human identity decisions, which belong to the API (§5.1).

Deliberately thin, but not empty. The individual steps live in `jobs_and_outbox` — `run_once`,
`dispatch_once`, and the two reclaims — and `one_pass` composes them. That composition has to live
here rather than in `jobs_and_outbox`, because it needs the §11.4 precondition check from
`outreach_and_replies`, which §18.2 forbids `jobs_and_outbox` from importing. This file is a leaf
that nothing imports, so it is the one place allowed to know about both halves.

Everything except `main` is free of processes, signals, and sleeps, so a whole cycle is testable.
"""

import logging
import os
import signal
import time
import types
import uuid
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy.orm import Session

from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.session import dispose_engines, get_engine
from app.jobs_and_outbox.dispatch import ExternalEffectAdapter, dispatch_once
from app.jobs_and_outbox.recovery import (
    reclaim_expired_dispatch_leases,
    reclaim_expired_leases,
)
from app.jobs_and_outbox.runner import run_once
from app.outreach_and_replies.adapters import build_effect_adapter
from app.outreach_and_replies.preconditions import send_precondition_check

log = structlog.get_logger(__name__)

#: How long to wait when the queue is empty. PostgreSQL is the queue (ADR-003), so this is a
#: poll rather than a push; a few seconds is well inside pilot latency needs and costs nothing.
IDLE_POLL_SECONDS: Final = 2.0

#: How many jobs one pass may lease. One keeps failure blast radius small at pilot volume.
BATCH_SIZE: Final = 1

_shutdown = False


def _request_shutdown(signum: int, _frame: types.FrameType | None) -> None:
    """Finish the job in flight, then stop. A killed worker's lease expires and recovers (T-032)."""
    global _shutdown
    _shutdown = True
    log.info("worker.shutdown_requested", signal=signum)


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

    **This function is where the two halves of §18.1's worker actually meet.** `jobs_and_outbox` may
    not import `outreach_and_replies` (§18.2), so nothing inside it can hand the dispatcher a §11.4
    precondition check. `worker.py` is a leaf that nothing imports, so it is the one place allowed
    to know about both — and passing `send_precondition_check` here is what makes the recheck
    actually run in production rather than only in its own tests.

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


def main() -> None:
    settings = get_settings()
    configure_logging(settings.app_env, level=logging.INFO)

    worker_id = (
        f"{os.uname().nodename if hasattr(os, 'uname') else 'worker'}-{uuid.uuid4().hex[:8]}"
    )
    structlog.contextvars.bind_contextvars(worker_id=worker_id)
    log.info(
        "worker.started",
        worker_id=worker_id,
        shadow_mode=settings.shadow_mode,
        outbound_email_enabled=settings.outbound_email_enabled,
    )

    for received in (signal.SIGINT, signal.SIGTERM):
        signal.signal(received, _request_shutdown)

    adapter = build_effect_adapter(settings)
    engine = get_engine(settings.database_url)
    try:
        while not _shutdown:
            with Session(engine) as session:
                result = one_pass(session, worker_id=worker_id, adapter=adapter, settings=settings)
            if result.did_nothing:
                time.sleep(IDLE_POLL_SECONDS)
    finally:
        dispose_engines()
        log.info("worker.stopped", worker_id=worker_id)


if __name__ == "__main__":
    main()
