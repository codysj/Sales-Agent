# Matrix Power Always-On AI Sales Agent — Implementation Backlog and Progress Ledger

> **This file is the authoritative work ledger for the development loop.** Read [process.md](process.md)
> before changing anything here.

| Field | Value |
|---|---|
| **Project** | Matrix Power Always-On AI Sales Agent |
| **Source specification** | `MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md` (v0.3, dated 2026-07-27, status: *Approved architecture for buildout and shadow deployment; live outreach remains gated*) |
| **Specification location** | `docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md` (repo-local; placed there by the user on 2026-07-27). SHA-256 `E571FC36420FEB7786AB2C984D24FDF0E100E89C6974E80F56C5D66173C57D9A`, 92,997 bytes. `MATRIX_POWER_NEMOCLAW_SALES_AGENT_SPEC_v0.2.md` is **SUPERSEDED** (spec §22) and is deliberately not vendored. |
| **Current implementation stage** | **Stage 1 — Core shadow backend** (spec §19.6). Repository is greenfield: only `LICENSE`, `README.md`, and an empty `docs/` directory exist. |
| **Current stage exit gate** | **G-02** — full import-to-review-ready-draft flow works against synthetic fixtures with **zero external writes**, on a deterministic fake model adapter and a fake external-effect adapter. |
| **Last updated** | 2026-07-27 |
| **Next recommended `READY` task** | **`T-010` — Independent lifecycle state machines** (pure domain, no database). ⚠️ **This is the last database-free Stage 1 task.** After it the loop reports `LOOP_BLOCKED` until the `T-134` Docker engine is available. |
| **`IN_PROGRESS` task** | none |

> ⚠️ **LIVE OUTREACH IS GATED.** No email send, no message send, no CRM mutation, no production
> credential, no deployment, no LinkedIn automation, and no autonomous follow-up may occur until the
> corresponding gate in §5 is explicitly unlocked by the user with the required stakeholder decisions
> recorded. Every gate below is currently **LOCKED**. All data in this repository must be synthetic.
> This repository has a public GitHub remote (`codysj/Sales-Agent`) — never commit real prospect
> records, real contact data, internal product decks, or credentials.

---

## 1. Status vocabulary

| Status | Meaning |
|---|---|
| `PLANNED` | Valid task whose dependency or stage gate is not yet satisfied. |
| `READY` | Safe to begin now. Dependencies satisfied, stage gate open, no blocking decision. |
| `IN_PROGRESS` | Currently claimed by a loop invocation. **At most one task may hold this status.** |
| `BLOCKED` | Cannot proceed without a named dependency, decision, credential, or authority. |
| `DONE` | All acceptance criteria met and required verification passed, with evidence recorded. |
| `DEFERRED` | Intentionally outside the current implementation horizon. |

Rules:

- At most **one** `IN_PROGRESS` task at any time.
- Task IDs are **stable and never reused or renumbered**, including after a task is deleted or deferred.
- A task behind an unmet gate (§5) must be `PLANNED` or `BLOCKED`, never `READY`.
- `DONE` requires source code plus verification evidence, not a scaffold.

## 2. Toolchain assumptions (reversible defaults)

These are conservative engineering defaults chosen where the specification leaves discretion (§18.1).
They are recorded here so every loop invocation uses the same commands. Changing one is itself a task.

| Concern | Default | Basis |
|---|---|---|
| Language / runtime | Python 3.12 | spec §18.1 |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.0 + Alembic | spec §18.1 (DECIDED) |
| Database | PostgreSQL 16 via Docker Compose locally | spec §18.1, ADR-003 |
| Dependency/env manager | `uv` | ASSUMED; single-file lock, no service dependency |
| Lint / format / types / tests | `ruff`, `ruff format`, `mypy`, `pytest` | ASSUMED, all mature and offline |
| HTTP test client | `httpx2` (**not** `httpx`) | Starlette 1.3.1 deprecates `httpx` for `TestClient`; `T-004` |
| Database access style | **Synchronous** SQLAlchemy + psycopg | The worker is a synchronous job loop (§7.2); pilot volume does not justify an async stack. Reversible per module; `T-004` |
| Frontend | Next.js (Stage 2 only) | spec §18.1 (DECIDED) |
| CI | GitHub Actions | ASSUMED; repo already has a GitHub remote |
| Layout | `backend/` (package `app/`, 13 modules per §18.2), `frontend/`, `docs/` (spec lives here), `docs/adr/`, `docs/architecture/` | spec §18.2, ADR-002 |
| Verification cwd | `backend/` for all Python commands | convention |

Canonical verification commands (available after `T-002`/`T-006`):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q
```

---

## 3. Stage 1 — Core shadow backend (current stage, fully decomposed)

Stage 1 build scope per spec §19.6: products/claims, accounts/contacts, campaign candidates,
evidence, qualification, drafts, jobs, outbox, audit. Exit gate **G-02**.

### 3.1 Repository foundation

#### T-001 — Make the specification and loop rules repository-local; add `AGENTS.md`
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** none
- **Spec:** §0 (instructions for future LLMs), §0.3 (source hierarchy), §23
- **Objective:** Make the authoritative specification and the loop's operating rules repository-local so no future invocation depends on a file outside the repository.
- **Scope (in):** The v0.3 specification present in the repository at a recorded, hash-verified path. A root `AGENTS.md` pointing to `process.md`, `tasks.md`, and the spec, recording the spec's version/size/SHA-256 and the SUPERSEDED status of v0.2, and restating the hard safety rules (synthetic data only, no external effects, no credentials, application owns workflow, dashboard is the approval authority). `README.md` with a project description, the gated-outreach warning, and document links. `tasks.md` header updated to the repo-local spec path.
- **Scope (out):** Any edit to the specification text. Any application code.
- **Scope reconciliation (2026-07-27):** The original scope said "copy the spec to `docs/spec/`". Before this run the user moved the file from `C:\Users\Cody\Downloads\` to `docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md` (same 92,997 bytes, same mtime `2026-07-27 02:27:19`; the Downloads path no longer exists). Per `process.md` §4, user work is preserved: the user's location is now canonical, no `docs/spec/` subdirectory was created, and no duplicate copy was vendored. Provenance was recorded in `AGENTS.md` rather than a separate `docs/spec/README.md` — one fewer file, same information.
- **Acceptance criteria (as met):**
  1. ✅ The v0.3 spec is repo-local at `docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md`, unmodified (92,997 bytes, SHA-256 `E571FC36…C57D9A`, header still "Version: 0.3 / 2026-07-27").
  2. ✅ `AGENTS.md` records the path, version, size, SHA-256, and the SUPERSEDED status of v0.2, which is confirmed absent from the repository.
  3. ✅ Root `AGENTS.md` exists and names `process.md` as the mandatory protocol.
  4. ✅ `tasks.md` header "Specification location" row now points at the repo-local path with its hash.
- **Verification:** `Get-FileHash -Algorithm SHA256 docs\MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md` → `E571FC36420FEB7786AB2C984D24FDF0E100E89C6974E80F56C5D66173C57D9A`; recursive search confirms exactly one spec copy in the repository and no v0.2; `git status --porcelain` → only `?? AGENTS.md`, `?? docs/`, `?? process.md`, `?? tasks.md`, ` M README.md`; markdown link targets resolved; no code, no dependency, no network call, no external effect.
- **Files:** `AGENTS.md` (new), `README.md` (modified), `tasks.md` (modified). Specification file untouched.
- **Blocker / Q:** none
- **Completion evidence:** SHA-256 above matches the file the user placed; `AGENTS.md` (13 hard rules + conflict order + layout + canonical verification command); `README.md` (gated-outreach warning + document index); the four header/scope edits in this file.

#### T-002 — Python project scaffold and quality tooling
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-001
- **Spec:** §18.1, §18.2
- **Objective:** A `backend/` Python project that lints, type-checks, and runs an empty test suite cleanly.
- **Scope (in):** `backend/pyproject.toml` (project metadata, deps: fastapi, pydantic, pydantic-settings, sqlalchemy, alembic, psycopg, structlog; dev deps: pytest, pytest-asyncio, ruff, mypy), `uv.lock`, ruff/mypy configuration (strict-ish mypy on `app`), `backend/tests/test_smoke.py`, root `.gitignore`, `.editorconfig`.
- **Scope (out):** Any domain model, any database connection, Docker, CI.
- **Acceptance criteria (as met):**
  1. ✅ `uv sync --all-groups` resolved and wrote `backend/uv.lock` (82,844 bytes, tracked — confirmed not git-ignored).
  2. ✅ `ruff check` / `ruff format --check` / `mypy app` / `pytest -q` all pass (output below).
  3. ✅ `.gitignore` ignores `.venv/`, `__pycache__/`, `.env`, `.env.*`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `node_modules/`, `.next/`, build output — each verified by `git check-ignore -q` exit code — while `.env.example`, `uv.lock`, and `pyproject.toml` stay trackable.
- **Verification (2026-07-27, from `backend/`):**
  - `uv run python --version` → `Python 3.12.11` (matches the `>=3.12,<3.13` pin)
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `2 files already formatted`
  - `uv run mypy app` → `Success: no issues found in 1 source file` (mypy `strict = true`)
  - `uv run pytest -q` → `2 passed in 10.26s`
  - `git check-ignore -q` matrix → 8/8 ignore targets ignored, 3/3 keep-trackable targets tracked
  - `git add -A --dry-run` → adds only the intended 11 paths; no `.venv`, cache, or lock-adjacent noise
- **Resolved versions pinned by the lock:** ruff 0.16.0, mypy 2.3.0, pytest 9.1.1, pytest-asyncio 1.4.0, sqlalchemy 2.0.51, pydantic 2.13.4, pydantic-settings 2.14.2, alembic (+ mako) 1.14-line, psycopg 3.3.4 (binary), structlog 26.1.0, uvicorn 0.51.0, starlette 1.3.1. All at or above the declared floors.
- **Notes:** `[tool.uv] package = false` — the backend is not a distributable, so no build backend is configured; `pytest` puts `backend/` on `sys.path` via `pythonpath = ["."]`. `filterwarnings = ["error"]` makes deprecation warnings fail the suite early. The smoke test guards the two real failure modes on this machine: wrong interpreter (3.12 vs 3.14 both installed) and `app` becoming unimportable.
- **Files:** `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/__init__.py`, `backend/tests/test_smoke.py`, `.gitignore`, `.editorconfig`
- **Blocker / Q:** none
- **Completion evidence:** the five command outputs above; `git status --porcelain` → ` M README.md`, `?? .editorconfig`, `?? .gitignore`, `?? AGENTS.md`, `?? backend/`, `?? docs/`, `?? process.md`, `?? tasks.md`. Network use was limited to PyPI package installation (permitted by `process.md` §6); no other external effect.

#### T-003 — Local development environment (Docker Compose PostgreSQL + configuration)
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27) — **live-container reachability split to `T-134`, see below**
- **Depends on:** T-002
- **Spec:** §18.1, §18.3, §15.5 (secrets separation)
- **Objective:** One command brings up a local PostgreSQL for development and tests, configured only through environment variables.
- **Scope (in):** `docker-compose.yml` with a single `postgres:16` service and a named volume; `.env.example` with `DATABASE_URL`, `APP_ENV`, `SHADOW_MODE=true`, `OUTBOUND_EMAIL_ENABLED=false`, `MODEL_PROVIDER=fake`; `app/core/settings.py` using `pydantic-settings` with fail-closed defaults (shadow mode on, outbound disabled); a short `docs/development.md`.
- **Scope (out):** Any production deployment configuration, any real credential, any managed-service definition.
- **Scope split (2026-07-27):** Acceptance criterion 1 required a *running* container. The Docker CLI and Compose v5.1.4 are installed but the Docker Desktop engine would not reach a ready state on this machine (`npipe:////./pipe/dockerDesktopLinuxEngine` absent; launching Docker Desktop and polling for ~5 minutes did not help — it appears to await interactive sign-in/WSL init). The compose file is **statically validated but never started**. Live reachability moved to `T-134` rather than claimed. Per `process.md` §5, unverifiable is not `DONE`.
- **Acceptance criteria (as met):**
  1. ⏸️ **Moved to `T-134`.** `docker compose config` renders the full service successfully (`postgres:16`, `pgdata` volume, `pg_isready` healthcheck, `5432` published) — proving the file is valid — but no container was started, so reachability is unproven.
  2. ✅ `Settings(_env_file=None)` with the environment cleared yields `shadow_mode=True`, `outbound_email_enabled=False`, `model_provider=FAKE`, `app_env=LOCAL`.
  3. ✅ Six tests in `tests/test_settings.py` cover the three fail-closed defaults, that `.env.example` ships the same safe values, that every declared setting is documented in the template, that no credential-shaped string is present, that an unlisted model provider is rejected, and that an env file can still override.
  4. ✅ No secret committed. `.env` and `.env.*` are git-ignored (verified in `T-002`); `.env.example` carries only throwaway local values and is explicitly labelled as such.
- **Verification (2026-07-27):**
  - `docker compose config` → valid, renders `name: sales-agent`, service `db`, volume `sales-agent_pgdata`
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `5 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 3 source files`
  - `uv run pytest -q` → `8 passed in 1.66s` (2 smoke + 6 settings)
  - `docker version` → engine unreachable, both before and after launching Docker Desktop
- **Notes:** `Settings` resolves the repository-root `.env` from `Path(__file__).parents[3]`, so configuration loads identically from any working directory. `ModelProvider` is a `StrEnum` with a single `FAKE` member, so selecting a real provider is a reviewable code change (`T-050`, gate **G-03**), not a config edit. `protected_namespaces=()` is set solely so the `MODEL_PROVIDER` variable can keep its natural field name.
- **Files:** `docker-compose.yml`, `.env.example`, `backend/app/core/__init__.py`, `backend/app/core/settings.py`, `backend/tests/test_settings.py`, `docs/development.md`
- **Blocker / Q:** none for this task; `T-134` carries the environment blocker.
- **Completion evidence:** the five command outputs above; `git status --porcelain` shows only intended additions. No external effect: no network call beyond the already-completed PyPI install, no container started, no credential.

