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
| **Next recommended `READY` task** | **`T-040` — synthetic fixture seeder.** Stage 1 has no way to populate a coherent world outside the test suite, so nothing can be demonstrated or reviewed by a human; §19.6 Stage 1 is explicitly synthetic-data-first. (`T-007`, `T-012`, `T-094`, `T-135`, `T-137` are also `READY`.) |
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
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-003
- **Spec:** §18.1, §18.3
- **Objective:** Prove the `db` service actually runs and accepts a connection using only `.env.example` values — the acceptance criterion `T-003` could not verify.
- **Scope (in):** Start the service, wait for the healthcheck, connect with `psycopg` using `DATABASE_URL`, run `SELECT 1`, confirm the server major version is 16, and record the output. Add `docs/development.md` troubleshooting notes if the startup path needs them.
- **Scope (out):** Any schema, migration, or ORM model (that is `T-006`). Any managed or remote database.
- **Acceptance criteria:**
  1. ✅ `docker compose up -d db` starts the service and the healthcheck reports healthy — `sales-agent-db-1  db  Up 13 seconds (healthy)`.
  2. ✅ A connection using the `.env.example` `DATABASE_URL` executes `SELECT 1` and reports server version 16.x — via the application's own `check_database()`, via SQLAlchemy, and via raw `psycopg` independently.
  3. ✅ `docker compose down -v && docker compose up -d db` reproduces a clean database — proved with a marker table rather than by assertion.
- **Verification (2026-07-27):**
  - `docker version` → Server `29.4.3` (the blocker cleared; the user started Docker Desktop)
  - `docker compose config --quiet` → valid
  - `docker compose up -d db` → created; polled `docker inspect --format '{{.State.Health.Status}}'` → `healthy`
  - `docker compose port db 5432` → `0.0.0.0:55432`
  - host round-trip → `check_database(): OK`; `SELECT 1 -> 1`; `server_version -> 16.14 (Debian 16.14-1.pgdg13+1)`; `current_database -> matrix_sales`; `current_user -> matrix`; `raw psycopg server_version_num -> 160014`; `ALL CHECKS PASSED`
  - clean-recreate proof → created `t134_marker` (1 row), `docker compose down -v` (volume removed), `up -d db`, healthy, then `SELECT to_regclass('public.t134_marker') IS NULL` → `t`
  - offline suite unaffected → `ruff` `All checks passed!`; `ruff format --check` `25 files already formatted`; `mypy app` `Success: no issues found in 21 source files`; `pytest -q` `33 passed`
- **Root cause found and fixed — host port collision (not a Docker fault):** the first host connection failed with `FATAL: password authentication failed for user "matrix"` while the container reported healthy. `netstat` showed **two** listeners on `0.0.0.0:5432`: `com.docker.backend` (PID 35932) and a native `postgres` (PID 8124) belonging to the Windows service **`postgresql-x64-18`**. Host connections were reaching PostgreSQL 18, where the `matrix` role does not exist. In-container `psql` was simultaneously perfect (`PostgreSQL 16.14`, user `matrix`, db `matrix_sales`), and the healthcheck could never detect the problem because `pg_isready` runs inside the container.
  **Fix:** publish the dev database on host port **55432** (`docker-compose.yml` default and `.env.example`). The user's native PostgreSQL service was **not** stopped, reconfigured, or touched — modifying a system service is out of bounds for this loop, and moving our own port is the reversible choice. `POSTGRES_PORT` still overrides it from a git-ignored `.env`.
- **Files:** `docker-compose.yml` (host port default 5432 → 55432, with the reason inline), `.env.example` (`POSTGRES_PORT`, `DATABASE_URL`), `docs/development.md` (a "Why host port 55432" section documenting the silent-collision symptom and how to diagnose it). No application code changed.
- **Blocker / Q:** cleared. Was an environment blocker, never a stakeholder decision; no `Q-###` applied.
- **Completion evidence:** the seven verification results above. No external effect beyond pulling the `postgres:16` image and running a local container; no credential, no remote service, no deployment.

#### T-136 — Convert approver columns to foreign keys once the user table exists
- **Stage / Priority:** 1 / P2
- **Status:** `PLANNED`
- **Depends on:** T-012, T-013
- **Spec:** §14.4 (`approved_by`), §12.2 (immutable actor attribution), §15.1
- **Objective:** Replace identity *strings* with real foreign keys to `user`, so an approver cannot be a typo and cannot be deleted out from under the record that depends on them.
- **Scope (in):** `product_status_version.approved_by` → FK; the same sweep for any approver/actor column added before `T-012` landed (check `approved_claim`, `approval` at the time of doing this). A migration converting existing values, and `ondelete="RESTRICT"` so an approver with history cannot be removed.
- **Scope (out):** `audit_event.actor_id`, which stays a string on purpose — the audit trail must remain readable after a user record is gone.
- **Acceptance criteria:**
  1. Every approver column outside `audit_event` is a foreign key to `user`.
  2. Deleting a user who approved something is refused; test-proven.
  3. `alembic check` is clean and the migration reverses.
- **Verification:** `uv run alembic upgrade head`/`downgrade`; `uv run pytest -q`
- **Files:** `backend/app/products_and_claims/models.py`, a new migration, affected tests
- **Blocker / Q:** none — waits on `T-012` only.
- **Completion evidence:** —

#### T-137 — Approval revocation entry point
- **Stage / Priority:** 1 / P1
- **Status:** `READY`
- **Depends on:** T-021, T-033
- **Spec:** §17.6 ("Revoke an approval"), §8.4 (approval invalidation)
- **Objective:** An operator can revoke a specific approval so nothing already approved can still be acted on, recorded with actor and reason.
- **Scope (in):** A `revoke_approval()` entry point in `drafts_and_approvals` that moves an approval out of a usable state, records actor and reason, writes an audit event, and is refused if the approval is already terminal; a check that revocation makes any pending send for that approval non-dispatchable; tests for each.
- **Scope (out):** Bulk revocation and UI (`T-069`). The operational *flag* store (`T-033`, done).
- **Acceptance criteria:**
  1. Revoking an approval prevents dispatch of anything depending on it; test-proven.
  2. Revocation records actor and a non-blank reason, and writes an audit event.
  3. Revoking an already-terminal approval is refused rather than silently ignored.
- **Verification:** `uv run pytest -q tests/test_approval.py`
- **Files:** `backend/app/drafts_and_approvals/approval.py`, `backend/tests/test_approval.py`
- **Blocker / Q:** none
- **Completion evidence:** —
- **Note:** Split out of `T-033` on 2026-07-29. §17.6 lists approval revocation next to the operational switches, but approvals live in `drafts_and_approvals`, which already imports `audit_and_operations` — putting the entry point in the flag store would close an import cycle. `T-033`'s own acceptance criteria never mentioned revocation, so its intent is preserved intact.

#### T-135 — `/readyz` returns 200 against a live database
- **Stage / Priority:** 1 / P0
- **Status:** `READY` — unblocked 2026-07-27 by `T-134`
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
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-003
- **Spec:** §18.1, §23 (migrations are the machine-readable source of truth)
- **Objective:** Migrations are the only way the schema changes, and every run can prove head applies cleanly to an empty database.
- **Pre-existing file note (2026-07-27):** `backend/app/db/session.py` already exists — `T-004` created it with the per-URL engine registry, `check_database`, and `dispose_engines`. **Extend it; do not recreate it.** `app/db/base.py`, the Alembic environment, and the migrated-database fixture are still this task's work. ~~Also inherits the `T-134` Docker blocker.~~ **Unblocked 2026-07-27:** `T-134` is `DONE`; a verified PostgreSQL 16.14 is available on `localhost:55432`.
- **Scope (in):** Alembic environment reading `DATABASE_URL`; naming convention for constraints/indexes; declarative base and `TimestampMixin`; an initial empty revision; a pytest fixture that creates a throwaway database, runs `alembic upgrade head`, and yields a session; a `tests/test_migrations.py` asserting `upgrade head` then `downgrade base` succeeds and that no model is missing a migration (`alembic check`).
- **Scope (out):** Any domain table.
- **Acceptance criteria (as met):**
  1. ✅ `alembic upgrade head` → `Running upgrade -> 3c526b2ea3ca, initial empty baseline`; `alembic downgrade base` → `Running downgrade 3c526b2ea3ca -> `; re-upgrade succeeds. Also asserted in-test by reading `alembic_version` before and after each direction.
  2. ✅ `alembic check` → `No new upgrade operations detected.`
  3. ✅ Integration tests obtain a migrated throwaway database through the `migrated_engine` fixture. A test greps `app/**` and `tests/**` for `.create_all(` and fails if any appears — **proved non-vacuous**: injecting `Base.metadata.create_all(...)` into `app/db/base.py` produced `assert not [WindowsPath('app/db/base.py')]`, and the suite returned green after removal.
- **Verification (2026-07-27, from `backend/`):**
  - `uv run alembic upgrade head` / `current` / `check` / `downgrade base` / re-upgrade → all succeed; `current` → `3c526b2ea3ca (head)`
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `30 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 22 source files`
  - `uv run pytest -q` → `42 passed`
  - **offline behaviour** with `DATABASE_URL` pointed at a closed port → `39 passed, 3 skipped` — the database tests skip cleanly rather than failing, so the suite still runs without Docker
- **Design decisions:**
  - **Model aggregation lives in `alembic/env.py`, not `app/db/base.py`.** The classic Alembic pattern imports every model into the base module, but `db` is foundation and may not import domain modules (`T-005` boundary rules). `alembic/` sits outside the `app` package, so `_load_all_models()` there satisfies autogenerate without breaking the boundary. **`T-011` onward must register each new model in that function** — a model nobody imports is invisible to `alembic check`; a test asserts the instruction stays in the file.
  - `alembic.ini` commits an **empty** `sqlalchemy.url`; the URL comes from settings, and tests override it per throwaway database. A test asserts the line stays empty so a connection string can never be committed.
  - Naming convention bound to `Base.metadata` for all five constraint types — without it PostgreSQL invents names, autogenerate diffs are unstable, and downgrades cannot reliably drop what upgrades created.
  - `TimestampMixin` uses database-side `server_default`/`onupdate`, not Python clocks: API, worker, and migrations all write rows, and a per-process clock would undermine the audit trail (§17.5).
  - `db_session` runs in a transaction that is always rolled back; the session-scoped database is dropped after terminating stragglers, so no abandoned test databases accumulate.
- **Two bugs found and fixed during this task:**
  1. **`str(URL)` masks the password as `***`.** The fixture yielded a masked connection string, so every database test failed authentication. Fixed with a `render_url()` helper using `render_as_string(hide_password=False)`, documented so the next cycle does not repeat it.
  2. **`T-134`'s port fix was incomplete.** `.env.example` and `docker-compose.yml` moved to 55432, but the `database_url` default in `app/core/settings.py` still said 5432, so anything running without a `.env` still hit the native PostgreSQL 18. Corrected here.
- **Files:** `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/alembic/versions/3c526b2ea3ca_initial_empty_baseline.py`, `backend/app/db/base.py`, `backend/tests/conftest.py`, `backend/tests/test_migrations.py`, `backend/pyproject.toml` (isort `known-third-party = ["alembic"]`, per-file ignores for generated migrations), `backend/app/core/settings.py` (port fix)
- **Blocker / Q:** none
- **Completion evidence:** the six verification results above plus both negative controls. No external effect: local container only, no credential committed, no deployment.

#### T-007 — CI pipeline
- **Stage / Priority:** 1 / P1
- **Status:** `READY` — unblocked 2026-07-27 by `T-006`
- **Port note:** CI's `postgres` service can use the standard 5432 (no native PostgreSQL competes in a runner). Set `DATABASE_URL` explicitly in the workflow rather than relying on the local 55432 default.
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
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-005
- **Spec:** §8.2, ADR-015, §19.2 (allowed/rejected transitions)
- **Objective:** Encode the five independent lifecycles as separate enums plus explicit allowed-transition tables, with a single guard function that raises on any illegal transition.
- **Scope (in):** `app/core/lifecycles.py` defining `CampaignCandidateState`, `MessageRevisionState`, `ApprovalState`, `OutreachThreadState`, `JobState` exactly as spec §8.2 lists them; per-lifecycle `ALLOWED_TRANSITIONS` mappings; `assert_transition(current, target)`; a terminal-state helper. Exhaustive tests over the full cross product asserting every allowed transition passes and every other pair raises.
- **Scope (out):** Any ORM model, any persistence, any cross-entity invariant (see T-024). **No global workflow enum** (rejected, spec §21.2).
- **Acceptance criteria (as met):**
  1. ✅ Five separate enums, exactly the states §8.2 lists. A test walks every `ClassDef` in `app/**` with `ast` and fails if any class mixes vocabulary from two lifecycles — no combined workflow enum can appear unnoticed (ADR-015, §21.2).
  2. ✅ 100% of ordered pairs per lifecycle: 10² + 6² + 5² + 10² + 6² = **297 parametrized cases**, each asserted allowed or asserted to raise. A separate test recomputes that total from the enums, so adding a state without extending coverage fails.
  3. ✅ `assert_transition` raises `IllegalTransition` (naming both states and listing what *is* allowed) or `CrossLifecycleTransition` (naming both enum types). Both are asserted by test — a bare "illegal transition" in a log is useless during an incident.
- **Verification (2026-07-27, from `backend/`):**
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `32 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 23 source files`
  - `uv run pytest -q` → `360 passed` (318 in this module)
  - **negative control** → adding the edge `REJECTED -> APPROVED` (resurrecting a rejected candidate) failed 3 tests, including `test_a_rejected_candidate_is_terminal`; `318 passed` after restore
- **Hazard found and designed around — `StrEnum` would have silently merged two lifecycles:** `StrEnum` members compare equal by string value and hash by member name, so `CampaignCandidateState.APPROVED` and `MessageRevisionState.APPROVED` are the **same dictionary key**. Verified before writing the module: `{A.APPROVED: 'a', B.APPROVED: 'b'}` yields **1** entry for `StrEnum` and **2** for plain `Enum`. The flat `ALLOWED_TRANSITIONS` lookup would have quietly lost a whole lifecycle's table. These enums are therefore plain `Enum`; `test_states_from_different_lifecycles_are_distinct` and a table-length check guard it permanently. (`AppEnv`/`ModelProvider` in settings stay `StrEnum` — no collision risk there.)
- **Transition edges beyond the §8.2 happy path**, each carrying its clause in a code comment: `DEFERRED → REVIEW_PENDING` (§10.6 "defer until a specific date/event"); `LEASED → QUEUED` (lease-expiry reclaim, §17.1/T-032); `APPROVED → INVALIDATED` on every lifecycle that can be invalidated by a claim-version change (§14.4/T-056); `REPLIED → UNSUBSCRIBED` (a reply can be an opt-out, §15.6). `DELIVERY_UNKNOWN` has **no** edge back to `SENDING` or `QUEUED`, making ADR-016's "no blind retry after an ambiguous result" structural rather than advisory.
- **Other deliberate decisions:** self-transitions are rejected everywhere (re-entering a state would write an audit event describing a change that did not happen, §3.5); `INELIGIBLE` and `REJECTED` are terminal, since resurrecting a candidate after a policy change is unspecified — a new membership is created instead; `Mapping` key invariance forced the five tables to share a widened `LifecycleTable` alias, and the precision that gives up is recovered by `test_each_table_contains_only_its_own_lifecycle`.
- **Files:** `backend/app/core/lifecycles.py`, `backend/tests/test_lifecycles.py`, `docs/architecture/modules.md` (the `core` row now states that it holds the lifecycle vocabulary, with the reasoning)
- **Blocker / Q:** none
- **Completion evidence:** the five verification results above plus the negative control. Pure domain code — no database, no persistence, no dependency, no network call, no external effect.

#### T-011 — Append-only audit event model and service
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Registration requirement (from `T-006`):** add this model's module to `_load_all_models()` in `backend/alembic/env.py`, or `alembic check` will not see it and the schema will drift silently.
- **Depends on:** T-006, T-010
- **Spec:** §3.5 (every consequential action has actor, revision, policy decision, audit event), §14.1, §17.5
- **Objective:** One audit primitive every later task writes through, recording actor, action, entity, versions, and correlation ID, with no update or delete path.
- **Scope (in):** `AuditEvent` table and migration (id, occurred_at, correlation_id, actor_type, actor_id, action, entity_type, entity_id, from_state, to_state, policy_decision, payload JSONB, app/prompt/schema/policy version columns); `record_audit_event()` requiring an explicit actor; a database-level guard against UPDATE/DELETE (revoke or trigger); tests asserting append-only behavior and required-actor enforcement.
- **Scope (out):** Log shipping, dashboards, metrics exporters.
- **Acceptance criteria (as met):**
  1. ✅ Three independent layers. `actor` is a keyword-only argument with **no default**, so omitting it is a `TypeError` rather than a silent "system"; `Actor.__post_init__` rejects a blank id; and a `CheckConstraint` rejects a blank `actor_id` even if the service is bypassed entirely.
  2. ✅ `UPDATE`, `DELETE`, **and `TRUNCATE`** all fail at the database level, each proven by a test asserting the error text contains `append-only`. A fourth test proves an **ORM** mutation hits the same wall, not just raw SQL.
  3. ✅ The correlation ID bound by the `T-004` request middleware flows into the trail via `structlog.contextvars`; an explicit argument overrides it; and writing with **neither** raises `MissingCorrelationId` rather than inventing one.
- **Verification (2026-07-27, from `backend/`):**
  - `uv run alembic upgrade head` / `downgrade base` **twice through the full cycle** → clean both times (proves the enum-drop fix below)
  - `uv run alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `36 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 25 source files`
  - `uv run pytest -q` → `386 passed` (25 in `tests/test_audit.py`)
  - boundary rules → `10 passed` (`audit_and_operations` is the platform module every other module may depend on)
- **Append-only is enforced by the database, not by convention.** A `plpgsql` trigger raises on `UPDATE OR DELETE`; a second, **statement-level** trigger covers `TRUNCATE`, which bypasses row-level triggers entirely and would otherwise erase the whole trail silently. `REVOKE` was rejected as the mechanism: the application user owns the table, so it would not bind. A migration test asserts both triggers still exist in the migrated schema, so a future migration cannot quietly drop them.
- **Payload safety (§15.5):** `record_audit_event` refuses payload keys matching a credential denylist (`password`, `secret`, `token`, `api_key`, `authorization`, `credential`, `private_key`), case-insensitive substring match — eight parametrized cases including `apiKey` and `refresh_token`. Cheap guard against the most likely way a secret reaches the trail.
- **Other decisions:** the event is added to the caller's session and **not committed**, so state, effect, and audit commit together or not at all (§17.2) — asserted by test. Lifecycle transitions are stored as enum *values*, so a later vocabulary rename cannot rewrite what history says happened. `occurred_at` uses the database clock, since API, worker, and migrations all write here. `ActorType.SYSTEM` exists for unattended work and is documented as never a substitute for an unknown human.
- **Two follow-on fixes:** (1) the `db_session` fixture now guards `transaction.rollback()` with `is_active` — a test that provokes a database error leaves the transaction already unwound, and the resulting `SAWarning` became a hard failure under `filterwarnings=["error"]`. (2) `T-006`'s `test_schema_is_created_only_by_migrations` asserted the schema held *only* `alembic_version`; that was written as a starting-point check and is now false by design, so it was replaced with a stamp-and-schema check plus the new trigger-presence test. `alembic check` remains the authority on model/migration agreement.
- **Files:** `backend/app/audit_and_operations/models.py`, `backend/app/audit_and_operations/service.py`, `backend/alembic/versions/6ea1f40a0e13_audit_event_table.py`, `backend/alembic/env.py` (model registered in `_load_all_models`), `backend/tests/test_audit.py`, `backend/tests/test_migrations.py`, `backend/tests/conftest.py`, `backend/pyproject.toml` (E501 ignored for generated migrations)
- **Blocker / Q:** none
- **Completion evidence:** the seven verification results above. No external effect: local container only, no credential, no deployment.

#### T-012 — Identity and access tables (no authentication yet)
- **Stage / Priority:** 1 / P1
- **Status:** `READY` — unblocked 2026-07-27 by `T-011`
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
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-011
- **Spec:** §2.3, §14.1, §14.4, GP-12
- **Objective:** Versioned product readiness with the five readiness categories from §2.3, plus provenance to a source document.
- **Scope (in):** `Product`; `ProductStatusVersion` (readiness_category enum: `sellable_now`, `evaluation_or_pilot`, `in_development`, `strategic_or_roadmap`, `paused_or_unavailable`; source_document_id, source_date, approved_by, approved_at, effective_from, expires_or_review_by, supersedes_version); `SourceDocument`; a repository function returning the *current effective* status for a product at a timestamp; tests for supersession and expiry.
- **Scope (out):** Real Matrix Power product specifications (`Q-021`, `Q-022`) — synthetic fixture products only. Any claim text (T-014).
- **Acceptance criteria (as met):**
  1. ✅ Enforced by a PostgreSQL **exclusion constraint** (`EXCLUDE USING gist (product_id WITH =, tstzrange(effective_from, expires_or_review_by, '[)') WITH &&)`), not an application check. Four tests: overlapping windows rejected with the constraint named in the error; two open-ended windows rejected; a **clean handover** (one window ending exactly where the next begins) allowed; other products unaffected.
  2. ✅ An expired version is never returned. `get_effective_status` excludes it, `require_effective_status` raises `NoEffectiveProductStatus`, and `is_effective_at` agrees with the query — tests for expired, not-yet-effective, and in-window cases.
  3. ✅ `ReadinessCategory` is a database enum with exactly the five §2.3 categories; writing `"probably_fine"` raises `DBAPIError`.
- **Verification (2026-07-27, from `backend/`):**
  - `uv run alembic upgrade head` → `downgrade base` → `upgrade head` → clean
  - `uv run alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `40 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 27 source files`
  - `uv run pytest -q` → `407 passed` (21 in `tests/test_product_status.py`)
