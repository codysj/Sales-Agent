"""The CI workflow (T-007; specification §18.1 one coordinated release process, §19.2).

The workflow file is the one piece of this repository that runs on somebody else's machine with
the repository checked out, so what it is *not allowed to do* matters more than what it runs.
Three things are asserted here, and none of them is "the YAML parses":

* it runs the canonical command list from `tasks.md` §2 — read out of `tasks.md` rather than
  copied here, so the two cannot drift apart quietly;
* it holds no more permission than reading the repository, and reads no secret;
* `alembic upgrade head` runs **before** `pytest`. Every database fixture skips when PostgreSQL
  is unreachable (`conftest.py`), so a job whose service container never came up would otherwise
  be green while running only the offline half of the suite. The alembic step shares the same
  `DATABASE_URL` and fails instead.

Offline: the workflow is text, and no test here runs it.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
LEDGER = REPO_ROOT / "tasks.md"

#: Actions this workflow is permitted to call. An action is third-party code running with the
#: checkout in scope; a new one is a deliberate decision, not a diff nobody reads.
ALLOWED_ACTIONS = frozenset({"actions/checkout", "astral-sh/setup-uv", "actions/setup-node"})

#: Actions that stopped publishing major and minor tags, so a pin has to be a full version.
#: `astral-sh/setup-uv` did so at v8 — "use immutable tags like `@v8.0.0` instead" — which means
#: the obvious tidy-up of shortening `@v9.0.0` to `@v9` resolves to a tag that does not exist and
#: breaks every run (`T-164a`). Nothing about the pin looks wrong when it happens.
IMMUTABLE_TAG_ONLY = frozenset({"astral-sh/setup-uv"})

#: Words that would mean the workflow reaches beyond the runner. `T-007` puts deployment, image
#: publishing, and environment promotion explicitly out of scope.
EXTERNAL_EFFECT_WORDS = ("deploy", "publish", "docker push", "npm publish", "environment:")


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.exists(), f"the CI workflow is missing at {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def effective_text(workflow_text: str) -> str:
    """The workflow with its comment lines removed.

    The text scans below run against this rather than the file: a comment cannot read a secret or
    reach a registry, and matching `publish` inside the header sentence that promises *no* image
    publishing would push the next author to stop writing the explanation down.
    """
    return "\n".join(
        line for line in workflow_text.splitlines() if not line.lstrip().startswith("#")
    )


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict[str, Any]:
    parsed = yaml.safe_load(workflow_text)
    assert isinstance(parsed, dict), "the workflow did not parse as a mapping"
    return parsed


def steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Every step of every job, in file order.

    Walks all jobs rather than a named one: a second job added later is exactly the thing that
    would otherwise slip past the permission and external-effect checks below.
    """
    found: list[dict[str, Any]] = []
    for job in workflow["jobs"].values():
        found.extend(job.get("steps", []))
    return found


def run_commands(workflow: dict[str, Any]) -> list[str]:
    return [step["run"].strip() for step in steps(workflow) if "run" in step]


def job_commands(workflow: dict[str, Any], job: str) -> list[str]:
    """One job's `run` commands, in order.

    Ordering is asserted per job, never across the flattened list: two jobs run concurrently, so
    a position in the whole-workflow list means nothing.
    """
    return [step["run"].strip() for step in workflow["jobs"][job].get("steps", []) if "run" in step]


def canonical_commands() -> list[str]:
    """The `uv run …` and `npm run …` commands from the fenced blocks under `tasks.md` §2.

    Read from the ledger, not restated: §2 is where the loop's command list is agreed, and a copy
    here would let CI and the loop diverge without either file looking wrong. **Every** fenced
    block in the section is read — the frontend list arrived as a second one (`T-163`), and a
    reader of only the first would have gone on reporting full coverage of half of it.
    """
    ledger = LEDGER.read_text(encoding="utf-8")
    section = ledger.split("## 2. Toolchain assumptions")[1].split("\n## ")[0]
    blocks = re.findall(r"```bash\n(.*?)\n```", section, re.DOTALL)
    assert blocks, "tasks.md §2 no longer contains a fenced bash block"
    commands = [part.strip() for block in blocks for part in block.split("&&")]
    return [
        command
        for command in commands
        if command.startswith("uv run ") or command.startswith("npm run ")
    ]


# --- criterion 1: the workflow runs what the loop runs -------------------------------------------


def test_the_workflow_is_valid_yaml_with_at_least_one_job(workflow: dict[str, Any]) -> None:
    assert workflow["jobs"], "the workflow declares no jobs"
    for name, job in workflow["jobs"].items():
        assert job.get("steps"), f"job {name} has no steps"


def test_it_actually_fires(workflow: dict[str, Any]) -> None:
    # A workflow with no trigger passes every other check in this file and never runs once.
    # The key is `True`, not `"on"`: YAML 1.1 reads a bare `on` as a boolean, which is a quirk of
    # the parser rather than of the file — GitHub reads the same document correctly.
    triggers = workflow.get(True, workflow.get("on"))
    assert triggers is not None, "the workflow declares no trigger"
    assert "push" in triggers


def test_it_runs_every_canonical_command_from_the_ledger(workflow: dict[str, Any]) -> None:
    commands = run_commands(workflow)
    missing = [command for command in canonical_commands() if command not in commands]
    assert not missing, f"the workflow does not run: {missing}"


def test_it_applies_and_checks_the_migrations(workflow: dict[str, Any]) -> None:
    commands = run_commands(workflow)
    assert "uv run alembic upgrade head" in commands
    assert "uv run alembic check" in commands