#### T-134 — Verify the local PostgreSQL container starts and is reachable
- **Stage / Priority:** 1 / P0
- **Status:** `BLOCKED`
- **Depends on:** T-003
- **Spec:** §18.1, §18.3
- **Objective:** Prove the `db` service actually runs and accepts a connection using only `.env.example` values — the acceptance criterion `T-003` could not verify.
- **Scope (in):** Start the service, wait for the healthcheck, connect with `psycopg` using `DATABASE_URL`, run `SELECT 1`, confirm the server major version is 16, and record the output. Add `docs/development.md` troubleshooting notes if the startup path needs them.
- **Scope (out):** Any schema, migration, or ORM model (that is `T-006`). Any managed or remote database.
- **Acceptance criteria:**
  1. `docker compose up -d db` starts the service and the healthcheck reports healthy.
  2. A `psycopg` connection using the `.env.example` `DATABASE_URL` executes `SELECT 1` and reports server version 16.x.
  3. `docker compose down -v && docker compose up -d db` reproduces a clean database.
- **Verification:** `docker compose up -d db`; `docker compose ps` (healthy); `uv run python -c "import psycopg; ..."` round-trip; teardown/recreate cycle.
- **Files:** possibly `docs/development.md` (troubleshooting only); no application code expected.
- **Blocker / Q:** **Environment, not a stakeholder decision.** The Docker Desktop engine is not running on this machine — `npipe:////./pipe/dockerDesktopLinuxEngine` does not exist; Docker CLI and Compose v5.1.4 are installed, and launching `Docker Desktop.exe` plus ~5 minutes of polling did not produce a ready engine (it appears to require interactive sign-in or WSL initialization). **Unblock condition:** the user starts Docker Desktop, completes any sign-in/onboarding, and `docker version` reports a Server version. No `Q-###` applies.
- **Downstream impact:** `T-004` (the `/readyz` 200 case), `T-006` (Alembic migration harness), and every later integration test that needs a migrated database inherit this blocker. Tasks needing no database — `T-005`, `T-008`, `T-010` — remain workable.
- **Completion evidence:** —

#### T-135 — `/readyz` returns 200 against a live database
- **Stage / Priority:** 1 / P0
- **Status:** `BLOCKED`
- **Depends on:** T-004, T-134
- **Spec:** §18.1, §17.5
- **Objective:** Close the half of `T-004` acceptance criterion 2 that needs a running PostgreSQL.
- **Scope (in):** A test that points the app at the live Compose database and asserts `GET /readyz` → `200` with `status=ready`, `database=ok`. Mark it so it skips cleanly when no database is configured, rather than failing the offline suite.
- **Scope (out):** Any schema or migration (that is `T-006`); any new application code — `check_database` already exists and is exercised by the 503 path.
- **Acceptance criteria:**
  1. With the Compose database running, `GET /readyz` returns 200, `status=ready`, `database=ok`.
  2. With no database configured, the test skips (it does not fail and does not silently pass).
  3. The offline suite result is unchanged when the database is absent.
- **Verification:** `docker compose up -d db`; `uv run pytest -q tests/test_health.py`
- **Files:** `backend/tests/test_health.py`
- **Blocker / Q:** Inherits `T-134` — the Docker engine is unreachable on this machine. **Unblock condition:** `docker version` reports a Server version and `docker compose up -d db` reports healthy. No `Q-###` applies.
- **Completion evidence:** —

#### T-004 — FastAPI application factory, structured logging, health endpoint
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27) — **`/readyz` 200-with-database split to `T-135`**
- **Depends on:** T-003
- **Spec:** §18.1, §17.5 (observability fields)
- **Objective:** An API process that starts, logs structurally with correlation IDs, and reports health.
- **Scope (in):** `app/main.py` application factory; request-ID middleware; `structlog` JSON logging configured to include request/correlation ID and app version; `GET /healthz` (liveness) and `GET /readyz` (database round-trip); OpenAPI enabled.
- **Scope (out):** Authentication, any domain route, metrics backends, error-tracking vendors.
- **Scope split (2026-07-27):** The Docker engine is still unreachable (`T-134`), so the *"200 with a database"* half of acceptance criterion 2 could not be executed. It is carried by **`T-135`**, not claimed here. The 503 half is fully covered against a guaranteed-closed port.
- **Acceptance criteria (as met):**
  1. ✅ `GET /healthz` returns `200 {"status":"ok","version":"0.1.0"}` while pointed at an unreachable database. It touches no dependency by design, so liveness stays true while dependencies are down.
  2. ⚠️ **Half met, half split.** `GET /readyz` returns `503` with `status=not_ready`, `database=unavailable` against a closed port — verified. The 200-with-database case is **`T-135`**.
  3. ✅ Real rendered log output is parsed as JSON in the test: the `request.completed` line carries `correlation_id`, `app_version`, `app_env`, `status_code`, `path`, and `timestamp`. A supplied `X-Request-ID` propagates into the log line and back out in the response header.
- **Verification (2026-07-27, from `backend/`):**
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `11 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 8 source files`
  - `uv run pytest -q` → `23 passed`
  - offline guarantee → grep for `requests|httpx|httpx2|aiohttp|urllib.request|smtplib` imports across `app/**` returns **nothing**; no HTTP or SMTP client exists in application code
- **Security decisions made here (each test-covered):**
  - An inbound `X-Request-ID` is untrusted input (§15.4). Only `[A-Za-z0-9._-]{1,128}` is accepted; newline (log forging), whitespace, over-length, empty, JSON-shaped, and path-traversal payloads are all replaced with a generated UUID — six parametrized cases.
  - `/readyz` reports **only the exception type** on failure, never the driver message: a test asserts the user, password, host, and database name from the connection string never appear in the response body.
  - `/readyz` surfaces `shadow_mode` so an operator can see the safety posture without reading configuration.
- **Notes:**
  - **Sync SQLAlchemy, not async.** The worker is a synchronous job loop (§7.2) and pilot volume does not justify an async stack. Recorded in §2 of this file.
  - `app/db/session.py` was created here (engine registry + `check_database`) because readiness needs a connection. `T-006` extends this file rather than creating it — its entry has been annotated.
  - Engines are cached per URL in a lock-guarded dict rather than `lru_cache`, so shutdown can iterate and dispose them; the lock matters because FastAPI runs sync endpoints in a threadpool.
  - **`httpx` → `httpx2`.** Starlette 1.3.1 deprecates `httpx` for `TestClient`; with `filterwarnings = ["error"]` (ADR-018) this surfaced immediately as a collection error rather than silently later. Dev dependency is `httpx2 2.9.1`. This is ADR-018's predicted trade-off behaving as intended.
- **Files:** `backend/app/main.py`, `backend/app/core/logging.py`, `backend/app/core/middleware.py`, `backend/app/db/__init__.py`, `backend/app/db/session.py`, `backend/app/__init__.py` (added `APP_VERSION`), `backend/tests/test_health.py`, `backend/pyproject.toml` + `uv.lock` (httpx2)
- **Blocker / Q:** none for this task; `T-135` carries the database-dependent half.
- **Completion evidence:** the five verification results above. No external effect: no container, no outbound request, no credential; network use limited to PyPI installation of `httpx2`.

#### T-005 — Backend module skeleton with enforced boundaries
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-004
- **Spec:** §18.2 (thirteen modules), §5.1 (component ownership)
- **Objective:** Create the thirteen module packages from §18.2 with a documented, test-enforced dependency direction.
- **Scope (in):** Packages `identity`, `products_and_claims`, `campaigns`, `prospects`, `research_and_evidence`, `qualification`, `drafts_and_approvals`, `outreach_and_replies`, `jobs_and_outbox`, `crm`, `messaging`, `model_gateway`, `audit_and_operations`, each with `__init__.py` and a one-paragraph module docstring naming what it owns and must not own. A `tests/test_module_boundaries.py` that fails on forbidden imports (e.g. `model_gateway` importing `drafts_and_approvals`; any module importing `crm`/`messaging` internals directly). `docs/architecture/modules.md` documenting the allowed direction.
- **Scope (out):** Any behavior inside the modules.
- **Acceptance criteria (as met):**
  1. ✅ All thirteen packages exist. Each docstring names what it owns, what it must not own, and cites specification sections — asserted by a test, not by inspection.
  2. ✅ The boundary suite passes (10 tests) **and was demonstrated to fail on a real violation**: a temporary `app/model_gateway/_tmp_violation.py` importing `app.drafts_and_approvals` produced `model_gateway must not import drafts_and_approvals — the LLM adapter must not own eligibility, approval, suppression, or execution (§5.1)`; the file was removed and the suite returned to green. Four further self-tests feed synthetic sources through the same functions so the checker can never become vacuous.
  3. ✅ `docs/architecture/modules.md` carries a generated enforced-rules block, and `test_documentation_matches_the_enforced_rules` fails if it drifts from `FORBIDDEN`.
- **Verification (2026-07-27, from `backend/`):**
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `25 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 21 source files`
  - `uv run pytest -q` → `33 passed`
  - negative control → injected violation produced `1 failed, 9 passed`; after removal `10 passed`
- **Rules enforced (each transcribed from a specification clause, not invented layering):**
  - `core`, `db` → no domain module (foundation stays foundation, §18.2)
  - `model_gateway` → no domain module (§5.1: the LLM adapter must not own eligibility, approval, suppression, or execution). Structural rather than advisory: it *cannot reach* the rules it may not decide.
  - `jobs_and_outbox` → no domain module (§17.1: generic mechanism; domain modules register handlers and recheck §11.4 themselves)
  - `messaging` → no domain module except `identity` (ADR-006: not an approval authority, not a workflow dependency; needs only channel-identity mapping per §15.2)
  - `crm` → `prospects` only (§5.1: must not own model runs, evidence, approvals, or job state)
  - nothing imports `main`; no cycles between packages (checked separately — individually legal edges can still close a loop)
- **Interpretation recorded (not a divergence):** §5.1 says the LLM *adapter* must not own budgets, while `T-050` puts budget enforcement in the **gateway**. The gateway is deterministic application logic that runs before any provider adapter is invoked. Documented in `docs/architecture/modules.md` and `docs/reconciliation.md` so a later cycle does not "fix" it.
- **Files:** thirteen `backend/app/<module>/__init__.py`, `backend/tests/test_module_boundaries.py`, `docs/architecture/modules.md`
- **Blocker / Q:** none
- **Completion evidence:** the five verification results above. Structure and documentation only — no behavior, no dependency, no network call, no external effect.

#### T-006 — Alembic wiring and migration verification harness
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-003
- **Spec:** §18.1, §23 (migrations are the machine-readable source of truth)
- **Objective:** Migrations are the only way the schema changes, and every run can prove head applies cleanly to an empty database.
- **Pre-existing file note (2026-07-27):** `backend/app/db/session.py` already exists — `T-004` created it with the per-URL engine registry, `check_database`, and `dispose_engines`. **Extend it; do not recreate it.** `app/db/base.py`, the Alembic environment, and the migrated-database fixture are still this task's work. Also inherits the `T-134` Docker blocker.
- **Scope (in):** Alembic environment reading `DATABASE_URL`; naming convention for constraints/indexes; declarative base and `TimestampMixin`; an initial empty revision; a pytest fixture that creates a throwaway database, runs `alembic upgrade head`, and yields a session; a `tests/test_migrations.py` asserting `upgrade head` then `downgrade base` succeeds and that no model is missing a migration (`alembic check`).
- **Scope (out):** Any domain table.
- **Acceptance criteria:**
  1. `uv run alembic upgrade head` and `uv run alembic downgrade base` both succeed on an empty database.
  2. `uv run alembic check` reports no pending model changes.
  3. Integration tests obtain a migrated database through the fixture, not `create_all`.