- **Why an exclusion constraint rather than an application check:** two concurrent writers would each pass a read-then-write "is there an overlapping window?" test and both commit, leaving a product with two "current" readiness answers and no way to tell which one a draft relied on. The database refuses instead. `btree_gist` (a contrib extension present in `postgres:16`) is what lets the constraint mix equality on `product_id` with range overlap. `[)` bounds make a handover a succession rather than a conflict; a NULL upper bound is unbounded.
- **Fail-closed reads:** `get_effective_status` returns `None`; `require_effective_status` raises. Both exist deliberately — the raising form is for eligibility, drafting, and the §11.4 final checks, where a missing readiness answer must stop the workflow rather than default to something permissive (GP-12).
- **Provenance:** `source_document_id` uses `ondelete="RESTRICT"`, so deleting the document that justified a readiness claim is refused rather than silently removing the justification (test-proven). `SourceDocument.is_internal` defaults to `True` — internal material is a source record, never an approved external claim (§15.7).
- **Known gap, tracked as `T-136`:** `approved_by` is an identity **string**, not a foreign key, because `T-012`'s user table does not exist yet. Documented in the model and scheduled rather than left implicit.
- **Files:** `backend/app/products_and_claims/models.py`, `backend/app/products_and_claims/status.py`, `backend/alembic/versions/259218227532_product_status_version_source_document.py`, `backend/alembic/env.py` (models registered), `backend/tests/test_product_status.py`
- **Blocker / Q:** `Q-021`, `Q-022`, `Q-025` — every fixture in the tests is synthetic (`SYNTHETIC-` names); no real specification, certification, roadmap date, or MOU figure appears anywhere.
- **Completion evidence:** the six verification results above. No external effect: local container only, no credential, no deployment.

#### T-014 — Approved claims and approved claim sets with fail-closed validity
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Sequencing note (2026-07-27):** deliberately taken **after** `T-015`. Acceptance criterion 3 (a claim not allowed for a campaign is never returned for it) and `get_valid_claim_set(product, campaign, at)` both need campaign identity. Building the allow-list against campaign key *strings* before `Campaign` existed would have traded a foreign key for a typo-tolerant string on a safety-critical scoping rule.
- **Depends on:** T-013
- **Spec:** §10.5, §14.4, §15.7, GP-12
- **Objective:** A versioned claim store where exact wording or paraphrase constraints, approver, effective window, and allowed campaigns are mandatory, and expired or superseded claims fail closed.
- **Scope (in):** `ApprovedClaim`, `ApprovedClaimSet` (+ set version), claim↔campaign allow-list, `is_valid_at(timestamp)` semantics, `get_valid_claim_set(product, campaign, at)` that raises rather than returning stale claims; tests for expiry, supersession, campaign scoping.
- **Scope (out):** Real approved Matrix Power claims (`Q-017`) — synthetic claims marked `SYNTHETIC` only. Draft rendering (T-054), invalidation jobs (T-056).
- **Acceptance criteria (as met):**
  1. ✅ `approved_by`, `effective_from`, and `expires_or_review_by` are all NOT NULL, with check constraints for blank approver, blank text, and `expires_or_review_by > effective_from`. **`expires_or_review_by` is NOT NULL here unlike product readiness** — a claim nobody must revisit is how a stale certification survives into a live send. Six tests.
  2. ✅ `get_valid_claim_set` raises `InvalidClaimInSet` if **any** member is expired, superseded, not yet effective, or campaign-revoked. There is deliberately no "skip the bad ones" mode. **Negative control:** patching the resolver to filter expired members instead of raising failed 2 tests; green after restore.
  3. ✅ Campaign scope is an **allow-list** (`approved_claim_campaign`): absence of a link means not permitted, never "unrestricted". A claim approved for one campaign returns nothing for another, publishing refuses an unlinked claim, and revoking a link *after* publication breaks the set rather than narrowing it.
  4. ✅ `is_synthetic` is a NOT NULL column defaulting to `True`, and the immutability trigger prevents flipping it by UPDATE — promoting a synthetic claim to real requires a new, reviewed claim. A standing test asserts no non-synthetic claim exists while `Q-017` is open.
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `49 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 32 source files`
  - `uv run pytest -q` → `459 passed` (27 in `tests/test_approved_claims.py`)
  - boundary suite → `10 passed`
- **Immutability:** an `approved_claim`'s wording, approver, dates, and synthetic flag cannot be rewritten — §10.5 stores *exact* wording, so editing in place would make an already-approved message say something nobody approved. Editing means publishing v2 and superseding v1. `superseded_at` stays mutable. Set membership cannot be repointed at a different claim either.
  - **Scoped deliberately:** the membership trigger fires on `UPDATE` only, not `DELETE`. Removing a claim set (or the campaign above it) legitimately cascades to members, and a `BEFORE DELETE` trigger cannot distinguish a cascade from a direct delete. Swapping a member's claim silently changes what an approved set says; deleting a whole set is a visible administrative act.
- **Paraphrase constraint:** `allow_paraphrase = true` requires `paraphrase_constraints` to be non-null, enforced by a check constraint — permission to paraphrase without stated limits is how wording drifts from what was approved (§10.5).
- **Two Alembic hazards hit and now documented in `docs/development.md`:** (1) a new table reusing an existing enum emits a second `CREATE TYPE` and fails — needs `postgresql.ENUM(name=..., create_type=False)`; (2) `drop_table` leaves the enum type behind, breaking re-upgrade. Both were encountered live this cycle.
- **Files:** `backend/app/products_and_claims/claim_models.py`, `backend/app/products_and_claims/claims.py`, `backend/alembic/versions/173f99bbd4a0_approved_claims_and_claim_sets.py`, `backend/alembic/env.py`, `backend/tests/test_approved_claims.py`, `docs/development.md`
- **Blocker / Q:** `Q-017`, `Q-016`, `Q-025` — every claim is synthetic and marked as such; no real claim text, certification, or figure appears anywhere.
- **Completion evidence:** the five verification results above plus the negative control. No external effect: local container only, no credential, no deployment.

#### T-015 — Campaign, target segment, and campaign policy version
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-013
- **Spec:** §8.1, §8.6, §14.1, ADR-012
- **Objective:** Two campaign configurations (sodium battery, DC fast charging) with versioned policy: ICP rules, exclusions, geography, volume limits, active/paused flag.
- **Scope (in):** `Campaign`, `TargetSegment`, `CampaignPolicyVersion` (JSONB typed by a Pydantic policy model: allowed geographies, exclusions, required readiness categories, daily/total volume caps, suppression scope); pause flag; current-policy resolution; tests that policy is versioned and immutable once referenced.
- **Scope (out):** Real ICP definitions (`Q-002`) — synthetic placeholders only. Eligibility evaluation (T-045).
- **Acceptance criteria (as met):**
  1. ✅ `get_current_policy_version` returns the single unsuperseded version; publishing a new one supersedes the previous in the same call. `require_current_policy` **raises** `NoCurrentPolicy` when there is none — an absent policy must never read as "no restrictions". A unique constraint on `(campaign_id, version)` prevents duplicate version numbers.
  2. ✅ Enforced by a **trigger**, not convention: `campaign_id`, `version`, `policy`, `approved_by`, and `approved_at` cannot be rewritten. Two tests assert `DBAPIError` containing `immutable`. `superseded_at` is deliberately the one mutable column — retiring a version is how the next takes over and changes no rule.
  3. ✅ Defaults: `allowed_countries=("US",)`, `daily_send_cap=5`, `total_send_cap=50`, `require_verified_email=True`, all suppression scopes on, and `SELLABLE_NOW` **excluded** from default readiness. **Negative control:** widening the default to `("US","DE")` failed two tests; green after restore.
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `45 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 30 source files`
  - `uv run pytest -q` → `432 passed` (25 in `tests/test_campaigns.py`)
  - boundary suite → `10 passed` (`campaigns → products_and_claims` introduces no cycle)
- **Sequencing:** taken **before** `T-014` (both P0, both unblocked by `T-013`). `T-014`'s campaign scoping needs campaign identity; doing it first would have meant an allow-list keyed on campaign *strings*, trading a foreign key for a typo-tolerant field on a safety-critical rule. Recorded on `T-014`.
- **Design decisions:**
  - **Policy is typed, not loose JSON.** Stored as JSONB but always read back through a frozen Pydantic `CampaignPolicy` with `extra="forbid"`, so a typo'd rule cannot become a silently ignored one and a drifted body fails loudly at load rather than granting eligibility later. Both are test-covered.
  - **A new campaign starts `paused=True`.** §17.6 requires a pause control; the safe initial value is "not running".
  - **Empty means nothing, not everything.** `allowed_countries=()` permits no country, and `permits_country(None)` is `False` — unknown geography is refused, never assumed domestic.
  - `product_id` uses `ondelete="RESTRICT"`: a product a campaign depends on cannot be deleted out from under it.
- **Files:** `backend/app/campaigns/policy.py`, `backend/app/campaigns/models.py`, `backend/app/campaigns/service.py`, `backend/alembic/versions/5a91cde91f87_campaign_target_segment_policy_version.py`, `backend/alembic/env.py`, `backend/tests/test_campaigns.py`
- **Blocker / Q:** `Q-002` (segments/buyer roles), `Q-013` (jurisdictions), `Q-014` (volumes) — every default is the conservative placeholder, and every fixture is `SYNTHETIC-` named. No real ICP, geography, or volume figure appears.
- **Completion evidence:** the five verification results above plus the negative control. No external effect: local container only, no credential, no deployment.

#### T-016 — Account, contact, contact point, and CRM mapping
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-011
- **Spec:** §14.1, §13.5 (provider-independent IDs and external-ID mapping)
- **Objective:** Prospect identity tables with normalized keys and a provider-neutral external-ID mapping table.
- **Scope (in):** `Account` (normalized domain, name, country), `Contact`, `ContactPoint` (case-normalized email, type, verification state), `CRMMapping` (internal_id, provider, external_id, unique per provider); normalization helpers; tests for case/whitespace normalization and mapping uniqueness.
- **Scope (out):** Any CRM call (T-093/T-094), deduplication logic (T-043), enrichment.
- **Acceptance criteria (as met):**
  1. ✅ Emails lowercase and whitespace-stripped on write. `A@X.example.com` and `a@x.example.com` collide on `uq_contact_point_type_value`; a second test proves one address cannot belong to two contacts (which would defeat suppression).
  2. ✅ `normalize_domain` strips scheme, userinfo, `www.`, path, query, fragment, port, and trailing dot, then lowercases — 10 parametrized cases. `https://WWW.Collide.Example.COM/` collides with `collide.example.com`.
  3. ✅ `uq_crm_mapping_internal` gives one external ID per (provider, record type, internal record). Also added `uq_crm_mapping_external` — one internal record per external ID — so two internal records cannot both claim the same CRM record and fight over it on the next sync.
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `53 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 34 source files`
  - `uv run pytest -q` → `507 passed` (48 in `tests/test_prospects.py`)
  - boundary suite → `10 passed`
- **Normalization is enforced twice, and the negative control proved both layers independently.** Removing the email validator from the model failed 2 tests — and the failure came from **psycopg raising `IntegrityError` on the check constraint** (`ck_contact_point_email_value_is_lowercase`) before the unique constraint could even apply. So the ORM validator and the database constraint each catch it alone. This matters because normalization that only happens on some write paths is worse than none: a suppression recorded against one spelling would not stop a send to the other (§15.6).
- **Deliberate non-normalization:** Gmail dot/`+`-tag canonicalization is **not** applied. It is wrong for other providers, and guessing that two addresses are the same person is worse than treating them as two. Test-documented.
- **Other decisions:** `(type, value)` on `ContactPoint` is globally unique — one mailbox is one person. Only emails are lowercased; a LinkedIn URL path can be case-sensitive. Contact points start `UNVERIFIED`, which is not a soft yes — campaign policy requires verification before a send (`T-015`). `Account.country_code` is nullable and unknown geography stays NULL rather than defaulting to domestic; policy refuses it. `CRMMapping.internal_id` is deliberately **not** a foreign key: it points at an account *or* a contact depending on `record_type`, which a polymorphic FK cannot express — referential integrity belongs to the sync adapter (`T-093`/`T-094`).
- **Files:** `backend/app/prospects/normalize.py`, `backend/app/prospects/models.py`, `backend/alembic/versions/9c7510908885_prospect_identity.py`, `backend/alembic/env.py`, `backend/tests/test_prospects.py`
- **Blocker / Q:** none. All fixtures use IANA reserved example domains; no real company, person, or address appears.
- **Completion evidence:** the five verification results above plus the two-layer negative control. No external effect: local container only, no credential, no deployment.

#### T-017 — Suppression store with precedence and survival rules
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-016
- **Spec:** §15.6, §3.5 (zero sends to suppressed recipients), §19.2
- **Objective:** Suppression that outranks campaign configuration, survives contact deletion, and applies immediately at person, email, domain, and account scope.
- **Scope (in):** `Suppression` (normalized identity, scope enum, source, reason, effective_at, jurisdiction/policy context); no foreign key that would cascade-delete it; `is_suppressed(identity, scope_context)` checked by scope precedence; tests for global-unsubscribe override, contact deletion survival, immediate effect.
- **Scope (out):** Send-time enforcement inside the outbox transaction (T-035, T-067), unsubscribe intake (T-102).
- **Acceptance criteria (as met):**
  1. ✅ Deleting a contact — and deleting the whole account — leaves email, person, domain, and account suppressions matching. Structural, not incidental: the table has **no foreign keys at all** (asserted by querying `pg_constraint`), so nothing can cascade one away, and a trigger blocks `DELETE` and `TRUNCATE` outright.
  2. ✅ A domain-scope suppression matches a contact who did not exist when it was recorded, because the domain is derived from the address at check time. Also matches when the suppression was recorded as `https://WWW.Blocked.example.com/path`.
  3. ✅ `require_not_suppressed` is asserted to take **no** campaign, policy, or campaign_id parameter — there is no configuration under which a suppressed recipient may be contacted. A test builds a maximally permissive `CampaignPolicy`, confirms it permits the country and does not exclude the domain, and shows the recipient is still refused.
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `56 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 35 source files`
  - `uv run pytest -q` → `533 passed` (26 in `tests/test_suppression.py`)
  - boundary suite → `10 passed`
  - **negative controls** → removing domain-derivation-from-email failed 5 tests; removing the lifted-status filter failed 1; green after each restore
- **A real bug the tests caught.** The first `TRUNCATE` guard did not fire. In a **statement-level `TRUNCATE` trigger, `NEW` and `OLD` are undefined**, so the `IS DISTINCT FROM` comparisons below it evaluated NULL-to-NULL, passed, and let the whole table be erased. `TRUNCATE` is now handled in the same branch as `DELETE`, before any `NEW`/`OLD` access. The equivalent `audit_event` trigger (`T-011`) was checked and is unaffected — it raises unconditionally.
- **Lifting is deliberately asymmetric.** `UNSUBSCRIBE` and `COMPLAINT` can **never** be lifted (trigger-enforced, parametrized test per source) — honouring an opt-out is a CAN-SPAM obligation (§15.8), not an operational preference. Other sources (a mistyped domain, a stale import) can be lifted with a recorded reason, because one typo must not kill a campaign forever. `source` is immutable too, so an unsubscribe cannot be relabelled `MANUAL` and then lifted — test-covered.
- **Other decisions:** identities are normalized on write, so a suppression recorded as `Blocked@Example.COM` stops a send to `blocked@example.com`. `PERSON`/`ACCOUNT` scopes hold internal IDs **as text**, not foreign keys, which is what makes survival structural. An unnormalizable domain yields no domain candidate rather than raising — a junk value must not abort a suppression check inside a send transaction.
- **Files:** `backend/app/prospects/suppression.py`, `backend/alembic/versions/614ee9042ca9_suppression.py`, `backend/alembic/env.py`, `backend/tests/test_suppression.py`
- **Blocker / Q:** `Q-013` — `jurisdiction` is free text until approved jurisdictions are confirmed. `Q-019` — retention is not yet applied to suppressions, and deliberately so: they are the one record type that must outlive a retention sweep.
- **Completion evidence:** the six verification results above plus two negative controls. No external effect: local container only, no credential, no deployment.

#### T-018 — Campaign candidate entity and lifecycle enforcement
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-015, T-016, T-010
- **Spec:** §8.1 (`campaign_id + account_id + contact_id`), §8.2, §14.2
- **Objective:** Campaign membership as the unit of qualification, with a uniqueness constraint on the effective identity and transitions guarded by T-010.
- **Scope (in):** `CampaignCandidate` table; unique constraint on `(campaign_id, account_id, contact_id)`; state column using `CampaignCandidateState`; a service that transitions state through `assert_transition` and writes an audit event; tests that the same account/contact yields two independent candidates across two campaigns with independent states.
- **Scope (out):** Eligibility rules (T-045), qualification (T-053), review (Stage 2).
- **Acceptance criteria (as met):**
  1. ✅ `uq_campaign_candidate_identity` rejects a duplicate triple. Declared **`NULLS NOT DISTINCT`** (PostgreSQL 15+), which matters because §14.2 says a candidate has *usually* one contact — with default NULL handling, two account-only candidates for the same campaign would both be accepted since NULL never equals NULL. Test-proven for both the full triple and the NULL-contact case.
  2. ✅ The same account and contact in two campaigns produce two candidates that move independently: one driven to `approved`, the other to `ineligible`, in the same test. Deleting one campaign leaves the other candidate intact.
  3. ✅ Creation and every transition write an audit event carrying `from_state`, `to_state`, actor, and correlation ID. A **refused** transition writes nothing — the trail must not record a change that did not happen (§3.5).
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `59 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 36 source files`
  - `uv run pytest -q` → `550 passed` (17 in `tests/test_campaign_candidate.py`)
  - boundary suite → `10 passed` (`campaigns → prospects` introduces no cycle)
  - **negative controls** → bypassing `assert_transition` failed 4 tests; removing the audit write from `transition()` failed 2; green after each restore
