"""Developer command line (task T-040).

The third entry point beside `main.py` and `worker.py`, and the only one that loads fixtures.
Kept a leaf that nothing imports — like `worker.py`, it composes, so it is allowed to reach
across module boundaries that domain code may not.

Every command here is local-development only. Nothing in this file may send, deploy, mutate an
external system, or read a credential; `seed_synthetic` refuses to run outside a seedable
environment (`app/fixtures/synthetic.py`).
"""

import argparse
import logging
import sys
import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor, record_audit_event
from app.campaigns.models import Campaign
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import dispose_engines, get_engine
from app.fixtures import PROSPECTS_CSV, SOURCE_DOCUMENTS
from app.fixtures.model_routing import TaskRoutingFake
from app.fixtures.synthetic import SeedRefused, require_seedable, seed_synthetic
from app.identity.models import Role, RoleKey, User, UserRole
from app.intake import enqueue_memberships_for_import
from app.job_types import register_job_types
from app.model_gateway.registry import set_fake_adapter_factory
from app.outreach_and_replies.adapters import build_effect_adapter
from app.prospects.imports import import_csv
from app.research_and_evidence.adapters.fixture import FixtureSourceAdapter
from app.research_and_evidence.adapters.registry import (
    FIXTURE_ADAPTER_NAME,
    register_source_adapter,
)
from app.worker_pass import one_pass

log = structlog.get_logger(__name__)

#: Exit code for a refused command. Distinct from 1 so a script can tell "not allowed here" from
#: "it broke".
EXIT_REFUSED = 2


def _seed_synthetic() -> int:
    settings = get_settings()
    engine = get_engine(settings.database_url)
    try:
        with Session(engine) as session:
            result = seed_synthetic(session, settings=settings)
            session.commit()
    except SeedRefused as refusal:
        log.error("cli.seed_synthetic.refused", reason=str(refusal))
        return EXIT_REFUSED
    finally:
        dispose_engines()

    log.info(
        "cli.seed_synthetic.done",
        app_env=settings.app_env.value,
        created=list(result.created),
        was_noop=result.was_noop,
    )
    return 0


#: The actor every CLI import is attributed to. A service identity, not a person: nobody
#: approved these rows, a developer ran a command (§12.2, ADR-025).
CLI_ACTOR = Actor(type=ActorType.SERVICE, id="cli.import_prospects")


def _import_prospects() -> int:
    """Load `app/fixtures/prospects.csv` into the configured database (`T-168`).

    **The gap this closes:** `seed_synthetic` builds the campaign world and `python -m app.worker`
    drains the pipeline, but the step between them lived only inside `tests/test_shadow_slice.py`,
    on a session that rolls back. A developer could reach a review queue by writing Python; nobody
    else could reach one at all, which is a poor answer to a gate about non-engineers.

    **No path argument, deliberately.** The file is the bundled synthetic fixture and nothing else,
    so this command cannot be pointed at real prospect data (AGENTS.md rule 1). Someone importing a
    real list should be doing it through a reviewed path, not a developer convenience.

    Idempotent because the walkthrough is run more than once: `import_batch.content_hash` is
    unique, so a second run reports `already_imported` and writes nothing.
    """
    settings = get_settings()
    try:
        require_seedable(settings)
    except SeedRefused as refusal:
        # Before the engine is built, like `seed_synthetic`: a refused command must not so much
        # as open a connection to an environment it is not allowed to touch.
        log.error("cli.import_prospects.refused", reason=str(refusal))
        return EXIT_REFUSED

    # Every consequential action needs a correlation id (§17.5), and `import_csv` writes an
    # audit event. Bound here because a command *is* the unit of work — without it a developer
    # running this gets `MissingCorrelationId` instead of an import, which is a poor first
    # experience for the one reader this command exists for.
    structlog.contextvars.bind_contextvars(correlation_id=f"cli-{uuid.uuid4().hex[:12]}")
    engine = get_engine(settings.database_url)
    try:
        with Session(engine) as session:
            content = PROSPECTS_CSV.read_bytes()
            result = import_csv(
                session,
                content=content,
                source_name=PROSPECTS_CSV.name,
                actor=CLI_ACTOR,
            )
            # The step §8.3 puts between the import and the worker (`T-169`). Without it the
            # import finishes with accounts and contacts and **no candidates**, so the worker
            # idles and the review queue stays empty.
            jobs = (
                0
                if result.already_imported
                else enqueue_memberships_for_import(
                    session,
                    content=content,
                    batch_id=result.batch.id,
                    actor=CLI_ACTOR,
                )
            )
            session.commit()
    finally:
        dispose_engines()

    # Counts only. A rejection reason names a field, never a cell (§15.5, and `import_csv` keeps
    # to that already) — and nothing here prints a name or an address.
    log.info(
        "cli.import_prospects.done",
        app_env=settings.app_env.value,
        already_imported=result.already_imported,
        created=len(result.created),
        reused=len(result.reused),
        rejected=len(result.rejections),
        membership_jobs=jobs,
    )
    return 0