- **Verification:** `uv run alembic upgrade head`; `uv run alembic check`; `uv run pytest -q tests/test_migrations.py`
- **Files:** `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/*`, `backend/app/db/base.py`, `backend/app/db/session.py`, `backend/tests/conftest.py`, `backend/tests/test_migrations.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-007 — CI pipeline
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-006
- **Spec:** §18.1 (coordinated release), §19.2
- **Objective:** Every push runs the same checks the loop runs locally, including migrations against a real PostgreSQL service.
- **Scope (in):** `.github/workflows/ci.yml` with a `postgres:16` service running lint, format check, mypy, pytest, `alembic upgrade head`, and `alembic check`. Pinned action versions. No deployment step, no secrets, no publishing.
- **Scope (out):** Deployment, image publishing, environment promotion, any workflow with repository write permissions.
- **Acceptance criteria:**
  1. The workflow file is valid and mirrors the canonical command list in §2 of this file.
  2. `permissions:` is set to `contents: read`.
  3. No workflow step can perform an external write or requires a secret.
- **Verification:** local equivalence run of every workflow step; YAML parse check.
- **Files:** `.github/workflows/ci.yml`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-008 — Repository ADR log and specification-reconciliation register
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-001
- **Spec:** §16 (ADR-001…ADR-017), §0.2, §23
- **Objective:** Give the loop a repo-local place to record implementation decisions and every specification-versus-implementation divergence, without editing the specification.
- **Scope (in):** `docs/adr/README.md` indexing spec ADR-001…ADR-017 as inherited and binding; `docs/adr/ADR-018-toolchain-defaults.md` recording the §2 toolchain defaults with rejected alternatives; `docs/reconciliation.md` with a table (`ID | date | spec section | implemented behavior | divergence | resolution task ID`), seeded with the two known items **R-001** and **R-002** below.
- **Scope (out):** Changing any inherited ADR; editing the specification.
- **Acceptance criteria (as met):**
  1. ✅ All seventeen inherited ADRs (ADR-001…ADR-017) are indexed with status and a one-line decision summary, verified programmatically as 17/17 present. The index deliberately **points at** spec §16 rather than restating it, so the two cannot drift.
  2. ✅ `docs/reconciliation.md` carries the R-001 and R-002 divergence and resolution text verbatim from §7 of this file (six ASCII-safe substring probes matched in both files).
  3. ✅ The only local ADR file is `ADR-018-toolchain-defaults.md`; a numbering check confirms no local file reuses 001–017, and `docs/adr/README.md` states the never-reuse/never-renumber rule.
- **Verification (2026-07-27):**
  - inherited-ADR index completeness → `17/17 indexed, missing: none`
  - local ADR numbering → `ADR-018-toolchain-defaults.md -> ok` (≥ 018)
  - verbatim R-001/R-002 carry-over → 6/6 probes `tasks=True recon=True`
  - link targets (`adr/README.md`, `ADR-018`, `reconciliation.md`, spec, `development.md`) → all resolve
  - backend unaffected → `ruff check` `All checks passed!`; `mypy app` `Success: no issues found in 3 source files`; `pytest -q` `8 passed`
- **Notes:** `ADR-018` records the discretionary choices §18.1 left open (Python 3.12 pin, uv, ruff, mypy strict, pytest with `filterwarnings=["error"]`, no build backend), each with rejected alternatives and an explicit revisit trigger. Pre-commit hooks are recorded as *deferred, not rejected*. `docs/reconciliation.md` also lists four "not divergences" (single-member `ModelProvider`, absent CRM adapter, absent messaging/OpenClaw, spec file location) so they are not re-opened as findings later.
- **Files:** `docs/adr/README.md`, `docs/adr/ADR-018-toolchain-defaults.md`, `docs/reconciliation.md`
- **Blocker / Q:** none
- **Completion evidence:** the five verification results above. Documentation only — no code, no dependency, no network call, no external effect.

#### T-009 — Record stakeholder acceptance of the v0.3 architecture contract (Stage 0 exit evidence)
- **Stage / Priority:** 0 / P2
- **Status:** `BLOCKED`
- **Depends on:** T-001
- **Spec:** §19.6 Stage 0 exit gate, §24 item 1
- **Objective:** Store written evidence that Matrix Power stakeholders accepted that the application owns workflow, the dashboard owns approval, WhatsApp/iMessage is complementary, OpenClaw is optional and isolated, and only one campaign goes live first.
- **Scope (in):** A dated `docs/decisions/architecture-contract-acceptance.md` capturing who accepted what, when, and in what forum.
- **Scope (out):** Inventing, paraphrasing, or inferring stakeholder acceptance. Engineering work does **not** wait on this task.
- **Acceptance criteria:** The file records a real, user-supplied acceptance record with names, roles, and date, or the task remains `BLOCKED`.
- **Verification:** user confirmation in the loop transcript.
- **Files:** `docs/decisions/architecture-contract-acceptance.md`
- **Blocker / Q:** Stakeholder authority. Related: `Q-005`, `Q-025`. The specification header already declares v0.3 "Approved architecture for buildout and shadow deployment", which is why Stage 1 engineering proceeds; this task only records the underlying human decision.
- **Completion evidence:** —

### 3.2 Schema, state model, and domain core

#### T-010 — Independent lifecycle state machines (pure domain, no database)
- **Stage / Priority:** 1 / P0
- **Status:** `READY`
- **Depends on:** T-005
- **Spec:** §8.2, ADR-015, §19.2 (allowed/rejected transitions)
- **Objective:** Encode the five independent lifecycles as separate enums plus explicit allowed-transition tables, with a single guard function that raises on any illegal transition.
- **Scope (in):** `app/core/lifecycles.py` defining `CampaignCandidateState`, `MessageRevisionState`, `ApprovalState`, `OutreachThreadState`, `JobState` exactly as spec §8.2 lists them; per-lifecycle `ALLOWED_TRANSITIONS` mappings; `assert_transition(current, target)`; a terminal-state helper. Exhaustive tests over the full cross product asserting every allowed transition passes and every other pair raises.
- **Scope (out):** Any ORM model, any persistence, any cross-entity invariant (see T-024). **No global workflow enum** (rejected, spec §21.2).
- **Acceptance criteria:**
  1. Five separate enums exist; no combined state enum exists anywhere in the codebase.
  2. Cross-product transition tests cover 100% of pairs per lifecycle.
  3. `assert_transition` raises a typed domain error naming both states.
- **Verification:** `uv run pytest -q tests/test_lifecycles.py`; `uv run mypy app`
- **Files:** `backend/app/core/lifecycles.py`, `backend/tests/test_lifecycles.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-011 — Append-only audit event model and service
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-006, T-010
- **Spec:** §3.5 (every consequential action has actor, revision, policy decision, audit event), §14.1, §17.5
- **Objective:** One audit primitive every later task writes through, recording actor, action, entity, versions, and correlation ID, with no update or delete path.
- **Scope (in):** `AuditEvent` table and migration (id, occurred_at, correlation_id, actor_type, actor_id, action, entity_type, entity_id, from_state, to_state, policy_decision, payload JSONB, app/prompt/schema/policy version columns); `record_audit_event()` requiring an explicit actor; a database-level guard against UPDATE/DELETE (revoke or trigger); tests asserting append-only behavior and required-actor enforcement.
- **Scope (out):** Log shipping, dashboards, metrics exporters.
- **Acceptance criteria:**
  1. Writing an audit event without an actor fails.
  2. Attempting UPDATE or DELETE on `audit_event` fails at the database level, proven by a test.
  3. Correlation ID from the request/job context is persisted.