def test_it_runs_against_a_real_postgresql(workflow: dict[str, Any]) -> None:
    # A suite whose schema comes from migrations cannot prove anything against no database.
    services = [
        service for job in workflow["jobs"].values() for service in job.get("services", {}).values()
    ]
    assert any(str(service.get("image", "")).startswith("postgres:") for service in services)


def test_the_database_is_proven_reachable_before_the_tests_run(workflow: dict[str, Any]) -> None:
    # The one that matters: the fixtures *skip* when PostgreSQL is unreachable, so without a step
    # that fails on an unreachable database, a broken service container reads as a pass.
    commands = job_commands(workflow, "backend")
    assert commands.index("uv run alembic upgrade head") < commands.index("uv run pytest -q")


def test_the_dependency_installs_refuse_to_re_resolve(workflow: dict[str, Any]) -> None:
    commands = run_commands(workflow)
    assert "uv sync --frozen" in commands
    assert "npm ci" in commands


# --- criterion 1 continued: the dashboard is checked too, and its contract is proven honest ------


def test_the_dashboard_runs_its_own_canonical_commands(workflow: dict[str, Any]) -> None:
    commands = job_commands(workflow, "frontend")
    missing = [
        command
        for command in canonical_commands()
        if command.startswith("npm run ") and command not in commands
    ]
    assert not missing, f"the dashboard job does not run: {missing}"


def test_the_node_version_is_pinned(workflow: dict[str, Any]) -> None:
    # `package.json` declares no `engines` range, so an unpinned setup would make a Node release
    # into a failure nobody changed anything to cause.
    versions = [
        step["with"]["node-version"]
        for step in steps(workflow)
        if str(step.get("uses", "")).startswith("actions/setup-node")
    ]
    assert versions, "no step sets up Node"
    assert all(str(version).strip() for version in versions)


def test_the_contract_drift_checks_this_workflow_relies_on_still_exist(
    workflow: dict[str, Any],
) -> None:
    """CI's cover for `application → openapi.json → api-types.ts` is two tests, not a step.

    `T-163` wrote a re-export-and-`git diff` step here and then deleted it: both arrows are
    already tested, and the two suites run in the jobs below. That makes those tests load-bearing
    for the workflow, so deleting one has to fail *here* too — otherwise the coverage disappears
    and the only record of it is a comment.
    """
    assert "uv run pytest -q" in job_commands(workflow, "backend")
    assert "npm run test" in job_commands(workflow, "frontend")

    backend_check = REPO_ROOT / "backend" / "tests" / "test_fixtures.py"
    frontend_check = REPO_ROOT / "frontend" / "tests" / "api-types.test.ts"
    assert (
        "def test_the_committed_openapi_document_matches_the_application"
        in backend_check.read_text(encoding="utf-8")
    ), "the application → openapi.json arrow lost its test, and CI has no other cover for it"
    assert frontend_check.exists(), (
        "the openapi.json → api-types.ts arrow lost its test, and CI has no other cover for it"
    )


# --- criterion 2: no more permission than reading the repository ---------------------------------


def test_the_workflow_permission_is_read_only(workflow: dict[str, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}


def test_no_job_grants_itself_more(workflow: dict[str, Any]) -> None:
    # A job-level `permissions:` overrides the workflow-level one entirely, so the top-level
    # declaration above is not on its own a guarantee.
    for name, job in workflow["jobs"].items():
        assert "permissions" not in job or job["permissions"] == {"contents": "read"}, (
            f"job {name} widens the workflow permission"
        )


# --- criterion 3: no secret, no external write ---------------------------------------------------


def test_no_step_reads_a_secret(effective_text: str) -> None:
    # Text, not structure: a secret can be referenced from `env:`, `with:`, `run:`, or a job-level
    # `secrets:` block, and a walk over one of those would miss the others.
    assert "secrets." not in effective_text


def test_no_step_reaches_outside_the_runner(effective_text: str) -> None:
    present = [word for word in EXTERNAL_EFFECT_WORDS if word in effective_text.lower()]
    assert not present, f"the workflow looks like it reaches outside the runner: {present}"


def test_every_action_is_allowed_and_pinned(workflow: dict[str, Any]) -> None:
    for step in steps(workflow):
        uses = step.get("uses")
        if uses is None:
            continue
        action, _, ref = uses.partition("@")
        assert action in ALLOWED_ACTIONS, f"unreviewed action: {action}"
        assert ref, f"{action} is not pinned to a version"


def test_an_action_without_major_tags_is_pinned_to_a_full_version(workflow: dict[str, Any]) -> None:
    """See `IMMUTABLE_TAG_ONLY`. A shortened pin here is a broken run, not a style change."""
    for step in steps(workflow):
        uses = step.get("uses")
        if uses is None:
            continue
        action, _, ref = uses.partition("@")
        if action not in IMMUTABLE_TAG_ONLY:
            continue
        assert re.fullmatch(r"v\d+\.\d+\.\d+", ref), (
            f"{action} is pinned to {ref!r}; it publishes no major or minor tags, so this must be"
            f" a full version"
        )


def test_the_safety_switches_are_stated_fail_closed(workflow: dict[str, Any]) -> None:
    # Not because the defaults are unsafe — they are — but because CI is where a future change to
    # them would show up as a diff somebody has to justify.
    for job in workflow["jobs"].values():
        env = job.get("env", {})
        if "DATABASE_URL" not in env:
            continue
        assert env["SHADOW_MODE"] == "true"
        assert env["OUTBOUND_EMAIL_ENABLED"] == "false"
        assert env["MODEL_PROVIDER"] == "fake"
        assert env["ALLOW_REAL_MODEL_PROVIDER"] == "false"
        assert env["APP_ENV"] == "test"