#: The local reviewer `grant_local_reviewer` creates. An IANA-reserved domain that can never be
#: delivered to (AGENTS.md rule 1), and the address a reader signs in with.
LOCAL_REVIEWER_EMAIL = "synthetic-reviewer@example.invalid"

#: One role, and only this one (`T-170`). `operator_reviewer` is what §12.1 gives the person who
#: reviews; the operations panel is `system_administrator`, and a convenience command that handed
#: that out would be a way to acquire tier-5 authority by running a script.
LOCAL_REVIEWER_ROLE = RoleKey.OPERATOR_REVIEWER


def _grant_local_reviewer() -> int:
    """Create a local reviewer who can sign in and review (`T-170`).

    **The gap this closes:** the six roles are seeded by migration and `seed_synthetic` creates one
    user — the approver — with none of them. `stub_sign_in` refuses an unknown email and never
    creates anybody, which is right: `Q-005` and `Q-026` own the real roster. The result was that a
    freshly set-up database had no email that signed in to anything, and every route answered
    `403` to a session that had been issued perfectly.

    **Local only, and one role only.** It refuses outside `local`/`test` before touching the
    database, and grants nothing beyond `operator_reviewer`.
    """
    settings = get_settings()
    try:
        require_seedable(settings)
    except SeedRefused as refusal:
        log.error("cli.grant_local_reviewer.refused", reason=str(refusal))
        return EXIT_REFUSED

    engine = get_engine(settings.database_url)
    try:
        with Session(engine) as session:
            user = session.execute(
                select(User).where(User.email == LOCAL_REVIEWER_EMAIL)
            ).scalar_one_or_none()
            created = user is None
            if user is None:
                user = User(
                    email=LOCAL_REVIEWER_EMAIL,
                    display_name="SYNTHETIC-Local reviewer",
                    subject=None,
                    active=True,
                )
                session.add(user)
                session.flush()

            role = session.execute(
                select(Role).where(Role.key == LOCAL_REVIEWER_ROLE.value)
            ).scalar_one()
            held = session.execute(
                select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
            ).scalar_one_or_none()
            granted = held is None
            if held is None:
                # `uq_user_role` would refuse a second grant anyway; checking first keeps a
                # re-run a no-op rather than an integrity error the reader has to interpret.
                session.add(UserRole(user_id=user.id, role_id=role.id, granted_by=CLI_ACTOR.id))
            session.commit()
    finally:
        dispose_engines()

    log.info(
        "cli.grant_local_reviewer.done",
        app_env=settings.app_env.value,
        email=LOCAL_REVIEWER_EMAIL,
        role=LOCAL_REVIEWER_ROLE.value,
        user_created=created,
        role_granted=granted,
    )
    return 0


def _start_campaign(slug: str) -> int:
    """Clear a named campaign's pause so the pipeline will produce candidates for it (`T-171`).

    **Seeded campaigns are paused on purpose** (`T-015`), and `create_memberships` gives a
    paused campaign no candidates (§17.6). Starting one is a deliberate operator act, so
    seeding them already running would quietly remove the control the pause exists to provide.
    This offers the act; it does not move it.

    **It names the campaign.** Starting every seeded campaign at once would make it a side
    effect of running a script rather than a decision about one campaign.
    """
    settings = get_settings()
    try:
        require_seedable(settings)
    except SeedRefused as refusal:
        log.error("cli.start_campaign.refused", reason=str(refusal))
        return EXIT_REFUSED

    engine = get_engine(settings.database_url)
    try:
        with Session(engine) as session:
            campaign = session.execute(
                select(Campaign).where(Campaign.slug == slug)
            ).scalar_one_or_none()
            if campaign is None:
                # Named, because a slug is not a secret and a developer who mistyped one needs
                # to see which. Nothing is changed on the way out.
                log.error("cli.start_campaign.unknown", slug=slug)
                return EXIT_REFUSED

            already_running = not campaign.paused
            campaign.paused = False
            record_audit_event(
                session,
                actor=CLI_ACTOR,
                action="campaign.resumed",
                entity_type="campaign",
                entity_id=campaign.id,
                policy_decision="cli: operator started the campaign",
                correlation_id=f"cli-{uuid.uuid4().hex[:12]}",
            )
            session.commit()
    finally:
        dispose_engines()

    log.info(
        "cli.start_campaign.done",
        app_env=settings.app_env.value,
        slug=slug,
        already_running=already_running,
    )
    return 0


