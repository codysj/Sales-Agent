# ADR-018 — Backend toolchain defaults

- **Status:** ACCEPTED (2026-07-27)
- **Scope:** Local to this repository. Does not modify any inherited specification ADR.
- **Specification basis:** §18.1 fixes the stack (FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL,
  Next.js, Docker Compose, one repository) and GP-10 asks for minimal operational burden. It does not
  name a dependency manager, linter, type checker, test runner, or Python patch line. This ADR fills
  exactly those gaps and nothing else.
- **Implemented by:** `T-002`, `T-003`. Recorded in `tasks.md` §2.

## Decision

| Concern | Choice |
|---|---|
| Python | 3.12, pinned `>=3.12,<3.13` in `backend/pyproject.toml` |
| Dependencies and environments | `uv`, with a committed `backend/uv.lock` |
| Lint and format | `ruff` (`E,F,I,UP,B,SIM,RUF`, line length 100) and `ruff format` |
| Types | `mypy` in `strict` mode with `warn_unreachable`, over `app` only |
| Tests | `pytest`, `pytest-asyncio` in auto mode, `filterwarnings = ["error"]` |
| Packaging | `[tool.uv] package = false` — no build backend; `pythonpath = ["."]` puts `backend/` on the path |
| Layout | `backend/` (package `app/`), `frontend/`, `docs/` |
| CI | GitHub Actions (`T-007`) |

## Why

**Python 3.12, not 3.13/3.14.** The 3.14 interpreter is the machine default, but the pinned stack
(SQLAlchemy, psycopg, Pydantic) has the longest-settled wheel and typing story on 3.12, and the pilot
gains nothing from a newer runtime. `uv` fetches 3.12 itself, so the pin costs nothing.

**uv, not pip-tools / Poetry / PDM.** One tool covers interpreter acquisition, resolution, locking,
and running, with no separate virtualenv step for a future maintainer to get wrong — which matters
because `Q-018` leaves the post-internship maintenance owner unnamed.

**ruff, not black + flake8 + isort.** One dependency and one configuration block instead of three
tools that must be kept consistent with each other.

**mypy strict, not pyright.** The typed-contract requirement in §23 is best served by a checker that
runs identically in CI and locally without a Node runtime, and strict-from-empty is far cheaper than
strict-from-legacy.

**`filterwarnings = ["error"]`.** Deprecations surface as failures while the codebase is small enough
to fix them in minutes. This is the setting most likely to become annoying; see the revisit trigger.

**No build backend.** The backend runs as an API process and a worker process from the source tree
(§18.1). It is not published anywhere, so a build backend would be configuration serving nothing.

## Rejected

| Rejected | Why |
|---|---|
| Poetry / PDM / pip-tools | More moving parts than `uv` for the same result; slower CI cold start. |
| black + flake8 + isort | Three dependencies and three configs where one suffices. |
| pyright | Requires a Node runtime in the Python CI job. |
| Python 3.13 or 3.14 | No benefit to the pilot; less-settled dependency support. |
| `src/` layout with a build backend | Packaging ceremony for something never distributed. |
| `nox`/`tox` matrix | One supported Python version means nothing to matrix over. |
| A `Makefile` task runner | Windows-hostile for the current primary developer; the four commands are already one line. |
| Pre-commit hooks | Deferred, not rejected — CI (`T-007`) enforces the same checks, and hooks add a setup step per clone. Revisit if CI catches formatting failures repeatedly. |

## Consequences

- `uv sync --all-groups` is required before any check; the lock file is authoritative and committed.
- Resolution pulled several dependencies above their declared floors (mypy 2.3.0, pytest 9.1.1,
  ruff 0.16.0, starlette 1.3.1). New code must target current-generation APIs.
- `mypy strict` means every new function needs annotations, including in `app/**/__init__.py`.
- `filterwarnings = ["error"]` will fail the suite on a library deprecation before it fails in
  production — accepted deliberately. **First observed instance (T-004, 2026-07-27):** Starlette
  1.3.1 deprecates `httpx` for `TestClient`; the setting surfaced it as an immediate collection
  error and the dev dependency became `httpx2`. Caught in one cycle rather than at an upgrade.

## Revisit when

- A required dependency does not support Python 3.12, or drops support for it.
- `filterwarnings = ["error"]` blocks work on a deprecation the project cannot fix (in that case,
  narrow it to specific warning classes rather than removing it).
- The backend genuinely needs to be installed as a package, e.g. an out-of-tree consumer appears.
- CI (`T-007`) repeatedly catches formatting or lint failures that a pre-commit hook would have caught
  locally.
