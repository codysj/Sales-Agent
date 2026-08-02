"""The worker process (specification §18.1, §7.2).

One of the two processes the backend runs. It owns scheduling, jobs, state transitions, and
outbox dispatch — never human identity decisions, which belong to the API (§5.1).

Deliberately thin, and now thinner: the cycle itself moved to `app/worker_pass.py` (`T-172a`,
ADR-027) so `python -m app.cli` can drive one too. What is left here is what a *process* adds —
signals, a poll interval, and logging.

**It also owns job-type registration**, for the same reason it owned the composition: the
registry is process-wide and empty at import, and every domain module that defines a job type
has to be told to put it there. A worker that skipped this would lease jobs it had no handler
for, retry each on a fixed backoff, and look busy while completing nothing — which is exactly
what it did until `T-148`. `register_job_types` is the list, `tests/test_jobs.py` proves the
list is complete by discovery rather than by inspection, and adding a job type without adding it
here fails that test.

**This process registers no source adapter and installs no fake**, and that is the property the
two adapter invariants in `tests/test_pipeline_jobs.py` exist to protect. A worker started here
resolves no source and no fixture-keyed model at all; the Stage 1 fixtures are the CLI's act
(`python -m app.cli run_worker`) or a test's.
"""

import logging
import os
import signal
import time
import types
import uuid
from typing import Final

import structlog
from sqlalchemy.orm import Session

from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import dispose_engines, get_engine
from app.job_types import register_job_types
from app.outreach_and_replies.adapters import build_effect_adapter
from app.worker_pass import one_pass

log = structlog.get_logger(__name__)

#: Every module that defines a job type. Ordered by §8.3 step so the list reads like the pipeline
#: it wires, though registration order carries no meaning — the registry refuses duplicate names
#: and each `register()` is idempotent.
#:
#: `tests/test_jobs.py::test_the_worker_registers_every_job_type_the_codebase_defines` discovers
#: the same set by AST and compares, so a module added without a line here fails rather than
#: silently never running.

#: How long to wait when the queue is empty. PostgreSQL is the queue (ADR-003), so this is a
#: poll rather than a push; a few seconds is well inside pilot latency needs and costs nothing.
IDLE_POLL_SECONDS: Final = 2.0

_shutdown = False


def _request_shutdown(signum: int, _frame: types.FrameType | None) -> None:
    """Finish the job in flight, then stop. A killed worker's lease expires and recovers (T-032)."""
    global _shutdown
    _shutdown = True
    log.info("worker.shutdown_requested", signal=signum)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.app_env, level=logging.INFO)
    register_job_types()

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
