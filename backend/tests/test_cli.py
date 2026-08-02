"""The developer command line (T-040, T-168; §19.6 Stage 2 exit gate, §9.3, §15.7).

**These commands had no test at all.** `seed_synthetic`'s underlying function is well covered by
`tests/test_fixtures.py`, but the command wrapping it — the environment guard, the commit, the exit
code — was not, and `T-168` added a second command beside it. What is asserted here is the wrapper:
that a refused environment stops *before* the database, that the work is committed rather than
merely flushed, and that running twice is safe.

**Each test gets its own database, created and dropped here.** These commands commit, and the
session-scoped database every other suite shares is rolled back per test — a committed import would
leak into every later test that assumed an empty one. It also matches what the commands are for:
proving a path works from clean.
"""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command as alembic
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from app.audit_and_operations.models import AuditEvent
from app.audit_and_operations.versioning import (
    ModelConfigVersion,
    PromptVersion,
    SchemaVersion,
)
from app.campaigns.candidate import CampaignCandidate
from app.campaigns.models import Campaign
from app.cli import CLI_ACTOR, EXIT_REFUSED, LOCAL_REVIEWER_EMAIL, main
from app.core.lifecycles import CampaignCandidateState
from app.core.settings import AppEnv, Settings
from app.drafts_and_approvals.models import MessageRevision
from app.fixtures.model_routing import TaskRoutingFake
from app.fixtures.synthetic import FAKE_MODEL_CONFIGS
from app.identity.models import RoleKey, User, UserRole
from app.identity.sessions import resolve
from app.identity.stub import stub_sign_in
from app.intake import enqueue_memberships_for_import
from app.job_types import register_job_types
from app.jobs_and_outbox.models import Job
from app.model_gateway.providers.echo import EchoModelAdapter
from app.model_gateway.registry import build_provider, reset_fake_adapter_factory
from app.outreach_and_replies.adapters import build_effect_adapter
from app.prospects.imports import ImportBatch, import_csv
from app.prospects.models import Account, Contact, ContactPoint
from app.qualification.models import QualificationRun
from app.research_and_evidence.adapters.registry import FIXTURE_ADAPTER_NAME, SOURCE_ADAPTERS
from app.research_and_evidence.models import EvidenceSnapshot
from app.worker_pass import one_pass
from tests.conftest import alembic_config, render_url