- **What the database enforces vs. what the service enforces, and why:** the **identity triple is immutable** by trigger — repointing a candidate at a different campaign, account, or contact would silently reassign every evidence snapshot, score, and review decision already recorded against it, so the audit trail would describe work done on someone else. **State stays writable at the database level on purpose:** transition legality is a *sequence* question owned by `app.core.lifecycles`, and duplicating that table in plpgsql would create two rule sets to keep in step. `transition()` is the only supported path, and the audit trail exposes any write that skipped it.
- **`ineligible` requires a reason**, enforced twice: `transition()` raises without one, and a check constraint refuses the state even when the service is bypassed by raw SQL. A rejection that cannot be explained is not reviewable (§10.1).
- **Files:** `backend/app/campaigns/candidate.py`, `backend/alembic/versions/deff839a67b6_campaign_candidate.py`, `backend/alembic/env.py`, `backend/tests/test_campaign_candidate.py`
- **Blocker / Q:** none. Structured eligibility-failure detail is deliberately left to `T-045`; this task stores only the human-readable `ineligible_reason`.
- **Completion evidence:** the six verification results above plus two negative controls. No external effect: local container only, no credential, no deployment.

#### T-019 — Evidence snapshot with full provenance
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-018
- **Spec:** §14.3 (exact field list), §9.5, GP-02
- **Objective:** Store the minimum evidence needed for explainability with every provenance field the specification requires.
- **Scope (in):** `EvidenceSnapshot` with all §14.3 fields (source_type, source_provider_id, source_url_if_permitted, retrieved_at, supporting_excerpt_or_fact, content_hash, extraction_field_or_span, extraction_method, source_quality, license_and_retention_class, contains_personal_or_confidential_data, expires_or_refresh_by); an excerpt length cap enforcing "minimum evidence, not whole documents"; validity-at-timestamp helper; tests.
- **Scope (out):** Any real network fetch (T-046 stays offline; SSRF-protected fetching is Stage 3+ and gated), evidence UI (Stage 2).
- **Acceptance criteria (as met):**
  1. ✅ All eight required §14.3 fields are NOT NULL, proven by a parametrized test that nulls each one in turn. `content_hash` additionally must match `^[0-9a-f]{64}$`. **`contains_personal_or_confidential_data` deliberately has no default** — an unanswered privacy classification must not silently become "contains nothing sensitive" (§15.5, `Q-019`); a separate test constructs a snapshot omitting it entirely and confirms the insert fails.
  2. ✅ Rejected with a `ValueError` naming the actual length and the cap, never truncated — and enforced twice: the ORM validator, plus a check constraint proven by a raw SQL insert that bypasses the ORM. **Negative control:** changing the validator to `return value[:EXCERPT_MAX_CHARS]` failed the test; green after restore.
  3. ✅ `current_evidence` excludes expired and not-yet-retrieved snapshots; `is_current_at` agrees; `require_current_evidence` raises when everything is stale. `evidence_by_id` **fails whole** if any cited ID is stale — same rule as the approved-claim set (`T-014`), because quietly returning a subset changes what a draft says.
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `63 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 38 source files`
  - `uv run pytest -q` → `579 passed` (29 in `tests/test_evidence.py`)
  - boundary suite → `10 passed`
- **Snapshots are immutable, but still deletable — a deliberate asymmetry with suppression.** A trigger blocks `UPDATE` because §9.5 says a refresh writes a *new* snapshot; editing one in place would change what a qualification run and any draft citing it were based on, after the decision was recorded. `DELETE` stays allowed because `Q-019` will set a retention policy and evidence about a person is exactly the category that must be removable. Suppression is the opposite case and blocks deletion outright.
- **Evidence attaches to a campaign candidate, not an account** — the same fact may support a candidate in one campaign and be irrelevant in another (§8.1).
- **`SourceType` has exactly one LinkedIn value, `LINKEDIN_HUMAN_PROVIDED`**, asserted by a test: ADR-005 keeps LinkedIn human-assisted, so there is no vocabulary for an autonomously-collected LinkedIn fact.
- **A bug the tests caught:** the excerpt validator raised `TypeError` on `None`, masking a missing-excerpt insert as a type error instead of letting the NOT NULL constraint report it. `None` now passes through to the constraint.
- **Files:** `backend/app/research_and_evidence/models.py`, `backend/app/research_and_evidence/evidence.py`, `backend/alembic/versions/6ed335d539bf_evidence_snapshot.py`, `backend/alembic/env.py`, `backend/tests/test_evidence.py`
- **Blocker / Q:** `Q-019` — `RetentionClass` values describe *what may be done with* the evidence, not how long it is kept; the retention sweep itself is not implemented. `Q-003` — no provider source types are exercised yet; fixtures use `SYNTHETIC_FIXTURE`.
- **Completion evidence:** the five verification results above plus the truncation negative control. No external effect: no HTTP client exists in this package (`T-046` keeps capture offline until gate **G-03**).

#### T-020 — Message draft and immutable message revision
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-018, T-010
- **Spec:** §8.2, §10.5, §14.2, §11.4 (`message_revision_id`)
- **Objective:** Drafts that accumulate strictly immutable revisions, each hashed and each carrying its claim and evidence references.
- **Scope (in):** `MessageDraft`; `MessageRevision` (revision_number, recipient contact_point_id, subject, body, referenced approved_claim_ids, referenced evidence_ids, content_hash, state per `MessageRevisionState`, created_by); database-level immutability (revoke UPDATE or trigger); an "edit creates a new revision and supersedes the prior" service; tests.
- **Scope (out):** Generation of body text (T-054), validation rules (T-055), approvals (T-021).
- **Acceptance criteria (as met):**
  1. ✅ A trigger rejects `UPDATE` of `draft_id`, `revision_number`, `recipient_contact_point_id`, `subject`, `body`, `approved_claim_ids`, `evidence_ids`, `content_hash`, and `created_by`. Five parametrized raw-SQL updates plus a citation-array update and a recipient repoint all raise with `immutable` in the message. `state` and `retired_at` stay mutable — progressing `draft → review_pending → approved` changes nothing about what the message says.
  2. ✅ `create_revision` retires whichever revision was live and adds N+1. Proven for a `draft` predecessor and for an **approved** one (§10.5's actual case). `live_revision` returns exactly one; a superseded revision is terminal and cannot be transitioned onward. **Negative control:** removing the supersede call failed 3 tests.
  3. ✅ The hash covers recipient, subject, body, claim IDs, and evidence IDs — five parametrized cases prove each one alters it, plus adding a citation and reordering citations. **Negative control:** dropping recipient from the hash input failed the recipient case.
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `67 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 40 source files`
  - `uv run pytest -q` → `609 passed` (30 in `tests/test_message_revision.py`)
  - boundary suite → `10 passed`
- **Citations are array columns, not join tables — deliberately.** A join table could gain a row *after* the revision was approved, quietly changing what the message cites while the revision row itself looked untouched. As columns they are part of the immutable row, covered by the same trigger, and included in the hash. The cost is no FK integrity on citations; `T-055` validates that the referenced claims and evidence exist and are current.
- **The recipient is part of the hash.** §11.4 approves "this message to this person" as one unit — the same words to a different address is a different thing, and an approval must not survive that change.
- **Citation order is preserved, not sorted.** Reordering therefore alters the hash. That errs toward invalidating an approval rather than silently keeping one, which is the right direction for a fail-closed system.
- **The hash proves integrity, not truth** (§10.5). Truth authority remains the approved-claim record and its approver; this only detects that content changed.
- **Files:** `backend/app/drafts_and_approvals/models.py`, `backend/app/drafts_and_approvals/revisions.py`, `backend/alembic/versions/57804e6a27d7_message_draft_and_revision.py`, `backend/alembic/env.py`, `backend/tests/test_message_revision.py`
- **Blocker / Q:** none. Body generation is `T-054`; claim/evidence validity checking is `T-055`; approval binding is `T-021`.
- **Completion evidence:** the five verification results above plus two negative controls. No external effect: local container only, no credential, no deployment.

#### T-021 — Approval entity with scope, expiry, revocation, and supersession
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-020
- **Spec:** §8.2, §8.4, §11.3, §11.4, ADR-008, §19.2
- **Objective:** An approval that binds exactly one approver, one recipient, one immutable revision, and one policy context, and that expires, revokes, and invalidates correctly.
- **Scope (in):** `Approval` (approver user_id, entity_type/entity_id, message_revision_id, recipient contact_point_id, approval_expires_at, product_status_version, approved_claim_set_version, record_versions, state per `ApprovalState`); services to approve, expire, revoke; invalidation when recipient, content, product status, or claim version changes; tests for each invalidation trigger from §8.4.
- **Scope (out):** The dashboard approval endpoint (T-067), the send command (T-035).
- **Acceptance criteria (as met):**
  1. ✅ `message_revision_id` is NOT NULL with `ondelete="RESTRICT"` — a null revision is rejected, and the approved revision cannot be deleted while an approval points at it. A **partial unique index** (`WHERE state IN ('PENDING','APPROVED')`) permits at most one *live* approval per revision, so "the" approval is never ambiguous at dispatch (§11.4); a rejected approval still frees the revision for re-review, which a full unique index would have blocked.
  2. ✅ Six tests, one per trigger, all exercising the real edit path (a new revision supersedes the old) rather than poking the model. **Negative controls:** removing the revision-retired check failed 5 tests (recipient, subject, body, personalization, plus `require_valid`); removing the product-status check failed 1; removing the claim-set check failed 1.
  3. ✅ `assert_transition` refuses `revoked/expired/rejected → approved`; three tests. A closed approval records `closed_at` and `closed_reason`.
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `71 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 41 source files`
  - `uv run pytest -q` → `633 passed` (24 in `tests/test_approval.py`)
  - boundary suite → `10 passed`
- **Six triggers, three pinned values.** The revision **content hash** already covers recipient, subject, body, and the evidence IDs behind every personalization fact (`T-020`), so only the product status version and the claim set need pinning separately. `invalidation_reason()` returns the human-readable cause; `require_valid()` **raises** rather than returning a boolean, so a caller that forgets to check a result cannot send.
- **A defect found and fixed in `T-011`'s audit trail.** A test asserting the last audit event for an approval kept reading the *first*: PostgreSQL's `now()` is the **transaction** timestamp, so every audit event written in one transaction shared an `occurred_at` and the trail could not be ordered — and a transaction is exactly where a related sequence happens (request → transition → revocation). §17.5 requires that history to be readable. Migration `262585e960c1` changes the default to `clock_timestamp()`.
- **Scope decision recorded:** the ledger listed a generic `entity_type`/`entity_id`, but criterion 1 forces `message_revision_id` NOT NULL, and candidate approval is already a candidate lifecycle transition with its own audit event (`T-018`). A polymorphic entity pointer would have been unused weight, so this models message approval only.
- **`DEFAULT_APPROVAL_TTL` is 72 hours** — deliberately short because `Q-020` has not set review thresholds. A stale approval is a message somebody agreed to days ago under product and claim facts that may since have moved. Test-asserted to stay ≤ 7 days.
- **Files:** `backend/app/drafts_and_approvals/approval.py`, `backend/app/audit_and_operations/models.py` (clock_timestamp), `backend/alembic/versions/0133f6adb316_approval.py`, `backend/alembic/versions/262585e960c1_audit_event_uses_clock_timestamp_for_.py`, `backend/alembic/env.py`, `backend/tests/test_approval.py`
- **Blocker / Q:** `Q-005` — `approver_id` is an identity string and no authority check exists yet; `T-062` enforces role-based approval authority and `T-136` converts the column to a foreign key.
- **Completion evidence:** the five verification results above plus three negative controls. Nothing here sends anything — `T-035` performs the §11.4 dispatch rechecks against these same pinned values.

#### T-022 — Outreach thread, send command, send attempt, delivery event, interaction
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-021
- **Spec:** §8.2, §11.4 (consequential-action contract), §14.1, ADR-016
- **Objective:** The outreach-side tables, including an immutable send command carrying the full §11.4 field list and an idempotency key.
- **Scope (in):** `OutreachThread` (state per `OutreachThreadState`, includes `delivery_unknown`); `SendCommand` (all §11.4 fields, unique `idempotency_key`, immutable); `SendAttempt`; `DeliveryEvent`; `Interaction`; tests that a duplicate idempotency key is rejected and that `delivery_unknown` is a distinct terminal-pending state.
- **Scope (out):** Any dispatch (T-035), any real email provider (Stage 5).
- **Acceptance criteria (as met):**
  1. ✅ Every §11.4 field is present; eight parametrized cases null one required field each and all are rejected. `create_send_command` additionally **refuses to order at all unless the approval is still valid** — the same check `T-035` repeats at dispatch, because §8.4 triggers can fire in the gap between ordering and sending. **Negative control:** removing that check failed the test.
  2. ✅ `uq_send_command_idempotency_key` rejects a duplicate. The key is **derived**, not random — `sha256(approval_id:message_revision_id:recipient_contact_point_id)` — so re-deriving it for the same logical send produces the same key and collides, whereas a random key would make every retry look like a new send (§17.3). **Negative control:** making the key random failed the derivation test. A second constraint, `uq_send_command_approval`, enforces that one approval orders one send (ADR-008).
  3. ✅ `delivery_unknown` has no edge back to `sending` or `queued` — asserted directly against the lifecycle table and again by attempting the transition and getting `IllegalTransition`. It is **not terminal**: reconciliation can move it to `delivered`/`bounced`/`replied`/`failed`, which is the only way out (§17.3). `unresolved_since` is stamped on entry and cleared on resolution.
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `75 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 43 source files`
  - `uv run pytest -q` → `662 passed` (29 in `tests/test_outreach.py`)
  - **offline guarantee** → a test greps this module's own source for `smtplib`/`httpx`/`requests`/`aiohttp` and finds none: `T-022` records, it does not act
- **`SendCommand` is fully immutable — no state column at all.** Unlike a revision or an approval, a command has nothing to progress: it is an order. What happened to it lives in `SendAttempt` rows. If any field could be edited, the idempotency key could be re-pointed at different content and the duplicate-send guard would stop guarding anything.
- **Idempotent webhook intake:** `uq_delivery_event_provider_event` on `(provider, provider_event_id)` means a redelivered provider webhook is counted once (§15.2), while two different providers may legitimately reuse an event ID.
- **Inbound interactions default to `requires_human=True`** — §21.2 rejects autonomous substantive reply handling, so the safe default is the one that escalates.
- **`AttemptOutcome.REFUSED_BY_SHADOW_MODE`** exists so a shadow-mode refusal is recorded as a real outcome rather than an error (§17.6).
- **Files:** `backend/app/outreach_and_replies/models.py`, `backend/app/outreach_and_replies/commands.py`, `backend/alembic/versions/4ad849bbfecc_outreach_thread_send_command_attempts_.py`, `backend/alembic/env.py`, `backend/tests/test_outreach.py`
- **Blocker / Q:** none. Dispatch, the fake adapter, and the full §11.4 recheck list are `T-035`; a real provider is `T-100` behind gate **G-07**.
- **Completion evidence:** the five verification results above plus two negative controls. No external effect — no HTTP or SMTP client exists anywhere in this module, asserted by test.

#### T-023 — Versioning tables for prompts, schemas, model configuration, and policy
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-27)
- **Depends on:** T-011
- **Spec:** §14.1, §17.5, GP-09
- **Objective:** Persist `PromptVersion`, `SchemaVersion`, `ModelConfigVersion`, `PolicyVersion` so every model run and decision is attributable to exact versions.
- **Scope (in):** Four tables with content hash, effective window, created_by; helper resolving the current version of each; audit/observability fields referencing them; tests for immutability of a referenced version.
- **Scope (out):** Prompt content authoring (T-053, T-054), routing (`DEFERRED`, T-131).
- **Acceptance criteria (as met):**
  1. ✅ A trigger on each of the four tables rejects any change to `key`, `version`, `content_hash`, `effective_from`, or `created_by`. `effective_to` stays mutable because closing a window is how the next version takes over and changes no content. Tested per table via the shared parametrized class (4 × each assertion). **Note:** the FK `RESTRICT` from `ModelRun` arrives with `T-050`, which is the task that creates that table; immutability is already enforced unconditionally, so a referenced version cannot be altered even before the FK exists.
  2. ✅ `content_hash()` uses sorted-key canonical JSON. Three tests: the hash changes with content, is stable under key reordering (otherwise an unedited version would look edited), and notices a nested change. **Negative control:** removing `sort_keys=True` failed the stability test.
  3. ✅ `ModelConfigVersion` holds `provider`, `model_name`, and `parameters`. A test greps all of `app/**` for vendor markers (`claude-`, `gpt-4`, `gpt-5`, `deepseek`, `api.openai.com`, `api.anthropic`) and asserts none appear — §18.4's "keep model names and provider endpoints in configuration, not business logic", enforced rather than intended. A second test asserts only the `fake` provider exists (gate **G-03**, `Q-012`).
- **Verification (2026-07-27, from `backend/`):**
  - `alembic upgrade head` → `downgrade base` → `upgrade head`, **run twice**, clean; `alembic check` → `No new upgrade operations detected.`
  - `uv run ruff check .` → `All checks passed!`; `ruff format --check .` → `78 files already formatted`
  - `uv run mypy app` (strict) → `Success: no issues found in 44 source files`
  - `uv run pytest -q` → `714 passed` (52 in `tests/test_versioning.py`)
  - boundary suite → `10 passed`
  - **negative controls** → removing `sort_keys` failed the hash-stability test; removing the exclusion constraints from the migration failed `test_two_overlapping_versions_are_rejected` for all four tables
- **One effective version per key per instant**, enforced by a PostgreSQL exclusion constraint on each table — the same mechanism product readiness uses (`T-013`), for the same reason: an application check lets two concurrent writers commit overlapping windows, and two "current" prompts would make a model run unattributable.
- **Scope decision recorded — `PolicyVersion` is the *global* policy record.** `CampaignPolicyVersion` (`T-015`) already covers campaign ICP, exclusions, geography, and volume caps, so this one holds messaging guidance, objection handling, and other non-campaign rules (§14.5). A test asserts the two remain distinct (`PolicyVersion` has no `campaign_id`, `CampaignPolicyVersion` does) so nobody merges or duplicates them later.
- **A process slip worth noting:** my scripted edit adding the enum drop to the downgrade silently matched nothing, because the generated `downgrade` drops `model_config_version` last rather than `schema_version`. The migration then failed on re-upgrade with `type "modelprovider" already exists`. Fixed, and the full cycle was subsequently run **twice** to prove it. Lesson applied: verify a scripted edit actually applied rather than assuming.
- **Files:** `backend/app/audit_and_operations/versioning.py`, `backend/alembic/versions/e05624f3ae74_versioned_artefacts.py`, `backend/alembic/env.py`, `backend/tests/test_versioning.py`
- **Blocker / Q:** `Q-012` — only the fake provider may be configured until gate **G-03**.
- **Completion evidence:** the six verification results above plus two negative controls. No external effect: local container only, no credential, no deployment.