- **Verification:** `uv run pytest -q tests/test_audit.py`; `uv run alembic upgrade head`
- **Files:** `backend/app/audit_and_operations/*`, `backend/alembic/versions/*`, `backend/tests/test_audit.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-012 — Identity and access tables (no authentication yet)
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-011
- **Spec:** §14.1, §12.1 (six roles), §12.2
- **Objective:** Persist `User`, `Role`, `UserRole`, `ServiceIdentity`, `ChannelIdentity` with the six roles from §12.1 seeded, so later authorization checks have a subject model.
- **Scope (in):** Tables, migration, role seed (product/claim owner, campaign/sales owner, operator/reviewer, reply owner, system administrator, viewer), separation of human and service identities, a `ChannelIdentity` that must map to an existing user.
- **Scope (out):** OIDC, sessions, password authentication (explicitly rejected, §12.2), any real user roster (`Q-026`).
- **Acceptance criteria:**
  1. The six roles are seeded by migration and asserted by test.
  2. A `ChannelIdentity` row cannot exist without a `User`; a test proves the constraint.
  3. Service identities cannot hold human-only roles; enforced and tested.
- **Verification:** `uv run pytest -q tests/test_identity.py`; `uv run alembic check`
- **Files:** `backend/app/identity/*`, `backend/alembic/versions/*`, `backend/tests/test_identity.py`
- **Blocker / Q:** Real roster/approvers deferred to `Q-005`, `Q-026`; synthetic users only.
- **Completion evidence:** —

#### T-013 — Product, product status version, and source document
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-011
- **Spec:** §2.3, §14.1, §14.4, GP-12
- **Objective:** Versioned product readiness with the five readiness categories from §2.3, plus provenance to a source document.
- **Scope (in):** `Product`; `ProductStatusVersion` (readiness_category enum: `sellable_now`, `evaluation_or_pilot`, `in_development`, `strategic_or_roadmap`, `paused_or_unavailable`; source_document_id, source_date, approved_by, approved_at, effective_from, expires_or_review_by, supersedes_version); `SourceDocument`; a repository function returning the *current effective* status for a product at a timestamp; tests for supersession and expiry.
- **Scope (out):** Real Matrix Power product specifications (`Q-021`, `Q-022`) — synthetic fixture products only. Any claim text (T-014).
- **Acceptance criteria:**
  1. Exactly one status version is effective per product per instant; overlap is rejected.
  2. An expired status version is never returned as current; test-proven.
  3. Readiness category is a database enum, not free text.
- **Verification:** `uv run pytest -q tests/test_product_status.py`
- **Files:** `backend/app/products_and_claims/*`, `backend/alembic/versions/*`, `backend/tests/test_product_status.py`
- **Blocker / Q:** `Q-021`, `Q-022`, `Q-025` — synthetic values only; no real specification may be entered.
- **Completion evidence:** —

#### T-014 — Approved claims and approved claim sets with fail-closed validity
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-013
- **Spec:** §10.5, §14.4, §15.7, GP-12
- **Objective:** A versioned claim store where exact wording or paraphrase constraints, approver, effective window, and allowed campaigns are mandatory, and expired or superseded claims fail closed.
- **Scope (in):** `ApprovedClaim`, `ApprovedClaimSet` (+ set version), claim↔campaign allow-list, `is_valid_at(timestamp)` semantics, `get_valid_claim_set(product, campaign, at)` that raises rather than returning stale claims; tests for expiry, supersession, campaign scoping.
- **Scope (out):** Real approved Matrix Power claims (`Q-017`) — synthetic claims marked `SYNTHETIC` only. Draft rendering (T-054), invalidation jobs (T-056).
- **Acceptance criteria:**
  1. A claim without approver, effective_from, and review/expiry date cannot be inserted.
  2. Requesting a claim set containing an expired or superseded claim raises; no silent filtering.
  3. A claim not allowed for a campaign is never returned for that campaign.
  4. Every fixture claim carries an explicit synthetic marker.
- **Verification:** `uv run pytest -q tests/test_approved_claims.py`
- **Files:** `backend/app/products_and_claims/*`, `backend/alembic/versions/*`, `backend/tests/test_approved_claims.py`
- **Blocker / Q:** `Q-017`, `Q-016`, `Q-025` — no real claim may be entered until an approved versioned claim set exists.
- **Completion evidence:** —

#### T-015 — Campaign, target segment, and campaign policy version
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-013
- **Spec:** §8.1, §8.6, §14.1, ADR-012
- **Objective:** Two campaign configurations (sodium battery, DC fast charging) with versioned policy: ICP rules, exclusions, geography, volume limits, active/paused flag.
- **Scope (in):** `Campaign`, `TargetSegment`, `CampaignPolicyVersion` (JSONB typed by a Pydantic policy model: allowed geographies, exclusions, required readiness categories, daily/total volume caps, suppression scope); pause flag; current-policy resolution; tests that policy is versioned and immutable once referenced.
- **Scope (out):** Real ICP definitions (`Q-002`) — synthetic placeholders only. Eligibility evaluation (T-045).
- **Acceptance criteria:**
  1. A campaign always resolves to exactly one current policy version.
  2. A referenced policy version cannot be mutated; a test proves it.
  3. Default geography is U.S.-only and default volume caps are conservative (spec §15.8, §19.6 Stage 6).
- **Verification:** `uv run pytest -q tests/test_campaigns.py`
- **Files:** `backend/app/campaigns/*`, `backend/alembic/versions/*`, `backend/tests/test_campaigns.py`
- **Blocker / Q:** `Q-002`, `Q-013`, `Q-014` — synthetic ICP and conservative caps until confirmed.
- **Completion evidence:** —

#### T-016 — Account, contact, contact point, and CRM mapping
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-011
- **Spec:** §14.1, §13.5 (provider-independent IDs and external-ID mapping)
- **Objective:** Prospect identity tables with normalized keys and a provider-neutral external-ID mapping table.
- **Scope (in):** `Account` (normalized domain, name, country), `Contact`, `ContactPoint` (case-normalized email, type, verification state), `CRMMapping` (internal_id, provider, external_id, unique per provider); normalization helpers; tests for case/whitespace normalization and mapping uniqueness.
- **Scope (out):** Any CRM call (T-093/T-094), deduplication logic (T-043), enrichment.
- **Acceptance criteria:**
  1. Emails are stored case-normalized; a test proves `A@X.com` and `a@x.com` collide.
  2. Account domains are normalized (lowercase, no scheme, no `www.`).
  3. `CRMMapping` enforces one external ID per (provider, internal record).
- **Verification:** `uv run pytest -q tests/test_prospects.py`
- **Files:** `backend/app/prospects/*`, `backend/alembic/versions/*`, `backend/tests/test_prospects.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-017 — Suppression store with precedence and survival rules
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-016
- **Spec:** §15.6, §3.5 (zero sends to suppressed recipients), §19.2
- **Objective:** Suppression that outranks campaign configuration, survives contact deletion, and applies immediately at person, email, domain, and account scope.
- **Scope (in):** `Suppression` (normalized identity, scope enum, source, reason, effective_at, jurisdiction/policy context); no foreign key that would cascade-delete it; `is_suppressed(identity, scope_context)` checked by scope precedence; tests for global-unsubscribe override, contact deletion survival, immediate effect.
- **Scope (out):** Send-time enforcement inside the outbox transaction (T-035, T-067), unsubscribe intake (T-102).
- **Acceptance criteria:**
  1. Deleting a contact leaves its suppression record intact; test-proven.
  2. A domain-scope suppression suppresses a new contact at that domain with no additional write.
  3. Suppression cannot be overridden by campaign policy; a test asserts the precedence order.
- **Verification:** `uv run pytest -q tests/test_suppression.py`
- **Files:** `backend/app/prospects/suppression*`, `backend/alembic/versions/*`, `backend/tests/test_suppression.py`
- **Blocker / Q:** `Q-019` (retention) — retention configurable, default conservative.
- **Completion evidence:** —

#### T-018 — Campaign candidate entity and lifecycle enforcement
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-015, T-016, T-010
- **Spec:** §8.1 (`campaign_id + account_id + contact_id`), §8.2, §14.2
- **Objective:** Campaign membership as the unit of qualification, with a uniqueness constraint on the effective identity and transitions guarded by T-010.
- **Scope (in):** `CampaignCandidate` table; unique constraint on `(campaign_id, account_id, contact_id)`; state column using `CampaignCandidateState`; a service that transitions state through `assert_transition` and writes an audit event; tests that the same account/contact yields two independent candidates across two campaigns with independent states.
- **Scope (out):** Eligibility rules (T-045), qualification (T-053), review (Stage 2).
- **Acceptance criteria:**
  1. Duplicate `(campaign, account, contact)` insertion fails at the database level.
  2. One account/contact in two campaigns has two candidates whose states move independently; test-proven.
  3. Every state change writes an audit event with from_state and to_state.
- **Verification:** `uv run pytest -q tests/test_campaign_candidate.py`
- **Files:** `backend/app/campaigns/candidate*`, `backend/alembic/versions/*`, `backend/tests/test_campaign_candidate.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-019 — Evidence snapshot with full provenance
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-018
- **Spec:** §14.3 (exact field list), §9.5, GP-02
- **Objective:** Store the minimum evidence needed for explainability with every provenance field the specification requires.
- **Scope (in):** `EvidenceSnapshot` with all §14.3 fields (source_type, source_provider_id, source_url_if_permitted, retrieved_at, supporting_excerpt_or_fact, content_hash, extraction_field_or_span, extraction_method, source_quality, license_and_retention_class, contains_personal_or_confidential_data, expires_or_refresh_by); an excerpt length cap enforcing "minimum evidence, not whole documents"; validity-at-timestamp helper; tests.
- **Scope (out):** Any real network fetch (T-046 stays offline; SSRF-protected fetching is Stage 3+ and gated), evidence UI (Stage 2).
- **Acceptance criteria:**
  1. Inserting a snapshot missing any required provenance field fails.
  2. Excerpts exceeding the configured cap are rejected, not silently truncated.
  3. Expired evidence is excluded from "current evidence" queries; test-proven.
- **Verification:** `uv run pytest -q tests/test_evidence.py`
- **Files:** `backend/app/research_and_evidence/*`, `backend/alembic/versions/*`, `backend/tests/test_evidence.py`
- **Blocker / Q:** `Q-019` retention class values configurable.
- **Completion evidence:** —

#### T-020 — Message draft and immutable message revision
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-018, T-010
- **Spec:** §8.2, §10.5, §14.2, §11.4 (`message_revision_id`)
- **Objective:** Drafts that accumulate strictly immutable revisions, each hashed and each carrying its claim and evidence references.
- **Scope (in):** `MessageDraft`; `MessageRevision` (revision_number, recipient contact_point_id, subject, body, referenced approved_claim_ids, referenced evidence_ids, content_hash, state per `MessageRevisionState`, created_by); database-level immutability (revoke UPDATE or trigger); an "edit creates a new revision and supersedes the prior" service; tests.
- **Scope (out):** Generation of body text (T-054), validation rules (T-055), approvals (T-021).
- **Acceptance criteria:**
  1. UPDATE on `message_revision` content columns fails at the database level; test-proven.
  2. Editing produces revision N+1 and marks revision N `superseded`.
  3. `content_hash` covers recipient, subject, body, claim IDs, and evidence IDs; a test proves any change alters the hash.
- **Verification:** `uv run pytest -q tests/test_message_revision.py`
- **Files:** `backend/app/drafts_and_approvals/*`, `backend/alembic/versions/*`, `backend/tests/test_message_revision.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-021 — Approval entity with scope, expiry, revocation, and supersession
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-020
- **Spec:** §8.2, §8.4, §11.3, §11.4, ADR-008, §19.2
- **Objective:** An approval that binds exactly one approver, one recipient, one immutable revision, and one policy context, and that expires, revokes, and invalidates correctly.
- **Scope (in):** `Approval` (approver user_id, entity_type/entity_id, message_revision_id, recipient contact_point_id, approval_expires_at, product_status_version, approved_claim_set_version, record_versions, state per `ApprovalState`); services to approve, expire, revoke; invalidation when recipient, content, product status, or claim version changes; tests for each invalidation trigger from §8.4.
- **Scope (out):** The dashboard approval endpoint (T-067), the send command (T-035).
- **Acceptance criteria:**
  1. An approval references exactly one immutable revision; a nullable or multi-revision approval is impossible.
  2. Each §8.4 change (recipient, subject, body, personalization fact, product status, claim version) invalidates the approval; six tests, one per trigger.
  3. An expired or revoked approval can never transition back to `approved`.
- **Verification:** `uv run pytest -q tests/test_approval.py`
- **Files:** `backend/app/drafts_and_approvals/approval*`, `backend/alembic/versions/*`, `backend/tests/test_approval.py`
- **Blocker / Q:** `Q-005` for real approver authority; synthetic users in tests.
- **Completion evidence:** —

#### T-022 — Outreach thread, send command, send attempt, delivery event, interaction
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-021
- **Spec:** §8.2, §11.4 (consequential-action contract), §14.1, ADR-016
- **Objective:** The outreach-side tables, including an immutable send command carrying the full §11.4 field list and an idempotency key.
- **Scope (in):** `OutreachThread` (state per `OutreachThreadState`, includes `delivery_unknown`); `SendCommand` (all §11.4 fields, unique `idempotency_key`, immutable); `SendAttempt`; `DeliveryEvent`; `Interaction`; tests that a duplicate idempotency key is rejected and that `delivery_unknown` is a distinct terminal-pending state.
- **Scope (out):** Any dispatch (T-035), any real email provider (Stage 5).
- **Acceptance criteria:**
  1. `SendCommand` cannot be created without approval_id, message_revision_id, recipient_id, and the version fields from §11.4.
  2. `idempotency_key` is unique; a second insert fails.
  3. `delivery_unknown` exists and does not auto-retry; asserted by a state-machine test.
- **Verification:** `uv run pytest -q tests/test_outreach.py`
- **Files:** `backend/app/outreach_and_replies/*`, `backend/alembic/versions/*`, `backend/tests/test_outreach.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-023 — Versioning tables for prompts, schemas, model configuration, and policy
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-011
- **Spec:** §14.1, §17.5, GP-09
- **Objective:** Persist `PromptVersion`, `SchemaVersion`, `ModelConfigVersion`, `PolicyVersion` so every model run and decision is attributable to exact versions.
- **Scope (in):** Four tables with content hash, effective window, created_by; helper resolving the current version of each; audit/observability fields referencing them; tests for immutability of a referenced version.
- **Scope (out):** Prompt content authoring (T-053, T-054), routing (`DEFERRED`, T-131).
- **Acceptance criteria:**
  1. A version row referenced by a model run cannot be mutated or deleted.
  2. Each version row has a content hash; a test proves hash changes with content.
  3. `ModelConfigVersion` stores provider and model as configuration values, never in business logic (spec §18.4).
- **Verification:** `uv run pytest -q tests/test_versioning.py`
- **Files:** `backend/app/audit_and_operations/versioning*`, `backend/alembic/versions/*`, `backend/tests/test_versioning.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-024 — Cross-entity invariant tests for lifecycle independence
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-018, T-020, T-021, T-022, T-030
- **Spec:** §8.2, ADR-015, §3.5, §19.2
- **Objective:** Prove that candidate, revision, approval, outreach-thread, and job lifecycles are genuinely independent and that safety invariants hold across them.
- **Scope (in):** A dedicated invariant test module asserting: a rejected candidate cannot yield an approved revision; an invalidated approval leaves the revision intact and immutable; a dead job never advances candidate state; an outreach thread cannot leave `not_started` without an approved send command; suppression outranks an approved candidate; no code path mutates two lifecycles in one unguarded step.
- **Scope (out):** New production behavior; this task only adds tests and, if a violation is found, a separately scoped fix task.
- **Acceptance criteria:**
  1. Each of the six invariants above has at least one test.
  2. Any violation discovered is filed as a new task ID rather than fixed opportunistically in this task.
  3. Tests reference spec section numbers in docstrings.
- **Verification:** `uv run pytest -q tests/test_invariants.py`
- **Files:** `backend/tests/test_invariants.py`
- **Blocker / Q:** none
- **Completion evidence:** —

### 3.3 Jobs, outbox, and operational controls

#### T-030 — PostgreSQL job table with `FOR UPDATE SKIP LOCKED` leasing and a worker loop
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-011, T-010
- **Spec:** §17.1, ADR-003, §7.2
- **Objective:** A durable job queue in PostgreSQL with bounded leases and a worker process entry point.
- **Scope (in):** `Job` table (stable id, type, typed JSONB payload validated by a Pydantic registry, priority, attempt_count, next_run_at, lease_expires_at, leased_by, state per `JobState`); `lease_jobs()` using `SELECT ... FOR UPDATE SKIP LOCKED`; a `worker` entry point running the §7.2 cycle; tests including a concurrency test proving two workers never lease the same job.
- **Scope (out):** Retry policy (T-031), lease recovery (T-032), Redis/Temporal (excluded, §18.6).
- **Acceptance criteria:**
  1. Two concurrent leasers over the same queue produce disjoint job sets; test-proven.
  2. Job payloads are schema-validated on enqueue; invalid payloads are rejected before insert.
  3. The worker process starts, leases, executes a no-op job type, and commits state plus audit atomically.
- **Verification:** `uv run pytest -q tests/test_jobs.py`
- **Files:** `backend/app/jobs_and_outbox/*`, `backend/app/worker.py`, `backend/alembic/versions/*`, `backend/tests/test_jobs.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-031 — Per-job-type retry policy, backoff, and dead-letter with human-readable reason
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-030
- **Spec:** §17.1, §7.2
- **Objective:** Explicit retry configuration per job type with exponential backoff plus jitter, and a `dead` state that always records why.
- **Scope (in):** Retry policy declared with each job type (max attempts, base delay, jitter, retryable exception classes); permanent-failure classification; `dead` with `failure_reason`; a "requires human review" outcome distinct from `dead`; tests for backoff progression, permanent-failure short-circuit, and reason presence.
- **Scope (out):** Alerting/notification (Stage 4), dashboard surfacing (T-069).
- **Acceptance criteria:**
  1. A job type without an explicit retry policy fails at registration time.
  2. A permanently failing job reaches `dead` with a non-empty human-readable reason; never silently.
  3. Backoff is deterministic under a seeded jitter source; test-proven.
- **Verification:** `uv run pytest -q tests/test_job_retries.py`
- **Files:** `backend/app/jobs_and_outbox/retry*`, `backend/tests/test_job_retries.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-032 — Lease expiry recovery
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-031
- **Spec:** §17.1, §17.4, §19.5 (worker crash during a job)
- **Objective:** A crashed worker's jobs become safely re-leasable without duplicating committed side effects.
- **Scope (in):** Expired-lease reclaim query; attempt-count increment on reclaim; a simulated crash test (lease, do not commit, expire, reclaim, complete once); a guard that a job whose side effect already committed is not re-executed (recorded outcome check).
- **Scope (out):** Outbox reconciliation (T-035).
- **Acceptance criteria:**
  1. An expired lease is reclaimed exactly once even with concurrent workers.
  2. A simulated crash-then-reclaim run produces exactly one committed effect; test-proven.
  3. Reclaim writes an audit event.
- **Verification:** `uv run pytest -q tests/test_job_recovery.py`
- **Files:** `backend/app/jobs_and_outbox/recovery*`, `backend/tests/test_job_recovery.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-033 — Operational control flags: global pause, campaign pause, shadow mode, outbound disable
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-030, T-015
- **Spec:** §17.6, §17.1 (pause preserves inspectability), §19.6
- **Objective:** Fail-closed operational switches that prevent new consequential work while leaving queued work inspectable.
- **Scope (in):** An `OperationalFlag` store with audit-logged changes; flags for global pause, shadow mode, outbound email disabled, per-campaign pause, per-product/claim-version disable, approval revocation entry point; enforcement checkpoint used by the worker and by any consequential path; tests that a paused campaign blocks new consequential jobs but leaves them visible and that shadow mode blocks every external adapter.
- **Scope (out):** UI (T-069), credential revocation (operations runbook, Stage 5+).
- **Acceptance criteria:**
  1. Default state is: shadow mode ON, outbound email OFF, no campaign live.
  2. With global pause set, no consequential job executes and none are lost; test-proven.
  3. Every flag change writes an audit event with actor.
  4. Shadow mode is checked in the adapter boundary, not only at call sites.
- **Verification:** `uv run pytest -q tests/test_operational_flags.py`
- **Files:** `backend/app/audit_and_operations/flags*`, `backend/alembic/versions/*`, `backend/tests/test_operational_flags.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-034 — Transactional outbox tables and atomic commit helper
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-030, T-022
- **Spec:** §17.2, ADR-016, §11.3 step 4–5
- **Objective:** A single transaction can commit business state, audit event, and outbox event together, so a committed decision is never lost before dispatch.
- **Scope (in):** `OutboxEvent` table (type, payload, state, attempt count, correlation ID, unique idempotency key); a `commit_with_outbox()` helper that refuses to write an outbox event outside an active transaction that also writes state and audit; tests proving atomicity by forcing a rollback.
- **Scope (out):** Dispatch and reconciliation (T-035).
- **Acceptance criteria:**
  1. Rolling back the transaction leaves neither business state nor outbox event; test-proven.
  2. Writing an outbox event without an accompanying audit event fails.
  3. Outbox idempotency key is unique and matches the send command's key when applicable.
- **Verification:** `uv run pytest -q tests/test_outbox.py`
- **Files:** `backend/app/jobs_and_outbox/outbox*`, `backend/alembic/versions/*`, `backend/tests/test_outbox.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-035 — Outbox dispatcher with fake external-effect adapter, reconciliation, and `delivery_unknown`
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-034, T-033, T-017
- **Spec:** §17.2, §17.3, §11.4 (final dispatch rechecks), ADR-016, §3.5
- **Objective:** Effectively-once dispatch semantics proven end to end against a fake adapter, with the full final-check list re-evaluated inside the dispatch transaction.
- **Scope (in):** An `ExternalEffectAdapter` protocol; a `FakeExternalEffectAdapter` that records calls and can simulate success, timeout, ambiguous acceptance, and rate limiting; a dispatcher that, inside the transaction, rechecks every item in §11.4 (approver authority, approval state/expiry, exact recipient and revision, suppression at all configured scopes, sender availability, campaign active status and volume limit, product-status and claim-set versions, record versions, existing result for the idempotency key); ambiguous provider response ⇒ `delivery_unknown` with **no blind retry**; pre-retry reconciliation call; tests for each failure mode and each recheck.
- **Scope (out):** Any real provider (Stage 5, gate **G-07**).
- **Acceptance criteria:**
  1. Each of the nine §11.4 rechecks has a test proving dispatch is refused when it fails.
  2. An ambiguous acceptance yields `delivery_unknown` and zero retries; test-proven.
  3. Replaying the same idempotency key produces exactly one fake effect.
  4. With shadow mode ON the adapter refuses to act at all, even if called; test-proven.
  5. No real network client exists in the dispatch path.
- **Verification:** `uv run pytest -q tests/test_dispatch.py`
- **Files:** `backend/app/jobs_and_outbox/dispatch*`, `backend/app/outreach_and_replies/adapters/fake.py`, `backend/tests/test_dispatch.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-036 — Webhook event intake with signature, timestamp, duplicate, and replay rejection (no live provider)
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-030, T-011
- **Spec:** §15.2, §19.2, §19.4 (forged/replayed webhooks)
- **Objective:** A provider-neutral, idempotent webhook intake path that is secure before any real provider is connected.
- **Scope (in):** `WebhookEvent` table (provider, external_event_id unique, received_at, signature_valid, processing_state); an intake service verifying HMAC signature, timestamp freshness, expected account, and duplicate/replay rejection; a test provider using a local test secret; enqueue-for-processing rather than inline processing; tests for valid, tampered, stale, duplicate, and replayed events.
- **Scope (out):** Any real provider endpoint or secret (Stage 4/5), reply classification (T-103).
- **Acceptance criteria:**
  1. Tampered signature, stale timestamp, duplicate event ID, and replayed event are each rejected with a distinct reason; four tests.
  2. Intake is idempotent: the same event ID twice yields one stored event and one job.
  3. No provider-specific secret is committed; the test secret is generated in the test.
- **Verification:** `uv run pytest -q tests/test_webhooks.py`
- **Files:** `backend/app/messaging/webhooks*` (or `outreach_and_replies/webhooks*`), `backend/alembic/versions/*`, `backend/tests/test_webhooks.py`
- **Blocker / Q:** none
- **Completion evidence:** —

### 3.4 Synthetic fixtures, import, eligibility, and evidence capture

#### T-040 — Synthetic campaign, product, status, and claim fixture seeder
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-014, T-015
- **Spec:** §19.6 Stage 0/1, §24 item 4, GP-06
- **Objective:** One command seeds two clearly synthetic campaigns (sodium battery, DC fast charging) with synthetic products, readiness versions, and approved claim sets, so no real product data is ever needed to develop.
- **Scope (in):** A `seed_synthetic` CLI; fixture data files where every product, claim, and campaign name is prefixed `SYNTHETIC-`; a guard that refuses to seed when `APP_ENV=production`; tests that seeding is idempotent and that every seeded claim is marked synthetic.
- **Scope (out):** Any real Matrix Power product specification, roadmap date, certification target, MOU figure, or pricing (`Q-017`, `Q-021`, `Q-022`) — these must never appear in fixtures.
- **Acceptance criteria:**
  1. Seeding twice produces the same state (idempotent); test-proven.
  2. A test asserts no fixture string contains a real certification, roadmap date, customer name, or pricing figure, and that all names carry the `SYNTHETIC-` prefix.
  3. Seeding is refused when `APP_ENV=production`.
- **Verification:** `uv run python -m app.cli seed_synthetic`; `uv run pytest -q tests/test_fixtures.py`
- **Files:** `backend/app/cli.py`, `backend/app/fixtures/*`, `backend/tests/test_fixtures.py`
- **Blocker / Q:** `Q-021`, `Q-022`, `Q-017` — synthetic values are the deliberate substitute, not a guess at real values.
- **Completion evidence:** —

#### T-041 — Synthetic prospect fixture set
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-040, T-016
- **Spec:** §19.1, GP-06, §15.9 (no real contact data to providers)
- **Objective:** A synthetic account/contact corpus with deliberate edge cases for import, dedup, eligibility, and evidence testing.
- **Scope (in):** A CSV fixture of clearly fake accounts/contacts using reserved example domains (`example.com`, `example.org`) and obviously synthetic names; edge cases: duplicate by email case, duplicate by domain+name, non-U.S. record, suppressed email, missing contact point, unverifiable email, account matching both campaigns.
- **Scope (out):** Any real company, person, or email address; any scraped or exported LinkedIn data.
- **Acceptance criteria:**
  1. Every email domain is an IANA reserved example domain; a test enforces this.
  2. The fixture contains at least the seven edge cases above, each labeled.
  3. No fixture row derives from a real organization or person.
- **Verification:** `uv run pytest -q tests/test_prospect_fixtures.py`
- **Files:** `backend/app/fixtures/prospects.csv`, `backend/tests/test_prospect_fixtures.py`
- **Blocker / Q:** `Q-003` — no provider or LinkedIn data until access and terms are confirmed.
- **Completion evidence:** —

#### T-042 — CSV/manual candidate import with normalization
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-041, T-016
- **Spec:** §9.3 (begin with manual/CSV import), §9.5 (import contract), §8.3 steps 1–2
- **Objective:** An offline import path that turns a CSV into normalized accounts, contacts, and contact points with row-level error reporting.
- **Scope (in):** A typed import schema; `import(record | file)` per §9.5 returning candidates plus per-row rejections; normalization of domain, email, country, role; treat every field as untrusted input; an import batch record for provenance; tests for malformed rows, injection-looking strings, and normalization.
- **Scope (out):** Discovery/`discover(criteria)` against any provider (`Q-003`, gated), refresh from live sources, dedup (T-043).
- **Acceptance criteria:**
  1. A malformed row is reported with row number and reason and does not abort the batch.
  2. Import is idempotent per batch content hash; re-importing the same file creates no duplicates.
  3. A row containing prompt-injection-style text is stored as inert data and never interpreted; test-proven.
- **Verification:** `uv run pytest -q tests/test_import.py`
- **Files:** `backend/app/prospects/import_*`, `backend/tests/test_import.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-043 — Deterministic deduplication against internal records
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-042
- **Spec:** §8.3 step 2, §13.5 rule 2 (CRM check deferred), §19.2 (dedup uniqueness)
- **Objective:** Deterministic, explainable dedup on normalized keys with a recorded match reason, internal-only for now.
- **Scope (in):** Match rules in priority order (exact normalized email; account domain + normalized contact name; account domain + role for account-level dedup) with a recorded `match_reason`; merge policy that never destroys evidence or suppression; tests using the T-041 duplicate edge cases.
- **Scope (out):** CRM-side dedup (gate **G-05**), fuzzy/embedding matching (no vector database, §18.6), enrichment-provider identity resolution.
- **Acceptance criteria:**
  1. Each duplicate edge case in the fixture resolves to one record with a recorded match reason.
  2. Merging preserves all evidence snapshots and every suppression record.
  3. No probabilistic or model-based matching is used.
- **Verification:** `uv run pytest -q tests/test_dedup.py`
- **Files:** `backend/app/prospects/dedup*`, `backend/tests/test_dedup.py`
- **Blocker / Q:** `Q-001` for CRM-side dedup; internal-only until then.
- **Completion evidence:** —

#### T-044 — Campaign membership creation
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-043, T-018
- **Spec:** §8.1, §8.3 step 3
- **Objective:** Create one `CampaignCandidate` per potentially applicable campaign, never a single shared lead record.
- **Scope (in):** A service that, given an account/contact and the active campaigns, creates separate memberships with independent state; explicit handling of the both-campaigns fixture account; audit events per membership; tests.
- **Scope (out):** Eligibility evaluation (T-045), scoring (T-053).
- **Acceptance criteria:**
  1. The dual-relevance fixture account produces exactly two candidates with independent state.
  2. Re-running creates no duplicates (uniqueness from T-018 holds).
  3. Each creation writes an audit event naming the campaign.
- **Verification:** `uv run pytest -q tests/test_membership.py`
- **Files:** `backend/app/campaigns/membership*`, `backend/tests/test_membership.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-045 — Deterministic hard-eligibility rule engine
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-044, T-017, T-013, T-015
- **Spec:** §10.1 stage 1, §8.3 step 4, GP-12
- **Objective:** A purely deterministic gate — geography, campaign exclusions, suppression, product readiness, contactability, existing-relationship conflict, approved source basis, obvious non-fit — that no model output can override.
- **Scope (in):** One rule per check, each returning a structured `EligibilityFailure` (rule ID, reason, evidence/inputs); an evaluator writing failures onto the candidate and transitioning `imported → eligible|ineligible`; a test asserting a model-supplied recommendation cannot flip a failed hard rule; a test per rule using fixture edge cases.
- **Scope (out):** Rubric scoring (T-053), real ICP thresholds (`Q-002`).
- **Acceptance criteria:**
  1. Every rule has a positive and a negative test using the synthetic fixtures.
  2. A candidate failing any hard rule becomes `ineligible` with all failure reasons recorded, not just the first.
  3. A test proves eligibility contains no model call and no nondeterminism.
  4. Non-U.S. and suppressed fixture rows are `ineligible` by default.
- **Verification:** `uv run pytest -q tests/test_eligibility.py`
- **Files:** `backend/app/qualification/eligibility*`, `backend/tests/test_eligibility.py`
- **Blocker / Q:** `Q-002`, `Q-013` — placeholder ICP/geography values, conservative defaults.
- **Completion evidence:** —

#### T-046 — Offline evidence capture service with provenance and retention class
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-045, T-019
- **Spec:** §8.3 steps 5–6, §9.5, §14.3, §15.3, §15.4
- **Objective:** Capture evidence from local fixture sources through a source-adapter contract, with full provenance, and treat all captured text as untrusted.
- **Scope (in):** A `SourceAdapter` protocol (`discover`, `import`, `refresh` per §9.5); a `FixtureSourceAdapter` reading local synthetic documents; an evidence-capture job writing snapshots with all §14.3 fields; content hashing; retention/license classification; personal-data flagging; a test proving injection text in a source document never becomes an instruction.
- **Scope (out):** Any network fetch. SSRF-hardened fetching, real providers, and LinkedIn paths are gated (**G-03**, `Q-003`) and must not be implemented here.
- **Acceptance criteria:**
  1. No HTTP client is imported anywhere in the capture path; a test asserts this.
  2. Every snapshot has a source, retrieval time, content hash, extraction method, and retention class.
  3. `refresh` produces a new snapshot rather than mutating an existing one.
  4. Injection-laden fixture content is stored as data and does not alter behavior; test-proven.
- **Verification:** `uv run pytest -q tests/test_evidence_capture.py`
- **Files:** `backend/app/research_and_evidence/adapters/fixture.py`, `backend/app/research_and_evidence/capture*`, `backend/tests/test_evidence_capture.py`
- **Blocker / Q:** `Q-003`, `Q-016`, `Q-019`
- **Completion evidence:** —

### 3.5 Model gateway, qualification, drafting, and the shadow slice

#### T-050 — Provider-neutral model gateway with budgets and limits
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-023, T-033
- **Spec:** §18.4, GP-04, GP-14, ADR-013, ADR-017, §18.7 (budgets)
- **Objective:** One typed gateway interface for all model work, with provider and model in configuration only, and per-task/daily/campaign budget enforcement.
- **Scope (in):** A `ModelGateway` protocol (`run_task(task_name, prompt_version, schema_version, inputs) -> validated result`); a `ModelRun` record capturing prompt/schema/model-config/policy versions, token counts, cost, latency, outcome; budget enforcement that refuses a call over budget; provider registry resolving `MODEL_PROVIDER` from settings with `fake` as the default; a hard guard that no real provider client can be constructed unless gate **G-03** is unlocked via explicit configuration.
- **Scope (out):** Any real provider SDK call, any API key, model routing (`DEFERRED`, ADR-013 / T-131).
- **Acceptance criteria:**
  1. Default configuration resolves to the fake provider; a test asserts a real provider cannot be selected without an explicit non-default setting **and** an unlocked gate flag.
  2. Every model call writes a `ModelRun` with all version fields populated.
  3. A call exceeding a configured per-task, daily, or campaign budget is refused before any provider invocation; three tests.
  4. Model names and endpoints appear only in configuration; a test asserts no model identifier is hard-coded in business logic.
- **Verification:** `uv run pytest -q tests/test_model_gateway.py`
- **Files:** `backend/app/model_gateway/*`, `backend/tests/test_model_gateway.py`
- **Blocker / Q:** `Q-012` blocks real-provider use only; the fake path is unblocked.
- **Completion evidence:** —

#### T-051 — Versioned JSON Schemas for model outputs with validation, retry, and escalation
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-050
- **Spec:** §10.4 (exact output shape), §10.2, §18.1, §23
- **Objective:** Every model output passes a versioned JSON Schema; invalid output retries within a small limit and then escalates to human review.
- **Scope (in):** A `schemas/` directory of versioned JSON Schemas including the §10.4 qualification output verbatim; Pydantic models generated from or checked against them; a validation wrapper with bounded retry, then `human_review_required`; schema version registration in `SchemaVersion`; tests for valid, invalid, and repeatedly invalid output.
- **Scope (out):** Task prompts (T-053, T-054).
- **Acceptance criteria:**
  1. The §10.4 field set is represented exactly, including enum values for `opportunity_type`, `evidence_completeness`, and `source_quality`.
  2. Invalid output retries at most the configured limit and then escalates to human review; never silently accepted.
  3. Every schema file is content-hashed and registered as a `SchemaVersion`.
  4. Schema changes require a new version; mutating a registered schema fails a test.
- **Verification:** `uv run pytest -q tests/test_output_schemas.py`
- **Files:** `backend/app/model_gateway/schemas/*`, `backend/app/model_gateway/validation*`, `backend/tests/test_output_schemas.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-052 — Deterministic fake model adapter
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-051
- **Spec:** GP-06, §19.2, ADR-017 (baseline behind an adapter)
- **Objective:** A fully deterministic fake model that produces schema-valid outputs from the synthetic fixtures, so the entire Stage 1 pipeline is testable with no provider.
- **Scope (in):** A `FakeModelAdapter` keyed on input hash returning fixture-defined outputs; deliberate failure modes on demand (schema-invalid output, refusal, timeout, unsupported claim attempt, injected-instruction echo); no randomness; tests proving identical inputs give identical outputs.
- **Scope (out):** Any real provider.
- **Acceptance criteria:**
  1. Same inputs produce byte-identical outputs across runs and processes.
  2. Each of the five failure modes can be triggered by fixture configuration and is covered by a test.
  3. The adapter never performs I/O beyond reading local fixtures.
- **Verification:** `uv run pytest -q tests/test_fake_model.py`
- **Files:** `backend/app/model_gateway/adapters/fake.py`, `backend/app/fixtures/model_outputs/*`, `backend/tests/test_fake_model.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-053 — Qualification and opportunity classification task
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-052, T-046, T-045
- **Spec:** §10.1 stage 2, §10.2, §10.3, §10.4, §8.5, GP-02
- **Objective:** A bounded model task producing the §10.4 structured output for an eligible candidate, grounded strictly in stored evidence IDs, classified into the five opportunity types.
- **Scope (in):** A versioned prompt referencing only stored evidence and current approved claim IDs; a `QualificationRun` record; the evaluator writing scores, opportunity type, ambiguities, risks, missing information, and `human_review_required`; enforcement that every personalization fact cites an evidence ID and every applicable claim cites a claim ID; refusal to qualify an ineligible candidate; tests over the synthetic corpus.
- **Scope (out):** Draft text (T-054), calibration of confidence (explicitly not a probability, §10.2), real ICP weights (`Q-002`).
- **Acceptance criteria:**
  1. Output validates against the T-051 schema for every fixture candidate.
  2. Any personalization statement without an evidence ID fails validation; test-proven.
  3. An ineligible candidate is never qualified; test-proven.
  4. `human_review_required` is `true` for every candidate in Stage 1 (ADR-008).
  5. Model self-confidence controls nothing; a test asserts no branch reads it.
- **Verification:** `uv run pytest -q tests/test_qualification.py`
- **Files:** `backend/app/qualification/*`, `backend/app/model_gateway/prompts/*`, `backend/tests/test_qualification.py`
- **Blocker / Q:** `Q-002`, `Q-020` — synthetic rubric weights; thresholds not treated as approved.
- **Completion evidence:** —

#### T-054 — Draft creation from approved claim IDs and evidence IDs
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-053, T-020, T-014
- **Spec:** §8.3 step 9, §10.5, §14.4
- **Objective:** Generate a draft whose every product sentence resolves to a current approved claim and whose every prospect fact resolves to a stored evidence snapshot, materialized as an immutable revision.
- **Scope (in):** A drafting task with a versioned prompt receiving only the valid claim set and the candidate's evidence; template rendering for approved boilerplate; creation of revision 1 with claim and evidence references, recipient, and content hash; tests that the draft cites only supplied IDs.
- **Scope (out):** Sending, approval, follow-up drafting (`Q-009`, `DEFERRED`).
- **Acceptance criteria:**
  1. Revision 1 records the exact claim IDs and evidence IDs used.
  2. A draft referencing an unknown or expired claim ID cannot be persisted.
  3. Approved boilerplate is rendered from a template, not generated, where a template exists.
  4. Generating twice for the same inputs creates a second revision, never mutates revision 1.
- **Verification:** `uv run pytest -q tests/test_drafting.py`
- **Files:** `backend/app/drafts_and_approvals/drafting*`, `backend/app/model_gateway/prompts/*`, `backend/tests/test_drafting.py`
- **Blocker / Q:** `Q-017` — synthetic claims only.
- **Completion evidence:** —

#### T-055 — Message revision validation (structure, claims, recipient, suppression, policy)
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-054, T-017, T-015
- **Spec:** §8.3 step 10, §10.5, §15.6, §15.7
- **Objective:** A deterministic validator that fails closed on any unsupported claim, wrong recipient, suppressed identity, expired claim version, or campaign-policy violation.
- **Scope (in):** Validators for: every product sentence maps to a claim ID; no free-form product statement; claim set current and campaign-allowed; product readiness compatible with the campaign; recipient contactable and not suppressed; required compliance elements present for the current stage; structured `ValidationFailure` list; revision transitions to `validation_failed` or `review_pending`; tests for each validator.
- **Scope (out):** Legal review of compliance text (`Q-017`, legal authority), live send checks (T-035 covers dispatch-time rechecks).
- **Acceptance criteria:**
  1. Each validator has a failing and a passing test.
  2. A revision with any failure never reaches `review_pending`.
  3. An expired claim causes failure even if the wording is unchanged; test-proven.
  4. Validation is deterministic and calls no model; test-proven.
- **Verification:** `uv run pytest -q tests/test_revision_validation.py`
- **Files:** `backend/app/drafts_and_approvals/validation*`, `backend/tests/test_revision_validation.py`
- **Blocker / Q:** `Q-017`
- **Completion evidence:** —

#### T-056 — Claim-version and product-status invalidation job
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-055, T-021, T-030
- **Spec:** §14.4 (new version triggers invalidation), §8.4, §17.6, §19.2
- **Objective:** Publishing a new product status or claim version invalidates dependent pending drafts and approvals automatically and audibly.
- **Scope (in):** An `invalidate_by_claim_version` job triggered on status/claim version change; transitions affected revisions to `invalidated` and approvals to `revoked`/invalid; audit events naming the triggering version; a report of what was invalidated; tests including an approved-but-unsent revision.
- **Scope (out):** Notifying humans through messaging (Stage 4), dashboard surfacing (T-068).
- **Acceptance criteria:**
  1. A new claim version invalidates every pending revision and approval that referenced the prior version; test-proven.
  2. Invalidation is idempotent and writes one audit event per affected entity.
  3. An already-sent outreach record is not retroactively altered, only flagged.
- **Verification:** `uv run pytest -q tests/test_invalidation.py`
- **Files:** `backend/app/products_and_claims/invalidation*`, `backend/tests/test_invalidation.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-057 — Untrusted-content normalization before higher-authority prompts
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-046, T-051
- **Spec:** §15.4 (prompt-injection rule), §0 item 8, §19.4
- **Objective:** Normalize external text into typed facts so no external content reaches a prompt as instruction-shaped input.
- **Scope (in):** A normalizer converting evidence excerpts into typed fact records (field, value, source evidence ID) before prompt assembly; prompt assembly that places untrusted content in a clearly delimited data section with explicit "data, not instructions" framing; an injection corpus fixture (webpage, email, CRM note, attachment text); tests asserting none of the injection strings changes tool selection, claim usage, suppression, or product readiness.
- **Scope (out):** Full adversarial suite (T-083), attachment parsing isolation (Stage 3+).
- **Acceptance criteria:**
  1. An injection corpus of at least ten distinct payloads is stored as a fixture.
  2. No payload alters output structure, claim set, suppression, or readiness; test-proven for each.
  3. Prompt assembly refuses to embed raw untrusted text outside the delimited data section; test-proven.
- **Verification:** `uv run pytest -q tests/test_injection_resistance.py`
- **Files:** `backend/app/research_and_evidence/normalize*`, `backend/app/model_gateway/prompt_assembly*`, `backend/app/fixtures/injection/*`, `backend/tests/test_injection_resistance.py`
- **Blocker / Q:** none
- **Completion evidence:** —

#### T-058 — Stage 1 exit: end-to-end shadow slice with zero external writes
- **Stage / Priority:** 1 / P0
- **Status:** `PLANNED`
- **Depends on:** T-024, T-035, T-036, T-045, T-046, T-053, T-054, T-055, T-056, T-057
- **Spec:** §19.6 Stage 1 exit gate, §24 item 5, §3.5
- **Objective:** Prove the complete import → membership → eligibility → evidence → qualification → draft → validated review-ready revision path runs on synthetic fixtures with no external effect of any kind.
- **Scope (in):** One integration test driving the whole path through the worker; an assertion harness that fails if any external adapter is invoked outside the fake, if any HTTP/SMTP client is instantiated, or if any outbox event dispatches beyond the fake; a `docs/stage1-exit-evidence.md` recording commands, output, counts, and the zero-external-write proof.
- **Scope (out):** Dashboard (Stage 2), any approval-triggered send.
- **Acceptance criteria:**
  1. The integration test starts from an empty migrated database and ends with at least one `review_pending` revision per campaign.
  2. A network-guard fixture fails the test if any socket is opened.
  3. Every intermediate entity is present with audit events forming a complete chain by correlation ID.
  4. `docs/stage1-exit-evidence.md` records the verification commands and their real output.
  5. Gate **G-02** is then marked open in §5 with a link to that evidence.
- **Verification:** `uv run pytest -q tests/test_shadow_slice.py`; full canonical command set from §2.
- **Files:** `backend/tests/test_shadow_slice.py`, `backend/tests/conftest.py` (network guard), `docs/stage1-exit-evidence.md`
- **Blocker / Q:** none
- **Completion evidence:** —

---

## 4. Stage 2 — Review dashboard (next stage, decomposed; entry gate G-02)

All Stage 2 tasks stay `PLANNED` until **G-02** is open. Stage 2 exit gate is **G-10**: a non-engineer
completes reviews without understanding the agent stack.

#### T-060 — Next.js dashboard scaffold and typed API client
- **Stage / Priority:** 2 / P0 · **Status:** `PLANNED` · **Depends on:** G-02, T-004
- **Spec:** §18.1, §12.3 · **Objective:** `frontend/` Next.js app with lint/type/test, and an API client generated from the FastAPI OpenAPI document.
- **Acceptance:** app builds; client types are generated, not hand-written; a drift test fails if OpenAPI and client disagree; no data-fetching against anything but the local API.
- **Verification:** `npm run lint`, `npm run typecheck`, `npm run build`, client-drift test. · **Files:** `frontend/*` · **Q:** none

#### T-061 — Authentication: OIDC integration with a local development stub
- **Stage / Priority:** 2 / P0 · **Status:** `BLOCKED` · **Depends on:** T-060, T-012
- **Spec:** §12.2 (managed SSO/OIDC; custom passwords rejected), §15.1 · **Objective:** Session handling through a managed identity provider, with a clearly-marked local stub for development.
- **Acceptance:** no password authentication exists; the stub is unusable when `APP_ENV != local` (test-proven); sessions are short and revocable; service identities are separate from human identities.
- **Verification:** authz test suite; a test asserting the stub is refused outside local. · **Files:** `backend/app/identity/auth*`, `frontend/*`
- **Q:** **`Q-026`** (identity provider and roster) blocks the real provider; the local stub is implementable now but only after G-02.

#### T-062 — Server-side RBAC enforcement on every action
- **Stage / Priority:** 2 / P0 · **Status:** `PLANNED` · **Depends on:** T-061
- **Spec:** §12.1, §12.2, §15.1, §7.4 (autonomy tiers) · **Objective:** A role matrix enforced server-side per endpoint, mapped to the §7.4 tiers.
- **Acceptance:** every mutating endpoint has an authorization test for allowed and denied roles; a route with no declared permission fails a test; approval endpoints require the reviewer/approver role and are never reachable by a service identity.
- **Verification:** `uv run pytest -q tests/test_authz.py` · **Files:** `backend/app/identity/rbac*` · **Q:** `Q-005` for real approver assignment.

#### T-063 — Review queue API
- **Stage / Priority:** 2 / P0 · **Status:** `PLANNED` · **Depends on:** T-062 · **Spec:** §12.3, §17.5
- **Objective:** Paginated, filterable review queue endpoints for candidates and revisions with backlog age.
- **Acceptance:** filters by campaign, state, opportunity type, and age; deterministic ordering; every response carries the record version used for optimistic concurrency.
- **Verification:** `uv run pytest -q tests/test_review_api.py` · **Files:** `backend/app/drafts_and_approvals/api*` · **Q:** none

#### T-064 — Candidate review card UI
- **Stage / Priority:** 2 / P0 · **Status:** `PLANNED` · **Depends on:** T-063 · **Spec:** §12.3 items 1–7
- **Objective:** Render all seven required review-card elements including evidence with source quality and retrieval time, product readiness, approved claims, suppression/CRM warnings, the exact revision, and what happens next.
- **Acceptance:** a component test asserts all seven elements are present; evidence rows show retrieval time and source quality; the card states explicitly that no send will occur in shadow mode.
- **Verification:** frontend component tests; manual walkthrough recorded in the loop report. · **Files:** `frontend/app/review/*` · **Q:** none

#### T-065 — Editing creates a new immutable revision
- **Stage / Priority:** 2 / P0 · **Status:** `PLANNED` · **Depends on:** T-064, T-020 · **Spec:** §10.5, §12.3, §8.4
- **Objective:** Dashboard edits create revision N+1, supersede N, invalidate any prior approval, and re-run T-055 validation.
- **Acceptance:** editing an approved revision invalidates the approval; the prior revision remains byte-identical; validation re-runs and can block; three tests.
- **Verification:** `uv run pytest -q tests/test_review_edit.py` · **Files:** `backend/app/drafts_and_approvals/*`, `frontend/app/review/*` · **Q:** none

#### T-066 — Candidate decisions with structured correction reasons
- **Stage / Priority:** 2 / P1 · **Status:** `PLANNED` · **Depends on:** T-064 · **Spec:** §10.6 (eleven categories), §12.3 item 7
- **Objective:** Approve, reject, defer, and request-more-research decisions, each requiring a structured reason from the §10.6 category list with optional notes.
- **Acceptance:** the eleven categories are a database enum; a rejection without a category is refused; "defer until date/event" stores the date/event; feedback is stored as evaluation data and never rewrites policy (test-proven).
- **Verification:** `uv run pytest -q tests/test_corrections.py` · **Files:** `backend/app/qualification/corrections*`, `frontend/app/review/*` · **Q:** none

#### T-067 — Message approval transaction (dashboard → outbox, fake adapter only)
- **Stage / Priority:** 2 / P0 · **Status:** `PLANNED` · **Depends on:** T-066, T-021, T-034, T-035 · **Spec:** §11.3 steps 1–6, §11.4, §3.5
- **Objective:** The §11.3 six-step approval transaction, ending in one atomic write of approval plus immutable send command plus outbox event, dispatched only to the fake adapter.
- **Acceptance:** identity, role, session, CSRF, record version, and scope are all verified before approval; approval and send command commit in one transaction or not at all; with shadow mode ON no effect occurs beyond the fake; no agent callback exists anywhere in the path (test-proven).
- **Verification:** `uv run pytest -q tests/test_approval_transaction.py` · **Files:** `backend/app/drafts_and_approvals/approve*` · **Q:** `Q-005`; real sending stays behind **G-07**/**G-08**.