@pytest.fixture
def cli_database(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A database of this test's own, migrated, with the CLI pointed at it.

    `database_url` is the session's throwaway database; this makes another beside it so a commit
    here cannot be seen by anything else.
    """
    name = f"cli_{uuid.uuid4().hex[:12]}"
    admin = create_engine(
        make_url(database_url).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = render_url(make_url(database_url).set(database=name))
    alembic.upgrade(alembic_config(url), "head")

    settings = Settings(app_env=AppEnv.TEST, database_url=url)
    monkeypatch.setattr("app.cli.get_settings", lambda: settings)
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def rows(url: str, model: type) -> int:
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            count: int = session.execute(select(func.count()).select_from(model)).scalar_one()
    finally:
        engine.dispose()
    return count


#: The three versioned artefacts `seed_synthetic` registers (`T-172b`). Counted rather than
#: inspected: what the idempotence test needs to know is that a second seed added no row.
VERSIONED = (PromptVersion, SchemaVersion, ModelConfigVersion)

#: Imported rather than restated: a test asserting "two" would keep passing after a third bounded
#: task was added and never seeded, which is the defect the half-seeded test below is about.
VERSIONED_MODEL_CONFIGS = FAKE_MODEL_CONFIGS


# --- criterion 1: the import lands, and it is committed -----------------------------------------


def test_importing_prospects_commits_them(cli_database: str) -> None:
    """Committed, not flushed: the point of the command is that the rows are still there when the
    process that made them has gone."""
    assert main(["import_prospects"]) == 0

    assert rows(cli_database, ImportBatch) == 1
    assert rows(cli_database, Account) > 0
    assert rows(cli_database, Contact) > 0
    assert rows(cli_database, ContactPoint) > 0


def test_the_imported_contacts_carry_their_provenance(cli_database: str) -> None:
    """`T-144b` refuses a candidate with no approved source basis, so an import that did not stamp
    the batch would produce a database in which nothing is ever eligible."""
    assert main(["import_prospects"]) == 0

    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            batch = session.execute(select(ImportBatch)).scalar_one()
            unattributed = session.execute(
                select(func.count())
                .select_from(Contact)
                .where(Contact.source_import_batch_id.is_(None))
            ).scalar_one()
            assert unattributed == 0
            assert batch.source_type == "csv"
    finally:
        engine.dispose()


# --- criterion 2: running it twice is safe ------------------------------------------------------


def test_importing_twice_changes_nothing(cli_database: str) -> None:
    """The walkthrough is run more than once. `import_batch.content_hash` is unique, so the second
    run reports `already_imported` rather than failing on the constraint."""
    assert main(["import_prospects"]) == 0
    accounts, contacts = rows(cli_database, Account), rows(cli_database, Contact)

    assert main(["import_prospects"]) == 0

    assert rows(cli_database, ImportBatch) == 1
    assert (rows(cli_database, Account), rows(cli_database, Contact)) == (accounts, contacts)


def test_seeding_and_importing_compose(cli_database: str) -> None:
    """The two commands are the walkthrough's steps 3 and 4 and must not tread on each other."""
    assert main(["seed_synthetic"]) == 0
    assert main(["import_prospects"]) == 0

    assert rows(cli_database, ImportBatch) == 1
    assert rows(cli_database, Account) > 0


# --- criterion 3: refused outside a seedable environment, before the database ---------------------


@pytest.mark.parametrize("app_env", [AppEnv.PRODUCTION, AppEnv.STAGING])
def test_importing_is_refused_outside_a_seedable_environment(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `cli_database` fixture on purpose: the settings below name a database that does not
    exist, so the command can only return `EXIT_REFUSED` by refusing *before* it connects."""
    settings = Settings(
        app_env=app_env,
        database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/does-not-exist",
    )
    monkeypatch.setattr("app.cli.get_settings", lambda: settings)

    assert main(["import_prospects"]) == EXIT_REFUSED


# --- criterion 4: it cannot be pointed at anything but the fixture -------------------------------


def test_the_command_takes_no_file_argument() -> None:
    """AGENTS.md rule 1. A path argument is how a developer convenience becomes the thing that
    imported a real prospect list into a synthetic-only database."""
    with pytest.raises(SystemExit) as caught:
        main(["import_prospects", "some-real-list.csv"])

    assert caught.value.code == 2  # argparse's usage error


def test_an_unknown_command_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["not_a_command"])


# --- T-170: a local reviewer who can actually sign in -------------------------------------------


def signed_in_roles(url: str, email: str) -> list[str]:
    """Sign in the way the dashboard does and report what the resolved principal holds."""
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            issued = stub_sign_in(session, email, settings=Settings(app_env=AppEnv.LOCAL))
            session.commit()
            principal = resolve(session, issued.token)
            assert principal is not None, "a session was issued but resolved to nobody"
            return sorted(principal.roles)
    finally:
        engine.dispose()


def test_the_local_reviewer_can_sign_in_and_holds_the_reviewer_role(cli_database: str) -> None:
    """Criterion 1, end to end: the command, then a real `stub_sign_in`.

    Asserting the row exists would not have caught this gap — the seeded approver *is* a row, and
    signing in as them gets a session that sees `403` everywhere. What matters is the resolved
    principal's roles.
    """
    assert main(["grant_local_reviewer"]) == 0

    assert signed_in_roles(cli_database, LOCAL_REVIEWER_EMAIL) == [RoleKey.OPERATOR_REVIEWER.value]


def test_granting_twice_grants_nothing_twice(cli_database: str) -> None:
    """`uq_user_role` would refuse the second grant; the command must be a no-op, not an error."""
    assert main(["grant_local_reviewer"]) == 0
    assert main(["grant_local_reviewer"]) == 0

    assert rows(cli_database, User) == 1
    assert rows(cli_database, UserRole) == 1


def test_the_reviewer_gets_no_role_beyond_reviewing(cli_database: str) -> None:
    """Criterion 4. The operations panel is `system_administrator` only, and a convenience command
    that handed that out would be a way to acquire tier-5 authority by running a script."""
    assert main(["grant_local_reviewer"]) == 0

    assert signed_in_roles(cli_database, LOCAL_REVIEWER_EMAIL) == [RoleKey.OPERATOR_REVIEWER.value]
    assert RoleKey.SYSTEM_ADMINISTRATOR.value not in signed_in_roles(
        cli_database, LOCAL_REVIEWER_EMAIL
    )


def test_the_reviewer_email_can_never_be_delivered_to() -> None:
    # AGENTS.md rule 1: an IANA-reserved domain, so a stray send could not reach anybody.
    assert LOCAL_REVIEWER_EMAIL.endswith("@example.invalid")


@pytest.mark.parametrize("app_env", [AppEnv.PRODUCTION, AppEnv.STAGING])
def test_granting_is_refused_outside_a_seedable_environment(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 3, and the database it names does not exist — so it can only pass by refusing
    before it connects."""
    settings = Settings(
        app_env=app_env,
        database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/does-not-exist",
    )
    monkeypatch.setattr("app.cli.get_settings", lambda: settings)

    assert main(["grant_local_reviewer"]) == EXIT_REFUSED


# --- T-169: the import produces candidates, and the worker can take them to review --------------


def drain(url: str, limit: int = 400) -> int:
    """Run the worker in-process until it idles. `python -m app.worker` loops forever."""
    register_job_types()
    settings = Settings(app_env=AppEnv.TEST, database_url=url)
    adapter = build_effect_adapter(settings)
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    passes = 0
    try:
        while passes < limit:
            with Session(engine) as session:
                result = one_pass(session, worker_id="test-cli", adapter=adapter, settings=settings)
            passes += 1
            if result.did_nothing:
                break
    finally:
        engine.dispose()
    return passes


def start_campaigns(url: str) -> None:
    """Seeded campaigns are paused (`T-015`) and a paused campaign gets no candidates (§17.6).

    Starting one is a deliberate operator act, which is why `seed_synthetic` does not do it — and
    why there is still no command for it. Done here the way `tests/test_shadow_slice.py` does it;
    the walkthrough needs a command, filed as `T-171`.
    """
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            for campaign in session.execute(select(Campaign)).scalars():
                campaign.paused = False
            session.commit()
    finally:
        engine.dispose()


def test_importing_enqueues_membership_work(cli_database: str) -> None:
    """Criterion 1, first half. Before `T-169` this was zero and nothing said so."""
    assert main(["seed_synthetic"]) == 0
    assert main(["import_prospects"]) == 0

    assert rows(cli_database, Job) > 0, "the import queued no membership work"


def test_the_imported_rows_become_candidates_that_enter_the_pipeline(cli_database: str) -> None:
    """Criterion 1, and the whole point of `T-169`: the documented commands produce candidates
    that the worker actually advances.

    Against a **committed** database, not a rolled-back session — which is exactly why the gap
    was invisible: `tests/test_shadow_slice.py` proves the same pipeline inside a transaction
    nobody keeps, and enqueues the membership jobs itself.

    **Stops short of `review_pending`, deliberately**, and this test drains with `drain()` rather
    than through `run_worker`, so it stays the assertion about the *import* that `T-169` wrote.
    What `run_worker` adds is asserted below (`T-172a`); why even that does not reach
    `review_pending` is `T-172b`.
    """
    assert main(["seed_synthetic"]) == 0
    assert main(["import_prospects"]) == 0
    start_campaigns(cli_database)

    drain(cli_database)

    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            candidates = list(session.execute(select(CampaignCandidate)).scalars())
    finally:
        engine.dispose()

    assert candidates, "the worker drained but produced no candidates"
    states = {candidate.state for candidate in candidates}
    advanced = states & {
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
        CampaignCandidateState.REVIEW_PENDING,
    }
    assert advanced, f"candidates exist but none advanced: {sorted(s.value for s in states)}"


def test_each_candidate_keeps_its_own_correlation_id(cli_database: str) -> None:
    """Criterion 2. §8.1 makes the two judgements on a both-campaigns row independent, so one
    shared id would put two histories on one trail."""
    assert main(["seed_synthetic"]) == 0
    assert main(["import_prospects"]) == 0

    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            ids = [job.correlation_id for job in session.execute(select(Job)).scalars()]
    finally:
        engine.dispose()

    assert ids, "no membership jobs to check"
    assert len(set(ids)) == len(ids), "two candidates share a correlation id"


# --- T-172a: a development entry point installs the Stage 1 fixtures ----------------------------


@pytest.fixture(autouse=True)
def stage_one_registry() -> Iterator[None]:
    """Put back the empty defaults `run_worker` installs into.

    Both registries are **process-wide**, so a successful `run_worker` here would otherwise leave
    a fixture adapter resolvable for every test that ran after it — including the ones asserting
    that a production process resolves nothing.
    """
    preexisting = dict(SOURCE_ADAPTERS)
    try:
        yield
    finally:
        SOURCE_ADAPTERS.clear()
        SOURCE_ADAPTERS.update(preexisting)
        reset_fake_adapter_factory()


def test_running_the_worker_captures_evidence(cli_database: str) -> None:
    """`T-172a` criterion 1. Before this, every `research.capture_evidence` job dead-lettered with
    *"no source adapter registered under 'fixture'"* — the whole reason `T-172` was filed.

    Against a **committed** database, and through the command a reader is told to run rather than
    through `drain()`, which is a test helper nobody outside this file has.
    """
    assert main(["seed_synthetic"]) == 0
    assert main(["start_campaign", "synthetic-sodium-battery"]) == 0
    assert main(["import_prospects"]) == 0

    assert main(["run_worker"]) == 0

    assert rows(cli_database, EvidenceSnapshot) > 0, (
        "the worker drained and captured no evidence; the fixture source adapter is not installed"
    )
    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            states = {
                candidate.state
                for candidate in session.execute(select(CampaignCandidate)).scalars()
            }
    finally:
        engine.dispose()

    # "At least researched", not "researched": `T-172b` registered the versions qualification
    # needs, so a candidate that finished research now carries on to `REVIEW_PENDING` in the same
    # drain. What this test owns is that research *completed* — the step the source adapter is
    # needed for. Reaching review is asserted by `T-172b`'s own test below.
    assert states & {CampaignCandidateState.RESEARCHED, CampaignCandidateState.REVIEW_PENDING}, (
        f"no candidate finished research: {sorted(s.value for s in states)}"
    )
    # The other half of what the command installs. Research needs no model, so nothing above
    # would notice if the fake were never installed — and `T-172b` cannot start from a process
    # that resolves `EchoModelAdapter`, which answers any prompt with an echo.
    assert isinstance(build_provider(Settings(app_env=AppEnv.TEST)), TaskRoutingFake), (
        "run_worker drained without installing the fixture-keyed model fake"
    )


# --- T-172b: the versions a real database had none of -------------------------------------------


def test_the_documented_commands_reach_a_review_queue(cli_database: str) -> None:
    """`T-172b` criterion 1, and `T-172`'s objective: a locally-run worker completes the pipeline.

    This is the assertion gate **G-10** rests on. Everything before it produced a queue a
    non-engineer could open and find empty — first no candidates (`T-169`), then no roles
    (`T-170`), then no source adapter (`T-172a`), then no model-config version (this task). Run
    against a **committed** database, through the four commands and nothing else.
    """
    assert main(["seed_synthetic"]) == 0
    assert main(["start_campaign", "synthetic-sodium-battery"]) == 0
    assert main(["import_prospects"]) == 0
    assert main(["run_worker"]) == 0

    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            states = [
                candidate.state
                for candidate in session.execute(select(CampaignCandidate)).scalars()
            ]
            qualified = session.execute(select(func.count()).select_from(QualificationRun))
            qualification_runs = qualified.scalar_one()
            drafted = session.execute(select(func.count()).select_from(MessageRevision))
            revisions = drafted.scalar_one()
    finally:
        engine.dispose()

    assert CampaignCandidateState.REVIEW_PENDING in states, (
        f"no candidate reached review: {sorted({s.value for s in states})}"
    )
    # A candidate could in principle be presented for review without the model having run at all,
    # so the run is asserted too — it is the thing the three missing versions were blocking.
    assert qualification_runs > 0, "a candidate reached review with no qualification run"

    # **And nothing is drafted, which is correct.** §8.3 step 8 presents for review and step 9
    # drafts; `approve_candidate` is what enqueues `drafts.draft_message`, and that is a human's
    # act in the dashboard. A drain that produced a message would mean the pipeline had written
    # prospect-facing copy nobody approved.
    assert revisions == 0, f"the drain drafted {revisions} revisions without a human approval"


def test_seeding_twice_publishes_no_second_version(cli_database: str) -> None:
    """`T-172b`, the property the whole module is built on: seeding is a get-or-create.

    A second `register_prompt_versions` that republished would close the first version's window
    and start a second, so a `ModelRun` written before the re-seed would cite a version that had
    been superseded for no reason. The registrars are content-hash idempotent and the model
    configurations are guarded per key; this is what proves both at once.
    """
    assert main(["seed_synthetic"]) == 0
    first = {model: rows(cli_database, model) for model in VERSIONED}

    assert main(["seed_synthetic"]) == 0

    assert {model: rows(cli_database, model) for model in VERSIONED} == first
    assert all(count > 0 for count in first.values()), f"seeding registered nothing: {first}"


def test_a_half_seeded_database_gains_the_missing_model_config(cli_database: str) -> None:
    """The `T-148` trap, which this repository has fallen into twice: a registration loop that
    stops at the first item it finds already present.

    Reachable rather than theoretical — the day a third bounded task is added, every existing
    local database is exactly this shape. Written as delete-and-re-seed because that is the
    cheapest way to produce "one present, one absent" without pretending a new task exists.

    **The key removed is the one the loop reaches last**, not the last alphabetically. The first
    version of this test used `order_by(key)` and a control proved it worthless: that happens to
    be the loop's *first* key, so replacing `continue` with `break` produced the same database
    and the test passed. A control that does not bite is a finding.
    """
    removed_key = VERSIONED_MODEL_CONFIGS[-1]
    assert main(["seed_synthetic"]) == 0
    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            session.delete(
                session.execute(
                    select(ModelConfigVersion).where(ModelConfigVersion.key == removed_key)
                ).scalar_one()
            )
            session.commit()
    finally:
        engine.dispose()
    assert rows(cli_database, ModelConfigVersion) == len(VERSIONED_MODEL_CONFIGS) - 1

    assert main(["seed_synthetic"]) == 0

    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            keys = set(session.execute(select(ModelConfigVersion.key)).scalars())
    finally:
        engine.dispose()
    assert removed_key in keys, f"re-seeding stopped before {removed_key}: {sorted(keys)}"


@pytest.mark.parametrize("app_env", [AppEnv.PRODUCTION, AppEnv.STAGING])
def test_running_the_worker_is_refused_outside_a_seedable_environment(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`T-172a` criterion 2, and the half that matters: it must register **nothing** on the way
    out.

    A refusal that had already made the fixture adapter resolvable would leave the process able to
    serve fixture evidence, which is the exact failure the two adapter invariants exist to
    prevent. The database named here does not exist, so this can also only pass by refusing before
    it connects.
    """
    settings = Settings(
        app_env=app_env,
        database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/does-not-exist",
    )
    monkeypatch.setattr("app.cli.get_settings", lambda: settings)

    assert main(["run_worker"]) == EXIT_REFUSED

    assert FIXTURE_ADAPTER_NAME not in SOURCE_ADAPTERS, (
        "a refused run_worker left a fixture source adapter registered"
    )
    assert isinstance(build_provider(Settings(app_env=AppEnv.TEST)), EchoModelAdapter), (
        "a refused run_worker left the fixture-keyed fake installed"
    )


def test_a_row_naming_no_campaign_enqueues_nothing(cli_database: str) -> None:
    """Behavioural, not structural. Joining every campaign by default is the "automated CRM
    creation for every discovered candidate" §9.3 says not to begin with.

    Written this way because the first version asserted the *parser* returned no slugs, which a
    control showed proved nothing: the guard it was meant to cover could be deleted with no test
    failing. This one enqueues and counts.
    """
    content = (
        "case_label,account_domain,account_name,country_code,full_name,role_title,"
        "contact_type,contact_value,verification_state,campaigns,note"
        + chr(10)
        + "no-campaign,zulu.example.com,SYNTHETIC-Account-Zulu,US,SYNTHETIC Person Zulu,"
        "SYNTHETIC Lead,email,zulu.person@zulu.example.com,verified,," + chr(10)
    ).encode("utf-8")
    register_job_types()
    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            import_csv(session, content=content, source_name="zulu.csv", actor=CLI_ACTOR)
            enqueued = enqueue_memberships_for_import(
                session, content=content, batch_id=uuid.uuid4(), actor=CLI_ACTOR
            )
            session.commit()
    finally:
        engine.dispose()

    assert enqueued == 0
    assert rows(cli_database, Job) == 0


# --- T-171: starting a campaign is an act somebody performs -------------------------------------


def campaign_slug(url: str) -> str:
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            return session.execute(select(Campaign.slug)).scalars().first() or ""
    finally:
        engine.dispose()


def test_starting_a_campaign_clears_its_pause_and_is_audited(cli_database: str) -> None:
    """Criterion 1. The act that makes the pipeline produce anything must itself be reviewable
    (§3.5) — `tests/test_shadow_slice.py::test_starting_the_campaigns_is_audited` says the same
    of the slice's own version."""
    assert main(["seed_synthetic"]) == 0
    slug = campaign_slug(cli_database)

    assert main(["start_campaign", slug]) == 0

    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            campaign = session.execute(select(Campaign).where(Campaign.slug == slug)).scalar_one()
            assert not campaign.paused
            actions = [
                event.action
                for event in session.execute(select(AuditEvent)).scalars()
                if event.entity_id == str(campaign.id)
            ]
    finally:
        engine.dispose()

    assert "campaign.resumed" in actions


def test_a_paused_campaign_produces_no_candidates(cli_database: str) -> None:
    """Why the command exists at all: without it a set-up database runs the whole pipeline and
    yields nothing, with no error to read (§17.6)."""
    assert main(["seed_synthetic"]) == 0
    assert main(["import_prospects"]) == 0

    drain(cli_database)

    assert rows(cli_database, CampaignCandidate) == 0


def test_starting_the_campaign_first_is_what_produces_candidates(cli_database: str) -> None:
    """The same flow with one step moved, which is the step this command adds.

    **Started before the import, not after.** A membership job is consumed once: enqueued while
    the campaign was paused, it succeeds, creates nothing, and is gone — starting the
    campaign afterwards does not bring it back. The walkthrough has to say so, and this test is
    what makes that ordering a fact rather than a habit.
    """
    assert main(["seed_synthetic"]) == 0
    assert main(["start_campaign", campaign_slug(cli_database)]) == 0
    assert main(["import_prospects"]) == 0

    drain(cli_database)

    assert rows(cli_database, CampaignCandidate) > 0


def test_starting_an_unknown_campaign_refuses_and_changes_nothing(cli_database: str) -> None:
    """Criterion 2."""
    assert main(["seed_synthetic"]) == 0

    assert main(["start_campaign", "synthetic-does-not-exist"]) == EXIT_REFUSED

    engine = create_engine(cli_database, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            paused = [c.paused for c in session.execute(select(Campaign)).scalars()]
    finally:
        engine.dispose()

    assert all(paused), "an unknown slug started something"


@pytest.mark.parametrize("app_env", [AppEnv.PRODUCTION, AppEnv.STAGING])
def test_starting_is_refused_outside_a_seedable_environment(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 3, and the database it names does not exist, so it can only pass by refusing
    before it connects."""
    settings = Settings(
        app_env=app_env,
        database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/does-not-exist",
    )
    monkeypatch.setattr("app.cli.get_settings", lambda: settings)

    assert main(["start_campaign", "synthetic-sodium-battery"]) == EXIT_REFUSED


def test_the_command_requires_a_slug() -> None:
    """Starting every seeded campaign at once would make it a side effect of running a script
    rather than a decision about one campaign."""
    with pytest.raises(SystemExit) as caught:
        main(["start_campaign"])

    assert caught.value.code == 2  # argparse's usage error