#### T-024 — Cross-entity invariant tests for lifecycle independence
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
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
- **Completion evidence:** 2026-07-29. `tests/test_invariants.py` — 23 tests covering all six invariants, no production code changed. **Two invariants turned out not to hold and were filed as `T-140` and `T-141`** rather than fixed here (criterion 2); both are recorded as `xfail(strict=True)` naming the task, so when the guard is implemented the marker becomes a failure telling the author to remove it and the finding cannot be lost.
  - Invariant 1 (rejected candidate → approved revision): **violated — `T-140`.** `request_approval` takes a revision and never consults its candidate's state. The half that does hold — a rejected candidate is terminal — is asserted separately.
  - Invariant 2 (invalidated approval leaves the revision intact and immutable): **holds.** Three tests: content hash and revision state unchanged after revocation, the immutability trigger still refuses an edit afterwards, and the two lifecycles' state sets are disjoint.
  - Invariant 3 (a dead job never advances candidate state): **holds.** The candidate is unchanged after `mark_dead`, `DEAD` is terminal, and candidate states never appear in the job table.
  - Invariant 4 (thread cannot leave `not_started` without an approved send command): **violated — `T-141`.** `transition_thread` checks the lifecycle table but not that a command exists. The guard that *does* exist — no send command without a valid approval — is asserted separately.
  - Invariant 5 (suppression outranks an approved candidate): **holds.** An approved candidate does not clear a suppression, and approving after a suppression does not lift it. `Suppression` has no `state` attribute at all, so there is nothing to transition out of (§15.6 permanence).
  - Invariant 6 (no code path mutates two lifecycles in one unguarded step): **holds**, enforced structurally. `LIFECYCLE_OWNERS` maps each of the five lifecycles to the packages allowed to name it, and an `ast` scan of `app/**` fails if any other module imports it — a function moving two lifecycles has to name both. A second scan asserts every module that assigns `.state` also imports `assert_transition`. `worker.py` and `main.py` are exempt and the exemption is documented: composition is their job and nothing imports them. Two guard-on-guard tests assert the owner map covers every lifecycle and that the state scan is not vacuous.
  - Criterion 3: every test docstring cites its specification section (§8.2, §8.4, §10.5, §15.6, §17.1, §7.2, §11.4, ADR-015).
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `109 files already formatted`; `mypy app` (strict) `Success: no issues found in 58 source files`; `pytest -q` `993 passed, 2 xfailed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (5, all valid, each verified to have changed the file): making a rejected candidate re-approvable failed 1; letting a dead job resume failed 1; a domain module naming another lifecycle failed 1; a state-moving module dropping its transition guard failed 1; giving `Suppression` a state failed 1. Green after each restore.
  - **A test-writing finding worth keeping:** the first draft moved candidates straight to `REJECTED`/`APPROVED` and three tests failed, because §8.2 has no shortcut from `imported` to a decision — it must walk eligible → research_pending → researched → review_pending. The helper now walks the legal path one step at a time, which is the right shape anyway: a test that assigned state directly would have been testing nothing.

#### T-140 — Approval must consult its candidate's state
- **Stage / Priority:** 1 / P1
- **Status:** `DONE`
- **Depends on:** T-024
- **Spec:** §8.2, §8.4, §11.4, ADR-015
- **Objective:** An approval cannot be granted for a revision whose candidate has been rejected, deferred, or invalidated.
- **Scope (in):** A check in `request_approval`/`approve` (or a §11.4 dispatch recheck, if that is the better placement) that refuses when the revision's candidate is in a terminal or non-approvable state; a decision recorded in the module docstring about *which* layer owns it; removal of the `xfail` on `test_a_rejected_candidate_cannot_yield_an_approved_revision`.
- **Scope (out):** Changing the candidate lifecycle table; making the two lifecycles interdependent beyond a read.
- **Acceptance criteria:**
  1. Approving a revision whose candidate is `rejected`, `deferred`, or `invalidated` is refused, naming the candidate state.
  2. The `xfail(strict=True)` marker in `tests/test_invariants.py` is removed and the test passes.
  3. ADR-015 independence is preserved: `drafts_and_approvals` reads candidate state, and does not transition it.
- **Verification:** `uv run pytest -q tests/test_invariants.py tests/test_approval.py`
- **Files:** `backend/app/drafts_and_approvals/approval.py`, `backend/app/outreach_and_replies/preconditions.py`, `backend/tests/test_invariants.py`, `backend/tests/test_preconditions.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `NON_APPROVABLE_CANDIDATE_STATES`, `CandidateNotApprovable`, `candidate_for_revision`, `candidate_refusal`, and `require_approvable_candidate` in `approval.py`, called from **both** `request_approval` and `approve`; plus a `Recheck.CANDIDATE_DECISION` recheck in `preconditions.py`. 12 new tests. No migration.
  - **Both layers were implemented, not one.** The task's scope said "in `request_approval`/`approve` **or** a §11.4 dispatch recheck", and its own note said both may be wanted. They are not substitutes: approval-time gives the reviewer immediate feedback, and the dispatch recheck catches a candidate rejected *after* approval — the case where a colleague rejects the prospect while a send sits in the outbox. Approval-time alone would have left that hole open while the task claimed to close it.
  - Criterion 1: `test_every_decided_against_candidate_state_blocks_approval` is parametrized over all four states and asserts the refusal names the state. `ineligible`, `rejected`, `deferred`, `invalidated` are refused; the six pre-decision states stay approvable, because a draft can legitimately exist during research and refusing there would break the drafting flow rather than protect anyone.
  - Criterion 2: the `xfail(strict=True)` is removed and `test_a_rejected_candidate_cannot_yield_an_approved_revision` passes. `T-141`'s xfail remains, correctly.
  - Criterion 3: `test_the_approval_module_reads_candidate_state_and_never_writes_it` asserts at the source that `approval.py` imports neither `transition_candidate` nor assigns `candidate.state`. `candidate_refusal` is a read; ADR-015 forbids one module *transitioning* another's entity, not consulting one — and no cross-entity invariant can be enforced without a read.
  - Extra coverage the task did not ask for but the design needed: `test_a_candidate_rejected_between_request_and_grant_is_caught` — `approve` re-reads rather than trusting the request-time check, because the reviewer window is exactly where a rejection lands.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `109 files already formatted`; `mypy app` (strict) `Success: no issues found in 58 source files`; `pytest -q` `1006 passed, 1 xfailed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (6 run, all eventually valid): `request_approval` not checking failed 5; `approve` not re-reading failed 1; `candidate_refusal` always permitting failed 6; the dispatch recheck disabled failed 1; `DEFERRED` removed from the set failed 1 (after a fix — see below). Green after each restore.
  - **A control found a tautology in my own test.** Removing `DEFERRED` from `NON_APPROVABLE_CANDIDATE_STATES` initially broke nothing, because the parametrized test draws its cases *from* that set — shrinking it removed a case instead of failing one. `test_the_non_approvable_set_is_exactly_the_decided_against_states` now pins both the set and its complement, and the redone control fails correctly.
  - **`T-024`'s own structural guard caught this change**, which is the guard working. `drafts_and_approvals` now names `CampaignCandidateState`, which `LIFECYCLE_OWNERS` forbade. Rather than widen the owner set — which would have been a hole — a separate `LIFECYCLE_READERS` map records who may *read* a lifecycle and why, and `test_a_reader_never_transitions_what_it_reads` holds every listed reader to reading only.
  - **Two more existing guards fired while writing the tests:** `ineligible` is reachable only straight from `imported` (§8.2 treats "does not qualify" as a screening outcome, not a review one), and `T-018` requires a reason for the negative outcomes. Both were my test's error, not the system's.
- **Note:** Found by `T-024` on 2026-07-29. A human who rejected a candidate decided nobody should be written to; an approval granted afterwards contradicts that without recording the contradiction anywhere. Note the placement question is genuine: doing it at approval time is earlier feedback, doing it as a §11.4 recheck catches a candidate rejected *after* approval. Both may be wanted.

#### T-141 — A thread may not leave `not_started` without a send command
- **Stage / Priority:** 1 / P2
- **Status:** `DONE`
- **Depends on:** T-024
- **Spec:** §8.2, §11.4, §3.5
- **Objective:** An outreach thread's state cannot claim a send was authorized when no send command exists.
- **Scope (in):** A check in `transition_thread` that leaving `not_started` requires at least one `SendCommand` on the thread; removal of the `xfail` on `test_a_thread_cannot_be_queued_without_a_send_command`.
- **Scope (out):** Any change to the thread lifecycle table; dashboard display (`T-069`).
- **Acceptance criteria:**
  1. `transition_thread(thread, QUEUED)` with no send command is refused.
  2. The same transition succeeds once a command exists.
  3. The `xfail(strict=True)` marker in `tests/test_invariants.py` is removed and the test passes.
- **Verification:** `uv run pytest -q tests/test_invariants.py tests/test_outreach.py`
- **Files:** `backend/app/outreach_and_replies/commands.py`, `backend/tests/test_invariants.py`, `backend/tests/test_outreach.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `ThreadNotStartable` and `require_send_command` in `commands.py`, called from `transition_thread` only when the *previous* state is `not_started`. 4 new tests; the `T-024` xfail removed. **No xfail remains anywhere in the suite** — both findings from `T-024` are now closed. No migration.
  - Criterion 1: `test_a_thread_cannot_be_queued_without_a_send_command` asserts the refusal and that no command exists first. `test_no_exit_from_not_started_works_without_a_command` parametrizes over **every** legal exit in `ALLOWED_TRANSITIONS[NOT_STARTED]`, so a future edge added to the table is covered the day it is added rather than left open.
  - Criterion 2: `test_the_guard_applies_only_when_leaving_not_started` orders a command, moves to `queued`, then to `sending`, proving both that the transition works once a command exists and that later transitions are not re-checked.
  - Criterion 3: the `xfail(strict=True)` is removed and the test passes.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `109 files already formatted`; `mypy app` (strict) `Success: no issues found in 58 source files`; `pytest -q` `1010 passed` (no xfailed); boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (3, all valid): removing the guard entirely — the original `T-141` gap — failed 3; `require_send_command` always permitting failed 2; applying the guard to *every* transition rather than only the first failed 1.
  - **An honest limit on control C.** Over-application is not behaviourally detectable: once a command exists the query succeeds at every transition, so `if True` still passes every functional test. Only `test_not_started_is_the_only_state_the_guard_reads` catches it, by asserting the condition and the single call site at the source. That test exists precisely because the behavioural route is closed — `SendCommand` is immutable and FK-restricted, so "a command that later vanishes" is not constructible.
  - **Three `T-022` tests had to change, and the guard was right, not the tests.** `test_resending_from_delivery_unknown_is_refused`, `test_reconciliation_can_resolve_delivery_unknown`, and `test_thread_transitions_are_audited` all moved a thread out of `not_started` with no command, because they were exercising the lifecycle table in isolation. Each now orders a command first, which is the correct precondition — reaching `delivery_unknown` presupposes a send was actually authorized.
  - **Why here and not in the §11.4 rechecks:** by dispatch time a command exists by definition, so the recheck would be unreachable. This is a truthfulness guarantee about the *record* — thread state is what the review dashboard reads — rather than a guard on an external effect.
- **Note:** Found by `T-024` on 2026-07-29. Lower priority than `T-140` because nothing external happens on this transition — no §3.5 violation on its own. But thread state is what the dashboard reads, so a thread in `queued` with nothing behind it is a record that asserts an approval exists when it does not.

### 3.3 Jobs, outbox, and operational controls

#### T-030 — PostgreSQL job table with `FOR UPDATE SKIP LOCKED` leasing and a worker loop
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
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
- **Completion evidence:** 2026-07-29. `Job` model + migration `63876c821f52`; `registry.py` (per-instance `JobRegistry`, Pydantic payload model per job type, duplicate registration refused); `queue.py` (`enqueue`, `lease_jobs`, `mark_succeeded`/`mark_for_retry`/`mark_dead`/`cancel`); `runner.py` (`execute`, `run_once`); `app/worker.py` process entry point. 23 tests in `tests/test_jobs.py`.
  - Criterion 1: `test_two_concurrent_workers_never_lease_the_same_job` leases from **two real `Session` connections before either commits** and asserts `first_ids.isdisjoint(second_ids)` with both batches full — proving the second worker neither blocked nor double-took. `test_the_leasing_query_actually_uses_skip_locked` additionally asserts `FOR UPDATE`/`SKIP LOCKED` in the compiled SQL, because the disjointness test alone would still pass in a *blocking* implementation.
  - Criterion 2: `enqueue` resolves the registered payload model and validates **before** `session.add`; `test_an_invalid_payload_never_reaches_the_queue` asserts `Job` row count is 0 after the rejection.
  - Criterion 3: `test_a_job_runs_and_commits_state_and_audit` and `test_a_handlers_writes_share_the_job_transaction`.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `85 files already formatted`; `mypy app` (strict) `Success: no issues found in 49 source files`; `pytest -q` `737 passed`; `alembic` up/down-to-base/up clean; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls:** dropping payload validation from `enqueue` failed `test_an_invalid_payload_never_reaches_the_queue`; replacing the `begin_nested()` SAVEPOINT with a full `session.rollback()` failed 2 tests; green after each restore. The `SKIP LOCKED` control was **deliberately not run as a mutation** — removing it makes the second worker *block* rather than fail, which would wedge the run, so the mechanism is pinned by the compiled-SQL assertion instead.