#### T-068 — Approval expiry, revocation, and invalidation surfacing
- **Stage / Priority:** 2 / P1 · **Status:** `PLANNED` · **Depends on:** T-067, T-056 · **Spec:** §7.5, §8.4, §17.6
- **Objective:** Show stale approvals, invalidated drafts, and expired claims in the dashboard and allow revocation.
- **Acceptance:** an invalidated item appears with the triggering version; revocation requires the correct role and writes an audit event; a revoked approval can never dispatch (test-proven).
- **Verification:** `uv run pytest -q tests/test_approval_lifecycle_ui.py` · **Files:** `backend/app/drafts_and_approvals/*`, `frontend/app/review/*` · **Q:** none

#### T-069 — Operations panel: pause, shadow mode, queue depth, dead jobs
- **Stage / Priority:** 2 / P1 · **Status:** `PLANNED` · **Depends on:** T-062, T-033 · **Spec:** §17.5 (operational dashboards), §17.6
- **Objective:** Administrator view exposing queue depth, oldest job, dead jobs with reasons, outbox backlog, delivery ambiguity, review backlog age, claim invalidations, and suppressed-send attempts, plus the pause and shadow-mode switches.
- **Acceptance:** every §17.6 control is reachable only by the administrator role; toggling writes an audit event; the panel shows shadow mode prominently; a test asserts a non-administrator receives 403 for each control.
- **Verification:** `uv run pytest -q tests/test_operations_api.py` · **Files:** `backend/app/audit_and_operations/api*`, `frontend/app/operations/*` · **Q:** none