#: A bound on `run_worker`'s loop. It exists so a command a reader is told to run terminates even
#: if a job is retrying forever; at Stage 1 volumes a full drain is a few dozen passes, so
#: reaching this is a symptom rather than a limit, and the log line says which happened.
MAX_DRAIN_PASSES = 2000


def _run_worker() -> int:
    """Drain the pipeline with the Stage 1 fakes installed (`T-172a`, ADR-027).

    **The gap this closes:** `python -m app.worker` registers no source adapter and installs no
    fake, deliberately — that is the property `tests/test_pipeline_jobs.py`'s two adapter
    invariants protect. So every `research.capture_evidence` job dead-lettered with *"no source
    adapter registered under 'fixture'"*, and the only place the Stage 1 fixtures were ever
    installed was inside `tests/test_shadow_slice.py`. A reader following the walkthrough saw a
    queue that never filled and a reason buried in a dead job.

    **It drains and stops**, where the production worker loops forever. A walkthrough step that
    ends is a step a non-engineer can complete; one that has to be interrupted is a step they have
    to be told how to interrupt.

    **Local only.** The refusal runs before anything is registered, so a refused environment does
    not so much as have a fixture adapter resolvable in its process.
    """
    settings = get_settings()
    try:
        require_seedable(settings)
    except SeedRefused as refusal:
        log.error("cli.run_worker.refused", reason=str(refusal))
        return EXIT_REFUSED

    register_source_adapter(
        FIXTURE_ADAPTER_NAME, lambda: FixtureSourceAdapter(directory=SOURCE_DOCUMENTS)
    )
    set_fake_adapter_factory(TaskRoutingFake)

    structlog.contextvars.bind_contextvars(correlation_id=f"cli-{uuid.uuid4().hex[:12]}")
    worker_id = f"cli-{uuid.uuid4().hex[:8]}"
    adapter = build_effect_adapter(settings)
    engine = get_engine(settings.database_url)
    passes = 0
    try:
        while passes < MAX_DRAIN_PASSES:
            with Session(engine) as session:
                result = one_pass(session, worker_id=worker_id, adapter=adapter, settings=settings)
            passes += 1
            if result.did_nothing:
                break
    finally:
        dispose_engines()

    log.info(
        "cli.run_worker.done",
        app_env=settings.app_env.value,
        passes=passes,
        drained_to_idle=passes < MAX_DRAIN_PASSES,
    )
    return 0


COMMANDS = {
    "seed_synthetic": _seed_synthetic,
    "import_prospects": _import_prospects,
    "grant_local_reviewer": _grant_local_reviewer,
    "run_worker": _run_worker,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Local development commands. No external effects.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    # Registered one at a time rather than in a loop that returns early on the first (`T-148`).
    subcommands.add_parser(
        "seed_synthetic",
        help="Load the synthetic campaign world (local and test environments only).",
    )
    subcommands.add_parser(
        "import_prospects",
        help="Import the bundled synthetic prospect CSV (local and test environments only).",
    )
    subcommands.add_parser(
        "grant_local_reviewer",
        help="Create a local reviewer who can sign in (local and test environments only).",
    )
    subcommands.add_parser(
        "run_worker",
        help="Drain the pipeline with the Stage 1 fixtures installed (local and test only).",
    )
    start = subcommands.add_parser(
        "start_campaign",
        help="Clear a seeded campaign's pause (local and test environments only).",
    )
    start.add_argument("slug", help="The campaign slug to start.")
    arguments = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.app_env, level=logging.INFO)
    # `enqueue` resolves each job type's payload model from the registry to validate it, so a
    # process with an empty registry raises `UnknownJobType` on the first thing it queues —
    # which `import_prospects` does (`T-169`). `worker.main` and `create_app` do the same.
    register_job_types()
    if arguments.command == "start_campaign":
        return _start_campaign(arguments.slug)
    return COMMANDS[arguments.command]()


if __name__ == "__main__":
    sys.exit(main())