#### T-031 — Per-job-type retry policy, backoff, and dead-letter with human-readable reason
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
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
- **Completion evidence:** 2026-07-29. `retry.py` (`RetryPolicy` validated at declaration, `classify` → `FailureOutcome`, `compute_backoff` with injectable `random.Random`, `PermanentFailure`/`NeedsHumanReview`); `retry_policy` now a keyword-**required** argument on `JobRegistry.register` and `register_job_type`; `Job.requires_human_review` plus two check constraints; `mark_for_human_review()`; `_record_failure()` in `runner.py`. Migration `90aa0487c939`. 30 tests in `tests/test_job_retries.py`.
  - Criterion 1: `test_registering_without_a_retry_policy_fails` — no default policy exists to fall back on, so omission is a `TypeError` at registration and `mypy` strict catches it at build time. `test_an_incoherent_policy_is_refused` covers four invalid policies rejected in `__post_init__`.
  - Criterion 2: `test_a_failing_job_out_of_attempts_becomes_dead_with_a_reason` and `test_a_permanently_failing_job_dies_on_its_first_attempt`. Enforced in the schema as well as the caller — `dead_job_must_carry_a_reason` rejects a `dead` row with a null or blank `last_error`, proven by `test_the_database_refuses_a_dead_job_without_a_reason` / `..._a_blank_reason`.
  - Criterion 3: `test_backoff_doubles_each_attempt` (`[10, 20, 40, 80]` with jitter off), `test_backoff_is_capped_at_max_delay`, `test_jitter_is_deterministic_under_a_seeded_source`, `test_jitter_stays_within_its_declared_fraction` (200 draws inside ±25%), and `test_jitter_actually_varies` — the last because a jitter function returning a constant would satisfy every other assertion.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `88 files already formatted`; `mypy app` (strict) `Success: no issues found in 50 source files`; `pytest -q` `767 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up clean; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (7, each verified to have changed the file before running): removing the `max_delay` cap failed 1; never exhausting the attempt budget failed 2; collapsing human review into `dead` failed 3; retrying every exception class failed 1; flattening the exponent failed 2; removing each of the two check constraints **from the migration** failed 2 and 1. Green after every restore.
  - **`R-003` recorded** in `docs/reconciliation.md`: §7.2 names four outcomes but §8.2's job lifecycle has five states and no review state, so review is a disposition on `dead`, not a sixth state.

#### T-032 — Lease expiry recovery
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
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
- **Files:** `backend/app/jobs_and_outbox/recovery.py`, `backend/app/worker.py`, `backend/tests/test_job_recovery.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `app/jobs_and_outbox/recovery.py` — `find_expired_leases` (`FOR UPDATE SKIP LOCKED`, bounded, ordered by expiry) and `reclaim_expired_leases` (`LEASED` → `QUEUED`, lease cleared, audit event). Wired into the worker loop before each lease, so the feature is reachable and not merely callable. 12 tests. No migration — the columns landed with `T-030`.
  - Criterion 1: `test_two_recovery_passes_reclaim_a_job_exactly_once` runs two reclaims from two real `Session` connections before either commits and asserts disjoint full batches.
  - Criterion 2: `test_a_crash_before_commit_leaves_no_effect_and_loses_no_work` — a real `rollback` stands in for `SIGKILL`; afterwards the effect count is 0, the job is back to `QUEUED` with `attempt_count == 0`, and one recovery run produces exactly one committed effect. `test_a_lease_that_outlives_its_worker_is_reclaimed_and_run_once` covers the harder shape where the lease was **committed** before the worker died — without reclaim that job sits `leased` forever.
  - Criterion 3: `test_reclaim_writes_an_audit_event` asserts the `job.lease_reclaimed` action, both states, the service actor, and `previous_holder`.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `104 files already formatted`; `mypy app` (strict) `Success: no issues found in 57 source files`; `pytest -q` `919 passed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (6 run, 5 valid): ignoring lease expiry failed 2; leaving the stale holder failed 7; double-charging the attempt failed 3; losing the audit action name failed 1; ignoring the reclaim bound failed 2. Green after each restore. **One control proved nothing, and that is recorded rather than hidden:** removing `assert_transition` broke no test, because the query can only select `LEASED` rows so the assertion is unreachable today. It is forward-defence against a widened query, and the rule it enforces is now pinned directly by `test_only_a_leased_job_may_return_to_the_queue`.
  - **Deliberate departure from the scope line:** the reclaim does **not** increment `attempt_count`. `lease_jobs` already charged the attempt, so a crash costs exactly one — charging again would dead-letter a job in half its configured attempts, meaning one unlucky restart would cost a job the retries its policy promised. The scope line said "attempt-count increment on reclaim"; the *intent* (a crash consumes budget, so a poisonous job still stops) is satisfied by the lease increment, and both directions are tested.
  - **`T-138` added** for outbox dispatch-lease recovery.

#### T-138 — Outbox dispatch-lease recovery
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
- **Depends on:** T-032, T-035b
- **Spec:** §17.1, §17.3, §17.4, ADR-016
- **Objective:** A dispatcher that dies mid-dispatch releases its outbox lease without any chance of a duplicate external effect.
- **Scope (in):** An expired-dispatch-lease reclaim that moves the event to `DELIVERY_UNKNOWN` rather than `PENDING`; a simulated dispatcher-crash test proving the event is not silently re-sent; reconciliation as the only exit; an audit event naming the reclaim.
- **Scope (out):** Job lease recovery (`T-032`, done).
- **Acceptance criteria:**
  1. An expired dispatch lease resolves to `DELIVERY_UNKNOWN`, never straight back to `PENDING`; test-proven.
  2. A simulated dispatcher crash produces at most one external effect, and reconciliation determines whether it happened.
  3. Reclaim writes an audit event.
- **Verification:** `uv run pytest -q tests/test_dispatch.py`
- **Files:** `backend/app/jobs_and_outbox/recovery.py`, `backend/tests/test_dispatch.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `find_expired_dispatch_leases` and `reclaim_expired_dispatch_leases` added to `recovery.py`. 12 new tests (70 in `test_dispatch.py`). No migration — `DISPATCHING` → `DELIVERY_UNKNOWN` was already in `OUTBOX_TRANSITIONS` and the lease columns landed with `T-035b`.
  - Criterion 1: `test_an_expired_dispatch_lease_becomes_delivery_unknown` asserts the state and explicitly asserts it is *not* `PENDING`; `test_a_reclaimed_dispatch_lease_is_not_dispatchable` then proves no dispatcher can pick it up, and that `DELIVERY_UNKNOWN` is absent from `DISPATCHABLE_STATES`. The forbidden requeue is impossible rather than merely avoided.
  - Criterion 2: `test_a_crash_after_the_provider_accepted_never_sends_twice` — one adapter instance across three sessions stands in for the provider's own memory. The dispatcher reaches the provider (effect really performed), commits its lease, then dies; reclaim marks the event `delivery_unknown`; reconciliation finds the effect and resolves to `DISPATCHED` with `effect_count == 1` and `len(calls) == 1`, so nothing was sent twice. `test_a_crash_before_the_provider_was_reached_can_be_retried` is the mirror: reconciliation returns the event to `PENDING`, and the retry produces exactly one effect.
  - Criterion 3: `test_dispatch_reclaim_writes_an_audit_event` asserts the `outbox.lease_reclaimed` action, both states, the service actor, and `previous_holder`.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `104 files already formatted`; `mypy app` (strict) `Success: no issues found in 57 source files`; `pytest -q` `931 passed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (6, all valid, each verified to have changed the file): requeueing to `PENDING` instead of `DELIVERY_UNKNOWN` failed 4; ignoring lease expiry failed 1; losing the audit action name failed 1; leaving the dead dispatcher holding the lease failed 1; making `DELIVERY_UNKNOWN` dispatchable failed 2; ignoring the reclaim bound failed 2. Green after each restore.
  - **Coverage gap closed:** `recovery.py` now settles outbox events, so it is on the dispatch path and was added to `DISPATCH_PATH` in the `T-035a` no-network check (the bound guard raised from 6 to 7). Without that it would have been the one dispatch-path module free to import a provider client.
  - **Boundary semantics pinned:** expiry is `<=`, matching `Job.is_lease_expired_at`. `test_the_expiry_boundary_is_inclusive` exists because an off-by-one here either reclaims a lease while a dispatcher may still be talking to a provider, or leaves a dead one held forever. My first draft asserted the opposite and the test caught it.
  - **`T-139` added** — nothing calls `dispatch_once` in a running process yet.

#### T-139 — Wire the outbox dispatcher into the worker process
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
- **Depends on:** T-035b, T-138
- **Spec:** §17.2 step 4, §18.1 (two processes), §17.6
- **Objective:** A running worker actually dispatches the outbox, so a committed decision reaches its effect without a human invoking anything.
- **Scope (in):** Call `dispatch_once` from the worker loop with the send precondition check and the configured adapter; call `reclaim_expired_dispatch_leases` alongside the job reclaim; select the adapter from settings so shadow mode gets the fake; a test that one loop pass dispatches a pending event and that shadow mode leaves it untouched.
- **Scope (out):** A separate dispatcher process or scheduler (revisit only if measurement shows the shared loop is a problem); any real provider (**G-07**).
- **Acceptance criteria:**
  1. One worker pass dispatches a pending outbox event through the fake adapter.
  2. One worker pass reclaims an expired dispatch lease to `DELIVERY_UNKNOWN`.
  3. With shadow mode on, a pending event is left pending and no effect occurs.
- **Verification:** `uv run pytest -q tests/test_worker_cycle.py`
- **Files:** `backend/app/worker.py`, `backend/app/jobs_and_outbox/dispatch.py`, `backend/app/outreach_and_replies/adapters/__init__.py`, `backend/tests/test_worker_cycle.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `one_pass()` + `PassResult` in `worker.py` compose both reclaims, `run_once`, and `dispatch_once` — with `send_precondition_check` injected. `build_effect_adapter()` in `adapters/__init__.py`. `main()` now loops on `one_pass` and sleeps on `PassResult.did_nothing`. 15 tests in a new `tests/test_worker_cycle.py`. No migration.
  - Criterion 1: `test_one_pass_dispatches_a_pending_outbox_event` — `events_dispatched == 1`, state `DISPATCHED`, `effect_count == 1`.
  - Criterion 2: `test_one_pass_reclaims_an_expired_dispatch_lease` (settles to `DELIVERY_UNKNOWN`, not `PENDING`) and `test_one_pass_reclaims_an_expired_job_lease`, so a regression in either reclaim is visible from the worker's own tests.
  - Criterion 3: `test_shadow_mode_leaves_a_pending_event_pending`, `test_the_shadow_mode_flag_also_stops_the_worker`, `test_a_global_pause_stops_the_worker_dispatching`, and `test_the_shipped_defaults_dispatch_nothing` — all assert `effect_count == 0` **and** that the event is still `PENDING`, so the switch stops the send without losing the work.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `105 files already formatted`; `mypy app` (strict) `Success: no issues found in 57 source files`; `pytest -q` `946 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up clean; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (6, all valid): dropping the precondition injection failed 2; removing the `dispatch_once` call — the exact `T-139` gap — failed 4; removing the dispatch reclaim failed 2; letting a kill switch propagate again failed 4; spending the retry budget on a switch failed 1; building the adapter without `is_email` failed 1. Green after each restore.
  - **A real bug was found by wiring this up, and fixed:** a §17.6 kill switch raised `ExternalEffectBlocked` straight out of `dispatch_once`, so the **first pending event would have killed the worker whenever shadow mode was on — the shipped default**. A switch is an operator decision, not an error. `dispatch_event` now catches both switch exceptions, settles the event back to `PENDING` with backoff, refunds the attempt the lease charged, records an audit event naming the switch, and re-raises as `DispatchRefused(recoverable=True)` so the batch continues. Control D restores the old behaviour and 4 tests fail. This is exactly the class of defect that only appears when a tested-but-uncalled function is actually called.
  - **Deviation from the scope line:** it said "select the adapter from settings". `build_effect_adapter` takes `settings` but does not branch on it, because there is nothing to choose between — the fake is the only adapter, `Q-004` has chosen no provider, and `G-07` gates writing one. A settings field whose sole legal value is `"fake"` would read as though a real option existed. The parameter is kept so the call site does not change when `G-07` opens.
  - **No separate dispatcher process**, per the task's own scope-out: §18.1 names two processes and the worker is one of them. Revisit only if measurement shows the shared loop is a problem.
- **Note:** Found while doing `T-138` on 2026-07-29. `app/worker.py`'s own docstring claims the worker owns "outbox dispatch", but its loop only calls `run_once` — `dispatch_once` and `reclaim_expired_dispatch_leases` are callable and tested, and nothing in a running process calls either. Not folded into `T-138`, whose criteria are all about the reclaim itself; recorded rather than silently widened.

#### T-033 — Operational control flags: global pause, campaign pause, shadow mode, outbound disable
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
- **Depends on:** T-030, T-015
- **Spec:** §17.6, §17.1 (pause preserves inspectability), §19.6
- **Objective:** Fail-closed operational switches that prevent new consequential work while leaving queued work inspectable.
- **Scope (in):** An `OperationalFlag` store with audit-logged changes; flags for global pause, shadow mode, outbound email disabled, per-campaign pause, per-product/claim-version disable, approval revocation entry point; enforcement checkpoint used by the worker and by any consequential path; tests that a paused campaign blocks new consequential jobs but leaves them visible and that shadow mode blocks every external adapter.
- **Scope (out):** UI (T-069), credential revocation (operations runbook, Stage 5+), the approval-revocation entry point (**split to `T-137`**: approvals live in `drafts_and_approvals`, which already imports `audit_and_operations`, so a revocation entry point in the flag store would close an import cycle).
- **Acceptance criteria:**
  1. Default state is: shadow mode ON, outbound email OFF, no campaign live.
  2. With global pause set, no consequential job executes and none are lost; test-proven.
  3. Every flag change writes an audit event with actor.
  4. Shadow mode is checked in the adapter boundary, not only at call sites.
- **Verification:** `uv run pytest -q tests/test_operational_flags.py`
- **Files:** `backend/app/audit_and_operations/flags*`, `backend/alembic/versions/*`, `backend/tests/test_operational_flags.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `app/audit_and_operations/flags.py` — `FlagKey`, `OperationalFlag` (unique `(key, scope_id)` with `NULLS NOT DISTINCT`, required non-blank reason, scoped-key check constraint), `set_flag`/`is_set`, the composed resolvers `shadow_mode_active`/`outbound_email_allowed`/`consequential_work_allowed`, and the `GuardedAdapter` base class. `consequential: bool` added as a keyword-required argument on `JobRegistry.register`; `lease_jobs(exclude_types=...)`; pause enforcement in `run_once` plus a defensive check in `execute`. Migration `4a4c4bf4623e`. 33 tests.
  - Criterion 1: `test_the_shipped_defaults_are_the_safe_ones` (shadow ON, outbound OFF, zero flag rows) and `test_a_campaign_is_not_live_by_default` (`Campaign.paused` defaults True, T-015).
  - Criterion 2: `test_a_pause_stops_consequential_jobs_without_losing_them` — the held job is still `QUEUED` with `attempt_count == 0` and no `last_error`, while the non-consequential job runs; `test_releasing_the_pause_lets_the_held_job_run` proves the work survived; `test_a_paused_job_leased_some_other_way_is_still_refused` covers the second layer.
  - Criterion 3: `test_setting_a_flag_writes_an_audit_event_with_the_actor` and `test_releasing_a_flag_is_audited_too` (releasing is the more consequential direction).
  - Criterion 4: `test_shadow_mode_blocks_the_adapter_before_it_acts` asserts the adapter body was never reached, and `test_a_subclass_cannot_skip_the_check_by_forgetting_it` asserts `_perform` contains no flag reference yet is blocked anyway — the check belongs to the base class's `perform`, so a subclass cannot omit it.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `94 files already formatted`; `mypy app` (strict) `Success: no issues found in 52 source files`; `pytest -q` `815 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up run **twice** clean; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (8, each verified to have changed the file): flag alone deciding shadow mode failed 4; adapter boundary not checking shadow mode failed 2; shadow mode not stopping email failed 1; reason not required failed 1; pause not excluding types from leasing failed 2; `exclude_types` ignored failed 2; `NULLS NOT DISTINCT` → `DISTINCT` **in the migration** failed 1; scoped-key constraint removed from the migration failed 2. Green after each restore.

#### T-034 — Transactional outbox tables and atomic commit helper
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
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
- **Completion evidence:** 2026-07-29. `app/jobs_and_outbox/outbox.py` — `OutboxState`, `OutboxEvent` (unique sha256 `idempotency_key`, partial pending index, three check constraints), `enqueue_outbox_event()`, and `commit_with_outbox()`. Migration `f09d40b96a8b`. 15 tests in `tests/test_outbox.py`.
  - Criterion 1: `test_a_rollback_leaves_neither_business_state_nor_outbox_event` uses its own committing session, asserts both rows exist *inside* the transaction, rolls back, then re-reads from a fresh session and finds neither. `test_a_commit_keeps_business_state_and_outbox_event_together` covers the other direction.
  - Criterion 2: `test_an_outbox_event_without_an_audit_event_is_refused`, `test_an_outbox_event_without_business_state_is_refused`, and `test_the_refusal_happens_before_the_commit` (a refusal that committed anyway would be worse than no check).
  - Criterion 3: unique constraint proven by `test_two_events_cannot_share_an_idempotency_key`; the "matches the send command's key" half by `test_an_outbox_event_for_a_send_carries_that_command_s_exact_key`, with `test_the_outbox_holds_no_foreign_key_into_the_domain` as the structural guard.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `91 files already formatted`; `mypy app` (strict) `Success: no issues found in 51 source files`; `pytest -q` `782 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up run **twice** clean (enum-drop trap); `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (6, each verified to have changed the file): removing the audit-event check failed 1; removing the business-state check failed 2; inspecting only unflushed session state failed 2; dropping the unique key **from the migration** failed 1; dropping the sha256-shape constraint from the migration failed 1; not flushing the event failed 4. Green after each restore.
  - **Design note carried forward:** `commit_with_outbox` cannot inspect `session.new`, because a flush empties it and both `enqueue_outbox_event` and ordinary autoflush flush. It accumulates written kinds in `session.info` via an `after_flush` listener, cleared on commit and soft-rollback. Control C reproduces the naive version and fails.

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
- **Status note (2026-07-29):** **Split into `T-035a`, `T-035b`, `T-035c`.** One change set covering the adapter layer, effectively-once dispatch semantics, *and* nine cross-module rechecks is not reviewable, and the rechecks need fixtures from six other modules. This parent entry stays as the acceptance-intent record; it becomes `DONE` only when all three children are. Criteria map: 4 and 5 → `T-035a`; 2 and 3 → `T-035b`; 1 → `T-035c`.

#### T-035a — External-effect adapter protocol and fake adapter
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
- **Depends on:** T-033, T-034
- **Spec:** §17.2, §17.3, ADR-016, §18.5 (fake adapters before real providers)
- **Objective:** A typed external-effect boundary with a fake implementation that can simulate every provider outcome the dispatcher must handle, and that cannot act while a kill switch is on.
- **Scope (in):** `EffectRequest`/`EffectResult`/`EffectOutcome`; an `ExternalEffectAdapter` base that inherits the §17.6 guard so shadow mode is enforced structurally; a `reconcile()` method in the contract (§17.3 pre-retry reconciliation); `FakeExternalEffectAdapter` recording calls and simulating success, timeout, ambiguous acceptance, and rate limiting; a test that no network client exists anywhere in the dispatch path.
- **Scope (out):** The dispatcher itself (`T-035b`), the §11.4 rechecks (`T-035c`), any real provider (Stage 5, gate **G-07**).
- **Acceptance criteria:**
  1. With shadow mode ON the adapter refuses to act at all, even when called directly, and records no call; test-proven.
  2. No real network client (`smtplib`, `httpx`, `requests`, `aiohttp`, `urllib`, raw sockets) appears in the dispatch path; test-enforced by inspection, not by convention.
  3. The fake can produce every `EffectOutcome` the dispatcher must branch on, and timeout and ambiguous acceptance both resolve to the same non-retryable outcome.
  4. `reconcile()` reports whether an effect with a given idempotency key actually happened.
- **Verification:** `uv run pytest -q tests/test_dispatch.py`
- **Files:** `backend/app/jobs_and_outbox/dispatch.py`, `backend/app/outreach_and_replies/adapters/fake.py`, `backend/tests/test_dispatch.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `app/jobs_and_outbox/dispatch.py` — `EffectOutcome`, `SAFE_TO_RETRY`, frozen `EffectRequest`/`EffectResult`, the `SupportsReconciliation` protocol, and `ExternalEffectAdapter` (a `GuardedAdapter[EffectRequest, EffectResult]`). `app/outreach_and_replies/adapters/fake.py` — `Scenario` and `FakeExternalEffectAdapter`. `GuardedAdapter` made generic over request and result so the boundary is typed rather than `**kwargs`-shaped. 34 tests, no migration needed.
  - Criterion 1: `test_shadow_mode_stops_the_adapter_and_records_no_call` asserts both `calls == []` and `effect_count == 0`; the flag and the global pause have their own tests; `test_the_adapter_never_writes_its_own_entry_point` asserts structurally that neither the fake nor the base class defines `perform`, so the guard is inherited and cannot be omitted.
  - Criterion 2: `test_no_network_client_exists_in_the_dispatch_path` parametrizes over six dispatch-path modules and parses each with `ast`, intersecting top-level imports against 20 network module names. `test_the_dispatch_path_list_is_not_silently_empty` guards against the parametrize list going empty and making it vacuous.
  - Criterion 3: `test_every_outcome_is_reachable_through_the_fake` asserts the reached set equals `set(EffectOutcome)` — so a new outcome with no fake scenario fails immediately. `test_timeout_and_ambiguous_acceptance_are_indistinguishable_downstream` pins the equivalence.
  - Criterion 4: `test_reconcile_discovers_the_truth_behind_a_timeout` — the fake records the effect as performed even though the caller saw silence, so reconciliation returns `ACCEPTED` and a blind retry is demonstrably a duplicate. `test_reconcile_reports_nothing_after_a_transient_failure` is the mirror.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `98 files already formatted`; `mypy app` (strict) `Success: no issues found in 55 source files`; `pytest -q` `849 passed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (7, each verified to have changed the file): adding a real `httpx2` import to the fake failed 1; making `AMBIGUOUS` safe to retry failed 2; allowing `ACCEPTED` without a correlation ID failed 1; the guard skipping shadow mode failed 2; timeout not recording the effect it performed failed 1; success not recording the effect failed 3; rate limiting reported as ambiguous failed 2. Green after each restore.

#### T-035b — Outbox dispatcher: effectively-once, `delivery_unknown`, no blind retry
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
- **Depends on:** T-035a
- **Spec:** §17.2 steps 4–6, §17.3, ADR-016
- **Objective:** A worker leases pending outbox events, dispatches each through the adapter exactly once in effect, and never retries an ambiguous result blindly.
- **Scope (in):** Outbox leasing (mirroring the job queue's `FOR UPDATE SKIP LOCKED`); recording the provider correlation ID and result; ambiguous acceptance ⇒ `delivery_unknown` with zero retries; a pre-retry `reconcile()` call before any retry of an ambiguous attempt; replay of one idempotency key producing exactly one fake effect.
- **Scope (out):** The §11.4 rechecks (`T-035c`).
- **Acceptance criteria:**
  1. An ambiguous acceptance yields `delivery_unknown` and zero retries; test-proven.
  2. Replaying the same idempotency key produces exactly one fake effect.
  3. A retry after an ambiguous result reconciles with the provider first, and skips the send if the effect already happened.
  4. Two concurrent dispatchers never dispatch the same outbox event.
- **Verification:** `uv run pytest -q tests/test_dispatch.py`
- **Files:** `backend/app/jobs_and_outbox/dispatch.py`, `backend/tests/test_dispatch.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `OutboxState.DELIVERY_UNKNOWN`, `DISPATCHABLE_STATES`, `OUTBOX_TRANSITIONS` + `assert_outbox_transition` (a local state machine, not a sixth entry in `core/lifecycles.py`); six dispatch-bookkeeping columns on `outbox_event`; `lease_outbox_events`, `dispatch_event`, `dispatch_once`, `reconcile_unknown`. Migration `025c23d5d4bc`. 58 tests in `tests/test_dispatch.py` (24 new).
  - Criterion 1: `test_an_ambiguous_result_becomes_delivery_unknown` and `test_a_timeout_becomes_delivery_unknown_too`; `test_a_delivery_unknown_event_is_never_leased_again` asserts a second lease returns nothing **and** `len(adapter.calls) == 1`. Zero retries is structural — `DELIVERY_UNKNOWN` is not in `DISPATCHABLE_STATES`, so the lease query cannot see the row.
  - Criterion 2: `test_replaying_one_idempotency_key_produces_exactly_one_effect` — two genuine attempts (transient failure then success), `len(calls) == 2` but `effect_count == 1`. `test_a_dispatched_event_is_never_leased_again` covers the success path.
  - Criterion 3: `test_reconciliation_finds_the_effect_already_happened_and_sends_nothing` — the provider is asked first, resolves to `DISPATCHED`, and `len(adapter.calls)` stays 1. `test_reconciliation_returns_the_event_to_pending_when_nothing_happened` is the mirror, after which the event is leasable again.
  - Criterion 4: `test_two_concurrent_dispatchers_never_take_the_same_event` leases from two real `Session` connections before either commits and asserts disjoint full batches; `test_the_leasing_query_uses_skip_locked` pins the mechanism in the compiled SQL.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `99 files already formatted`; `mypy app` (strict) `Success: no issues found in 55 source files`; `pytest -q` `873 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up run **twice** clean; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (4 valid): making `DELIVERY_UNKNOWN` leasable failed 1; filing ambiguous as `FAILED` failed 4; reconciliation not asking the provider failed 1; accepting an unleased event failed 1. Green after each restore. A fifth (removing `SKIP_LOCKED`) was **attempted and had to be abandoned** — see the progress log.
  - **Scope honesty:** `dispatch_event` applies **no §11.4 rechecks**. The adapter guard means no kill switch can be bypassed, but "the switches are off" is not "every §11.4 condition still holds". That gap is `T-035c`, and the docstring says so at the call site.

#### T-035c — The nine §11.4 dispatch-time rechecks
- **Stage / Priority:** 1 / P0
- **Status:** `DONE`
- **Depends on:** T-035b, T-021, T-020, T-015, T-023
- **Spec:** §11.4, §3.5, §8.4
- **Objective:** Every §11.4 condition is re-evaluated inside the dispatch transaction, so a decision that became invalid between approval and dispatch cannot still be acted on.
- **Scope (in):** Rechecks for approver authority, approval state and expiry, exact recipient and revision, suppression at all configured scopes, sender availability, campaign active status and volume limit, product-status and claim-set versions, record versions, and an existing result for the idempotency key. One test per recheck proving dispatch is refused when it fails.
- **Scope (out):** The **sender-availability** half of §11.4's "email verification and sender availability" bullet — split to `T-035d`, `BLOCKED` on `Q-004`. No mailbox, provider, sender identity, reply address, or domain has been chosen, so there is no sender entity to check availability against and inventing one would be fabricating a product fact. The email-verification half **is** in scope here (`ContactPoint.verification_state` exists).
- **Acceptance criteria:**
  1. Each of the nine §11.4 rechecks has a test proving dispatch is refused when it fails.
  2. Each refusal writes an audit event naming which check failed.
  3. A recheck failure does not consume the outbox event's retry budget where the condition may later become valid again.
- **Verification:** `uv run pytest -q tests/test_preconditions.py`
- **Files:** `backend/app/outreach_and_replies/preconditions.py`, `backend/app/jobs_and_outbox/dispatch.py`, `backend/tests/factories.py`, `backend/tests/test_preconditions.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `app/outreach_and_replies/preconditions.py` (`Recheck`, `PreconditionFailure` carrying which check failed, `RECOVERABLE`, `recheck_send_command`, `send_precondition_check`); `PreconditionCheck` protocol + `DispatchRefused` + `_run_preconditions` in the dispatcher; `tests/factories.py` extracted so one fixture chain serves both suites. 34 tests. No migration.
  - Criterion 1: every implementable condition has a refusal test. **Six of the nine are enforced by `invalidation_reason` (§8.4), not re-checked here** — see the delegation table in the module docstring; the tests assert the `APPROVAL_VALIDITY` label and the specific detail string for those. Implemented here and separately tested: approver-authority stamp, suppression (parametrized over all four scopes), email verification, campaign status, total send cap, record versions, existing send attempt, missing send command.
  - Criterion 2: `test_a_refusal_writes_an_audit_event_naming_the_check` asserts `payload["refused_check"]`, under a new `outbox.recheck_refused` action.
  - Criterion 3: `test_a_recoverable_refusal_holds_the_work_without_spending_the_budget` asserts state `PENDING` and `attempt_count == 0` after the lease had spent one; `test_a_permanent_refusal_does_fail_the_event` is the other side.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `102 files already formatted`; `mypy app` (strict) `Success: no issues found in 56 source files`; `pytest -q` `907 passed`; boundary suite `10 passed`; `alembic check` -> `No new upgrade operations detected.`
  - **Negative controls** (6, each verified to have changed the file): dispatcher not running the rechecks failed 4; suppression not re-checked failed 5; recoverable refusal spending the budget failed 1; a paused campaign treated as permanent failed 2; approver stamp not compared failed 1; audit event not naming the check failed 1. Green after each restore.
  - **`T-035d` split out**, `BLOCKED` on `Q-004`.

#### T-035d — Sender-availability recheck
- **Stage / Priority:** 1 / P1
- **Status:** `BLOCKED`
- **Depends on:** T-035c
- **Spec:** §11.4 ("email verification and sender availability"), §15.8
- **Objective:** The dispatch transaction refuses a send when the sending mailbox is unavailable, over its own limit, or not the sender the approval assumed.
- **Scope (in):** A sender/mailbox entity; an availability check replacing the `Recheck.SENDER_AVAILABILITY` placeholder; per-sender volume accounting; a test proving dispatch is refused when the sender is unavailable.
- **Scope (out):** Provider credentials and live sending (gate **G-07**), SPF/DKIM/DMARC evidence (`T-101`).
- **Acceptance criteria:**
  1. `Recheck.SENDER_AVAILABILITY` is reachable and test-proven.
  2. A send whose approved sender differs from the sender now configured is refused.
- **Verification:** `uv run pytest -q tests/test_preconditions.py`
- **Files:** `backend/app/outreach_and_replies/preconditions.py`, a sender model, `backend/tests/test_preconditions.py`
- **Blocker / Q:** **`Q-004`** — no mailbox, provider, sender identity, reply address, or domain has been chosen. There is no sender entity to check availability against, and inventing one would fabricate a product fact. Also gated by **G-07**.
- **Completion evidence:** —
- **Note:** Split out of `T-035c` on 2026-07-29. §11.4 states "email verification **and** sender availability" as one bullet; the verification half is implemented and tested in `T-035c`. `Recheck.SENDER_AVAILABILITY` exists as a named placeholder so the gap is visible in code, and a test asserts the name is present.

#### T-036 — Webhook event intake with signature, timestamp, duplicate, and replay rejection (no live provider)
- **Stage / Priority:** 1 / P1
- **Status:** `DONE`
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
- **Files:** `backend/app/outreach_and_replies/webhooks.py`, `backend/app/core/settings.py`, `.env.example`, `backend/alembic/versions/224564968fc6_webhook_event_intake.py`, `backend/tests/test_webhooks.py`
- **Blocker / Q:** none
- **Completion evidence:** 2026-07-29. `app/outreach_and_replies/webhooks.py` — `WebhookEvent` (unique `(provider, external_event_id)`, three check constraints, partial unprocessed index), `WebhookProcessingState`, `RejectionReason`, `expected_signature`/`verify_signature` (HMAC-SHA256 over `timestamp.body`, `hmac.compare_digest`), `verify_freshness`, and `receive_webhook` returning `(event, created)`. `webhook_signing_secret` added to `Settings` (blank default) and to `.env.example`. Migration `224564968fc6`. 26 tests.
  - Criterion 1 — four distinct reasons, each its own test: `INVALID_SIGNATURE` (tampered body, forged signature, wrong secret — three tests), `STALE_TIMESTAMP`, `FUTURE_TIMESTAMP`, and duplicate handled idempotently rather than as an error. Plus `NO_SIGNING_SECRET`, `UNPARSABLE_TIMESTAMP`, and `INCOMPLETE_REQUEST`.
  - Criterion 2: `test_the_same_event_twice_yields_one_event_and_one_job` asserts one stored row **and** one job; `test_a_duplicate_does_not_advance_the_state` covers re-delivery of an already-processed event; `test_the_database_refuses_two_rows_for_one_provider_event` covers the race the read-before-write cannot.
  - Criterion 3: every test generates its own `secrets.token_hex(32)`, `Settings().webhook_signing_secret == ""` is asserted, and a scan for secret-shaped strings across the module, the tests, and `.env.example` finds none.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `108 files already formatted`; `mypy app` (strict) `Success: no issues found in 58 source files`; `pytest -q` `972 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up run **twice** clean; `alembic check` → `No new upgrade operations detected.`
  - **Negative controls** (6, all valid, each verified to have changed the file): signature not verified failed 3; timestamp dropped from the signed material failed 1; blank secret treated as "no check needed" failed 1; stale timestamps accepted failed 2; forward-dated timestamps accepted failed 1; duplicate detection removed failed 3. Green after each restore.
  - **Module choice:** placed in `outreach_and_replies`, not `messaging`. The task's files line allowed either, but `messaging` is forbidden from importing `jobs_and_outbox` (§18.2) precisely because ADR-006 keeps the messaging gateway out of the workflow — and "enqueue for processing" makes it a workflow dependency. Delivery and reply webhooks *are* a workflow dependency: they feed §17.3 reconciliation.
  - **Replay protection is the composition of two guards, and both halves are tested.** A captured request replayed inside the window is stopped by id uniqueness (one event, one job); replayed after the window it is refused outright before any lookup. Neither alone suffices — a window with no id check allows free replay for the window's width, and an id check with no window allows replay forever once the id is purged. A forward-dated timestamp gets its own rejection reason because a forged future timestamp would otherwise never go stale.
  - **The signed material includes the timestamp**, so a captured body cannot be re-signed with a fresh timestamp. Pinned directly by `test_the_timestamp_is_inside_the_signed_material` rather than left to inference, since that single omission would defeat the entire window.
  - **Nothing is stored unless it verified.** A `signature_valid` check constraint means the table cannot hold an unverified row, and rejected requests are not persisted at all — a table of rejected requests would be an attacker-controlled write primitive.
  - **A verified event with no registered handler is still stored** (`RECEIVED`, warned, not raised): dropping a verified provider notification is worse than holding one nobody can interpret yet. `T-103` classifies replies.
  - **Caught by an existing guard:** `test_env_example_documents_every_setting` (from `T-004`) failed until `WEBHOOK_SIGNING_SECRET` was added to `.env.example`. The drift test did its job.

### 3.4 Synthetic fixtures, import, eligibility, and evidence capture

#### T-040 — Synthetic campaign, product, status, and claim fixture seeder
- **Stage / Priority:** 1 / P0
- **Status:** `READY` — unblocked 2026-07-27 by `T-014` and `T-015`
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
| `T-094` | `READY` | `FakeCRMAdapter` plus internal shadow-mode repository for existing-relationship and suppression reads | T-016, T-017 | §13.2, §13.4 | Test-only adapter; safe before **G-05** |
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
| 2026-07-27 | `T-134` | `DONE`. Docker engine 29.4.3 now available. Verified the local PostgreSQL 16.14 container end to end and fixed a host port collision found in the process. No application code changed. | `docker compose config --quiet` valid; healthcheck polled to `healthy`; `docker compose port db 5432` → `0.0.0.0:55432`; host round-trip `check_database(): OK`, `SELECT 1 -> 1`, `server_version -> 16.14`, `current_user -> matrix`, raw psycopg `160014`, `ALL CHECKS PASSED`; clean-recreate proved by marker table (`to_regclass(...) IS NULL` → `t`) after `down -v`; offline suite still `33 passed` with `ruff`/`mypy` clean. | **Root cause:** a native Windows service `postgresql-x64-18` (PID 8124) already bound `0.0.0.0:5432` alongside `com.docker.backend`, so host connections silently reached PostgreSQL 18 and failed authentication while the container stayed healthy — `pg_isready` runs *inside* the container and cannot detect this. **Fix:** moved the published host port to **55432** in `docker-compose.yml` and `.env.example`, and documented the symptom and diagnosis in `docs/development.md`. The user's native PostgreSQL service was deliberately left untouched. **Unblocked `T-006` and `T-135`** (both now `READY`). Also noted: the user committed and pushed all prior loop output as `b0ff71e`. |
| 2026-07-27 | `T-006` | `DONE`. Alembic environment, declarative `Base` with naming convention, `TimestampMixin`, initial empty revision `3c526b2ea3ca`, throwaway-database fixtures, and 9 migration tests. | `alembic upgrade head` → ran `3c526b2ea3ca`; `alembic current` → `3c526b2ea3ca (head)`; `alembic check` → `No new upgrade operations detected.`; `alembic downgrade base` → ran downgrade; re-upgrade OK; `ruff` `All checks passed!`; `ruff format --check` `30 files already formatted`; `mypy app` `Success: no issues found in 22 source files`; `pytest -q` `42 passed`; **offline control** `DATABASE_URL` → closed port gave `39 passed, 3 skipped`; **guard control** injecting `create_all` into `app/db/base.py` failed the suite, green after removal. | **Two bugs found and fixed.** (1) `str(URL)` masks the password as `***`, so the fixture handed every test an unusable connection string — fixed with `render_url()` and documented. (2) `T-134`'s port fix was incomplete: the `database_url` default in `app/core/settings.py` still said 5432, so anything without a `.env` still reached the native PostgreSQL 18. **Boundary-preserving decision:** model aggregation for autogenerate lives in `alembic/env.py`, not `app/db/base.py`, because `db` is foundation and may not import domain modules; `T-011` onward must register each model in `_load_all_models()`. Also configured ruff's isort `known-third-party = ["alembic"]` — the local `alembic/` directory made it classify the installed package as first-party. `T-007` unblocked → `READY`. |
| 2026-07-27 | `T-010` | `DONE`. Five independent lifecycle enums with explicit transition tables, `assert_transition`, terminal/reachability helpers, and 318 tests. Pure domain — no persistence. | `ruff` `All checks passed!`; `ruff format --check` `32 files already formatted`; `mypy app` (strict) `Success: no issues found in 23 source files`; `pytest -q` `360 passed`; **negative control** adding `REJECTED -> APPROVED` failed 3 tests, `318 passed` after restore; exhaustiveness self-check confirms 297 parametrized pairs = 10²+6²+5²+10²+6². | **Hazard avoided:** `StrEnum` members from different lifecycles collide as dictionary keys (verified: 1 entry vs 2 for plain `Enum`), which would have silently merged two transition tables in the flat lookup — these enums are plain `Enum`, guarded by a test. ADR-016's "no blind retry" is now structural: `DELIVERY_UNKNOWN` has no edge back to `SENDING`/`QUEUED`. Edges beyond the §8.2 happy path each cite their clause in a comment. `docs/architecture/modules.md` updated: `core` holds lifecycle vocabulary (values and pure functions, no imports), which does not change the dependency direction. **`T-011` unblocked → `READY`.** |
| 2026-07-27 | `T-011` | `DONE`. First real table: `audit_event` with database-enforced append-only guarantees, `record_audit_event`, `Actor`/`ActorType`, migration `6ea1f40a0e13`, and 25 tests. | Two full `downgrade base` → `upgrade head` cycles clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `36 files already formatted`; `mypy app` (strict) `Success: no issues found in 25 source files`; `pytest -q` `386 passed`; boundary suite `10 passed`. | **Append-only is enforced by the database**: a row-level trigger on `UPDATE OR DELETE` plus a **statement-level** trigger on `TRUNCATE` (which bypasses row triggers and would otherwise erase the trail silently). `REVOKE` was rejected — the application user owns the table. A migration test asserts both triggers survive, so a later migration cannot quietly drop them. Added a §15.5 credential denylist for payload keys. **Two follow-on fixes:** the `db_session` fixture now guards `rollback()` with `is_active` (a provoked database error leaves the transaction unwound, and the `SAWarning` was fatal under `filterwarnings=["error"]`); and `T-006`'s "schema holds only `alembic_version`" test — written as a starting-point check — was replaced now that a real table exists. Also learned: PostgreSQL enum types outlive `drop_table`, so the downgrade drops `actortype` explicitly or a re-upgrade fails. **`T-012`, `T-013`, `T-016`, `T-023` unblocked → `READY`.** |
| 2026-07-27 | `T-013` | `DONE`. `Product`, `ProductStatusVersion`, `SourceDocument`, migration `259218227532`, readiness resolution service, and 21 tests. All fixtures synthetic. | `alembic upgrade head` → `downgrade base` → `upgrade head` clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `40 files already formatted`; `mypy app` (strict) `Success: no issues found in 27 source files`; `pytest -q` `407 passed`. | **"Exactly one readiness answer per instant" is a PostgreSQL exclusion constraint**, not an application check — a read-then-write guard would let two concurrent writers both commit overlapping windows. Uses `btree_gist` (contrib, present in `postgres:16`) to mix `product_id WITH =` and range overlap; `[)` bounds make a clean handover legal. Reads fail closed: `require_effective_status` raises rather than returning something stale (GP-12). `source_document_id` is `RESTRICT`, so deleting a readiness claim's justification is refused. **New task `T-136`**: `approved_by` is an identity string until `T-012`'s user table exists, then becomes a foreign key — documented in the model rather than left implicit. **`T-014`, `T-015` unblocked → `READY`.** |
| 2026-07-27 | `T-015` | `DONE`. `Campaign`, `TargetSegment`, `CampaignPolicyVersion`, a typed `CampaignPolicy` model, policy publish/resolve service, migration `5a91cde91f87`, and 25 tests. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `45 files already formatted`; `mypy app` (strict) `Success: no issues found in 30 source files`; `pytest -q` `432 passed`; boundary suite `10 passed`; **negative control** widening the default geography to `("US","DE")` failed 2 tests, green after restore. | **Took `T-015` before `T-014`** (both P0, both unblocked by `T-013`): `T-014`'s campaign-scoped claim rule needs campaign identity, and doing it first would have keyed the allow-list on campaign *strings* — a typo-tolerant field where a foreign key belongs. Rationale recorded on `T-014`. Policy is **typed, not loose JSON**: JSONB storage but always read through a frozen Pydantic model with `extra="forbid"`, so a drifted body fails loudly instead of quietly granting eligibility. Campaigns start `paused=True`; `allowed_countries=()` permits nothing rather than everything; `SELLABLE_NOW` is excluded from default readiness until `Q-021`/`Q-022`. Immutability of published policy is a trigger, with `superseded_at` the one mutable column. |
| 2026-07-27 | `T-014` | `DONE`. `ApprovedClaim`, campaign allow-list, `ApprovedClaimSet` + members, fail-closed resolution service, migration `173f99bbd4a0`, and 27 tests. All claims synthetic. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `49 files already formatted`; `mypy app` (strict) `Success: no issues found in 32 source files`; `pytest -q` `459 passed`; boundary suite `10 passed`; **negative control** patching the resolver to filter expired members instead of raising failed 2 tests, green after restore. | **The set fails whole.** `get_valid_claim_set` raises if any member is expired, superseded, or campaign-revoked — silently returning fewer claims than were approved is how an approved message becomes an unapproved one. Campaign scope is an **allow-list**, so absence of a link means *not permitted*. Claim wording is immutable by trigger (editing means publishing v2), and `is_synthetic` cannot be flipped by UPDATE. **Two Alembic hazards hit and documented in `docs/development.md`:** reusing an existing enum needs `create_type=False`, and `drop_table` leaves the enum type behind. Membership trigger is `UPDATE`-only by design — a `BEFORE DELETE` trigger cannot tell a cascade from a direct delete. **`T-040` unblocked → `READY`.** |
| 2026-07-27 | `T-016` | `DONE`. `Account`, `Contact`, `ContactPoint`, `CRMMapping`, a normalization module, migration `9c7510908885`, and 48 tests. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `53 files already formatted`; `mypy app` (strict) `Success: no issues found in 34 source files`; `pytest -q` `507 passed`; boundary suite `10 passed`. | **Negative control proved both normalization layers independently:** removing the email validator failed 2 tests, and the failure came from psycopg raising `IntegrityError` on the **check constraint** before the unique constraint could apply — so the ORM validator and the database each catch it alone. That redundancy is the point: normalization that happens on only some write paths would let a suppression recorded against one spelling miss the other (§15.6). Gmail dot/`+`-tag canonicalization deliberately **not** applied — wrong for other providers, and guessing two addresses are one person is worse than treating them as two. Added `uq_crm_mapping_external` beyond the required criterion so two internal records cannot claim one CRM record. The four new enums needed explicit downgrade drops — the hazard documented last cycle, applied without rediscovering it. **`T-017`, `T-018` unblocked → `READY`.** |
| 2026-07-27 | `T-017` | `DONE`. `Suppression` model with four scopes, permanence trigger, precedence-aware check functions, migration `614ee9042ca9`, and 26 tests. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `56 files already formatted`; `mypy app` (strict) `Success: no issues found in 35 source files`; `pytest -q` `533 passed`; boundary suite `10 passed`; **negative controls** removing domain-derivation-from-email failed 5 tests and removing the lifted-status filter failed 1, green after each restore. | **A real bug the tests caught:** the `TRUNCATE` guard silently did nothing. In a statement-level `TRUNCATE` trigger `NEW`/`OLD` are undefined, so the `IS DISTINCT FROM` checks compared NULL to NULL, passed, and would have let the whole suppression table be erased. `TRUNCATE` now shares the `DELETE` branch, before any `NEW`/`OLD` access; the `audit_event` equivalent was checked and is unaffected (it raises unconditionally). **Survival is structural:** the table has no foreign keys at all (asserted against `pg_constraint`), so nothing can cascade a suppression away. **Lifting is asymmetric by design:** `UNSUBSCRIBE`/`COMPLAINT` can never be lifted (CAN-SPAM, §15.8) and `source` is immutable so an opt-out cannot be relabelled and then lifted; operator errors remain correctable. `require_not_suppressed` takes no campaign argument — asserted by test, because no configuration may permit a suppressed recipient. **`T-094` unblocked → `READY`.** |
| 2026-07-27 | `T-018` | `DONE`. `CampaignCandidate` with the §8.1 identity triple, `create_candidate`/`transition` services routing through `assert_transition` and the audit trail, migration `deff839a67b6`, and 17 tests. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `59 files already formatted`; `mypy app` (strict) `Success: no issues found in 36 source files`; `pytest -q` `550 passed`; boundary suite `10 passed`; **negative controls** bypassing `assert_transition` failed 4 tests and removing the audit write failed 2, green after each restore. | **`NULLS NOT DISTINCT` on the identity key** — §14.2 allows an account-only candidate, and with default NULL handling two of them for the same campaign would both be accepted because NULL never equals NULL. Verified by the error text naming `contact_id)=…null already exists`. **Deliberate split of enforcement:** the identity triple is trigger-immutable (repointing would silently reassign every decision recorded against it), but `state` stays writable at the database level because transition legality is a sequence question owned by `app.core.lifecycles` — duplicating that table in plpgsql would create two rule sets to keep in step. `ineligible` requires a reason, enforced both in the service and by a check constraint. **`T-019` unblocked → `READY`.** |
| 2026-07-27 | `T-019` | `DONE`. `EvidenceSnapshot` with the full §14.3 provenance set, excerpt cap, staleness-aware read helpers, migration `6ed335d539bf`, and 29 tests. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `63 files already formatted`; `mypy app` (strict) `Success: no issues found in 38 source files`; `pytest -q` `579 passed`; boundary suite `10 passed`; **negative control** changing the excerpt validator to truncate instead of raise failed the test, green after restore. | **Excerpts are rejected, never truncated** — a silently shortened excerpt could drop the clause that justified the claim, leaving a reviewer looking at evidence that no longer says what it was cited for. Enforced by both an ORM validator and a check constraint (proven via raw SQL). **`contains_personal_or_confidential_data` has no default**, so an unanswered privacy classification cannot become "nothing sensitive". **Deliberate asymmetry with suppression:** snapshots are immutable (a refresh writes a new one, §9.5) but still deletable, because `Q-019` retention must be able to remove evidence about a person; suppression is the reverse. **A bug the tests caught:** the validator raised `TypeError` on `None`, masking a missing-excerpt insert as a type error instead of a NOT NULL violation. **`T-020` unblocked → `READY`.** |
| 2026-07-27 | `T-020` | `DONE`. `MessageDraft` and immutable `MessageRevision` with claim/evidence citation arrays, content hashing, supersession service, migration `57804e6a27d7`, and 30 tests. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `67 files already formatted`; `mypy app` (strict) `Success: no issues found in 40 source files`; `pytest -q` `609 passed`; boundary suite `10 passed`; **negative controls** removing the supersede call failed 3 tests and dropping recipient from the hash failed 1, green after each restore. | **Citations are array columns, not join tables** — a join table could gain a row after approval, changing what the message cites while the revision row looked untouched. As columns they are inside the immutable row and inside the hash; `T-055` will validate they exist and are current. **The recipient is part of the hash**: §11.4 approves "this message to this person" as one unit. **Citation order is preserved, not sorted**, so reordering invalidates — erring toward re-approval rather than silently keeping one. `state`/`retired_at` stay mutable because progressing a revision changes nothing about what it says. **`T-021` unblocked → `READY`.** |
| 2026-07-27 | `T-021` | `DONE`. `Approval` pinning revision, recipient, content hash, product status version and claim set; approve/reject/revoke/expire services; `invalidation_reason`/`require_valid`; migration `0133f6adb316`; 24 tests. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `71 files already formatted`; `mypy app` (strict) `Success: no issues found in 41 source files`; `pytest -q` `633 passed`; boundary suite `10 passed`; **negative controls** removing the revision-retired check failed 5 tests, removing the product-status check failed 1, removing the claim-set check failed 1 — together covering all six §8.4 triggers. | **Six §8.4 triggers reduce to three pinned values**: the revision content hash already covers recipient, subject, body, and personalization evidence (`T-020`), leaving product status and claim set. `require_valid` raises rather than returning a boolean so a forgotten check cannot send. **Defect found in `T-011`:** PostgreSQL `now()` is the *transaction* timestamp, so audit events written in one transaction shared an `occurred_at` and the trail was unorderable — §17.5 needs that history. Migration `262585e960c1` switches to `clock_timestamp()`. **Scope recorded:** the generic `entity_type`/`entity_id` was dropped because criterion 1 forces a NOT NULL revision and candidate approval is already a lifecycle transition (`T-018`). **`T-022` unblocked → `READY`.** |
| 2026-07-27 | `T-022` | `DONE`. `OutreachThread`, immutable `SendCommand` carrying the whole §11.4 contract, `SendAttempt`, `DeliveryEvent`, `Interaction`, migration `4ad849bbfecc`, and 29 tests. Records only — nothing sends. | `alembic` up/down/up clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `75 files already formatted`; `mypy app` (strict) `Success: no issues found in 43 source files`; `pytest -q` `662 passed`; offline guarantee — a test greps this module for `smtplib`/`httpx`/`requests`/`aiohttp` and finds none; **negative controls** making the idempotency key random failed 1 test and dropping the approval-validity check failed 1, green after each restore. | **The idempotency key is derived, not random** — `sha256(approval:revision:recipient)` — so a re-derived duplicate collides on the unique constraint, whereas a random key would make every retry look like a new send (§17.3). **`SendCommand` has no state column at all**: it is an order, fully immutable, and what happened to it lives in `SendAttempt`. If it were editable the key could be re-pointed at different content and the duplicate guard would stop guarding. **`delivery_unknown` is non-terminal but has no edge back to `sending`/`queued`** — reconciliation is the only exit (ADR-016). Ordering re-checks approval validity because §8.4 triggers can fire between ordering and dispatch. **`T-023` unblocked → `READY`.** |
| 2026-07-27 | `T-023` | `DONE`. `PromptVersion`, `SchemaVersion`, `ModelConfigVersion`, `PolicyVersion` with content hashing, non-overlapping effective windows, immutability triggers, generic resolvers, migration `e05624f3ae74`, and 52 tests. | `alembic` up/down/up run **twice** clean; `alembic check` → `No new upgrade operations detected.`; `ruff` `All checks passed!`; `ruff format --check` `78 files already formatted`; `mypy app` (strict) `Success: no issues found in 44 source files`; `pytest -q` `714 passed`; boundary suite `10 passed`; **negative controls** removing `sort_keys` failed the hash-stability test, removing the exclusion constraints failed the overlap test for all four tables. | **§18.4 enforced, not intended:** a test greps `app/**` for vendor markers (`claude-`, `gpt-4`, `deepseek`, `api.openai.com`…) and asserts none appear — model names live in `ModelConfigVersion`, not code. **Scope recorded:** `PolicyVersion` is the *global* policy record; campaign ICP/exclusions/volumes stay in `CampaignPolicyVersion` (`T-015`), and a test asserts the two stay distinct so nobody merges them. **Process slip:** a scripted edit adding the enum drop matched nothing (the generated downgrade drops `model_config_version` last, not `schema_version`), so re-upgrade failed with `type "modelprovider" already exists` — fixed, then the cycle was run twice to prove it. Also caught an invalid negative control: dropping constraints on `matrix_sales` proved nothing because tests build a throwaway database from migrations; redone at the migration level. **§14.1 entity map is now complete.** |
| 2026-07-29 | `T-030` | `DONE`. Durable PostgreSQL job queue: `Job` model, migration `63876c821f52`, per-instance `JobRegistry` with a Pydantic payload model per job type, `lease_jobs()` on `FOR UPDATE SKIP LOCKED`, the §7.2 run cycle in `runner.py`, and a thin `app/worker.py` process entry point. 23 tests. | `ruff` `All checks passed!`; `ruff format --check` `85 files already formatted`; `mypy app` (strict) `Success: no issues found in 49 source files`; `pytest -q` `737 passed`; `alembic` up/down-to-base/up clean; `alembic check` → `No new upgrade operations detected.`; **negative controls** — dropping enqueue-time payload validation failed 1 test, replacing the SAVEPOINT with a full rollback failed 2, green after each restore. | **The concurrency test uses two real connections leasing before either commits**, which is the only arrangement where `SKIP LOCKED` is distinguishable from a plain lock. But that test would *also* pass without `SKIP LOCKED` — the second worker would just block, then find nothing — so a second test asserts `SKIP LOCKED` is in the compiled SQL. The mutation control was deliberately skipped there: removing it wedges the run rather than failing it. **A failing handler rolls back to a SAVEPOINT, not the whole transaction** — a full rollback would discard the lease *including the incremented attempt count*, so a job failing forever would look like a job never tried. **Only the exception type name is stored**, never its message, since a message can quote payload contents (§15.5). `mark_for_retry` is deliberately policy-free — backoff and attempt limits are `T-031`, so a failing job currently retries immediately and forever. **Process slip:** the first SAVEPOINT negative control reported "no failure" because the scripted edit used CRLF against an LF file and matched nothing; redone with an explicit changed-content assertion, which then failed 2 tests as expected. Second time this cycle family that an unverified scripted edit lied — the assertion is now the habit. **`T-024`, `T-031`, `T-033`, `T-034`, `T-036` unblocked → `READY`.** |
| 2026-07-29 | `T-031` | `DONE`. Explicit per-job-type retry policy: `RetryPolicy` (validated at declaration), `classify()` returning one of §7.2's three failure outcomes with the reason to record, `compute_backoff()` with an injectable RNG, `PermanentFailure`/`NeedsHumanReview`, a `requires_human_review` disposition, and two check constraints. Migration `90aa0487c939`. 30 tests. | `ruff` `All checks passed!`; `ruff format --check` `88 files already formatted`; `mypy app` (strict) `Success: no issues found in 50 source files`; `pytest -q` `767 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up clean; `alembic check` → `No new upgrade operations detected.`; **7 negative controls** (uncapped delay, unlimited attempts, review collapsed into dead, retry-everything, flat backoff, and each check constraint removed **from the migration**) failed 1/2/3/1/2/2/1 tests respectively, green after each restore. | **`retry_policy` is keyword-required with no default**, so §17.1's "explicit per job type" is enforced by the signature rather than by a convention someone can forget. **`retryable` is a whitelist, not a blacklist** — an unrecognized exception is treated as permanent, because an unfamiliar error is more likely a bug we would retry forever than a network hiccup. **`R-003` recorded:** §7.2 names four outcomes but §8.2's job lifecycle has five states and no review state, so "requires human review" is a *disposition* on terminal `dead`, not a sixth state — adding one would break ADR-015's lifecycle independence to satisfy a different section. **§17.1's reason requirement is in the schema**, not only in `mark_dead`: `dead_job_must_carry_a_reason` rejects a null or blank `last_error` on a dead row. **`classify` reduces non-sentinel exceptions to a type name** before it ever reaches `last_error`, so a payload value cannot leak into an operator-facing field via an exception message (§15.5) — asserted directly. **Process note:** two controls initially proved nothing — one because `ruff format` had reflowed the target expression, one because the constraint control was applied to the model while tests build the schema from migrations (the T-023 trap again). Both were redone correctly; the control script now aborts when its edit matches nothing. **`T-032` unblocked → `READY`.** |
| 2026-07-29 | `T-034` | `DONE`. Transactional outbox: `OutboxEvent` with a unique sha256 idempotency key and a partial pending index, `enqueue_outbox_event()` which writes its own audit event, and `commit_with_outbox()` which refuses an outbox event that arrives without an audit event or without business state. Migration `f09d40b96a8b`. 15 tests. | `ruff` `All checks passed!`; `ruff format --check` `91 files already formatted`; `mypy app` (strict) `Success: no issues found in 51 source files`; `pytest -q` `782 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up **twice** clean; `alembic check` → `No new upgrade operations detected.`; **6 negative controls** (audit check removed, business-state check removed, unflushed-only inspection, unique key dropped from the migration, sha256-shape constraint dropped from the migration, event never flushed) failed 1/2/2/1/1/4 tests, green after each restore. | **`commit_with_outbox` cannot inspect `session.new`** — that was my first implementation and five tests caught it. A flush empties the collection, and both `enqueue_outbox_event` and ordinary autoflush flush, so the check would have inspected an empty set and waved through precisely the commit it exists to stop. It now accumulates written kinds in `session.info` from an `after_flush` listener, cleared on commit and soft-rollback; negative control C restores the naive version and fails. **No foreign key from `outbox_event` to `send_command`**, deliberately: §18.2 forbids `jobs_and_outbox` from knowing the domain, and that has to hold for schema edges and not only Python imports. The shared `idempotency_key` is the join — unique in *both* tables, so it links them *and* makes a second outbox row for one approved send impossible, which is what §17.3 wanted anyway. A test asserts the table has no foreign keys at all, and `docs/architecture/modules.md` now states the schema-edge rule. **`OutboxState` lives in the outbox module, not `core/lifecycles.py`**: that file holds §8.2's five entity lifecycles and ADR-015 requires them independent; a test asserts `LIFECYCLES` still has exactly five members and does not include `OutboxState`. **`T-035` stays `PLANNED`** — it also depends on `T-033`. |
| 2026-07-29 | `T-033` | `DONE`. Operational kill switches: `OperationalFlag` store with audited changes, the composed resolvers, a `GuardedAdapter` base that checks the switches in its own entry point, `consequential` as a required job-type declaration, and pause enforcement by *excluding* paused types from leasing. Migration `4a4c4bf4623e`. 33 tests. **Split `T-137`** (approval revocation) out of scope. | `ruff` `All checks passed!`; `ruff format --check` `94 files already formatted`; `mypy app` (strict) `Success: no issues found in 52 source files`; `pytest -q` `815 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up **twice** clean; `alembic check` → `No new upgrade operations detected.`; **8 negative controls** (flag alone decides shadow mode, adapter stops checking shadow mode, shadow mode stops blocking email, reason not required, pause stops excluding types, `exclude_types` ignored, `NULLS NOT DISTINCT`→`DISTINCT` in the migration, scoped-key constraint removed from the migration) failed 4/2/1/1/2/2/1/2 tests, green after each restore. | **The two configuration layers compose by conjunction, never by override.** Shadow mode is on if *either* the environment or the flag says so; outbound email needs *all four* switches to agree. A flag that could turn shadow mode off would make the environment setting decorative — control A asserts exactly that and fails. **A pause excludes consequential types from the lease rather than refusing them after it.** Refusing post-lease would burn attempt budget and eventually dead-letter work nobody meant to abandon; §17.1's "preserving inspectability" means the held row stays `queued` with `attempt_count == 0`, which is asserted directly. `execute` keeps a second check for a pause thrown between lease and run. **`consequential` is keyword-required on registration** for the same reason `retry_policy` is: guessing what a global pause covers is the guess an operator cannot afford. **Campaign pause was *not* duplicated here** — `Campaign.paused` already exists from T-015, and a second source of truth for one question is how a paused campaign ends up sending; the checkpoint takes it as a parameter because `audit_and_operations` may not import `campaigns`. **Coverage gap found by a control:** the `NULLS NOT DISTINCT` clause was initially untested, because `set_flag` reads before writing and so never reaches the constraint. Four raw-insert tests now cover it and both check constraints; control G2 fails without the clause. **`T-035` unblocked → `READY`; `T-137` added → `READY`.** |
| 2026-07-29 | `T-035` | **Split** into `T-035a` / `T-035b` / `T-035c` and left `PLANNED` as the acceptance-intent record. | — (no code in this entry) | One change set covering the adapter layer, effectively-once dispatch semantics, *and* nine cross-module rechecks is not reviewable, and the rechecks need fixtures from six other modules. Criteria map explicitly: 4 and 5 → `T-035a`; 2 and 3 → `T-035b`; 1 → `T-035c`. The parent becomes `DONE` only when all three children are, so nothing is quietly dropped. |
| 2026-07-29 | `T-035a` | `DONE`. The external-effect boundary: `EffectOutcome`, frozen `EffectRequest`/`EffectResult`, `SupportsReconciliation`, and `ExternalEffectAdapter` inheriting the §17.6 guard; `FakeExternalEffectAdapter` with five scenarios and a real effect ledger. `GuardedAdapter` made generic over request and result. 34 tests, no migration. | `ruff` `All checks passed!`; `ruff format --check` `98 files already formatted`; `mypy app` (strict) `Success: no issues found in 55 source files`; `pytest -q` `849 passed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`; **7 negative controls** (real `httpx2` import in the fake, `AMBIGUOUS` made safe to retry, `ACCEPTED` without a correlation ID, guard skipping shadow mode, timeout not recording its effect, success not recording its effect, rate limiting reported as ambiguous) failed 1/2/1/2/1/3/2 tests, green after each restore. | **A timeout and an explicitly ambiguous acceptance collapse to one outcome.** They arrive differently — silence versus a provider saying "maybe" — but §17.3 requires identical handling, and two outcome values is how someone eventually treats the timeout as a failure and retries it blindly. The distinction survives in `detail`, for humans, never in control flow. **`SAFE_TO_RETRY` contains exactly one value**, and control B (adding `AMBIGUOUS` to it) fails 2 tests. **The fake is not a mock**: it keeps an effect ledger keyed by idempotency key, and the `TIMEOUT` scenario writes to it *while returning `AMBIGUOUS`* — so `reconcile()` can discover that a blind retry would duplicate a real effect, which is the precise scenario §17.3 exists for. A call-counting mock could not distinguish "sent twice" from "sent once, asked twice"; `test_repeating_one_key_is_distinguishable_from_two_effects` asserts 2 calls / 1 effect. **`EffectResult` refuses to be constructed as `ACCEPTED` without a provider correlation ID** — without one there is nothing for §17.3 to reconcile against. **The no-network check parses with `ast`, not grep**: a text search is fooled by the word in a comment and misses any import spelling it did not anticipate. Control A adds a genuine `import httpx2` and the check catches it. **`GuardedAdapter` is now generic** rather than `**kwargs`-shaped, so `_perform` is typed at the boundary; the T-033 adapter tests were updated to match. **`T-035b` unblocked → `READY`.** |
| 2026-07-29 | `T-035b` | `DONE`. The outbox dispatcher: `OutboxState.DELIVERY_UNKNOWN`, a local `OUTBOX_TRANSITIONS` state machine, six bookkeeping columns, `lease_outbox_events` on `FOR UPDATE SKIP LOCKED`, `dispatch_event`, `dispatch_once`, and `reconcile_unknown`. Migration `025c23d5d4bc`. 24 new tests (58 in the file). | `ruff` `All checks passed!`; `ruff format --check` `99 files already formatted`; `mypy app` (strict) `Success: no issues found in 55 source files`; `pytest -q` `873 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up **twice** clean; `alembic check` → `No new upgrade operations detected.`; **4 valid negative controls** (`DELIVERY_UNKNOWN` made leasable, ambiguous filed as `FAILED`, reconciliation not asking the provider, unleased event accepted) failed 1/4/1/1 tests, green after each restore. | **"No blind retry" is enforced by absence, not by a branch.** `DELIVERY_UNKNOWN` is simply not in `DISPATCHABLE_STATES`, so the lease query cannot see the row — there is no retry decision to get wrong. Control A adds it back and the test fails. Its only exits are the two reconciliation outcomes, asserted directly. **`reconcile_unknown` is the sole way out**, and it asks the provider *before* anything is sent: if the effect already happened the event resolves to `DISPATCHED` with `len(adapter.calls)` still 1. **Effectively-once is measured as calls ≠ effects** — the replay test makes two genuine attempts and asserts 2 calls, 1 effect, which a call-counting mock could not distinguish. **`OUTBOX_TRANSITIONS` lives in the outbox module**, not `core/lifecycles.py`, for the R-003 reason; it refuses self-transitions too, since re-entering a state writes an audit event for a change that did not happen. **Migration note:** autogenerate does not detect a new enum *value*, so `ALTER TYPE outboxstate ADD VALUE` is hand-written; the downgrade deliberately leaves the value, because PostgreSQL cannot drop one and downgrading past `f09d40b96a8b` drops the type anyway. **Process failure worth recording:** I ran a `SKIP LOCKED`-removal control here despite having correctly refused the same control in `T-030` for the same reason — without it the second connection *blocks* rather than failing, so pytest hung for 10 minutes and left `dispatch.py` mutated. I stopped the task, killed the process, and restored the file with an explicit content check. The mechanism is pinned by a compiled-SQL assertion instead, exactly as in `T-030`. Lesson recorded: a control that removes a *lock-avoidance* primitive is never safe to run. **`T-035c` unblocked → `READY`.** |
| 2026-07-29 | `T-035c` | `DONE`. The §11.4 dispatch-time rechecks: `preconditions.py` in `outreach_and_replies`, an injected `PreconditionCheck` protocol in the dispatcher, `DispatchRefused`, and `tests/factories.py` extracted so one fixture chain serves both suites. 34 tests, no migration. **`T-035d` split out, `BLOCKED` on `Q-004`.** | `ruff` `All checks passed!`; `ruff format --check` `102 files already formatted`; `mypy app` (strict) `Success: no issues found in 56 source files`; `pytest -q` `907 passed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`; **6 negative controls** (dispatcher not running the rechecks, suppression not re-checked, recoverable refusal spending the budget, paused campaign treated as permanent, approver stamp not compared, audit event not naming the check) failed 4/5/1/2/1/1 tests, green after each restore. | **Six of §11.4's nine conditions were already enforced** by `invalidation_reason` (§8.4) — approval state, expiry, exact recipient, exact revision content, product-status version, and claim-set version are all pinned on the approval and checked there. I wrote duplicates of two of them; both fired *second* and reported the wrong condition, which is how I found out. The duplicates are deleted and the module docstring now carries a delegation table, so the next person does not repeat it. **`jobs_and_outbox` still knows nothing about approvals**: the check is an injected `PreconditionCheck` taking the *idempotency key*, and the dispatcher reads `check`/`detail`/`is_recoverable` off the refusal by attribute rather than importing the domain exception type. The T-034 key-as-join is what makes this possible at all. **A recheck refusal never touches the adapter and never counts as a provider attempt** — a recoverable one (paused campaign, volume cap) refunds the attempt the lease spent and returns the event to `PENDING`, because burning budget on a condition that will become valid again dead-letters work nobody abandoned. **§11.4's "as configured" does not narrow suppression:** `T-015` had already decided a policy may widen and never narrow at send time, so the recheck queries all four scopes unconditionally; I nearly implemented the opposite and a test now pins it. **Several conditions are unreachable rather than unchecked** — `send_command` is immutable by trigger and its contract fields are `RESTRICT` FKs copied from the approval, so "the command points somewhere else" is prevented; two tests assert that instead of asserting a refusal that cannot happen. **Process:** five of my first-draft tests were invalid because they mutated immutable rows, and one suppression fixture used the real clock while the rechecks ran at a fixed `NOW` — the same defaulted-timestamp trap as `T-030`. **Ledger repair:** a scripted edit had left a duplicated `Completion evidence` line in `T-035c`, and a later global backtick replacement damaged a code fence at line 65; both fixed and verified. |
| 2026-07-29 | `T-032` | `DONE`. Lease expiry recovery: `find_expired_leases` + `reclaim_expired_leases` in a new `recovery.py`, wired into the worker loop before each lease. 12 tests, no migration. **`T-138` added** for outbox dispatch-lease recovery. | `ruff` `All checks passed!`; `ruff format --check` `104 files already formatted`; `mypy app` (strict) `Success: no issues found in 57 source files`; `pytest -q` `919 passed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`; **6 negative controls, 5 valid** (ignoring lease expiry, leaving the stale holder, double-charging the attempt, losing the audit action name, ignoring the reclaim bound) failed 2/7/3/1/2 tests, green after each restore. | **The reclaim does not increment `attempt_count`, which departs from the task's own scope line.** `lease_jobs` already charged the attempt, so a crash costs exactly one; charging again would dead-letter a job in half its configured attempts, meaning one unlucky restart costs a job the retries its policy promised. The scope line's *intent* — a crash consumes budget so a poisonous job still stops — is satisfied by the lease increment, and `test_repeated_crashes_still_exhaust_the_budget` proves that direction while `test_a_crash_consumes_exactly_one_attempt` proves the other. **The "already-committed effect" guard the scope asked for turned out to be structural, not new code:** a finished job has no lease, because `leased_state_needs_a_holder` forbids it and `T-030` commits outcome and lease release in one transaction — so a completed job is invisible to the reclaim query. A test asserts that instead of adding a redundant check. **Crashes are simulated with a real `rollback`, not a mock**, which is what `SIGKILL` looks like to PostgreSQL; the harder shape — lease *committed* before the worker died, so the job would sit `leased` forever — has its own test. **A control proved nothing and it is recorded:** removing `assert_transition` broke no test, since the query only selects `LEASED` rows. It is forward-defence against a widened query, and `test_only_a_leased_job_may_return_to_the_queue` now pins the rule directly. **`T-138` was split out rather than folded in** — an expired *dispatch* lease is ambiguous under §17.3 because the dispatcher may have reached the provider, so requeueing it the way jobs are requeued would be the blind retry §17.3 forbids. **Ledger defect fixed:** the "Next recommended `READY` task" header had been stale since the `T-035a` cycle — a combined scripted edit succeeded on its other strings, so the no-change guard never tripped. Header edits are now applied and verified by line index. |
| 2026-07-29 | `T-138` | `DONE`. Outbox dispatch-lease recovery: `find_expired_dispatch_leases` + `reclaim_expired_dispatch_leases` in `recovery.py`, settling to `DELIVERY_UNKNOWN`. 12 new tests (70 in the file). No migration — the transition and the columns already existed. **`T-139` added.** | `ruff` `All checks passed!`; `ruff format --check` `104 files already formatted`; `mypy app` (strict) `Success: no issues found in 57 source files`; `pytest -q` `931 passed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`; **6 negative controls, all valid** (requeueing to `PENDING`, ignoring lease expiry, losing the audit action name, leaving the dead dispatcher holding the lease, making `DELIVERY_UNKNOWN` dispatchable, ignoring the reclaim bound) failed 4/1/1/1/2/2 tests, green after each restore. | **This is why `T-138` was not folded into `T-032`.** A job that died mid-run committed nothing, so requeueing is safe; a *dispatcher* that died may have reached the provider first, so requeueing would be the blind retry §17.3 forbids. Control A implements exactly that mistake and 4 tests fail. **The crash test uses one adapter instance across three sessions** so its ledger stands in for the provider's own memory: the dispatcher performs the effect, commits its lease, dies; reclaim marks the event unknown; reconciliation finds the effect and resolves to `DISPATCHED` with `effect_count == 1` and `len(calls) == 1` — nothing sent twice. The mirror case (never reached the provider) returns to `PENDING` and the retry produces exactly one effect. **Coverage gap closed:** `recovery.py` now settles outbox events, so it belongs on the dispatch path; it was added to `DISPATCH_PATH` in the `T-035a` no-network check and the bound guard raised 6 → 7. Without that it would have been the one dispatch-path module still free to import a provider client. **Boundary pinned:** expiry is `<=`, matching `Job.is_lease_expired_at`; my first draft asserted the opposite and the test caught it, so `test_the_expiry_boundary_is_inclusive` now states it — an off-by-one either reclaims while a dispatcher may still be mid-call, or leaves a dead lease held forever. **Real gap found and recorded as `T-139`:** `worker.py`'s docstring claims the worker owns "outbox dispatch", but its loop only calls `run_once`. `dispatch_once` and both reclaims are tested and callable, and *nothing in a running process calls the outbox ones* — so a committed decision currently never reaches its effect without a human. Not widened into this task, whose criteria are all about the reclaim. |
| 2026-07-29 | `T-139` | `DONE`. `one_pass()` + `PassResult` in `worker.py` compose both reclaims, `run_once`, and `dispatch_once` with `send_precondition_check` injected; `build_effect_adapter()` supplies the fake; `main()` loops on it and sleeps on `did_nothing`. New `tests/test_worker_cycle.py`, 15 tests. No migration. | `ruff` `All checks passed!`; `ruff format --check` `105 files already formatted`; `mypy app` (strict) `Success: no issues found in 57 source files`; `pytest -q` `946 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up clean; `alembic check` → `No new upgrade operations detected.`; **6 negative controls, all valid** (dropping the precondition injection, removing the `dispatch_once` call, removing the dispatch reclaim, letting a kill switch propagate, spending the budget on a switch, building the adapter without `is_email`) failed 2/4/2/4/1/1 tests, green after each restore. | **Wiring it up found a real bug, which is the whole argument for the task.** A §17.6 kill switch raised `ExternalEffectBlocked` straight out of `dispatch_once`, so the **first pending event would have killed the worker whenever shadow mode was on — and shadow mode is the shipped default.** A switch is an operator decision, not an error: `dispatch_event` now catches both switch exceptions, settles the event back to `PENDING` with backoff, refunds the attempt the lease charged, records an audit event naming the switch, and re-raises as `DispatchRefused(recoverable=True)` so the batch continues. Control D restores the old behaviour and 4 tests fail. Everything about that path was individually tested before; the defect existed only in the composition nobody had written. **`one_pass` is where §18.1's worker actually becomes whole**, and it has to live in `worker.py`: `jobs_and_outbox` may not import `outreach_and_replies` (§18.2), so nothing inside it can hand the dispatcher a §11.4 check, and `worker.py` is the leaf allowed to know both halves. `test_one_pass_applies_the_dispatch_time_rechecks` proves the injection is real by pausing the campaign — without it the send would go through. **Deviation from the scope line:** it asked to "select the adapter from settings". `build_effect_adapter` takes `settings` and deliberately does not branch on it — the fake is the only adapter, `Q-004` has chosen no provider, and a settings field whose sole legal value is `"fake"` would read as though a real option existed. The parameter stays so the call site is unchanged when `G-07` opens. **A structural test** asserts `one_pass` references all five collaborators by name, so an edit that silently drops one restores the exact gap this task closed. |
| 2026-07-29 | `T-036` | `DONE`. Webhook intake: `WebhookEvent` with a unique `(provider, external_event_id)`, HMAC-SHA256 verification over `timestamp.body`, a freshness window in both directions, idempotent duplicate handling, and enqueue-for-processing. `webhook_signing_secret` added to `Settings` and `.env.example`. Migration `224564968fc6`. 26 tests. | `ruff` `All checks passed!`; `ruff format --check` `108 files already formatted`; `mypy app` (strict) `Success: no issues found in 58 source files`; `pytest -q` `972 passed`; boundary suite `10 passed`; `alembic` up/down-to-base/up **twice** clean; `alembic check` → `No new upgrade operations detected.`; **6 negative controls, all valid** (signature not verified, timestamp dropped from the signed material, blank secret treated as no-check, stale accepted, forward-dated accepted, duplicate detection removed) failed 3/1/1/2/1/3 tests, green after each restore. | **Placed in `outreach_and_replies`, not `messaging`.** The task allowed either, but `messaging` is forbidden from importing `jobs_and_outbox` (§18.2) precisely because ADR-006 keeps the messaging gateway out of the workflow — and "enqueue for processing" makes it one. Delivery and reply webhooks *are* a workflow dependency: they feed §17.3 reconciliation. **Replay protection is the composition of two guards, and both halves have their own test.** A captured request replayed *inside* the window is stopped by id uniqueness — one event, one job; replayed *after* it, refused outright before any lookup. Neither alone suffices: a window with no id check allows free replay for the window's width, and an id check with no window allows replay forever once the id is purged. **A forward-dated timestamp gets its own rejection reason**, because a forged future timestamp would otherwise never go stale — an attacker signs one request dated a year out and replays it all year. **The timestamp is inside the signed material**, so a captured body cannot be re-signed with a fresh one; pinned directly rather than inferred, since that single omission defeats the whole window. `hmac.compare_digest`, not `==`, because a plain comparison leaks how much of the signature matched. **A blank secret rejects everything rather than accepting everything** — the failure mode of treating "unconfigured" as "no check needed" — and blank is the shipped default. **Nothing is stored unless it verified:** a `signature_valid` check constraint makes an unverified row impossible, and rejected requests are not persisted at all, since a table of rejected requests would be an attacker-controlled write primitive. **A verified event with no registered handler is still stored** and warned rather than raised: dropping a verified provider notification is worse than holding one nobody can interpret yet (`T-103` classifies replies). **Caught by an existing guard:** `test_env_example_documents_every_setting` from `T-004` failed until `WEBHOOK_SIGNING_SECRET` was documented — the drift test did its job. |
| 2026-07-29 | `T-024` | `DONE`. `tests/test_invariants.py` — 23 tests across all six cross-entity invariants, **no production code changed**. Four hold; two do not and were filed as **`T-140`** and **`T-141`**. | `ruff` `All checks passed!`; `ruff format --check` `109 files already formatted`; `mypy app` (strict) `Success: no issues found in 58 source files`; `pytest -q` `993 passed, 2 xfailed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`; **5 negative controls, all valid** (rejected candidate made re-approvable, dead job allowed to resume, a domain module naming another lifecycle, a state-moving module dropping its guard, `Suppression` given a state) failed 1 test each, green after each restore. | **Two genuine gaps found, and filed rather than fixed — which was the task's own instruction.** `T-140`: `request_approval` takes a revision and never consults its candidate's state, so a *rejected* candidate's draft can still be approved; a human's "do not contact this prospect" decision is contradicted with nothing recording the contradiction. `T-141`: `transition_thread` checks the lifecycle table but not that a send command exists, so a thread can sit in `queued` asserting an approval that does not exist — lower priority because nothing external happens on that transition, but thread state is what the dashboard reads. Both are `xfail(strict=True)` naming their task, so implementing the guard turns the marker into a failure telling the author to delete it; the finding cannot be quietly lost, and the suite stays green meanwhile. **Invariant 6 is enforced structurally rather than by review.** `LIFECYCLE_OWNERS` maps each lifecycle to the packages allowed to *name* it and an `ast` scan fails if any other module imports it — a function that moves two lifecycles has to name both, so import-level checking catches the coupling where it first appears. A second scan asserts every module assigning `.state` also imports `assert_transition`. `worker.py`/`main.py` are exempt with the reason stated: composition is their job and nothing imports them. Two guard-on-guard tests assert the owner map covers every lifecycle and that the state scan is not vacuous. **A test-writing finding:** my first draft moved candidates straight to `REJECTED`/`APPROVED` and three tests failed — §8.2 has no shortcut from `imported` to a decision, it must walk eligible → research_pending → researched → review_pending. The helper now walks the legal path one step at a time, which is the right shape regardless: a test that assigned state directly would have been testing nothing. |
| 2026-07-29 | `T-140` | `DONE`. Approval now consults its candidate's state at **both** layers: `require_approvable_candidate` in `request_approval` *and* `approve`, plus a `Recheck.CANDIDATE_DECISION` in the §11.4 dispatch rechecks. 12 new tests; `T-024`'s xfail on this invariant removed. No migration. | `ruff` `All checks passed!`; `ruff format --check` `109 files already formatted`; `mypy app` (strict) `Success: no issues found in 58 source files`; `pytest -q` `1006 passed, 1 xfailed`; boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`; **6 negative controls** (request-time check removed, `approve` not re-reading, `candidate_refusal` always permitting, dispatch recheck disabled, `DEFERRED` removed from the set) failed 5/1/6/1/1 tests, green after each restore. | **Both layers, not one.** The scope offered "`request_approval`/`approve` **or** a §11.4 recheck" and the note said both may be wanted — they are not substitutes. Approval-time gives the reviewer immediate feedback; the dispatch recheck catches a candidate rejected *after* approval, which is what happens when a colleague rejects the prospect while a send sits in the outbox. Doing only the first would have left that hole open while the task claimed to close it. **`approve` re-reads rather than trusting `request_approval`**, because the reviewer window is exactly where a rejection lands. **ADR-015 is preserved by reading, never writing:** a test asserts at the source that `approval.py` imports neither `transition_candidate` nor assigns `candidate.state`. Independence forbids one module *transitioning* another's entity; it cannot forbid consulting one, or no cross-entity invariant could be enforced at all. **`T-024`'s own structural guard caught this change** — `drafts_and_approvals` now names `CampaignCandidateState`, which `LIFECYCLE_OWNERS` forbade. I did **not** widen the owner set, which would have been a hole; a separate `LIFECYCLE_READERS` map records who may read and why, and `test_a_reader_never_transitions_what_it_reads` holds each listed reader to reading only. **A control found a tautology in my own test:** removing `DEFERRED` from the non-approvable set broke nothing, because the parametrized test drew its cases *from* that set — shrinking it removed a case instead of failing one. The set and its complement are now pinned explicitly and the redone control fails correctly. **Two more existing guards fired**, both catching my test rather than the system: `ineligible` is reachable only straight from `imported` (§8.2 makes it a screening outcome, not a review one), and `T-018` requires a reason for negative outcomes. |
| 2026-07-29 | `T-141` | `DONE`. `ThreadNotStartable` + `require_send_command` in `commands.py`, called from `transition_thread` only when the previous state is `not_started`. 4 new tests; three `T-022` tests updated. **The last xfail in the suite is gone — both `T-024` findings are closed.** No migration. | `ruff` `All checks passed!`; `ruff format --check` `109 files already formatted`; `mypy app` (strict) `Success: no issues found in 58 source files`; `pytest -q` `1010 passed` (no xfailed); boundary suite `10 passed`; `alembic check` → `No new upgrade operations detected.`; **3 negative controls, all valid** (guard removed entirely, `require_send_command` always permitting, guard applied to every transition) failed 3/2/1 tests, green after each restore. | **Three `T-022` tests had to change, and the guard was right rather than the tests.** They moved a thread out of `not_started` with no command because they were exercising the lifecycle table in isolation; each now orders a command first, which is the correct precondition — reaching `delivery_unknown` presupposes a send was actually authorized. **The exit test parametrizes over `ALLOWED_TRANSITIONS[NOT_STARTED]`** rather than checking `queued` alone, so an edge added to the table later is covered the day it is added instead of quietly bypassing the guard. **An honest limit worth recording:** over-application is not behaviourally detectable. Once a command exists the query succeeds at every transition, so applying the guard to *every* transition still passes every functional test — control C only tripped the structural assertion. That test exists because the behavioural route is closed: `SendCommand` is immutable and FK-restricted, so "a command that later vanishes" is not constructible. **Why here and not in the §11.4 rechecks:** by dispatch time a command exists by definition, so a recheck there would be unreachable. This guards the truthfulness of the *record* — thread state is what the review dashboard reads — not an external effect. |

> The progress log is a summary trail, not a substitute for updating the task entry itself. Every run
> updates both.