#### T-070 — Session, CSRF, and web-security hardening with tests
- **Stage / Priority:** 2 / P0 · **Status:** `PLANNED` · **Depends on:** T-061 · **Spec:** §15.1
- **Objective:** Secure session cookies, CSRF protection on all state-changing routes, reauthentication for high-risk administration, and immutable actor attribution.
- **Acceptance:** a state-changing request without a CSRF token fails; cookies are `HttpOnly`/`Secure`/`SameSite`; high-risk administrative actions require reauthentication; every mutation records an immutable actor.
- **Verification:** `uv run pytest -q tests/test_web_security.py` · **Files:** `backend/app/core/security*` · **Q:** none

#### T-071 — Stage 2 exit rehearsal: non-engineer review walkthrough
- **Stage / Priority:** 2 / P1 · **Status:** `PLANNED` · **Depends on:** T-064, T-065, T-066, T-067, T-068, T-069, T-070 · **Spec:** §19.6 Stage 2 exit gate
- **Objective:** A written, reproducible walkthrough letting a non-engineer complete candidate and message review end to end on synthetic data, plus recorded evidence that they did.
- **Acceptance:** `docs/stage2-exit-evidence.md` contains the script, the synthetic dataset used, observed timings, and the reviewer's confirmation; every step works from a clean seeded database; gate **G-10** is then marked open.
- **Verification:** full canonical command set plus the documented walkthrough. · **Files:** `docs/stage2-exit-evidence.md` · **Q:** `Q-005` for a real reviewer identity; a synthetic operator account suffices for the rehearsal.

