"""Which job types this build defines (T-154a; §17.1, §18.2).

Every process that touches the queue needs the same answer, and there are two of them: the worker
runs handlers, and the API *enqueues* — `enqueue` resolves each job type's payload model from the
registry to validate it, so an API process with an empty registry raises `UnknownJobType` on the
first endpoint that queues anything.

**This list moved out of `app.worker`, and it is deliberately not in `jobs_and_outbox` either.**
`tests/test_module_boundaries.py` forbids anything importing `main` or `worker` — they are entry
points that wire everything together — so the list could not stay where it was. It also forbids
`jobs_and_outbox` from importing any domain module (§17.1: the queue is a generic mechanism, and
domain modules register handlers into it rather than the other way round), so it could not move
next to the registry either. Both refusals are right, and together they say what this is: a
**composition** module. It names which domain modules this build wires into the queue, which is
knowledge neither the mechanism nor any one domain has, and it sits beside the two entry points
that need it rather than inside anything it composes.

Registration is idempotent, so a process that is both API and worker, a restarted worker, and a
test that registers for itself are all fine.
"""

from typing import Final, Protocol

from app.campaigns import jobs as campaign_jobs
from app.drafts_and_approvals import invalidation as claim_invalidation
from app.drafts_and_approvals import jobs as draft_jobs
from app.jobs_and_outbox.registry import JobRegistry
from app.qualification import jobs as qualification_jobs
from app.research_and_evidence import jobs as research_jobs


class _RegistersJobTypes(Protocol):
    """A module that contributes job types."""

    def register(self, registry: JobRegistry | None = None) -> None: ...


#: Every module that defines job types. Registration order carries no meaning — the registry
#: refuses duplicate names and each `register()` is idempotent.
#:
#: `tests/test_jobs.py::test_the_worker_registers_every_job_type_the_codebase_defines` discovers
#: the same set by AST and compares, so a module added without a line here fails rather than
#: silently never running.
JOB_TYPE_MODULES: Final[tuple[_RegistersJobTypes, ...]] = (
    campaign_jobs,
    qualification_jobs,
    research_jobs,
    draft_jobs,
    claim_invalidation,
)


def register_job_types(registry: JobRegistry | None = None) -> None:
    """Tell the registry about every job type this build defines.

    Idempotent, because each module's `register()` is: a second call is a no-op rather than a
    duplicate-name error, so a test, a restarted worker, or an API process may call it freely.
    """
    for module in JOB_TYPE_MODULES:
        module.register(registry)