---

## 5. Stage gates and prohibited starts

Every gate below is **LOCKED**. A task behind a locked gate must be `PLANNED` or `BLOCKED`, never
`READY`. Only the user may unlock a gate, and only by recording the required evidence in the repository.

| Gate | Unlocks | Required before unlocking | State |
|---|---|---|---|
| **G-01** | Stage 1 engineering | v0.3 specification approved for buildout (spec header) and vendored into the repo (`T-001`). Written stakeholder acceptance record (`T-009`) is still outstanding and is tracked, not assumed. | **OPEN** (document-satisfied) |
| **G-02** | Stage 2 dashboard work (`T-060`…`T-071`) | `T-058` passes: full import→review-ready-draft slice on synthetic fixtures, zero external writes, evidence recorded in `docs/stage1-exit-evidence.md`. Note: spec §1.3 authorizes dashboard work as scope ("GO now"); spec §19.6 sequences it after Stage 1, which this gate enforces. | **LOCKED** |
| **G-03** | Production-like or real model-provider data use | `Q-012` answered (approved baseline model, provider, and data-handling settings); `Q-016` answered (approved materials for model processing); §15.9 provider review recorded; `T-050` budget enforcement `DONE`; no real contact data before `Q-019` retention policy. | **LOCKED** |
| **G-04** | Messaging-provider integration (`T-091`, `T-092`) | **G-10** open (Stage 2 complete); `Q-027` answered (WhatsApp Business account/phone or approved iMessage path); `Q-008` overlay role confirmed; channel-neutral gateway (`T-090`) `DONE`; gateway holds no approval authority. | **LOCKED** |
| **G-05** | CRM integration (`T-093`) | `Q-001` answered yes (a commercial owner will actually use HubSpot); `Q-010` answered (fields, owners, pipeline stages); field-ownership map recorded to prevent sync loops. | **LOCKED** |
| **G-06** | OpenClaw/NemoClaw spike (`T-095`, `T-096`) | Stage 1 exposes a useful API vertical slice (**G-02** open); separate Linux VM available; commit and image digest pinned; egress restricted; no production secret on the VM; spec §6.5 controls recorded. | **LOCKED** |
| **G-07** | Email-provider execution, even in test mode | `Q-004` answered (mailbox, provider, sender identity, reply address, domain); **G-10** open; SPF/DKIM/DMARC verified; suppression and opt-out paths `DONE`; `Q-015` reply owner named; §15.8 checklist complete. | **LOCKED** |
| **G-08** | Any live outreach to a real recipient | Every Stage 5 exit condition in spec §19.6; `Q-002`, `Q-004`, `Q-005`, `Q-013`, `Q-014`, `Q-015`, `Q-017`, `Q-018`, `Q-020` answered; approved versioned claim set exists; U.S.-only; ~5 individually approved sends/day; legal/commercial owner authorization recorded; all §3.5 safety invariants demonstrated. | **LOCKED** |
| **G-09** | Automatic follow-ups and scoped automation (`T-120`, `T-121`) | Multiple completed live review cycles showing reliable behavior and clear value; `Q-009` decided; §8.4 explicitly amended by an approved decision record. | **LOCKED** |
| **G-10** | Stage 3 evaluation/staging work and (with other conditions) Stages 4–5 | `T-071` passes: a non-engineer completes reviews unaided; evidence in `docs/stage2-exit-evidence.md`. | **LOCKED** |

**Prohibited starts** — do not begin these under any status, in any task, until the named gate opens:

- Real LLM provider calls or sending any real prospect/contact data to a provider → **G-03**.
- Any HTTP client in the research/evidence path, any live web fetch, any scraping → **G-03** plus an SSRF-hardening task filed at that time.
- WhatsApp, iMessage, or any messaging-provider credential or webhook endpoint → **G-04**.
- HubSpot or any CRM write → **G-05**.
- NemoClaw/OpenClaw installation, container pull, or VM provisioning → **G-06**.
- Email provider OAuth, SMTP client, or send in "test mode" → **G-07**.
- Any message to a real recipient → **G-08**.
- Automatic follow-up scheduling → **G-09**.
- Kubernetes, microservices, Kafka, Redis, Temporal, a vector database, a second production LLM or CRM provider, a local inference stack, generic browser control, or an agent plugin marketplace → **never**, absent a measured requirement and an approved architecture change (spec §18.6, §21.2).
- Autonomous LinkedIn operation, authenticated LinkedIn automation, or scraping → **REJECTED** (ADR-005).
- Any model or agent approving or executing an action → **REJECTED** (§3.5, §6.3).

---

## 6. Stakeholder-decision register (references the specification's canonical `Q-###` IDs)

This section **references** spec §20.1. It does not duplicate, renumber, or re-answer it. Statuses
below are the specification's. If a question is answered, record it in the specification (a separate,
explicitly scoped task) and update the reference here.

### 6.1 Blocks current engineering

| `Q-###` | Effect | Affected tasks |
|---|---|---|
| `Q-026` | Real OIDC provider and user roster unavailable → real authentication cannot be wired. Local stub only. | `T-061` (`BLOCKED`) |
| `Q-005` | Approval authority is not assigned → real approver identities cannot be configured; synthetic reviewers only. | `T-021`, `T-062`, `T-067`, `T-071`, `T-009` |
| Stakeholder acceptance record (no `Q-###`) | Stage 0 exit evidence is not stored in the repository; engineering proceeds on the spec header's approved status. | `T-009` (`BLOCKED`) |

### 6.2 Blocks only production-like testing

| `Q-###` | Effect | Affected tasks / gates |
|---|---|---|
| `Q-012` | No approved baseline model/provider or data settings → fake adapter only. | `T-050`, `T-082`, **G-03** |
| `Q-016` | No approved source-material set for model processing. | `T-046`, **G-03** |
| `Q-019` | No retention/deletion policy → conservative configurable defaults. | `T-017`, `T-019`, `T-046` |
| `Q-003` | No confirmed LinkedIn/provider/enrichment access or terms → CSV and fixture sources only. | `T-041`, `T-042`, `T-046` |
| `Q-011`, `Q-024` | No enrichment/verification provider selected or evaluation budget set. | Stage 3/4 provider tasks |
| `Q-018` | No hosting environment or post-internship maintenance owner. | `T-086`, **production blocker** |
| `Q-006` | No pilot deadline or spend ceiling → no external provider commitment. | `T-050` budgets, provider trials |
| `Q-020` | No numerical success/stop thresholds → shadow baseline measured first. | `T-085`, **G-08** |
| `Q-001`, `Q-010` | HubSpot adoption and field mapping undecided. | `T-093`, **G-05** |
| `Q-027` | No WhatsApp Business account or approved iMessage path. | `T-091`, `T-092`, **G-04** |

### 6.3 Blocks live outreach

| `Q-###` | Effect |
|---|---|
| `Q-017` | No versioned approved claim set → every real outbound product statement would fail validation. Synthetic claims only. |
| `Q-021`, `Q-022` | No approved sodium-battery or DC-fast-charging product brief → no real ICP, positioning, or claim can exist. |
| `Q-002` | No confirmed segments or buyer roles → campaign evaluation is not yet credible. |
| `Q-004` | No mailbox, provider, sender identity, reply address, or domain. |
| `Q-013` | No approved jurisdictions → U.S.-only by default. |
| `Q-014` | No expected research/send volume → conservative hard caps. |
| `Q-015` | No named reply owner. |
| `Q-025` | No owner/reviewer for the product-status and approved-claim store. |

### 6.4 Does not prevent synthetic shadow-mode implementation

`Q-007` (DECIDED — OpenClaw for the spike, optional and isolated), `Q-008` (DECIDED — messaging is a
complementary overlay), `Q-009` (DEFERRED — draft-only follow-ups), `Q-023` (DECIDED — build both
campaigns, pilot one). Also: `Q-001`, `Q-003`, `Q-004`, `Q-010`, `Q-011`, `Q-024`, `Q-027` do not
block Stage 1 because Stage 1 is entirely synthetic, offline, and fake-adapter based.

---

## 7. Known specification-versus-implementation reconciliation items

The live register is [docs/reconciliation.md](docs/reconciliation.md) (created by `T-008`); it also lists
known **non**-divergences so they are not re-opened as findings. The two seed items are repeated here
because they affect task selection.

| ID | Spec sections | Item | Resolution |
|---|---|---|---|
| **R-001** | §1.3 vs §19.6 | §1.3 marks "Review dashboard and authentication" as **GO now**, while §19.6 sequences the dashboard as Stage 2 after the Stage 1 exit gate. | Read §1.3 as scope authorization and §19.6 as sequencing. Enforced by gate **G-02**. No specification change proposed. Revisit only if the user directs dashboard-first work. |
| **R-002** | §19.6 Stage 0 vs repository | Stage 0's exit gate is stakeholder acceptance; the specification header already declares v0.3 approved for buildout, but no acceptance record exists in the repository. | Proceed with Stage 1 on the header's approved status; track the missing record as `T-009` (`BLOCKED`). Do not fabricate an acceptance record. |

---

## 8. Stage 3–7 gated epics and refinement tasks

These remain coarse until their prerequisites are close. Decompose an epic only when its gate is one
task away from opening.

### Stage 3 — Evaluation and staging (entry gate G-10; exit: safety invariants pass and baseline quality documented)

| ID | Status | Task | Depends on | Spec | Notes |
|---|---|---|---|---|---|
| `T-080` | `PLANNED` | Evaluation-fixture harness: 30–50 labeled synthetic prospects per campaign with the eight §19.1 label dimensions and a held-out subset | G-10, T-058 | §19.1 | Synthetic labels only until `Q-002`/`Q-020`; label schema is versioned |
| `T-081` | `PLANNED` | Consolidate the deterministic correctness suite to cover all eleven §19.2 items with an explicit coverage map | T-058 | §19.2 | Any uncovered item becomes its own task ID |
| `T-082` | `BLOCKED` | Model-quality harness for the nine §19.3 checks, run on the fake adapter now and on the baseline model after **G-03** | T-080, G-03 | §19.3 | Blocked on `Q-012` for real-provider runs only |
| `T-083` | `PLANNED` | Adversarial safety suite covering all nine §19.4 categories, extending the `T-057` injection corpus | T-057, T-081 | §19.4 | Includes approval replay and post-approval content change |
| `T-084` | `PLANNED` | Operational recovery suite covering the eight §19.5 scenarios including crash-after-provider-acceptance and database restore | T-032, T-035 | §19.5, §17.4 | Uses the fake adapter's ambiguous-acceptance mode |
| `T-085` | `PLANNED` | Cost and quality reporting per §17.5/§18.7 attribution dimensions | T-050, T-080 | §17.5, §18.7 | Baseline must be measured before `Q-020` thresholds are set |
| `T-086` | `BLOCKED` | Staging environment definition with separate credentials and a tested restore procedure | G-10 | §18.3, §15.5 | Blocked on `Q-018` (hosting, maintenance owner) |

### Stage 4 — Optional interfaces and integrations (each must fail without stopping the core workflow)

| ID | Status | Task | Depends on | Spec | Notes |
|---|---|---|---|---|---|
| `T-090` | `PLANNED` | Channel-neutral trusted messaging gateway and provider-neutral notification/command contract, with a fake channel adapter | G-10, T-036 | §12.4, §12.5, ADR-006 | Buildable with a fake channel before **G-04**; must never hold approval authority; ambiguous replies are never approval |
| `T-091` | `BLOCKED` | Official WhatsApp Business API webhook path and identity mapping | T-090, G-04 | §12.5 item 2 | `Q-027`; signature/timestamp/replay verification from `T-036` |
| `T-092` | `DEFERRED` | iMessage path via a company-managed bridge | T-090, G-04 | §12.5 item 3, §21.1 | Must never become the sole or critical channel |
| `T-093` | `BLOCKED` | `HubSpotAdapter` limited to the §13.5 contract, asymmetric sync per §13.4 | G-05 | §13.2–§13.5 | `Q-001`, `Q-010`; no `NoCRMAdapter`, no second general-purpose CRM |
| `T-094` | `PLANNED` | `FakeCRMAdapter` plus internal shadow-mode repository for existing-relationship and suppression reads | T-016, T-017 | §13.2, §13.4 | Test-only adapter; safe before **G-05** |
| `T-095` | `PLANNED` | Isolated OpenClaw-on-NemoClaw spike against real read/propose tools, with the §6.5 control checklist | G-06, T-096 | §6.1–§6.5, ADR-011 | Separate VM, pinned digests, deny-by-default egress, no production secret; graceful degradation test required |
| `T-096` | `PLANNED` | Least-privilege read/propose tool surface from §11.1, explicitly excluding every §11.1-prohibited tool | G-02, T-063 | §11.1, §6.3 | Buildable as ordinary API scopes before the spike; a test must assert no send/execute/SQL/shell/URL-fetch tool is exposed |

### Stage 5 — Email readiness (gate G-07; exit: legal/commercial owner authorizes a controlled live pilot)

| ID | Status | Task | Depends on | Spec | Notes |
|---|---|---|---|---|---|
| `T-100` | `BLOCKED` | Email adapter behind the existing external-effect boundary, provider test mode only | G-07, T-035 | §15.8, §5.1 | `Q-004`; adapter never decides whether a send is authorized |
| `T-101` | `BLOCKED` | SPF/DKIM/DMARC verification evidence and sender-identity approval record | G-07 | §15.8 | `Q-004`; evidence document, not code |
| `T-102` | `PLANNED` | Opt-out/unsubscribe intake with immediate suppression across active campaigns | T-017, T-036 | §15.6, §15.8 | Implementable against the fake channel before **G-07** |
| `T-103` | `PLANNED` | Delivery, bounce, reply, and unsubscribe event processing with sequence-stop on any reply | T-036, T-022 | §8.3 steps 13–16, §17.3 | Reply *classification* may propose only; no autonomous substantive reply handling |
| `T-104` | `BLOCKED` | Reply-ownership routing and handoff notification | T-103 | §8.3 step 17, §12.1 | `Q-015` |
| `T-105` | `BLOCKED` | Compliance footer, physical business address, and truthful-header configuration | G-07 | §15.8 | `Q-017` plus legal authority; never inferred |

### Stage 6 — Single-campaign U.S.-only micro-pilot (gate G-08)

| ID | Status | Task | Depends on | Spec | Notes |
|---|---|---|---|---|---|
| `T-110` | `BLOCKED` | Micro-pilot runbook: one campaign, ~5 sends/day, every message individually approved, hard volume caps, stop conditions | G-08 | §19.6 Stage 6, §8.4, ADR-008, ADR-012 | Campaign selected per §8.6: first approved brief, else DC fast charging |
| `T-111` | `BLOCKED` | Pre-live safety-invariant verification: demonstrate all seven §3.5 invariants against the real configuration | G-08, T-083, T-084 | §3.5 | Must be evidenced, not asserted |

### Stage 7 — Scoped automation (gate G-09)

| ID | Status | Task | Depends on | Spec | Notes |
|---|---|---|---|---|---|
| `T-120` | `DEFERRED` | Preapproved follow-up sending | G-09 | §8.4, §21.1, `Q-009` | Draft-only until multiple live cycles prove reliability |
| `T-121` | `DEFERRED` | Selected low-risk automatic CRM updates | G-09, G-05 | §19.6 Stage 7 | Requires proven field ownership |

### Cross-cutting deferred work

| ID | Status | Task | Spec |
|---|---|---|---|
| `T-130` | `DEFERRED` | Discovery via `discover(criteria)` against a licensed data provider | §9.5, `Q-003`, `Q-011` |
| `T-131` | `DEFERRED` | Tiered model routing / cheaper-model substitution | ADR-013, GP-14 — requires a measured baseline and labeled set first |
| `T-132` | `DEFERRED` | Multi-agent decomposition | ADR-009, §21.1 |
| `T-133` | `DEFERRED` | Vector retrieval or Redis | ADR-010, §18.6 — only after a measured requirement |

---

## 9. Progress log (append-only)

| Date | Task | Result | Verification evidence | New follow-up or blocker |
|---|---|---|---|---|
| 2026-07-27 | — (loop initialization) | Repository assessed; `tasks.md` and `process.md` created. No application code written. | `git status` (clean before writing, only these two files after); repository tree contains just `LICENSE`, `README.md`, empty `docs/`; specification v0.3 (1,984 lines) read in full from `C:\Users\Cody\Downloads\`; v0.2 confirmed superseded by date and revision history §22. | Specification is **outside** the repository → `T-001` created as the first `READY` task. Stakeholder architecture-acceptance record missing → `T-009` `BLOCKED` (**R-002**). §1.3-vs-§19.6 dashboard sequencing recorded as **R-001**. Public GitHub remote noted: synthetic data only. |
| 2026-07-27 | `T-001` | `DONE`. Spec confirmed repo-local and hash-verified; `AGENTS.md` created; `README.md` expanded; ledger and `process.md` spec path corrected. No application code. | `Get-FileHash SHA256 docs\…SPEC_v0.3.md` = `E571FC36420FEB7786AB2C984D24FDF0E100E89C6974E80F56C5D66173C57D9A` (92,997 bytes, header "Version: 0.3", "Last updated: 2026-07-27"); recursive search → exactly one spec copy, no v0.2 in repo; `git status --porcelain` → `?? AGENTS.md`, `?? docs/`, `?? process.md`, `?? tasks.md`, ` M README.md`; no network call, no dependency, no external effect. | User relocated the spec from `Downloads` to `docs/` between invocations; `T-001` scope adapted to the user's path instead of creating `docs/spec/` (recorded in the task's *Scope reconciliation*). `process.md` §1 spec path corrected in the same run to prevent a stale pointer. `T-002` promoted to `READY`. No new blockers. |
| 2026-07-27 | `T-002` | `DONE`. `backend/` project scaffolded: pyproject with pinned toolchain, `uv.lock`, `app/` package, smoke tests, root `.gitignore` and `.editorconfig`. No domain code. | `uv run python --version` → 3.12.11; `ruff check` → `All checks passed!`; `ruff format --check` → `2 files already formatted`; `mypy app` (strict) → `Success: no issues found in 1 source file`; `pytest -q` → `2 passed in 10.26s`; `git check-ignore -q` matrix → 8/8 ignore targets ignored, 3/3 keep-trackable tracked; `git add -A --dry-run` → only the 11 intended paths. | uv resolved several dependencies above their declared floors (mypy 2.3.0, pytest 9.1.1, ruff 0.16.0, starlette 1.3.1) and pinned them in `uv.lock`, so `T-004`+ must code against current-generation APIs. Network use limited to PyPI installation. `T-003` promoted to `READY`. No new blockers. |
| 2026-07-27 | `T-003` | `DONE` for the configuration and compose definition; live-container reachability **not** verified and split to `T-134`. Added `docker-compose.yml`, `.env.example`, `app/core/settings.py` with three fail-closed switches, six settings tests, `docs/development.md`. | `docker compose config` → valid (`postgres:16`, `pgdata`, `pg_isready` healthcheck); `ruff check` → `All checks passed!`; `ruff format --check` → `5 files already formatted`; `mypy app` (strict) → `Success: no issues found in 3 source files`; `pytest -q` → `8 passed in 1.66s`. | **New blocker:** the Docker Desktop engine will not start on this machine (`npipe:////./pipe/dockerDesktopLinuxEngine` missing; launching Docker Desktop + ~5 min polling did not help). Filed as `T-134` (`BLOCKED`, environment — no `Q-###`). It also gates `T-004`'s `/readyz` 200 case and `T-006`'s migration harness, so `T-008` (docs-only, no database) is the next `READY` task. |
| 2026-07-27 | `T-008` | `DONE`. Added `docs/adr/README.md` (ADR-001…017 indexed as inherited and binding, plus the never-reuse numbering rule), `docs/adr/ADR-018-toolchain-defaults.md`, and `docs/reconciliation.md` seeded with R-001/R-002. Documentation only. | inherited-ADR index → `17/17 indexed, missing: none`; local ADR numbering → `ADR-018… -> ok`; verbatim R-001/R-002 carry-over → 6/6 substring probes true in both files; all 5 link targets resolve; backend unaffected (`ruff` `All checks passed!`, `mypy` `Success: no issues found in 3 source files`, `pytest -q` `8 passed`). | Docker engine still unreachable, so `T-134` remains `BLOCKED` and `T-006` stays gated. `T-004` promoted to `READY` with an environment note: if Docker is still down, implement everything except the `/readyz`-200 case and split that assertion rather than claiming it. No new `R-###` items — nothing implemented so far diverges from the specification. |
| 2026-07-27 | `T-004` | `DONE` except the database-dependent half of criterion 2, split to `T-135`. Added the FastAPI factory, JSON structlog config, correlation-ID middleware, `app/db/session.py` (engine registry + `check_database`), `/healthz`, `/readyz`, and 15 tests. | `ruff check` → `All checks passed!`; `ruff format --check` → `11 files already formatted`; `mypy app` (strict) → `Success: no issues found in 8 source files`; `pytest -q` → `23 passed`; offline-guarantee grep for HTTP/SMTP client imports across `app/**` → **no matches**. | **Discovered:** Starlette 1.3.1 deprecates `httpx` for `TestClient` — `filterwarnings=["error"]` (ADR-018) turned it into an immediate collection error, so the dev dependency is now `httpx2 2.9.1`. ADR-018's trade-off working as designed. **Decision recorded:** synchronous SQLAlchemy (§2 table). **New task `T-135`** (`BLOCKED` on `T-134`) for `/readyz` 200-with-database. `T-006` annotated that `app/db/session.py` already exists and must be extended, not recreated. `T-005` promoted to `READY`. |
| 2026-07-27 | `T-005` | `DONE`. Created the thirteen §18.2 module packages with ownership docstrings, a `ast`-based import-boundary checker with 10 tests, and `docs/architecture/modules.md` with a drift-tested rule block. Structure and documentation only. | `ruff check` → `All checks passed!`; `ruff format --check` → `25 files already formatted`; `mypy app` (strict) → `Success: no issues found in 21 source files`; `pytest -q` → `33 passed`; **negative control** → injecting `app/model_gateway/_tmp_violation.py` importing `app.drafts_and_approvals` gave `1 failed, 9 passed` with the §5.1 clause quoted, and `10 passed` after removal. | Boundary rules are transcribed from §5.1/§6.3 clauses rather than an invented layer lattice, so each is traceable. Recorded a specification **interpretation** (budget enforcement belongs to the model *gateway*, not the provider *adapter*) in `docs/reconciliation.md` under "not divergences". `T-010` promoted to `READY` — **the last database-free Stage 1 task**; after it the loop is blocked on `T-134` (Docker engine). |

> The progress log is a summary trail, not a substitute for updating the task entry itself. Every run
> updates both.
