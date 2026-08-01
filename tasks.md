# Matrix Power Always-On AI Sales Agent — Implementation Backlog and Progress Ledger

> **This file is the authoritative work ledger for the development loop.** Read [process.md](process.md)
> before changing anything here.

| Field | Value |
|---|---|
| **Project** | Matrix Power Always-On AI Sales Agent |
| **Source specification** | `MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md` (v0.3, dated 2026-07-27, status: *Approved architecture for buildout and shadow deployment; live outreach remains gated*) |
| **Specification location** | `docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md` (repo-local; placed there by the user on 2026-07-27). SHA-256 `E571FC36420FEB7786AB2C984D24FDF0E100E89C6974E80F56C5D66173C57D9A`, 92,997 bytes. `MATRIX_POWER_NEMOCLAW_SALES_AGENT_SPEC_v0.2.md` is **SUPERSEDED** (spec §22) and is deliberately not vendored. |
| **Current implementation stage** | **Stage 2 — Review dashboard** (spec §19.6), entered 2026-07-31. Stage 1 is complete: the import→membership→eligibility→evidence→qualification→draft→validated-revision pipeline runs end to end through the worker on synthetic fixtures with zero external writes — see [docs/stage1-exit-evidence.md](docs/stage1-exit-evidence.md). The dashboard now has sign-in, the review card, and all five §12.3 item 6 actions live (127 frontend tests). |
| **Current stage exit gate** | **G-10** — a non-engineer completes reviews without understanding the agent stack. (**G-02**, the Stage 1 exit, is **OPEN** as of 2026-07-31.) |
| **Last updated** | 2026-07-31 |
| **Next recommended `READY` task** | **`T-157` — the approval transaction pins no version, so two §8.4 triggers can never fire** (P1). Confirmed by the 2026-07-31 checkpoint as its only HIGH finding and linked to gate **G-10**. (`T-068b` — promoted by the audit — `T-137` residual, `T-152`, `T-135`, and `T-007` are also `READY`; `T-158` is `BLOCKED` on a user commit decision.) |
| **`IN_PROGRESS` task** | *none* |
| **Latest checkpoint** | [docs/checkpoints/2026-07-31_stage2_checkpoint.md](docs/checkpoints/2026-07-31_stage2_checkpoint.md) — **PASS_WITH_ACTIONS** (2026-07-31). Baseline: commit `62514a4904cc` + full working tree. Open audit tasks: `T-157` (HIGH, gate-linked), `T-158` (BLOCKED on user commit authorization). Audit annotations on `T-137`, `T-152`, gate **G-10**. |

> ⚠️ **LIVE OUTREACH IS GATED.** No email send, no message send, no CRM mutation, no production
> credential, no deployment, no LinkedIn automation, and no autonomous follow-up may occur until the
> corresponding gate in §5 is explicitly unlocked by the user with the required stakeholder decisions
> recorded. Every gate below is **LOCKED** except **G-01** and **G-02** (open). All data in this repository must be synthetic.
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
- **Checkpoint note (2026-07-31):** Most of this scope now exists via `T-021` (`approval.revoke()`, actor + reason + audit event) and `T-068a` (`POST /api/review/approvals/{approval_id}/revoke`, non-dispatchability proven at `require_valid`). **Residual scope only:** (a) the *function* accepts a blank reason — only the HTTP schema refuses one — so criterion 2 is not enforced at the entry point; (b) revoking a terminal approval surfaces as `IllegalTransition` rather than a domain refusal at the entry point. Do not rebuild what exists; close the two gaps and mark the overlap in evidence.
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
- **Status:** `DONE` (2026-07-31)
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
- **Completion evidence:** `uv run pytest -q tests/test_identity.py` -> **27 passed**; full suite **1694 passed** (was 1667); `ruff check .` clean; `ruff format --check .` 172 files formatted; `mypy app` clean on 96 source files; `alembic check` -> No new upgrade operations detected; migration `ba1a2b2420a4` reverses and **re-applies** cleanly.
  1. **Six roles seeded by migration** — `test_the_six_roles_are_seeded`, `test_each_seeded_role_carries_its_responsibility` (§12.1's wording verbatim), `test_the_migration_seed_agrees_with_the_module` (the migration hard-codes the roles rather than importing `app.identity.models`, because a migration that imported application code would seed whatever the code says *today* and replaying history would build a different database — this test is what keeps the two copies honest), and `test_role_ids_are_stable_across_a_rebuild` (deterministic `uuid5`, so a `user_role` row dumped from one database and loaded into a freshly migrated one still points at the same role).
  2. **A `ChannelIdentity` cannot exist without a `User`** — `test_a_channel_identity_cannot_omit_its_user` (raw SQL against the `NOT NULL`, so "an unmapped handle" is unrepresentable rather than discouraged), `test_a_channel_identity_cannot_name_a_user_that_does_not_exist` (the foreign key), `test_one_address_maps_to_one_user`, and `test_the_same_address_on_two_channels_is_allowed` — one phone number is legitimately both a WhatsApp and an iMessage handle, so uniqueness is per channel.
  3. **Services cannot hold human-only roles** — `test_a_service_cannot_hold_a_human_only_role` parametrized over all five, plus `test_a_service_cannot_claim_a_human_only_role_by_lying_about_the_flag`, which closes the obvious way around it. `test_a_service_may_hold_the_viewer_role` and `test_a_human_may_hold_any_role` prove the restriction is on services rather than on people (§12.1: one person may hold several).
- **Design:** the service-role restriction is a **composite foreign key**, not a trigger and not an application check. `role` carries a unique `(id, human_only)`; `service_identity_role` carries a `human_only` column pinned to `false` by a check constraint and joined to that key. A grant naming a human-only role has no matching row, so the insert fails — and if a role is ever flipped to human-only, the grants that depended on it fail rather than silently widening. Humans and services are **separate tables** rather than one table with a flag: §12.2 requires the separation, and a boolean is exactly the shape that lets a query forget to filter. `test_no_identity_table_has_a_password_column` asserts against `information_schema` rather than the models, because what must not exist is a *column* — a future migration could add one that no model names.
- **Negative controls (applied by line index after `ruff format` reflowed the file, `grep`-confirmed, observed failing, restored, re-verified green):** removing the composite foreign key from the migration -> 5 failed; removing the `human_only = false` check -> 1 failed; making `channel_identity.user_id` nullable -> 1 failed; seeding `reply_owner` with the wrong `human_only` -> 3 failed. All four mutate the **migration**, not the model metadata, because that is what the test schema is built from.
- **Found while verifying:** the first migration passed `upgrade` and `downgrade` but failed on `downgrade` *then* `upgrade` — dropping a table does not drop its enum, so `CREATE TYPE channeltype` hit an existing type. `process.md` §5 asks for reversal; re-application is what actually caught it. The downgrade now drops the enum explicitly.
- **First three controls did not match and said so.** They were written against the pre-`ruff format` text; the scripted asserts refused rather than writing nothing and reading as passes. Re-applied by line index against the formatted file.

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
  - Checks: canonical set green (§2) — `pytest -q` 993 passed; `mypy app` (strict) clean across 58 files; boundary suite green; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 1006 passed; `mypy app` (strict) clean across 58 files; boundary suite green; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 1010 passed; `mypy app` (strict) clean across 58 files; boundary suite green; `alembic check` no drift.
  - **Negative controls** (3, all valid): removing the guard entirely — the original `T-141` gap — failed 3; `require_send_command` always permitting failed 2; applying the guard to *every* transition rather than only the first failed 1.
  - **An honest limit on control C.** Over-application is not behaviourally detectable: once a command exists the query succeeds at every transition, so `if True` still passes every functional test. Only `test_not_started_is_the_only_state_the_guard_reads` catches it, by asserting the condition and the single call site at the source. That test exists precisely because the behavioural route is closed — `SendCommand` is immutable and FK-restricted, so "a command that later vanishes" is not constructible.
  - **Three `T-022` tests had to change, and the guard was right, not the tests.** `test_resending_from_delivery_unknown_is_refused`, `test_reconciliation_can_resolve_delivery_unknown`, and `test_thread_transitions_are_audited` all moved a thread out of `not_started` with no command, because they were exercising the lifecycle table in isolation. Each now orders a command first, which is the correct precondition — reaching `delivery_unknown` presupposes a send was actually authorized.
  - **Why here and not in the §11.4 rechecks:** by dispatch time a command exists by definition, so the recheck would be unreachable. This is a truthfulness guarantee about the *record* — thread state is what the review dashboard reads — rather than a guard on an external effect.
- **Note:** Found by `T-024` on 2026-07-29. Lower priority than `T-140` because nothing external happens on this transition — no §3.5 violation on its own. But thread state is what the dashboard reads, so a thread in `queued` with nothing behind it is a record that asserts an approval exists when it does not.

#### T-142 — `tests/factories.py` has a fixed `NOW` that has now expired, reddening 89 tests
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
- **Depends on:** —
- **Spec:** §8.4 (approval expiry), §23 (tests build the schema from migrations)
- **Objective:** Every database test that builds an approval through the `World` factory fails from 2026-07-30 12:00 UTC onward. Make the shared test clock stable over wall-clock time without weakening the expiry constraint.
- **Observed:** `sqlalchemy.exc.IntegrityError: (psycopg.errors.CheckViolation) new row for relation "approval" violates check constraint "ck_approval_expiry_after_creation"`. `tests/factories.py` pins `NOW = 2026-07-27 12:00 UTC`; `request_approval` defaults the expiry to `NOW + DEFAULT_APPROVAL_TTL` (72h) = 2026-07-30 12:00 UTC; the migration's constraint is `approval_expires_at > created_at`, and `created_at` comes from the server clock. Once real time passed that instant the two disagree. Verified by arithmetic: `factories.NOW + DEFAULT_APPROVAL_TTL` → `2026-07-30 12:00:00+00:00`, `datetime.now(UTC)` → `2026-07-30 22:32:51+00:00`, `constraint holds? False`.
- **Scope (in):** A test clock that cannot go stale — anchor `NOW` to `datetime.now(UTC)` (truncated for determinism) or have `World.approval()` derive its expiry from the server clock. Fix the factory, not the constraint.
- **Scope (out):** Relaxing, removing, or making `ck_approval_expiry_after_creation` conditional; freezing the database clock in production code; any change to `DEFAULT_APPROVAL_TTL`.
- **Acceptance criteria:**
  1. The 89 failing tests pass, and `ck_approval_expiry_after_creation` is unchanged in the migration; a compiled-SQL or structural assertion pins that.
  2. A test proves the fixture clock cannot expire again — e.g. asserting `factories.NOW + DEFAULT_APPROVAL_TTL > datetime.now(UTC)`.
  3. Approval-expiry behaviour is still tested with a *deliberately* past expiry, so the fix does not remove the expiry coverage it repairs.
- **Verification:** `uv run pytest -q` from `backend/`
- **Files:** `backend/tests/factories.py`, affected test modules
- **Blocker / Q:** none — no product decision involved.
- **Note:** Found by `T-041` on 2026-07-30. Pre-existing and unrelated: the suite was green at 1025 passed earlier the same day and the trigger is the wall clock, not a code change. `T-041`'s own suites are pure and unaffected (37 passed).
- **Completion evidence:**
  - The literal was in **thirteen** places, not one: `tests/factories.py` plus twelve modules each redeclaring the identical `NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)`. `NOW` now lives once in `factories.py`, derived as `datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=1)`, and the twelve import it. Deduplicating was the fix, not tidying: a per-module literal cannot be pinned by one assertion, and the next module would have copied the date again.
  - Criterion 1 (89 tests pass, constraint unchanged): `pytest -q` → `1054 passed` (was `89 failed, 958 passed`; 958 + 89 + 7 new = 1054). The constraint is pinned two ways — `test_the_migration_still_carries_the_expiry_constraint` reads the migration file, and `test_the_model_and_the_migration_agree_on_the_constraint` reads the compiled `Approval.__table__` `sqltext`. `git diff` shows `alembic/` untouched.
  - Criterion 2 (the clock cannot expire again): `test_an_approval_built_at_the_fixture_clock_still_has_a_future_expiry` asserts the exact arithmetic that broke; `test_the_fixture_clock_keeps_a_margin_on_both_sides` demands ≥24h on each side so a slow suite cannot cross mid-run; `test_the_clock_is_derived_rather_than_written_down` asserts `datetime.now(` appears in the declaration; `test_no_test_module_declares_its_own_clock` greps every sibling module for a `NOW =` redeclaration.
  - Criterion 3 (expiry still tested with a past expiry): `test_the_database_refuses_an_approval_that_expired_before_it_was_created` inserts an approval expiring a day before now and expects `IntegrityError` matching `ck_approval_expiry_after_creation`. `test_an_expired_approval_authorizes_nothing` (T-021) still evaluates validity past the TTL.
  - Negative controls, each restored and re-verified green: (a) putting the literal back reddened 3 clock guards and 8 `test_worker_cycle` tests — the original failure reproduced on demand; (b) appending `NOW = "CONTROL"` to `test_jobs.py` failed `test_no_test_module_declares_its_own_clock`; (c) weakening the constraint **in the migration** to `approval_expires_at IS NOT NULL` failed both the structural test and the database-refusal test, which also proves the schema really is built from migrations rather than model metadata (§23).
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `115 files already formatted`; `mypy app` (strict) `Success: no issues found in 61 source files`; `pytest -q` `1054 passed`, which includes `test_upgrade_head_then_downgrade_base` and `alembic check`. No schema change and no new migration.

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
  - Checks: canonical set green (§2) — `pytest -q` 737 passed; `mypy app` (strict) clean across 49 files; `alembic` up/down-to-base/up clean; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 767 passed; `mypy app` (strict) clean across 50 files; boundary suite green; `alembic` up/down-to-base/up clean; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 919 passed; `mypy app` (strict) clean across 57 files; boundary suite green; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 931 passed; `mypy app` (strict) clean across 57 files; boundary suite green; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 946 passed; `mypy app` (strict) clean across 57 files; boundary suite green; `alembic` up/down-to-base/up clean; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 815 passed; `mypy app` (strict) clean across 52 files; boundary suite green; `alembic` up/down-to-base/up clean **twice** (enum-drop trap); `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 782 passed; `mypy app` (strict) clean across 51 files; boundary suite green; `alembic` up/down-to-base/up clean **twice** (enum-drop trap); `alembic check` no drift.
  - **Negative controls** (6, each verified to have changed the file): removing the audit-event check failed 1; removing the business-state check failed 2; inspecting only unflushed session state failed 2; dropping the unique key **from the migration** failed 1; dropping the sha256-shape constraint from the migration failed 1; not flushing the event failed 4. Green after each restore.
  - **Design note carried forward:** `commit_with_outbox` cannot inspect `session.new`, because a flush empties it and both `enqueue_outbox_event` and ordinary autoflush flush. It accumulates written kinds in `session.info` via an `after_flush` listener, cleared on commit and soft-rollback. Control C reproduces the naive version and fails.

#### T-035 — Outbox dispatcher with fake external-effect adapter, reconciliation, and `delivery_unknown`
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30 — reconciled: all three children `DONE`, per the split note below)
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
  - Checks: canonical set green (§2) — `pytest -q` 849 passed; `mypy app` (strict) clean across 55 files; boundary suite green; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 873 passed; `mypy app` (strict) clean across 55 files; boundary suite green; `alembic` up/down-to-base/up clean **twice** (enum-drop trap); `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 907 passed; `mypy app` (strict) clean across 56 files; boundary suite green; `alembic check` no drift.
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
  - Checks: canonical set green (§2) — `pytest -q` 972 passed; `mypy app` (strict) clean across 58 files; boundary suite green; `alembic` up/down-to-base/up clean **twice** (enum-drop trap); `alembic check` no drift.
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
- **Status:** `DONE` (2026-07-30)
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
- **Completion evidence:**
  - Shipped `app/fixtures/` (package docstring + `synthetic.py`), `app/cli.py`, `tests/test_fixtures.py`, and a "Synthetic fixtures" section in `docs/development.md`. Two worlds: product, open-ended readiness version, two segments, a policy version, two approved claims with campaign scope, and a published claim set each. No schema change (`alembic check` → `No new upgrade operations detected.`).
  - Criterion 1 (idempotent): `test_seeding_twice_changes_nothing` — re-seed reports `was_noop`, row counts unchanged, claim-set IDs identical, zero superseded sets. Also observed live: second `uv run python -m app.cli seed_synthetic` logged `"created": [], "was_noop": true`. Seeding is a get-or-create on each natural key precisely because `publish_policy_version`/`publish_claim_set` supersede-and-add. Negative control: replacing the claim-set guard with `if True` failed the test with `re-seeding created: ('claim set synthetic-sodium-battery', ...)`; restored, green.
  - Criterion 2 (no real content): `test_every_fixture_name_carries_the_synthetic_prefix`, `test_every_fixture_prose_string_says_it_is_synthetic`, `test_no_fixture_string_contains_a_digit` (a digit-free rule is the mechanical proxy for roadmap date, price, and certification number), `test_no_fixture_string_uses_claim_vocabulary_reserved_for_approved_claims`, `test_no_fixture_readiness_claims_general_availability` (never `sellable_now`). Negative control: one segment renamed `microgrid-operator-2027-certified-usd` failed all four content tests; restored, green.
  - Criterion 3 (refused in production): `test_seeding_is_refused_outside_a_seedable_environment[production|staging]` — `staging` is refused too, and passing `None` as the session proves the guard fires before any database use. Observed live: `APP_ENV=production uv run python -m app.cli seed_synthetic` logged `cli.seed_synthetic.refused` and exited `2`. Negative control: removing the `require_seedable` call turned both cases into `AttributeError: 'NoneType' object has no attribute 'execute'`; restored, green.
  - Extra invariants beyond the criteria: `test_seeded_campaigns_start_paused` (fixtures never start work), `test_every_seeded_claim_is_marked_synthetic`, `test_each_seeded_claim_set_resolves_against_its_campaign` (the fail-closed resolver accepts what the seeder published), and `test_only_the_cli_imports_the_fixtures` + `test_the_fixture_import_check_can_fail` — no production module may reach the synthetic world. Negative control: adding `from app.fixtures.synthetic import SEED_APPROVER` to `app/qualification/__init__.py` failed the boundary test; file restored byte-identically (`git diff HEAD` empty).
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `113 files already formatted`; `mypy app` (strict) `Success: no issues found in 61 source files`; `pytest -q` `1025 passed`; `pytest -q tests/test_fixtures.py` `15 passed`; `alembic upgrade head` clean.

#### T-041 — Synthetic prospect fixture set
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-30)
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
- **Blocker / Q:** `Q-003` — no provider or LinkedIn data until access and terms are confirmed. Not blocking: the corpus is hand-written, so no provider access is needed to build it.
- **Completion evidence:**
  - Shipped `app/fixtures/prospects.csv` (15 rows, 11 columns, every row labeled and annotated), `PROSPECTS_CSV` in `app/fixtures/__init__.py`, and `tests/test_prospect_fixtures.py` (22 tests, no database). The §19.1 labeled evaluation set (30-50 per campaign, eight dimensions) is deliberately **not** here — that is `T-080`.
  - Criterion 1 (reserved domains): `test_every_email_domain_is_a_reserved_example_domain` and `test_every_account_domain_is_a_reserved_example_domain` normalize through the T-016 normalizers first, so `www.Delta.example.com` is judged as `delta.example.com`. `test_the_reserved_domain_check_rejects_a_lookalike` keeps the check from being a naive suffix match (`notexample.com`, `example.com.attacker.test`).
  - Criterion 2 (seven labeled edge cases): `test_every_required_edge_case_is_present` plus one test per case proving the label is not a lie — `test_duplicate_email_case_rows_normalize_to_one_mailbox`, `test_duplicate_domain_name_rows_share_an_account_and_a_person_but_not_an_address`, `test_the_non_us_row_is_a_valid_country_that_is_not_us`, `test_the_suppressed_row_would_otherwise_be_eligible` (verified + US, so a suppression test cannot pass for the wrong reason), `test_the_missing_contact_point_row_has_no_contact_point_at_all`, `test_the_unverifiable_rows_cover_both_known_bad_and_never_checked`, `test_the_both_campaigns_rows_name_both_seeded_campaigns`. Three extra cases carry labels too: `baseline-eligible`, `no-country`, `non-email-contact-point`.
  - Criterion 3 (nothing real): `test_every_account_and_person_name_is_marked_synthetic`, `test_every_local_part_is_derived_from_its_synthetic_account`, and `test_no_cell_contains_a_digit` — the same blunt no-digit rule as `T-040`, which is what stops a real phone number or street address hiding in a `note`.
  - Coherence with the seeded world: `test_every_campaign_reference_matches_a_seeded_campaign` cross-checks the `campaigns` column against `CAMPAIGN_FIXTURES`, and `test_every_identity_value_survives_normalization` proves `T-042` can import every row.
  - Negative controls, each restored and re-run green: rewriting the `non-us-record` row as a plausible real company on a non-reserved domain with a real-looking person and a typo'd campaign slug failed five tests (both domain tests, the name test, the local-part test, the slug test); breaking the `duplicate-email-case` pair into two mailboxes, renaming the `suppressed-email` label, and unquoting a note failed four more (`test_duplicate_email_case_rows_normalize_to_one_mailbox`, `test_every_required_edge_case_is_present`, `test_the_suppressed_row_would_otherwise_be_eligible`, `test_no_row_is_ragged`); adding `tel 555` to a role title failed `test_no_cell_contains_a_digit` with a clean assertion.
  - `test_no_row_is_ragged` exists because the first draft had unquoted commas in `note`: `csv.DictReader` parked the overflow under a `None` key and every column after it shifted, which reads as a corpus that parsed fine.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `114 files already formatted`; `mypy app` (strict) `Success: no issues found in 61 source files`; `pytest -q tests/test_prospect_fixtures.py` `22 passed`; `pytest -q tests/test_fixtures.py tests/test_prospect_fixtures.py` `37 passed`. No schema change and no migration.
  - **Broader suite is red for an unrelated pre-existing reason**, filed as `T-142`: `pytest -q` → `89 failed, 958 passed`, every failure `CheckViolation ... "ck_approval_expiry_after_creation"` from `tests/factories.py` pinning `NOW = 2026-07-27 12:00 UTC` against a 72-hour approval TTL that lapsed at 2026-07-30 12:00 UTC. Not caused by this task — the trigger is the wall clock, the same suite was `1025 passed` earlier the same day, and none of the failing modules import anything `T-041` added. Not fixed here: repairing a shared test clock is its own change set.

#### T-042 — CSV/manual candidate import with normalization
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
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
- **Completion evidence:**
  - Shipped `app/prospects/imports.py` (`ImportBatch` model, typed `ImportRow`, `import_csv`, `RowRejection`/`ImportResult`), migration `e94c35cb931f`, registration in `alembic/env.py`, and `tests/test_import.py` (26 tests). `discover(criteria)` from the §9.5 contract is deliberately absent — it needs `Q-003` and **G-03**.
  - Criterion 1 (malformed row reported, batch survives): `test_a_malformed_row_is_reported_with_its_line_and_reason` — the bad row is line 3 and the rows either side still import; `test_each_kind_of_bad_field_names_itself` parametrizes six failure kinds (blank domain, blank name, three-letter country, unusable address, unknown contact type, half-given contact point) and asserts each reason names its field; `test_a_batch_of_only_bad_rows_still_records_the_batch`; `test_an_unusable_header_fails_the_whole_file_rather_than_every_row` (a header failure is one message, not fifty identical rejections).
  - Criterion 2 (idempotent per content hash): `test_reimporting_the_same_bytes_creates_nothing` (row counts identical, `already_imported` set), `test_the_batch_is_keyed_by_content_not_by_file_name` (same bytes under a new name return the same batch), `test_a_changed_file_is_a_new_batch` (the row already present is reused, not duplicated).
  - Criterion 3 (injection text is inert): `test_an_injection_style_row_is_stored_verbatim_as_a_name` (stored byte-identical), `test_an_injection_style_row_changes_nothing_else`, `test_sql_shaped_text_is_a_parameter_not_a_statement` (`'); DROP TABLE account;--` stored as a name, `account` intact), and the §15.5 pair `test_a_rejection_reason_quotes_the_offending_cell` + `test_the_audit_event_records_counts_and_lines_but_no_row_text`.
  - **The §15.5 test was too weak on the first pass and the control caught it.** Its hostile row put the injected text in a field the reason did not quote, so leaking reasons into the audit payload still passed. The bad row now carries the text in `account_domain` — the field whose reason quotes the cell verbatim — so the payload test proves neither the row nor a reason derived from it reaches the trail.
  - Normalization and the vertical slice: `test_identity_values_are_normalized_on_the_way_in` (`https://WWW.Xray.example.com/about` → `xray.example.com`, `us` → `US`, padded mixed-case address → lowercase), `test_two_spellings_of_one_address_produce_one_contact_point`, `test_a_contact_with_no_contact_point_still_imports`, and `test_the_t041_corpus_imports_whole` — the shipped fixture file through the shipped importer: 15 rows, zero rejections, 12 accounts, 13 contacts, 13 contact points.
  - Negative controls, each restored and re-verified: removing the batch lookup failed both idempotency tests; raising instead of collecting a `RowRejection` failed 9; adding rejection reasons to the audit payload failed the §15.5 test (after it was strengthened); weakening `created_count + reused_count + rejected_count = row_count` **in the migration** failed `test_a_batch_row_count_must_account_for_every_row`.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `118 files already formatted`; `mypy app` (strict) `Success: no issues found in 62 source files`; `pytest -q tests/test_import.py` `26 passed`; `pytest -q` `1080 passed`; `alembic upgrade head` / `downgrade -1` / `upgrade head` clean and `alembic check` `No new upgrade operations detected.`
- **Note:** Identity is exact-key get-or-create (domain, `(account, full_name)`, `(type, value)`) — the keys the database already enforces. Fuzzy resolution is `T-043` and campaign membership is `T-044`; this module stops at prospect identity.
- **Completion evidence:** —

#### T-043 — Deterministic deduplication against internal records
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-30)
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
- **Completion evidence:**
  - Shipped `app/prospects/dedup.py` (`MatchReason`, `find_contact_match`, `find_account`, `merge_contacts`, `MergeResult`), `normalize_person_name` in `normalize.py`, `docs/adr/ADR-019`, and `tests/test_dedup.py` (23 tests). No schema change and no migration.
  - Criterion 1 (each fixture duplicate resolves to one record with a recorded reason): `test_the_corpus_duplicate_cases_each_resolve_to_one_contact` imports `T-041`'s corpus through `T-042` and asserts `charlie` and `delta` each hold one contact, with `EXACT_EMAIL` reported for the mixed-case pair; `test_a_second_import_under_a_new_address_is_matched_and_merged` covers the duplicate exact-key import *cannot* catch — same person, new address, new row — matching `DOMAIN_AND_NAME` and merging to one contact holding both addresses. Reason recorded on the audit event: `test_the_merge_is_audited_with_its_match_reason_and_no_contact_details` (`payload["match_reason"]`, `policy_decision="dedup:domain_and_name"`, and no name or address in the payload, §15.5).
  - Criterion 2 (merging preserves evidence and every suppression): `test_a_suppression_naming_the_losing_contact_still_suppresses_after_the_merge` is the safety case — `PERSON` suppressions hold a contact ID as text with no foreign key, so a merge could silently un-suppress someone; `test_the_original_suppression_row_is_never_deleted`; `test_suppression_carried_forward_keeps_the_earlier_effective_time`; `test_an_email_suppression_survives_because_the_address_survives`; `test_a_merge_preserves_every_evidence_snapshot`; `test_a_contact_point_only_the_loser_had_moves_to_the_survivor`; `test_a_duplicate_address_row_is_dropped_rather_than_duplicated`.
  - Criterion 3 (nothing probabilistic): `test_the_rule_set_is_exactly_two_deterministic_rules`, `test_name_normalization_only_folds_case_and_whitespace` (asserts `Person, Synthetic` and `SYNTHETIC P. Alpha` are deliberately *not* matches), `test_two_people_sharing_a_role_are_not_a_match`, `test_a_blank_name_never_matches_another_blank_name`, `test_the_same_name_at_a_different_account_is_a_different_person`.
  - **The scope's third rule is rejected, not skipped:** ADR-019 records why "account domain + role" is not a contact-match rule — two people at one company routinely share a title, and a wrong merge is unrecoverable while a missed one is not. Account-level dedup is exact by construction (`Account.domain` unique + normalized), proven by `test_account_lookup_is_exact_and_normalized`.
  - **Campaign membership does not move, and the database said so.** The first implementation re-pointed `CampaignCandidate.contact_id`; the §8.1 trigger refused it (`RestrictViolation: campaign_candidate identity (campaign, account, contact) is immutable`). The merge now leaves candidates where they are, reports them as `stranded_candidates`, and keeps the losing contact alive when it holds any — deleting it would cascade their evidence away. `T-044` decides whether the survivor needs its own membership.
  - Negative controls, each restored and re-verified green: removing the suppression carry failed 3 tests; deleting the losing contact regardless of stranded candidates failed 2; making `normalize_person_name` order-and-punctuation insensitive (the ADR-019 fuzzy rule) failed the normalization test; removing the cross-account guard and adding the merged contact's name to the audit payload failed 2 more.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `120 files already formatted`; `mypy app` (strict) `Success: no issues found in 63 source files`; `pytest -q tests/test_dedup.py` `23 passed`; `pytest -q` `1103 passed`.

#### T-044 — Campaign membership creation
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-043, T-018
- **Note (from `T-043`):** `merge_contacts` reports `stranded_candidates` — memberships that stay with a merged-away contact because `(campaign, account, contact)` is immutable (§8.1). Deciding whether the surviving contact needs its own membership belongs here.
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
- **Completion evidence:**
  - Shipped `app/campaigns/membership.py` (`create_memberships`, `find_membership`, `MembershipResult`) and `tests/test_membership.py` (15 tests). No schema change and no migration: `T-018` already owns the table and the identity constraint, and `create_candidate` already writes the audit event — this module composes them rather than reimplementing either.
  - Criterion 1 (dual relevance → two independent candidates): `test_the_dual_relevance_account_produces_exactly_two_candidates` (two memberships naming two campaigns) and `test_the_two_memberships_have_genuinely_independent_state`, which moves one to `ineligible` and asserts the other is still `imported` — counting rows alone would not catch a shared record. `test_the_same_contact_in_one_campaign_is_one_membership` is the converse: `[SODIUM, SODIUM]` yields one.
  - Criterion 2 (re-running creates no duplicates): `test_rerunning_creates_no_duplicates` (second pass reports `existing`, row count unchanged), `test_rerunning_does_not_reset_a_candidate_that_has_moved_on` (an `eligible` candidate is returned untouched, not re-imported), `test_an_account_level_membership_is_matched_on_its_null_contact` (`IS NULL`, matching `T-018`'s `NULLS NOT DISTINCT`), `test_an_account_level_membership_is_not_the_contact_level_one`.
  - Criterion 3 (audit naming the campaign): `test_each_creation_writes_an_audit_event_naming_the_campaign` asserts two `campaign_candidate.created` events carrying both campaign IDs and `to_state=imported`; `test_a_reused_membership_writes_no_second_creation_event` — an audit trail that records a creation which did not happen is not evidence.
  - Fail-closed choices, both reported rather than raised: a paused campaign receives no new membership (§17.6) — `test_a_paused_campaign_receives_no_new_membership`, `test_no_membership_is_created_while_the_seeded_campaigns_are_still_paused` (the shipped default: `T-040`'s world does nothing until someone starts a campaign) — while `test_pausing_a_campaign_does_not_hide_the_membership_already_in_it` keeps the pause from erasing existing work; an unknown slug is reported and the other campaigns still land (`test_an_unknown_slug_is_reported_and_the_others_still_land`), matching `T-042`'s per-row philosophy.
  - Whole chain end to end: `test_the_corpus_both_campaigns_account_gets_two_memberships_per_contact` seeds `T-040`'s campaigns, activates them, imports `T-041`'s corpus through `T-042`, and drives this module from the corpus's own `campaigns` column — the `juliett` account ends with four candidates across two contacts and two campaigns.
  - Negative controls, each restored and re-verified green: removing the existing-membership lookup failed 7 tests (including a real `UniqueViolation`); replacing it with a lookup that ignores `campaign_id` — the "one shared lead record" §8.1 forbids — failed 5; letting paused campaigns accept work failed 2; constructing a `CampaignCandidate` directly instead of through the audited `create_candidate` failed 2.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `122 files already formatted`; `mypy app` (strict) `Success: no issues found in 64 source files`; `pytest -q tests/test_membership.py` `15 passed`; `pytest -q` `1118 passed`.

#### T-045 — Deterministic hard-eligibility rule engine
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
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
- **Completion evidence:**
  - Shipped `app/qualification/eligibility.py` (`Rule`, `EligibilityFailure`, `EligibilityDecision`, `evaluate`, `apply_eligibility`) and `tests/test_eligibility.py` (37 tests). No schema change: `ineligible_reason` already exists from `T-018` and `transition` already enforces that an `ineligible` candidate carries a reason.
  - **Five of §10.1's eight checks are implemented; three are named in `Rule` but cannot fire and are filed as `T-143`/`T-144`/`T-145`.** Existing-relationship needs the CRM (`Q-001`, **G-05** locked), approved-source-basis needs provenance a candidate does not yet carry, obvious-non-fit needs a confirmed ICP (`Q-002`). Naming them follows the `Recheck.SENDER_AVAILABILITY` precedent: a rule that always passed would read as coverage. `test_every_rule_is_either_implemented_or_explicitly_deferred`, `test_each_deferred_rule_names_the_task_that_will_implement_it`, and `test_no_deferred_rule_can_appear_in_a_decision` hold the register honest.
  - Criterion 1 (positive and negative per rule): `test_a_fully_valid_candidate_passes_every_rule` is the shared positive; negatives are `test_geography_refuses_a_country_outside_the_allowed_set`, `test_geography_refuses_an_unknown_country_rather_than_assuming_domestic`, `test_campaign_exclusion_refuses_an_excluded_domain` (+ `_permits_a_domain_that_is_not_listed`), `test_suppression_refuses_at_every_scope[email|person|domain|account]` (+ `test_a_lifted_suppression_no_longer_refuses`), `test_product_readiness_refuses_a_readiness_the_policy_excludes` / `_refuses_when_no_status_version_is_in_force` (+ `_permits_a_readiness_the_policy_allows`), `test_contactability_refuses_a_contact_with_no_email` / `_an_unverified_address...` / `_an_invalid_address` / `_an_account_level_candidate` (+ `_accepts_an_unverified_address_when_policy_does_not_require_it`).
  - Criterion 2 (all reasons, not the first): `test_a_candidate_failing_four_rules_records_all_four` breaks all five rules at once and asserts the failure list equals `IMPLEMENTED_RULES` in order, that the state is `ineligible`, and that every rule name appears in `ineligible_reason`; `test_the_decision_is_audited_with_every_failed_rule` pins `policy_decision="eligibility:fail:geography,contactability"`.
  - Criterion 3 (no model, no nondeterminism): `test_the_module_imports_nothing_from_the_model_gateway` (AST, because the boundary checker *permits* that import — §10.1 is what forbids it), `test_no_entry_point_accepts_an_override` (signature inspection: no `override`, `force`, `recommendation`, `confidence`, `skip_rules`), `test_evaluating_twice_produces_an_identical_result`, `test_a_failure_is_comparable_by_value_so_determinism_is_testable`, `test_failure_inputs_carry_no_contact_details` (§15.5).
  - Criterion 4 (fixture rows ineligible by default): `test_the_non_us_fixture_row_is_ineligible` and `test_the_suppressed_fixture_row_is_ineligible` — the latter is verified and US on purpose, so suppression is provably the only thing that refused it. `test_an_ineligible_candidate_cannot_be_walked_back_by_a_second_pass` confirms §8.2 terminality survives a re-run.
  - **One safety invariant was deliberately widened, with a compensating check.** `LIFECYCLE_OWNERS["CampaignCandidateState"]` now includes `qualification`: §8.3 step 4 makes eligibility the thing that moves a candidate out of `imported`, so this package transitions rather than reads, and `LIFECYCLE_READERS` would have been the wrong register. The guarantee that map exists for — no function spanning two lifecycles — is intact and now pinned by `test_eligibility_names_exactly_one_lifecycle`, which asserts the module imports `CampaignCandidateState` and no other lifecycle enum. A cleaner split (rules here, transition in `campaigns`) was rejected: `campaigns` importing `qualification` creates the import cycle `test_no_import_cycles` forbids.
  - **The broader suite caught two defects the targeted run could not**, both fixed before completion: `test_eligibility.py` had declared its own `NOW` literal, which `T-142`'s `test_no_test_module_declares_its_own_clock` rejected (now imports the shared clock); and the lifecycle-owner violation above, surfaced by `T-024`'s `test_only_the_owning_package_names_a_lifecycle`.
  - Negative controls, each restored and re-verified green: truncating the failure list to the first entry failed 2 tests; adding an `override` parameter and importing `app.model_gateway` failed 2; defaulting an unknown country to `US` and treating a missing readiness version as acceptable failed 2; letting `CampaignPolicy.suppression_scope` narrow which scopes are checked failed `test_campaign_policy_cannot_narrow_which_suppression_scopes_apply`.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` clean; `mypy app` (strict) `Success: no issues found in 65 source files`; `pytest -q tests/test_eligibility.py` `37 passed`; `pytest -q` `1155 passed`.

#### T-143 — Hard-eligibility rule: existing relationship conflict
- **Stage / Priority:** 4 / P1
- **Status:** `BLOCKED`
- **Depends on:** T-045, T-093, gate **G-05**
- **Spec:** §10.1 stage 1 ("existing relationship conflicts"), §13.5 rule 2
- **Objective:** Refuse a candidate whose account or contact already has a relationship the pilot must not cut across — an open opportunity, an existing owner, a live support case.
- **Scope (in):** `Rule.EXISTING_RELATIONSHIP` in `app/qualification/eligibility.py` moved from `DEFERRED_RULES` to `IMPLEMENTED_RULES`, reading through the CRM adapter's `find_account`/`find_contact`; a positive and a negative test.
- **Scope (out):** Any CRM write; inventing an internal proxy for "relationship" while no CRM exists.
- **Acceptance criteria:**
  1. The rule reads only through the `T-093` adapter, never a provider client directly.
  2. A candidate with a conflicting relationship is `ineligible` naming this rule; one without is unaffected.
  3. `test_every_rule_is_either_implemented_or_explicitly_deferred` still passes with the rule moved.
- **Verification:** `uv run pytest -q tests/test_eligibility.py`
- **Files:** `backend/app/qualification/eligibility.py`, `backend/tests/test_eligibility.py`
- **Blocker / Q:** `Q-001` — no CRM is adopted, so there is nothing to ask about a relationship. Gate **G-05** is LOCKED.
- **Completion evidence:** —

#### T-144 — Hard-eligibility rule: approved source basis
- **Stage / Priority:** 1 / P1
- **Status:** `PLANNED`
- **Depends on:** T-045, T-042, T-046
- **Spec:** §10.1 stage 1 ("approved source basis"), §9.3, ADR-005
- **Objective:** Refuse a candidate whose identity came from a source §9.3 has not approved, so a scraped or unattributed row cannot reach outreach merely by existing in the database.
- **Scope (in):** Provenance from the candidate back to its `ImportBatch` (`T-042`) or evidence source (`T-046`) — a link that does not exist today; `Rule.APPROVED_SOURCE_BASIS` moved into `IMPLEMENTED_RULES`; an allow-list of approved source types with a conservative default; a positive and a negative test.
- **Scope (out):** Any provider or LinkedIn source (`Q-003`, ADR-005 REJECTED).
- **Acceptance criteria:**
  1. A candidate with no recorded source basis is `ineligible`, not passed by default.
  2. A candidate imported through `T-042`'s CSV path is accepted, and the batch it came from is identifiable.
  3. The schema change carries a migration that reverses cleanly.
- **Verification:** `uv run pytest -q tests/test_eligibility.py tests/test_import.py`
- **Files:** `backend/app/campaigns/candidate.py`, `backend/app/qualification/eligibility.py`, migration, tests
- **Blocker / Q:** none, but it needs a schema decision on where provenance lives — candidate, membership, or account.
- **Completion evidence:** —

#### T-145 — Hard-eligibility rule: obvious non-fit
- **Stage / Priority:** 1 / P2
- **Status:** `BLOCKED`
- **Depends on:** T-045, `Q-002`
- **Spec:** §10.1 stage 1 ("obvious non-fit"), §8.6
- **Objective:** Refuse a candidate that is plainly outside the ideal customer profile before any model sees it — the deterministic half of fit, not the rubric (`T-053`).
- **Scope (in):** ICP exclusions expressed as campaign policy data (industry, company type, size band) rather than code; `Rule.OBVIOUS_NON_FIT` moved into `IMPLEMENTED_RULES`; a positive and a negative test per exclusion.
- **Scope (out):** Ranked scoring or any model judgement of fit (`T-053`); guessing an ICP.
- **Acceptance criteria:**
  1. Every exclusion is a policy value, so changing the ICP needs no code change.
  2. A candidate matching an exclusion is `ineligible` naming this rule.
  3. No threshold or score appears anywhere in the rule.
- **Verification:** `uv run pytest -q tests/test_eligibility.py`
- **Files:** `backend/app/campaigns/policy.py`, `backend/app/qualification/eligibility.py`, tests
- **Blocker / Q:** `Q-002` — Matrix Power has not confirmed segments, applications, or buyer roles. Inventing an ICP here would be exactly the fabricated product decision `AGENTS.md` rule 10 forbids.
- **Completion evidence:** —

#### T-146 — The importer must carry the declared contact-point verification state
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-041, T-042
- **Spec:** §9.5 (import contract), §15.8 (verified address before a send), §8.3 steps 1–2
- **Found by:** `T-058a`. The shadow slice could not advance a single candidate: every one failed `Rule.CONTACTABILITY`. `T-041`'s corpus declares a `verification_state` column and marks its `baseline-eligible` rows `verified`, but `ImportRow` is `extra="ignore"` and `_contact_point_for` never reads it, so every imported address lands on the model default `unverified`. The two tasks disagreed and nothing failed, because no test imported a row and then asked whether the address was contactable.
- **Objective:** An imported contact point records the verification state its row declared, failing closed on anything that is not an explicit `verified`.
- **Scope (in):** `verification_state` on `ImportRow` with a fail-closed validator; `_contact_point_for` passing it through; tests that a `verified` row imports verified, that `unverified`, `invalid`, blank, absent, and unrecognized values all import `unverified`, and that an imported baseline row passes `Rule.CONTACTABILITY`.
- **Scope (out):** Any real address-verification provider (`Q-011`, gated); a third `VerificationState` member for "known undeliverable" — the corpus's `invalid` rows collapse to `unverified` and are refused either way, and adding a state to the enum is a lifecycle change, not an import fix.
- **Acceptance criteria:**
  1. A row declaring `verified` produces a contact point in `VerificationState.VERIFIED`.
  2. Every other spelling — `unverified`, `invalid`, blank, missing column, unrecognized text — produces `UNVERIFIED`; test-proven for each.
  3. A `baseline-eligible` row from the fixture corpus passes hard eligibility end to end after import.
- **Verification:** `uv run pytest -q tests/test_import.py tests/test_eligibility.py`
- **Files:** `backend/app/prospects/imports.py`, `backend/tests/test_import.py`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_import.py` -> **39 passed** (was 31); full suite **1547 passed**; `ruff check app tests` clean; `mypy app` clean.
  1. **`verified` imports verified** - `test_a_row_declaring_verified_imports_a_verified_address`, plus `test_the_case_of_the_declared_value_does_not_matter` for surrounding whitespace and capitalisation.
  2. **Everything else fails closed** - `test_every_other_spelling_imports_unverified` parametrized over `unverified`, `invalid`, empty, whitespace, `VERIFIED_MAYBE`, `yes`, `true`, `1`; `test_a_file_with_no_verification_column_imports_unverified` covers the absent column; `test_an_unrecognized_value_does_not_reject_the_row` proves a questionable cell does not cost an otherwise usable identity. `yes`/`true`/`1` are in the list because they are what a spreadsheet produces when the column is reformatted, and each silently meaning "verified" would put an unchecked address through §15.8's gate looking checked.
  3. **A corpus baseline row is contactable end to end** - `test_the_corpus_baseline_rows_import_verified` (alpha and bravo verified, india and hotel not), and `T-058a`'s slice advances five candidates through `Rule.CONTACTABILITY` where it previously advanced none.
- **Negative controls (applied, observed failing, restored, suite re-verified green):** dropping `verification_state=` from `_contact_point_for` -> 3 failed; relaxing the validator to accept any non-empty string -> 7 failed, including the `true` and `1` cases specifically.

#### T-147 — Who advances a candidate through the research lifecycle
- **Stage / Priority:** 1 / P0 (raised 2026-07-31: `T-058b2b` cannot proceed without it)
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058b2a
- **Spec:** §8.2 (candidate lifecycle), §8.3 steps 5–7, ADR-015
- **Found by:** `T-058b2a`. Writing the capture handler to advance the candidate failed `tests/test_invariants.py::test_a_reader_never_transitions_what_it_reads[CampaignCandidateState]`, which is correct: ADR-015 lists `research_and_evidence` as a *reader* of the candidate lifecycle, not an owner. The handler was rewritten to capture only, and the gap is recorded here rather than closed by widening the guard.
- **Objective:** Decide and implement which module advances a candidate `eligible → research_pending → researched`, without weakening ADR-015.
- **Context:** `research_pending` and `researched` are states §8.2 defines that **no code reaches today** — `capture_evidence` and `qualify_candidate` both gate on candidate state and neither changes it, so a candidate sits in `eligible` for the whole pipeline and `T-058a`'s slice drafted from one still in that state. Three shapes are worth weighing: a `campaigns`-owned progress API the research job calls; an owner-side job type in `campaigns` that brackets the research job; or adding `research_and_evidence` to `LIFECYCLE_OWNERS` with a compensating test, which is what `qualification` already did for the eligibility transition and is the precedent to argue against or follow.
- **Scope (in):** The decision, recorded as an ADR; the transitions themselves; a test that the states are reachable; `xfail(strict=True)` markers in `tests/test_pipeline_jobs.py` naming this task removed as part of the fix.
- **Scope (out):** Any change to what evidence capture stores.
- **Acceptance criteria:**
  1. A candidate driven by the worker reaches `researched`, test-proven.
  2. `tests/test_invariants.py` passes unchanged, or its widening is accompanied by a compensating test in the shape `test_a_reader_never_transitions_what_it_reads` already uses.
  3. An ADR records which module owns the transition and why.
- **Verification:** `uv run pytest -q tests/test_pipeline_jobs.py tests/test_invariants.py`
- **Files:** `backend/app/campaigns/jobs.py`, `backend/app/research_and_evidence/jobs.py`, `backend/app/qualification/jobs.py`, `docs/adr/ADR-020-the-lifecycle-owner-brackets-a-step-it-does-not-perform.md`
- **Blocker / Q:** none
- **Decision:** **ADR-020** — `campaigns` owns every campaign-candidate transition and brackets the research step with two job types of its own (`campaigns.start_research`, `campaigns.complete_research`). `research_and_evidence` stays a *reader* and is **not** added to `LIFECYCLE_OWNERS`. The chain is now membership -> eligibility -> start_research -> capture -> complete_research.
- **Why not the one-line alternative:** adding `research_and_evidence` to the owner map is the `qualification` precedent, and the precedent does not transfer. `qualification` owns because §8.3 step 4 makes hard eligibility *the thing that moves* a candidate out of `imported` — the decision and the transition are one event. Research's outcome is an `EvidenceSnapshot`; that the candidate is now "researched" is bookkeeping about workflow position, and a candidate with zero evidence is researched too. Granted on the weaker argument, every module performing a §8.3 step qualifies, the owner map lists most of the backend, and ADR-015's guarantee is gone. A `campaigns`-owned helper the reader calls was rejected separately, as evasion: the invariant test matches `transition` by name, so a renamed wrapper would pass it while doing the forbidden thing — the same reasoning that rejected aliasing `revisions.transition` in `T-055`.
- **Completion evidence:** `uv run pytest -q tests/test_pipeline_jobs.py` -> **57 passed**; `tests/test_invariants.py` **45 passed** unchanged; full suite **1604 passed, 0 xfailed** (was 1592 passed, 2 xfailed); `ruff check app tests` clean; `mypy app` clean on 93 source files. No migration.
  1. **A worker-driven candidate reaches `researched`** — `test_the_chain_reaches_researched` and `test_the_candidate_passes_through_research_pending`, both of which were the `strict=True` xfails this task existed to remove; plus `test_the_chain_reaches_capture_with_evidence_stored` and `test_the_full_chain_is_five_jobs`, which pins ADR-020's stated cost so the chain cannot lengthen unnoticed.
  2. **The invariant is upheld, not widened** — `tests/test_invariants.py` passes **unchanged**; `test_research_and_evidence_never_imports_the_transition_helper` repeats the rule where a reader of the capture handler will see it; `test_research_and_evidence_is_still_only_a_reader` asserts the *register* itself, so a future task that widened `LIFECYCLE_OWNERS` quietly would fail here even if the code looked fine.
  3. **The decision is recorded** — `docs/adr/ADR-020-…md`, registered in `docs/adr/README.md`, stating the decision, the rejected alternatives, the cost in plain terms (two extra job types, four links where three would do), and what would justify revisiting it.
- **Also proven:** the bracket is atomic (`test_start_research_queues_the_capture_in_the_same_transaction` — §7.2; a candidate in `research_pending` with no capture job queued is one nothing will ever finish), replay-safe on both halves (`test_replaying_a_bracket_job_does_not_transition_twice` parametrized over both handlers, `test_a_replayed_bracket_job_succeeds_rather_than_failing`), permanent on a missing candidate, and non-consequential in §17.6's sense.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, suite re-verified green):** `start_research` no longer queueing the capture -> 10 failed; the bracket replay guard removed -> 3 failed; the capture job no longer closing the bracket -> 5 failed; re-introducing the original ADR-015 violation by importing `transition` into the capture handler -> `test_a_reader_never_transitions_what_it_reads` failed.
- **That last control found a weak test of my own.** It failed `test_invariants.py` but *not* `test_research_and_evidence_never_imports_the_transition_helper`, which checked for the substring `"import transition"` — and the control wrote `from ... import CampaignCandidate, transition`, which a substring check reads straight past. It now matches imported *names* via AST, the way the real invariant does, and the control fails it.

#### T-148 — The worker registers no job types
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058b2b2a
- **Spec:** §17.1, §18.2, §7.2
- **Found by:** `T-058b2b2b`. Driving the shadow slice through the worker raised `UnknownJobType: no handler registered for job type 'campaigns.create_membership'; known types: (none)`. `app/worker.py` imports the runner, the dispatcher, and the recovery helpers, but calls no module's `register()` — so the process-wide registry is empty in a running worker and **every** job would be retried on a fixed backoff until an operator noticed. This is not new: `claims.invalidate_by_version` (`T-056`) has had the same problem since it was written, and nothing failed because every test registers what it needs.
- **Objective:** A started worker knows every job type this build defines.
- **Scope (in):** `worker.py` calling each owning module's `register()` at startup — it is a leaf that nothing imports, so it is the one place allowed to know about every module (its own docstring says so); a test asserting the registry a started worker holds contains every `register()` the codebase defines, so a new job type that nobody wired fails rather than silently never running.
- **Scope (out):** Any change to the job types themselves; dispatch and recovery, which already work because `worker.py` wires them explicitly.
- **Acceptance criteria:**
  1. A worker's registry contains every job type defined under `app/`; test-proven by discovery rather than by a hand-maintained list, so the test cannot go stale.
  2. `claims.invalidate_by_version` is among them — the pre-existing case that motivated this.
  3. A job type added without wiring it fails that test.
- **Verification:** `uv run pytest -q tests/test_jobs.py tests/test_pipeline_jobs.py`
- **Files:** `backend/app/worker.py`, `backend/tests/test_jobs.py`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_jobs.py` -> **31 passed** (was 23); full suite **1664 passed** (was 1656); `ruff check app tests` clean; `mypy app` clean on 95 source files. Diff is two files, +208/-2. No migration.
  1. **Every job type the codebase defines** — `test_the_worker_registers_every_job_type_the_codebase_defines` discovers the registrars by AST (a module-level `def register` with a `JobRegistry` annotation), registers them into one registry, registers the worker's list into another, and compares the two as **sets of job-type names** — which is what a worker actually has to hold. Two guards on the guard: `test_the_discovery_finds_the_modules_that_define_job_types` (discovery that found nothing would make the comparison vacuously green — the same failure mode a hand-maintained list has) and `test_the_discovery_ignores_registrars_that_are_not_job_types`, since `register_prompt_versions`, `register_source_adapter`, and `register_job_type` all match a loose `^def register` grep and none of them registers a job type.
  2. **`claims.invalidate_by_version` among them** — `test_the_worker_registers_the_claim_invalidation_job`. It had the defect from the day `T-056` wrote it; nothing caught it because every test registers what it needs.
  3. **An unwired job type fails the test** — proven by control, below.
- **Also proven:** `test_the_worker_registers_the_whole_pipeline` names the eight types the shadow slice drives, so a reader of `tests/test_jobs.py` sees what a worker is expected to run; `test_main_registers_before_it_starts_working` asserts on `main`'s AST that it registers **and** that it does so before building anything it would run jobs with — registering after the first pass would leave that pass leasing jobs it could not run; `test_registering_twice_is_a_no_op` for a restarted worker, since `JobRegistry.register` raises on a duplicate name; and `test_no_registered_job_type_is_consequential`, recorded as an assertion rather than an assumption so that the day a send job is added, whoever adds it must decide deliberately whether §17.6's pause stops it.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, suite re-verified green):** dropping one module from the worker's list -> 2 failed (criterion 3); reverting the registration entirely, which is the original defect -> 3 failed; `main` no longer registering -> 1 failed; breaking the discovery itself -> 2 failed.
- **One control did not match and said so.** The first attempt at the dropped-module control used a shell string whose `
` stayed literal, so the replacement found nothing; the script's `assert` refused rather than writing nothing and reading as a pass. Re-applied by line index and re-verified by `grep` before being trusted.
- **Not in scope, noted:** `webhook.process` (`app/outreach_and_replies/webhooks.py`) is enqueued by name and no module registers a handler for it — the module already logs `webhook.no_handler_registered` when that happens, so it is a known absence rather than a silent one. The discovery test does not demand it, because no module defines a registrar for it to find.

#### T-046 — Offline evidence capture service with provenance and retention class
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-30)
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
- **Blocker / Q:** `Q-003`, `Q-016`, `Q-019` — not blocking offline capture: the fixture adapter needs no provider, and the privacy classification is a required field on every document rather than a guess.
- **Completion evidence:**
  - Shipped `app/research_and_evidence/adapters/` (`protocol.py` with the §9.5 `SourceAdapter` contract, `CapturedFact`, `SourceCapabilityUnavailable`; `fixture.py` with `FixtureSourceAdapter`), `app/research_and_evidence/capture.py`, four synthetic documents under `app/fixtures/source_documents/`, and `tests/test_evidence_capture.py` (26 tests). No schema change: `T-019` already owns `EvidenceSnapshot` and its immutability trigger.
  - Criterion 1 (no HTTP client): `test_the_capture_path_imports_no_http_client` walks every module under `research_and_evidence` with `ast` and rejects twelve socket-opening roots; `test_the_network_import_check_can_fail` proves the checker is not vacuous. `discover` and `import_records` exist and raise `SourceCapabilityUnavailable` naming `Q-003`/**G-03** and `T-042` respectively — `test_discovery_is_refused_and_names_its_gate`, `test_import_is_refused_and_points_at_the_module_that_owns_it`. A refusal, not an empty list: "the source had nothing to say" is a different claim from "this capability does not exist".
  - Criterion 2 (full §14.3 provenance): `test_every_captured_snapshot_has_complete_provenance` checks every field on every snapshot; `test_the_content_hash_is_over_the_whole_source_not_the_excerpt` (a hash of the excerpt could not detect that the document changed); `test_the_privacy_flag_is_carried_from_the_document_not_defaulted`; `test_a_document_missing_its_privacy_flag_is_skipped_not_defaulted` — the malformed fixture exists so that refusal is exercised, not asserted. Also `test_an_oversized_document_is_refused_unread` (§15.3's size limit applied to the local equivalent) and `test_an_over_long_excerpt_is_skipped_rather_than_truncated`.
  - Criterion 3 (refresh adds, never mutates): `test_a_changed_source_produces_a_second_snapshot_and_leaves_the_first` rewrites a document between two captures and asserts the first snapshot still carries its original hash and text; `test_recapturing_an_unchanged_source_stores_nothing_new`; `test_the_database_refuses_an_update_to_a_stored_snapshot` (T-019's trigger — the reason capture has no update path to get wrong).
  - Criterion 4 (injection text is data): the hostile document is a real fixture asking for approval, unsuppression, a readiness change, and an API key. `test_the_hostile_document_is_captured_as_ordinary_evidence` (stored verbatim, unsanitized), `test_the_hostile_document_changes_nothing_about_the_candidate`, `test_its_classification_is_taken_from_the_document_metadata_not_its_prose` (the text claims maintenance mode; the fields say low quality, internal only), `test_the_audit_event_records_documents_and_counts_but_no_excerpt` (§15.5), `test_no_module_in_the_capture_path_branches_on_excerpt_text`.
  - Ordering: capture is refused before the eligibility gate (`test_capture_is_refused_before_the_eligibility_gate`, `test_capture_is_refused_for_an_ineligible_candidate`). §8.3 puts step 4 before steps 5-6, and researching a candidate hard rules refused would build a dossier on someone who must not be contacted. `test_a_domain_with_no_documents_captures_nothing` holds GP-02: absence stays absence.
  - **`research_and_evidence` registered as a lifecycle *reader*, not an owner.** The broader suite caught `capture.py` naming `CampaignCandidateState`; it consults the state to refuse and never moves it, so it joins `LIFECYCLE_READERS` (the register `T-140` created for exactly this) rather than `LIFECYCLE_OWNERS`. `test_a_reader_never_transitions_what_it_reads` is the compensating check and passes.
  - **`R-004` opened** in `docs/reconciliation.md`: `refresh` takes the account domain and returns `CapturedFact` rather than §9.5's literal `refresh(candidate_id) -> EvidenceSnapshot[]`. An adapter holds no session and must not own persistence; the capability set is honoured in full.
  - Negative controls, each restored and re-verified green: adding `import urllib.request` to `capture.py` failed the no-network test; defaulting the privacy flag to `False` failed 2; removing the eligibility gate and the duplicate check failed 3; adding excerpts to the audit payload failed the §15.5 test.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `129 files already formatted`; `mypy app` (strict) `Success: no issues found in 69 source files`; `pytest -q tests/test_evidence_capture.py` `26 passed`; `pytest -q` `1181 passed`.

### 3.5 Model gateway, qualification, drafting, and the shadow slice

#### T-050 — Provider-neutral model gateway with budgets and limits
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
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
- **Completion evidence:**
  - Shipped `app/model_gateway/` — `protocol.py` (`ModelGateway`, `ModelProviderAdapter`, `ModelTaskRequest`/`Result`), `models.py` (`ModelRun`), `budgets.py`, `registry.py`, `providers/echo.py` — migration `c1b7f16c23f2`, a new `ALLOW_REAL_MODEL_PROVIDER` setting, and `tests/test_model_gateway.py` (34 tests).
  - Criterion 1 (fake by default; a real provider needs an explicit setting **and** an unlocked gate): `test_default_configuration_resolves_to_the_fake_provider`, `test_a_non_fake_provider_is_refused_without_the_gate_flag`, `test_a_non_fake_provider_is_still_refused_with_the_gate_flag_set`, `test_the_real_provider_registry_is_empty`, `test_the_gate_flag_defaults_to_false_in_a_fresh_environment`. **Three locks, not two:** the enum has one member, `ALLOW_REAL_MODEL_PROVIDER` defaults false, and `REAL_PROVIDER_ADAPTERS` is empty — so even both flags flipped constructs nothing, because no real adapter has been written or reviewed (§15.9). The stand-in enum lives in the test, so proving "adding a member changes nothing" does not require adding one.
  - Criterion 2 (every call writes a `ModelRun` with all version fields): `test_a_successful_call_records_every_version`, `test_the_run_records_tokens_cost_and_latency`, `test_cost_is_attributable_to_a_campaign_and_candidate` (§18.7), `test_a_provider_failure_is_recorded_before_it_propagates`, plus two database-level structural tests — `failure_reason_matches_outcome` and `a_refused_run_spends_nothing`. `VersionUnavailable` stops a call whose prompt/schema/config cannot be resolved or is not effective, so a run can never misreport the version it used (§17.5).
  - Criterion 3 (budgets refuse before any provider invocation; three tests): `test_a_per_task_budget_refuses_before_the_provider_is_reached`, `..._a_daily_budget_...`, `..._a_campaign_budget_...` — each asserts `provider.calls == 0`, which is the criterion stated exactly. Supporting: `test_a_refusal_is_recorded_as_a_run`, `test_a_budget_counts_earlier_runs_in_the_same_day`, `test_a_budget_does_not_count_yesterdays_runs`, `test_refused_runs_do_not_themselves_consume_the_budget` (else a burst of refusals locks out the day), `test_a_cost_cap_refuses_once_spend_passes_it`, `test_a_zero_budget_refuses_everything`, `test_a_day_boundary_is_utc`.
  - **Only the call caps bind today, and the ledger should say so plainly.** The fake reports zero cost because nothing is bought, so the money caps cannot fire in Stage 1. They are wired and tested with a priced stub adapter so the check is already in the path when a real provider arrives; the numbers in them are conservative placeholders, not a budget anyone approved (`Q-006`, `Q-012`).
  - Criterion 4 (model names only in configuration): `test_the_gateway_never_names_a_model` renames the model in the configuration version and asserts the run follows; `test_no_endpoint_or_base_url_appears_in_the_gateway_package`; `test_model_parameters_come_from_the_configuration_version`. `T-023`'s repository-wide vendor-marker grep still passes.
  - **A §15.4 defect was found by its own test and fixed.** The first `_render` replaced placeholders key by key, which re-scans inserted text: an input whose *value* was `{secret}` pulled in the real secret on a later iteration. It is now a single regex pass, so inserted values are never re-scanned — `test_an_input_value_containing_a_placeholder_is_not_expanded` and `test_rendering_does_not_evaluate_attribute_access`.
  - Negative controls, each restored and re-verified green: removing the gate-flag check failed 1; moving the budget check after the provider call failed 4 (the three criterion-3 tests plus the provider-error test); restoring the sequential renderer failed the §15.4 test; hard-coding `claude-sonnet-5` failed 3 including `T-023`'s repository grep; weakening `a_refused_run_spends_nothing` **in the migration** failed its structural test. One scripted control silently no-opped against formatter-reflowed source and was re-applied after reading the actual text — the file was verified changed before the run was trusted.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `138 files already formatted`; `mypy app` (strict) `Success: no issues found in 76 source files`; `pytest -q tests/test_model_gateway.py` `34 passed`; `pytest -q` `1215 passed`; `alembic upgrade head` / `downgrade -1` / `upgrade head` clean, `alembic check` `No new upgrade operations detected.` The migration reuses the existing `modelprovider` enum with `create_type=False` and drops only its own `modelrunoutcome` on downgrade, per `docs/development.md`.
- **Note:** mypy's `warn_unreachable` proved the registry's real-provider branch unreachable while `ModelProvider` has one member. The comparison is by `.value` rather than identity so the guard survives — deleting it would leave nothing to enforce the rule the day a member is added.

#### T-051 — Versioned JSON Schemas for model outputs with validation, retry, and escalation
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-050
- **Note (from `T-050`):** the gateway records `schema_version_id` on every run and returns the provider's raw text; `ModelRunOutcome.INVALID_OUTPUT` already exists for this task to write.
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
- **Completion evidence:**
  - Shipped `app/model_gateway/schemas/` (`qualification.py` — the §10.4 model; `__init__.py` — registry, export, registration, tamper check; `qualification-output.json` — the exported artefact) and `app/model_gateway/validation.py`, with `tests/test_output_schemas.py` (42 tests). No schema change and no migration: `T-023`'s `SchemaVersion` already holds versioned JSON Schemas.
  - **No `jsonschema` dependency was added.** Pydantic is already in the manifest, already validates, and already emits JSON Schema; a second library to re-check what the model just checked would be one more thing to keep in step (process.md §4).
  - Criterion 1 (the §10.4 field set exactly, including the three enums): `test_the_model_carries_exactly_the_spec_field_set`; `test_the_field_set_matches_the_specification_text` parses §10.4's own JSON block out of the specification file, so a spec revision cannot pass unnoticed; `test_each_enum_matches_the_specification[OpportunityType|EvidenceCompleteness|SourceQualityRating]`; `test_the_four_fit_dimensions_are_the_specified_ones`; `test_no_field_has_a_default` — an omitted `human_review_required` must never become `False` by default (§3.5).
  - Criterion 2 (bounded retry, then escalation, never silent acceptance): `test_valid_output_on_the_first_attempt_calls_once`, `test_invalid_output_is_retried_and_then_succeeds`, `test_repeatedly_invalid_output_escalates_to_human_review` (`Escalated.human_review_required is True`), `test_the_retry_limit_is_small`, `test_a_custom_attempt_limit_is_honoured`, `test_invalid_output_is_never_silently_accepted`, plus eleven validation tests covering each way output can be wrong (bad enum, missing field, extra field, non-JSON, out-of-range score, unregistered key). **Each attempt goes through `run_task`**, so `test_retries_are_still_subject_to_the_budget` proves a model looping on invalid output cannot outspend the cap a single call would have hit; `test_a_provider_failure_is_not_retried_as_though_it_were_invalid_output` keeps a raised provider distinct from a bad answer.
  - Criterion 3 (content-hashed and registered): `test_every_schema_registers_with_its_content_hash`, `test_registering_twice_publishes_nothing_new`, `test_the_exported_file_matches_the_model` (the `.json` artefact cannot go stale), `test_the_registered_schema_is_the_one_a_run_can_cite` — the run → schema-version → contract join that makes a decision explainable.
  - Criterion 4 (a change is a new version; mutation fails a test): `test_a_changed_schema_publishes_the_next_version`, `test_two_versions_of_one_key_cannot_share_a_number`, `test_the_content_hash_of_a_registered_version_cannot_be_rewritten` (`T-023`'s trigger), and `test_a_body_edited_after_registration_is_detected`.
  - **The trigger's exact reach was checked rather than assumed, and it left a hole worth closing.** `T-023`'s trigger pins `key`, `version`, `content_hash`, `effective_from`, and `created_by` — but deliberately not `json_schema` or `effective_to`, because a window has to be closable when the next version publishes. That leaves one way to tamper: edit the body and leave the hash. `verify_registered_schema` detects exactly that, and the negative control (disabling the comparison) fails its test.
  - **`ex_schema_version_no_overlap` also turned up during testing** — two open effective windows for one key are refused, which is what makes "the current version" unambiguous. `register_schema_versions` already closed the previous window; my first test did not, and was corrected rather than the constraint worked around.
  - Negative controls, each restored and re-verified green: `extra="allow"` failed 2; returning a constructed empty object instead of escalating failed 4; not recording the failed attempt failed 2; deleting `missing_information` failed 8; disabling the tamper check failed 1.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `142 files already formatted`; `mypy app` (strict) `Success: no issues found in 79 source files`; `pytest -q tests/test_output_schemas.py` `42 passed`; `pytest -q` `1257 passed`.

#### T-052 — Deterministic fake model adapter
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-051
- **Note (from `T-050`/`T-051`):** `providers/echo.py` is the minimal stand-in this task replaces; `QualificationOutput` is the schema its fixture outputs must satisfy, and `Escalated` is what its schema-invalid failure mode must produce.
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
- **Completion evidence:**
  - Shipped `app/model_gateway/providers/fake.py` (`FakeModelAdapter`, `ModelOutputFixture`, `FailureMode`, `prompt_key`), six fixtures under `app/fixtures/model_outputs/`, and `tests/test_fake_model.py` (38 tests). No schema change, no migration, no new dependency.
  - **Path differs from this block's Files line:** the adapter is at `providers/fake.py`, not `adapters/fake.py`. `T-050` established `app/model_gateway/providers/` as where adapters live, and a second directory for one file would be the drift the ledger exists to prevent.
  - Criterion 1 (byte-identical across runs **and processes**): `test_the_same_prompt_returns_the_same_bytes` covers within-process; `test_the_output_is_identical_across_processes_under_different_hash_seeds` runs the adapter in two subprocesses under `PYTHONHASHSEED=1` and `=2` and compares stdout, because within-process repetition cannot detect the usual cause of cross-process drift. Supported by `test_the_module_imports_nothing_nondeterministic` (no `random`, `time`, `datetime`, `uuid`, `secrets`, `os`), `test_dictionary_output_is_serialized_with_sorted_keys`, and `test_parameters_do_not_change_the_output`.
  - Criterion 2 (five fixture-triggered failure modes): `test_every_failure_mode_has_a_shipped_fixture` and `test_a_failure_mode_is_selected_by_fixture_not_by_code` pin the set; then one test per mode asserting what the *pipeline* sees — `test_schema_invalid_mode_escalates_through_the_validator` and `test_refusal_mode_is_not_valid_output_either` (both reach `Escalated` via `T-051`), `test_timeout_mode_is_recorded_as_a_provider_error` (`ModelRun.outcome` is `provider_error`), `test_unsupported_claim_mode_is_schema_valid_and_still_wrong`, and three echo tests. The last two modes are deliberately **schema-valid**, so nothing before `T-055`'s claim and evidence validators can catch them — which is the point of shipping them now.
  - Criterion 3 (no I/O beyond local fixtures): `test_the_adapter_opens_no_socket`, plus `test_an_oversized_fixture_is_refused_unread` and `test_the_fixture_directory_is_a_constructor_argument` — the directory is passed in, so `app/fixtures/` stays unimported by production code (`T-040`).
  - Fail-closed lookup: `test_an_unmatched_prompt_raises_when_there_is_no_default` — a fake that answers anything lets a test pass against a prompt nobody wrote an expectation for. A `"default"` entry is opt-in, declared in the file. `test_two_fixtures_claiming_one_match_is_fatal` refuses a set whose answer would depend on file order, and `test_a_malformed_fixture_is_fatal_rather_than_skipped` records the deliberate difference from `T-046`: a broken *expectation* must not be quietly dropped the way a broken source document can be.
  - **A fixture `match` may be written as the prompt text and is hashed at load**, so lookup stays hash-only while the files stay readable. The first implementation accepted only digests, which made every fixture an opaque hash — reviewable by nobody.
  - Negative controls, each restored and re-verified green: returning the first available fixture instead of raising failed 1; dropping `sort_keys` and importing `random` failed 2; ignoring the timeout mode and allowing duplicate matches failed 2.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `144 files already formatted`; `mypy app` (strict) `Success: no issues found in 80 source files`; `pytest -q tests/test_fake_model.py` `38 passed`; `pytest -q` `1295 passed`.
- **Note:** five fixture files were first written to a stray `app/fixtures/model_outputs/` at the repository root because the shell's working directory had reset. Caught by the tests failing to find them, moved into `backend/`, and the stray directory removed; `git status` shows no residue.

#### T-053 — Qualification and opportunity classification task
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
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
- **Blocker / Q:** `Q-002`, `Q-020` — synthetic rubric weights; thresholds not treated as approved. Not blocking: this task contains **no threshold at all**, which is why it can ship before they are answered.
- **Completion evidence:**
  - Shipped `app/qualification/models.py` (`QualificationRun`), `app/qualification/qualify.py` (the evaluator), `app/model_gateway/prompts/` (versioned prompt + registration, mirroring `T-051`'s schema registry), migration `f5eafa7d8ad9`, and `tests/test_qualification.py` (36 tests).
  - Criterion 1 (output validates): `test_a_valid_output_produces_a_qualification_run`, `test_the_run_points_at_the_model_run_that_produced_it` (the §17.5 join to prompt/schema/config), `test_output_that_never_validates_escalates_rather_than_being_stored`, and `test_the_shipped_fake_fixture_qualifies_end_to_end` — the whole path on `T-052`'s shipped adapter, not a test-local stub.
  - Criterion 2 (a personalization statement without an evidence ID fails): `check_grounding` compares every cited ID against what the candidate actually has. `test_an_unknown_evidence_id_is_refused`, `test_an_unapproved_claim_id_is_refused`, `test_the_unsupported_claim_fixture_is_caught_here` — `T-052`'s schema-valid fixture citing `SYNTHETIC-CLAIM-that-was-never-approved` dies exactly here, which is what it was built for. `test_an_expired_claim_is_not_citable` and `test_stale_evidence_is_not_citable` prove the sets are resolved at run time, and `test_citing_nothing_is_allowed` keeps the rule one-directional: fewer citations is a model with less to say, not a violation.
  - Criterion 3 (an ineligible candidate is never qualified): `test_an_imported_candidate_is_refused_before_any_model_call` and `test_an_ineligible_candidate_is_refused` both assert `provider.prompts == []` and no `ModelRun` — the refusal happens before anything is spent. `test_the_qualifiable_states_exclude_every_terminal_decision` pins the state set.
  - Criterion 4 (`human_review_required` always true): `test_human_review_is_always_required[True|False]` — parametrized over what the model asked for; `test_a_model_asking_for_no_review_is_recorded_as_having_asked` (overruled, not ignored — `model_requested_no_review` records the request); and `test_the_database_refuses_a_run_that_does_not_require_review`, a check constraint in the migration rather than a value the service remembers to set.
  - Criterion 5 (self-confidence controls nothing): `test_the_schema_has_no_confidence_field` (§10.4 has nowhere to put one), `test_no_branch_reads_a_confidence_value` (code lines only, prose excluded), `test_no_score_is_compared_against_a_threshold` (`Q-002`/`Q-020`), `test_the_scores_are_carried_through_unchanged` — the judgement reaches a reviewer intact and gates nothing. `test_a_reject_classification_still_stores_a_run` confirms the model's recommendation does not move the candidate lifecycle.
  - The prompt shows only stored rows: `test_the_prompt_contains_the_stored_evidence_and_its_id`, `test_the_prompt_marks_evidence_as_untrusted` (§15.4, in the prompt text itself), `test_the_prompt_names_no_fact_that_is_not_a_stored_row`, `test_a_candidate_with_no_evidence_still_renders_a_prompt`. Registration follows `T-051`: `test_the_prompt_registers_with_its_content_hash`, `test_registering_the_prompt_twice_publishes_nothing_new`, `test_the_prompt_names_no_vendor_or_model`.
  - **Three immutability guarantees corrected my tests rather than the reverse.** `ApprovedClaim` and `EvidenceSnapshot` are immutable by trigger (`T-014`, `T-019`), so "an expired claim" and "stale evidence" had to be *published* in that state instead of edited into it; and §8.2 has no `eligible → ineligible` edge, so the ineligible candidate is built from `imported`. Each is the schema being right.
  - Negative controls, each restored and re-verified green: letting the model decide review and removing the eligibility gate failed 4; trusting the citations failed 6; weakening the review constraint **in the migration** failed its structural test.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `149 files already formatted`; `mypy app` (strict) `Success: no issues found in 83 source files`; `pytest -q tests/test_qualification.py` `36 passed`; `pytest -q` `1331 passed`; `alembic upgrade head` / `downgrade -1` / `upgrade head` clean and `alembic check` `No new upgrade operations detected.`

#### T-054 — Draft creation from approved claim IDs and evidence IDs
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-053, T-020, T-014
- **Note (from `T-053`):** `check_grounding` is the citation check to reuse — a draft's claim and evidence citations need the same treatment, against the same resolvers.
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
- **Completion evidence:**
  - Shipped `app/drafts_and_approvals/drafting.py`, `app/drafts_and_approvals/templates/initial_outreach.txt`, `app/model_gateway/schemas/draft.py` (+ exported `draft-output.json`), `app/model_gateway/prompts/draft.txt`, and `tests/test_drafting.py` (29 tests). No schema change and no migration: `T-020` already owns `MessageDraft`/`MessageRevision` and their immutability trigger.
  - **The strongest guarantee is structural, not a validation.** `DraftOutput` has no `body` field, so there is no channel through which a model-written product sentence can arrive. The model returns a subject, one personalization paragraph, and claim *keys*; the claim wording is copied verbatim from the approved record and the boilerplate is rendered from a template. §10.5's "a free-form product statement without a claim ID fails validation" therefore has nothing to fail on. `test_the_model_cannot_supply_body_text_at_all` and `test_the_claim_text_in_the_body_is_byte_identical_to_the_approved_record` pin both halves.
  - Criterion 1 (revision 1 records the exact IDs): `test_the_revision_records_the_cited_ids`, `test_the_revision_has_a_content_hash_covering_its_citations` (recomputed with `T-020`'s hash function), `test_citing_no_claim_is_allowed`.
  - Criterion 2 (unknown or expired claim cannot be persisted): `test_an_unknown_claim_id_is_refused`, `test_an_expired_claim_id_is_refused` (published lapsed, since `ApprovedClaim` is immutable by trigger), `test_a_claim_approved_for_another_campaign_is_refused` (§14.4's allow-list), `test_an_unknown_evidence_id_is_refused`, `test_a_refused_draft_leaves_the_model_run_recorded` — nothing written, cost still recorded.
  - Criterion 3 (boilerplate rendered, not generated): `test_the_body_is_rendered_from_the_shipped_template`, `test_rendering_does_not_alter_the_claim_wording`, `test_a_purpose_with_no_template_cannot_be_drafted` (refused *before* a model call is spent), `test_rendering_refuses_a_purpose_with_no_template`.
  - Criterion 4 (drafting twice creates revision 2): `test_drafting_twice_creates_a_second_revision` (revision 1's subject and hash unchanged), `test_the_earlier_revision_is_retired_not_deleted`, `test_both_revisions_share_one_draft`, `test_the_database_refuses_an_edit_to_a_stored_revision` (`T-020`'s trigger).
  - Ordering and grounding: `test_an_unqualified_candidate_cannot_be_drafted` (§8.3 qualifies at step 7, drafts at step 9), `test_the_prompt_carries_the_claim_wording_and_evidence_ids`, `test_the_prompt_tells_the_model_it_does_not_describe_the_product`, `test_inputs_contain_only_stored_rows`, plus validation and §15.5 audit tests.
  - **A negative control found an untested guard.** Disabling `render_body`'s missing-template check produced no failure, because `draft_message`'s earlier check was the only one exercised; `test_rendering_refuses_a_purpose_with_no_template` now covers it, and the control fails against it.
  - **Adding a second prompt and schema broke five tests in `T-051` and `T-053` that indexed `register_*_versions(...)[0]` positionally.** Registration returns artefacts in key order, so `draft` and `draft-output` silently became `[0]`. Both suites now index by key, with a comment saying why. Caught by the broader suite, not the targeted one.
  - Paraphrase is deliberately not implemented: `allow_paraphrase` exists on the claim record, but nothing here asks for one or checks that a paraphrase stayed inside its constraints, so claims are reproduced exactly.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `152 files already formatted`; `mypy app` (strict) `Success: no issues found in 85 source files`; `pytest -q tests/test_drafting.py` `29 passed`; `pytest -q` `1360 passed`.

#### T-055 — Message revision validation (structure, claims, recipient, suppression, policy)
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-054, T-017, T-015
- **Note (from `T-054`):** drafting already resolves claim and evidence citations at creation time; this task validates the *stored revision* — the recheck that catches a claim expiring between drafting and approval.
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
- **Blocker / Q:** `Q-017` — not blocking: what counts as compliant *wording* stays a legal owner's decision, so the compliance check verifies the approved template's text is present and unedited rather than judging the text itself.
- **Completion evidence:**
  - Shipped `app/drafts_and_approvals/validation.py` (nine checks, `ValidationFailure`, `validate_revision`, `apply_validation`) and `tests/test_revision_validation.py` (34 tests). No schema change and no migration: `T-020` already owns the revision lifecycle and its immutability trigger.
  - Criterion 1 (a passing and a failing test per check): `test_a_well_formed_revision_passes_every_check` is the shared positive; the negatives are `test_claim_citations_fail_when_a_cited_claim_no_longer_resolves`, `test_claim_currency_fails_for_an_expired_claim_...`, `test_campaign_scope_fails_for_a_claim_approved_elsewhere`, `test_product_readiness_fails_when_the_status_lapses` and `..._when_policy_stops_permitting_it`, `test_evidence_citations_fail_when_a_snapshot_goes_stale`, `test_recipient_fails_when_the_address_is_unverified` and `..._for_a_non_email_contact_point`, `test_suppression_fails_at_every_scope[email|person|domain|account]`, `test_product_statement_grounding_fails_when_a_sentence_is_inserted` and `..._when_the_claim_wording_is_altered`, `test_compliance_elements_fail_when_the_boilerplate_is_removed` — each with its passing counterpart.
  - Criterion 2 (a failing revision never reaches `review_pending`): `test_a_valid_revision_moves_to_review_pending`, `test_any_failure_sends_the_revision_to_validation_failed`, `test_every_failing_check_is_reported_not_just_the_first`, `test_a_failed_revision_cannot_then_be_moved_to_review_pending` (§8.2 has no such edge — editing creates revision N+1), and `test_there_is_no_way_to_force_the_passing_transition` (no `override`, `force`, or `skip_checks` parameter exists).
  - Criterion 3 (an expired claim fails even with unchanged wording): `test_claim_currency_fails_for_an_expired_claim_even_though_the_wording_is_unchanged` asserts the body and content hash are *identical* to the revision that validated a moment earlier — only the claim's review date passed. This is precisely the check `T-054` structurally cannot make, since at drafting time the claim was current.
  - Criterion 4 (deterministic, no model): `test_the_module_calls_no_model` (AST; the boundary checker permits `model_gateway` here, so §8.3 step 10 is what forbids it), `test_validating_twice_produces_an_identical_result`, `test_a_failure_compares_by_value`, `test_every_check_in_the_enum_is_reachable`.
  - **"No free-form product statement" is a string comparison, not a judgement.** `T-054` renders every body as `personalization + cited claim texts + boilerplate`, so `_check_product_statement_grounding` asserts the cited claims appear verbatim, in order, immediately before the boilerplate. An inserted sentence or an altered word fails. Nothing here reads the prose for meaning, which is the only honest way to claim this check works.
  - Negative controls, each restored and re-verified green: truncating the failure list and importing `model_gateway` failed 3; sending every revision to `review_pending` and dropping the claim-currency check failed 2; accepting a tampered body and skipping suppression failed 7.
  - **The reader compensating check caught a real coupling risk.** `drafts_and_approvals` is a registered *reader* of `CampaignCandidateState` (`T-140`), and `test_a_reader_never_transitions_what_it_reads` flags any reader importing a bare `transition` name. The fix is a module-qualified `revisions.transition(...)` — aliasing the import would have evaded the check, which is the wrong repair for a guard that exists to stop exactly this.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `154 files already formatted`; `mypy app` (strict) `Success: no issues found in 86 source files`; `pytest -q tests/test_revision_validation.py` `34 passed`; `pytest -q` `1394 passed`.

#### T-056 — Claim-version and product-status invalidation job
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-055, T-021, T-030
- **Note (from `T-055`):** validation already fails a revision whose claim has lapsed *when it is validated*; this task is the push side — publishing a new version must invalidate dependent drafts and approvals without waiting for someone to re-validate.
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
- **Completion evidence:**
  - Shipped `app/drafts_and_approvals/invalidation.py` (`invalidate_for_claim`, `invalidate_for_product_status`, the `claims.invalidate_by_version` job type and its handler), `revision_already_sent` in `app/outreach_and_replies/commands.py`, and `tests/test_invalidation.py` (32 tests). No schema change and no migration.
  - **It lives in `drafts_and_approvals`, not `products_and_claims` as this block's file line said.** `drafts_and_approvals` already imports `products_and_claims`, so the other placement makes the import graph cyclic and `test_no_import_cycles` fails. What invalidation *changes* is revisions and approvals, which this module owns; the claim that triggers it is only read.
  - Criterion 1 (a new version invalidates every pending revision and approval): `test_a_pending_revision_citing_the_claim_is_invalidated`, `test_an_approved_but_unsent_revision_is_invalidated_and_its_approval_revoked` (the case the task singles out), `test_a_pending_approval_is_expired_rather_than_revoked` (§8.2 has no `pending → revoked` edge, so expiry is the edge that exists), `test_a_revision_citing_a_different_claim_is_untouched`, `test_a_readiness_change_reaches_revisions_through_the_products_claims`, `test_the_query_finds_only_invalidatable_revisions`.
  - Criterion 2 (idempotent, one audit event per entity): `test_running_twice_changes_nothing_the_second_time`, `test_each_affected_revision_gets_one_transition_event` (exactly one after two runs), `test_the_run_records_an_audit_event_naming_the_triggering_version`, `test_the_invalidation_reason_names_the_claim`, `test_a_run_that_changes_nothing_still_records_that_it_ran`, `test_a_second_claim_on_the_same_revision_still_finds_it_invalidated`.
  - Criterion 3 (a sent record is flagged, never altered): `test_an_already_sent_revision_is_not_altered` (state and approval unchanged) and `test_an_already_sent_revision_is_flagged` (an audit event naming the withdrawn claim). Whether a revision was dispatched is a fact `outreach_and_replies` owns and §18.2 forbids importing here, so it arrives as an injected `AlreadySentCheck` — the shape `T-035c` established. `test_the_sent_check_is_injected_because_the_import_is_forbidden` asserts the import is absent; `revision_already_sent` is the real check, tested separately, and it keys on an *attempt* rather than a success because `delivery_unknown` must count as sent (§17.3).
  - **`R-005` opened** rather than silently diverging: §14.4 says invalidation covers pending *drafts*, but §8.2 has no `draft → invalidated` edge. §8.2 stays authoritative for the state machine (ADR-015), and §14.4's intent is met by a different mechanism — a draft citing a withdrawn claim cannot pass `T-055`, so it never reaches a reviewer. `test_a_draft_revision_is_left_alone` pins the behaviour.
  - Job registration: `test_the_job_type_registers_with_an_explicit_retry_policy`, `test_the_job_type_is_not_consequential` (§17.6 — a pause stops work going *out*; withdrawing work is on the same side as the pause), `test_registering_twice_is_harmless`, plus handler tests for both trigger kinds, an unknown kind, a missing claim, and the `SYSTEM` actor recorded on an unattended run.
  - Negative controls, each restored and re-verified green: rewriting already-sent revisions and skipping approval revocation failed 4; adding `invalidated` to the invalidatable states (breaking idempotence) and marking the job consequential failed 5.
  - Checks: `ruff check` `All checks passed!`; `ruff format --check` `156 files already formatted`; `mypy app` (strict) `Success: no issues found in 87 source files`; `pytest -q tests/test_invalidation.py` `32 passed`; `pytest -q` `1426 passed`.

#### T-057 — Untrusted-content normalization before higher-authority prompts
- **Stage / Priority:** 1 / P1
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-046, T-051
- **Note (from `T-053`/`T-054`):** both prompts already fence evidence with an UNTRUSTED marker and instruct the model to treat it as data; this task is the *normalization* half — turning external text into typed facts before it reaches a prompt at all.
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
- **Completion evidence:** `uv run pytest -q tests/test_injection_resistance.py` → **80 passed**; full suite **1506 passed** (was 1426); `ruff check app tests` clean; `mypy app` clean on 89 files.
  1. **Corpus ≥ 10 payloads** — `app/fixtures/injection/payloads.json` holds **12** payloads across all four §19.4 channels (webpage, email, CRM note, attachment). Proven by `test_the_corpus_has_at_least_ten_distinct_payloads` (IDs and texts all distinct), `test_the_corpus_covers_every_channel_the_specification_names`, and `test_the_corpus_covers_the_attack_shapes_that_matter_here` (instruction override, suppression lift, readiness change, claim invention, tool selection, delimiter escape, schema subversion).
  2. **No payload alters structure, claims, suppression, or readiness** — `test_storing_a_payload_as_evidence_changes_no_claim_suppression_or_readiness` (parametrized ×12; row counts for `ApprovedClaim`, `Suppression`, `ProductStatusVersion` compared before/after) and `test_a_payload_never_reaches_a_readiness_or_suppression_decision` (parametrized ×12; `eligibility.evaluate` failure list and `is_suppressed` identical before/after). Asserted against the database, not against a model's answer, so the guarantee survives a model being fooled.
  3. **No raw untrusted text outside the delimited section** — `test_the_instruction_region_is_identical_with_and_without_the_payload` (parametrized ×12: the instruction region is byte-identical for benign and hostile evidence) and `test_every_payload_character_stays_inside_the_fence` (×12). Escape attempts are refused, not sanitized: `test_a_payload_forging_the_fence_is_refused`, `test_a_trusted_value_forging_the_fence_is_refused`, `test_a_hostile_field_name_is_refused_too`. Containment is structural — `test_the_template_has_no_placeholder_for_untrusted_content` proves `render_instructions` never sees a fact, and `test_containment_does_not_depend_on_recognizing_a_payload` proves there is no denylist to evade.
- **Negative controls (applied, observed failing, restored, suite re-verified green):** leaking fact text into the instruction region → **23 failed**; removing the fence-marker check on facts → 3 failed; removing it on trusted values → 1 failed; dropping Unicode category `Cf` so bidi overrides and zero-width characters survive → 3 failed; tolerating an unfilled placeholder → 1 failed. The first attempt at the leak control was a **syntax error, not a control** (the heredoc collapsed `\n` escapes); it was re-applied via the editor and re-verified by `grep` before being trusted.
- **Boundary correction:** the first implementation put `NormalizedFact` in `research_and_evidence` and imported it from `model_gateway`, which `test_module_boundaries.py` failed under §5.1 ("the LLM adapter must not own eligibility, approval, suppression, or execution"). The type is the *prompt's* input contract, so it now lives in `model_gateway/prompt_assembly.py` and `research_and_evidence/normalize.py` imports and re-exports it — the same direction `qualification` already depends on the gateway. Caught by the existing checker, not by inspection.
- **Deliberately not claimed:** nothing here shows a *real model* ignores an instruction it was told to treat as data — no real model runs under gate **G-03**. What is proven is placement, containment, traceability (every fact line carries its evidence ID), and the absence of any deterministic path that reads evidence text. `T-083` owns the model-behavior half.

#### T-058 — Stage 1 exit: end-to-end shadow slice with zero external writes
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31 — `T-058a`, `T-058b`, and `T-058c` are all `DONE`; gate **G-02** is **OPEN**)
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
- **Status note (2026-07-30):** **Split into `T-058a`, `T-058b`, `T-058c`.** Scope (in) names "driving the whole path through the worker", but no domain module registers a job handler for any pipeline step today — `jobs_and_outbox.registry` holds only `claims.invalidate_by_version` and the webhook processor. Building six handlers *and* the integration harness *and* the exit-evidence record in one change set is not reviewable, and the handlers need idempotency decisions per step that the harness does not. This parent stays as the acceptance-intent record and becomes `DONE` only when all three children are. Criteria map: 1, 2, 3 → `T-058a`; the "through the worker" clause → `T-058b`; 4 and 5 → `T-058c`.
- **Completion evidence:** —

#### T-058a — Shadow-slice integration harness: empty database to review-ready draft
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-024, T-035, T-036, T-045, T-046, T-053, T-054, T-055, T-056, T-057, T-146
- **Spec:** §19.6 Stage 1 exit gate, §24 item 5, §3.5, §8.3
- **Objective:** Drive the complete import → membership → eligibility → evidence → qualification → draft → validated review-ready revision path on synthetic fixtures, and prove no external effect of any kind occurred.
- **Scope (in):** One integration test composing the real module entry points in §8.3 order against the seeded synthetic world; a network-guard fixture that fails the test if any socket is opened to anything but the test database; assertions that every intermediate entity exists and that the audit events form one chain per candidate correlation ID; the per-campaign draft fixtures the fake model adapter needs.
- **Scope (out):** Registering the path as job types and running it through the worker (`T-058b`); the exit-evidence document and the gate change (`T-058c`); dashboard (Stage 2); any approval-triggered send.
- **Acceptance criteria:**
  1. The test starts from an empty migrated database and ends with at least one `review_pending` revision per campaign.
  2. A network-guard fixture fails the test if any socket is opened; the guard itself has a control proving it can fail.
  3. Every intermediate entity is present, and the audit events for a candidate form a complete chain under one correlation ID.
- **Verification:** `uv run pytest -q tests/test_shadow_slice.py`
- **Files:** `backend/tests/test_shadow_slice.py`, `backend/tests/netguard.py`, `backend/tests/conftest.py`, `backend/app/fixtures/model_outputs/slice_*/`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_shadow_slice.py` -> **28 passed**; full suite **1547 passed** (was 1506); `ruff check app tests` clean; `mypy app` clean on 89 files.
  1. **Empty database to review-ready revision per campaign** - `test_the_database_starts_empty` asserts the precondition rather than assuming it; `test_each_campaign_reaches_at_least_one_review_pending_revision` asserts every revision that exists is `review_pending` and that the count matches what the slice produced; `test_the_two_campaigns_produced_independent_revisions` (ADR-012) and `test_the_slice_refused_more_candidates_than_it_advanced` — the corpus is mostly refusal cases, so a slice that advanced everything would be a slice whose eligibility gate did nothing. Observed: 15 candidates, 5 advanced, 10 refused (2 geography, 8 contactability).
  2. **Network guard, with its own control** - `test_the_guard_blocks_an_outbound_connection`, `test_the_guard_blocks_create_connection`, and `test_the_guard_blocks_connect_ex` each drive a refused connection to a TEST-NET-1 address; `test_the_guard_still_permits_the_test_database` proves it is not simply blocking everything; `test_the_whole_slice_runs_under_the_guard` names the guarantee that the `slice_result` fixture's dependency on `no_network` otherwise only implies.
  3. **Every intermediate entity, one audit chain per candidate** - `test_every_intermediate_entity_exists` over eleven models; `test_each_advanced_candidate_has_one_complete_audit_chain`; `test_no_candidate_scoped_audit_event_is_missing_its_correlation_id`; `test_the_correlation_ids_are_distinct_per_candidate`; `test_starting_the_campaigns_is_audited`.
- **Beyond the criteria, because the slice is where they are cheap:** `test_nothing_was_queued_for_sending` (no `SendCommand`, `SendAttempt`, or `OutboxEvent`), `test_no_revision_was_approved`, `test_every_model_run_used_the_fake_provider`, `test_the_slice_is_deterministic` (two runs, same shape), and `test_seeding_alone_produces_no_candidate` — the control for the one line of the slice that is an operator act rather than a pipeline step.
- **Negative controls (applied, observed failing, restored, suite re-verified green):** making the network guard a no-op -> 3 failed; leaving the campaigns paused -> 12 failed; pointing the no-send assertion at a table known to be populated -> 1 failed. `T-146`'s two controls are recorded on its own block.
- **What it found:** the slice could not advance a single candidate on first run. `T-041`'s corpus declares a `verification_state` column and `T-042`'s importer silently ignored it, so every address landed `unverified` and failed `Rule.CONTACTABILITY`. Filed and fixed as `T-146` rather than patched here. Two tasks had disagreed for three cycles and nothing failed, because no test imported a row and then asked whether the address was contactable — which is the case for building the slice at all.
- **Design notes:** seeded campaigns start paused (`T-015`) and `create_memberships` gives a paused campaign no candidates (§17.6), so the slice starts them explicitly and audits it; seeding them already running would have quietly removed the control. The fake model needs one fixture directory per `match: "default"`, and qualification grounding is campaign-scoped, so the slice uses one shared qualification directory citing no claims plus one draft directory per campaign. `NetworkUsed` lives in `tests/netguard.py`, not `conftest.py`: pytest imports `conftest.py` as top-level `conftest`, so a test importing `tests.conftest` would catch a different class than the fixture raises — which is exactly what happened, and read as the guard failing to fire.

#### T-058b — The shadow slice as registered job types, executed by the worker
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31 — reconciled: `T-058b1` and `T-058b2` are both `DONE`)
- **Depends on:** T-058a
- **Spec:** §17.1, §7.2, §8.3, §19.6
- **Objective:** Run the same slice through `jobs_and_outbox.runner` so the path is executed the way production would execute it, not only the way a test can call it.
- **Scope (in):** A job type per §8.3 step that the slice performs, each registered by its owning domain module with a typed payload; idempotency for each (a replayed job must not double-write); the slice test extended to drive the worker rather than call the functions directly.
- **Scope (out):** Any external effect; scheduling policy; concurrency tuning.
- **Acceptance criteria:**
  1. Each pipeline step is a registered job type owned by its domain module, not by `jobs_and_outbox`.
  2. Replaying every job in the slice produces no second candidate, evidence snapshot, qualification run, or revision.
  3. The slice reaches the same terminal state through the worker as `T-058a` reaches directly.
- **Verification:** `uv run pytest -q tests/test_shadow_slice.py tests/test_jobs.py`
- **Files:** `backend/app/*/jobs.py`, `backend/tests/test_shadow_slice.py`
- **Blocker / Q:** none
- **Status note (2026-07-30):** **Split into `T-058b1` and `T-058b2`.** The slice has seven steps across five modules, and the back half needs something the front half does not: a way for a handler to obtain a model gateway and a source adapter. `JobHandler` is `(session, payload, *, job_id)` — there is no argument to pass either through — and the two obvious answers are both wrong as they stand. `build_provider` returns `EchoModelAdapter`, not `T-052`'s fixture-keyed `FakeModelAdapter`, so a qualification handler built on it would produce output that fails §10.4 validation; and the only Stage 1 source adapter reads `app/fixtures/`, which `T-040` forbids production code to import. Resolving that is a design decision of its own and does not belong in the same change set as the chaining pattern. This parent stays as the acceptance-intent record and becomes `DONE` only when both children are. Criteria map: 1 and 2 → both children, each for the steps it owns; 3 → `T-058b2`.

#### T-058b1 — Membership and eligibility as chained job types
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-30)
- **Depends on:** T-058a
- **Spec:** §17.1, §7.2 ("commit state + audit + next job/outbox atomically"), §8.3 steps 2–4
- **Objective:** Establish the chaining pattern on the two pipeline steps that need no model provider and no source adapter, executed by the worker.
- **Scope (in):** `campaigns.create_membership` and `qualification.apply_eligibility` as job types, each registered by its owning domain module with a typed payload and an explicit retry policy and `consequential` flag; each idempotent under replay; the membership handler enqueuing one eligibility job per candidate in the same transaction; tests driving both through `runner.execute`.
- **Scope (out):** Evidence capture, qualification, drafting, and validation (`T-058b2`); making CSV import itself a job — an operator uploading a file is a request, not background work, and the import commits the batch then enqueues the first jobs; any external effect.
- **Acceptance criteria:**
  1. Both job types are registered by their owning domain module; `tests/test_module_boundaries.py` still passes, proving `jobs_and_outbox` gained no domain knowledge.
  2. Replaying either job produces no second candidate and no second transition; test-proven for each.
  3. A membership job leaves one eligibility job queued per candidate it created, in the same transaction, and the worker runs the chain to a candidate in `eligible` or `ineligible`.
- **Verification:** `uv run pytest -q tests/test_pipeline_jobs.py tests/test_jobs.py tests/test_module_boundaries.py`
- **Files:** `backend/app/campaigns/jobs.py`, `backend/app/qualification/jobs.py`, `backend/tests/test_pipeline_jobs.py`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_pipeline_jobs.py` -> **24 passed**; full suite **1571 passed** (was 1547); `ruff check app tests` clean; `mypy app` clean on 91 source files. No migration.
  1. **Owned by the domain module** - `test_both_job_types_are_registered_by_their_owning_module` asserts by *handler identity* (`registry.get(name).handler is campaign_jobs.handle_membership`), not by the registry's contents; `test_the_job_types_are_namespaced_to_their_module`; `test_registering_twice_is_a_no_op`; `test_neither_job_type_is_consequential` and `test_both_types_declare_a_retry_policy` for the two flags §17.1 and §17.6 require to be explicit. `tests/test_module_boundaries.py` still passes (10 passed), so `jobs_and_outbox` gained no domain knowledge.
  2. **Replay changes nothing** - `test_replaying_a_membership_job_creates_no_second_candidate`, `test_replaying_a_membership_job_writes_no_second_candidate_audit_event`, `test_replaying_an_eligibility_job_does_not_transition_twice`, `test_a_replayed_eligibility_job_succeeds_rather_than_failing` (the outcome a queue needs: replay leaves the queue), and `test_an_already_decided_candidate_is_left_alone` parametrized over `eligible` and `ineligible`.
  3. **The chain runs in one transaction** - `test_a_membership_job_queues_one_eligibility_job_per_candidate`, `test_the_follow_on_job_inherits_the_correlation_id`, `test_the_whole_chain_runs_to_a_decided_candidate` (one enqueue, two jobs run, candidate `eligible`), `test_a_refused_candidate_also_terminates_the_chain`, `test_two_campaigns_produce_two_candidates_and_two_eligibility_jobs`.
- **Also asserted:** `test_the_eligibility_payload_has_no_field_that_could_force_an_outcome` - structural, not behavioural. §10.1 and §3.5 put the decision beyond a caller's reach and `apply_eligibility` has no override argument; this pins that the payload did not reintroduce one. Plus `test_a_missing_candidate_is_a_permanent_failure`, `test_an_unknown_campaign_slug_does_not_fail_the_job`, and two `enqueue`-refuses-a-bad-payload tests (§17.1: a malformed job must never reach the queue).
- **Negative controls (applied, observed failing, restored, suite re-verified green):** removing the eligibility replay guard -> 4 failed; the membership handler no longer chaining -> 6 failed; chaining only for newly *created* candidates rather than all of them -> 1 failed; a missing candidate raising a retryable error instead of `PermanentFailure` -> 1 failed (observed `outcome=retry` where the job should dead-letter).
- **Design notes:** `campaigns.jobs` names the next job type as a **string**, not an import - `qualification.eligibility` already imports `campaigns`, so importing `qualification.jobs` back would make the package graph cyclic and `test_no_import_cycles` says so. `enqueue` resolves the payload model from the registry, so a wrong name is a refused enqueue rather than a bad job, and `test_the_chained_job_name_matches_the_type_it_names` pins the two constants together. The eligibility guard is explicit rather than incidental: §8.2 has no `eligible -> eligible` edge (`T-010`), so a replay without it would raise an illegal transition, be classified permanent, and dead-letter a job that had already succeeded. The membership handler deliberately enqueues for existing candidates too, so a crash between the membership write and the enqueue cannot strand a candidate with no follow-on work; a duplicate eligibility job is harmless because that job is idempotent, which `test_replaying_a_membership_job_still_queues_the_follow_on` records as the intended trade.
- **Test-isolation note:** the fixture populates the **process-wide** registry, because `handle_membership` chains through `queue.enqueue`, which resolves the payload model from the default registry - a handler cannot be handed a test registry, so a private `JobRegistry()` would have tested a chain that could never link. It snapshots and restores rather than calling `clear()`, which would discard another module's registrations. Two assertions were first written against the registry's whole name list and passed alone but failed in the full suite; both now assert on the two types this task owns.

#### T-058b2 — Evidence, qualification, drafting, and validation as chained job types
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31 — reconciled: `T-058b2a` and `T-058b2b` are both `DONE`)
- **Depends on:** T-058b1
- **Spec:** §17.1, §7.2, §8.3 steps 5–10, §18.5 (fake adapters before real providers)
- **Objective:** Complete the cascade, and decide how a job handler obtains a model gateway and a source adapter without production code importing fixtures.
- **Scope (in):** A resolution mechanism for handler dependencies that keeps `app/fixtures/` out of every production import path — an empty-by-default registry the CLI and tests populate, following `model_gateway.registry.REAL_PROVIDER_ADAPTERS`; `research.capture_evidence`, `qualification.qualify_candidate`, `drafts.draft_message`, and `drafts.validate_revision` as job types; idempotency for each, including the two that are not naturally idempotent (a second qualification run and a second revision must not be created); the shadow slice driven end to end by the worker.
- **Scope (out):** Any real provider or real source (gates **G-03**, **G-06**); approval or send.
- **Acceptance criteria:**
  1. No module under `app/` outside `app/fixtures/` imports `app.fixtures`, still enforced by `tests/test_fixtures.py`, with the adapter registry empty by default.
  2. Replaying every job in the slice produces no second evidence snapshot, qualification run, or revision.
  3. `tests/test_shadow_slice.py` reaches the same terminal state through the worker as it reaches by direct composition, asserted against the same counts.
- **Verification:** `uv run pytest -q tests/test_shadow_slice.py tests/test_pipeline_jobs.py`
- **Files:** `backend/app/research_and_evidence/jobs.py`, `backend/app/qualification/jobs.py`, `backend/app/drafts_and_approvals/jobs.py`, `backend/tests/test_shadow_slice.py`
- **Blocker / Q:** none
- **Status note (2026-07-30):** **Split into `T-058b2a` and `T-058b2b`.** Two things surfaced in preflight that change the shape of the work. First, **nothing drives §8.2 past `eligible`**: `capture_evidence` and `qualify_candidate` gate on candidate state but neither transitions it, which is why `T-058a`'s direct slice drafted from a candidate still sitting in `eligible`. A job *is* a workflow step, so the handlers are the right owner of those transitions — and that makes each job type a state-machine change, not just a call wrapper. Second, **§8.3 step 9 gates drafting on candidate approval**, not on qualification finishing, so the automatic chain must stop at step 8 ("present the candidate for human review") and drafting must be triggered by an approval that only the Stage 2 dashboard can produce. Chaining drafting off qualification would encode "draft without candidate approval" into the production path. This parent stays as the acceptance-intent record and becomes `DONE` only when both children are. Criteria map: 1 → `T-058b2a`; 2 and 3 → both, each for the steps it owns.

#### T-058b2a — Handler-dependency resolution and evidence capture as a job type
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058b1
- **Spec:** §17.1, §7.2, §8.3 steps 5–6, §8.2 (candidate lifecycle), §18.5, §15.3
- **Objective:** Give a job handler a way to obtain a source adapter without production code importing fixtures, and run §8.3 steps 5–6 as a chained job that advances the candidate through its lifecycle.
- **Scope (in):** An empty-by-default source-adapter registry in `research_and_evidence`, following `model_gateway.registry.REAL_PROVIDER_ADAPTERS`, populated by the CLI and tests; `research.capture_evidence` as a job type owned by `research_and_evidence`, named in its payload by adapter name rather than by object; the `eligible → research_pending → researched` transitions §8.2 defines and nothing currently performs; the eligibility job chaining into it on an eligible outcome only.
- **Scope (out):** Qualification, drafting, and validation (`T-058b2b`); the model gateway's own resolution, which `build_provider` already owns; any real source (gate **G-06**, `Q-003`).
- **Acceptance criteria:**
  1. The source-adapter registry is empty by default and no module under `app/` outside `app/fixtures/` imports `app.fixtures`; both test-proven, the second still by `tests/test_fixtures.py`.
  2. Replaying the capture job produces no second evidence snapshot and no second transition; test-proven.
  3. An eligible candidate reaches `researched` with its evidence stored, driven only by the worker from one membership job; an ineligible one enqueues no capture job.
- **Verification:** `uv run pytest -q tests/test_pipeline_jobs.py tests/test_fixtures.py tests/test_evidence_capture.py`
- **Files:** `backend/app/research_and_evidence/adapters/registry.py`, `backend/app/research_and_evidence/jobs.py`, `backend/app/qualification/jobs.py`, `backend/tests/test_pipeline_jobs.py`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_pipeline_jobs.py` -> **45 passed, 2 xfailed**; full suite **1592 passed, 2 xfailed**; `ruff check app tests` clean; `mypy app` clean on 93 source files. No migration.
  1. **Registry empty by default, fixtures unimported** - `test_the_source_adapter_registry_is_empty_by_default` (asserted against the module source, because the fixtures in that file register into the live dict and a runtime check after they ran would prove nothing) and `test_no_production_module_registers_an_adapter` (AST-free scan of every `app/**/*.py` for a call to the registrar). `tests/test_fixtures.py` still passes unchanged. Refusal quality: `test_an_unregistered_adapter_name_is_refused` and `test_the_refusal_names_the_gate_rather_than_failing_quietly` — a job that silently captured nothing would leave a candidate that *looks* researched.
  2. **Replay stores no second snapshot** - `test_replaying_a_capture_job_stores_no_second_snapshot` and `test_a_replayed_capture_records_that_it_stored_nothing`, which asserts the replay's audit event records `captured: 0` and `duplicates: N`. A replay *does* write a second audit event and that is correct — each capture attempt is a real event — so the assertion is on the trail's content rather than on its length. `test_a_replayed_capture_job_succeeds_rather_than_failing` pins the outcome a queue needs.
  3. **Worker-driven, chained only on a pass** - `test_the_chain_reaches_capture_with_evidence_stored` (one enqueue, three jobs run, snapshots stored), `test_an_eligible_candidate_queues_a_capture_job`, `test_an_ineligible_candidate_queues_no_capture_job`, `test_a_candidate_with_no_matching_documents_captures_nothing_and_still_succeeds` (GP-02: missing facts remain missing), `test_the_chain_stops_at_researched`, plus ownership and failure-mode tests.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, suite re-verified green):** chaining capture for ineligible candidates too -> 1 failed; removing the capture state guard -> 1 failed; a missing adapter raising a retryable error instead of `PermanentFailure` -> 1 failed (observed `outcome=retry` where the job must dead-letter); a production module calling `register_source_adapter` -> 1 failed.
- **Two tests were weaker than they read, and the controls found it.** `test_an_ineligible_candidate_queues_no_capture_job` asserted on *queued* jobs, but `drain` had already run and dead-lettered the offending job, so the queue was empty either way — it now counts capture jobs in any state. And the capture state guard was entirely unexercised, because nothing moves a candidate out of `eligible` (`T-147`); `test_a_candidate_past_research_returns_instead_of_dead_lettering` now builds that state directly.
- **Safety invariant upheld, not widened:** the handler was first written to advance the candidate `eligible -> research_pending -> researched`, and `tests/test_invariants.py::test_a_reader_never_transitions_what_it_reads[CampaignCandidateState]` failed — correctly, because ADR-015 lists `research_and_evidence` as a *reader* of that lifecycle. The transitions were removed rather than the guard widened, and the gap is filed as **`T-147`** with two `xfail(strict=True)` tests naming it (`test_the_chain_reaches_researched`, `test_the_candidate_passes_through_research_pending`) so it cannot be forgotten and cannot silently start passing.

#### T-058b2b — Qualification, drafting, and validation as job types
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31 — reconciled: `T-058b2b1` and `T-058b2b2` are both `DONE`)
- **Depends on:** T-058b2a, T-147
- **Was blocked because:** criterion 1 is "the automatic chain stops with the candidate in `review_pending`", and the qualification job's transition is `researched -> review_pending`. No candidate reaches `researched` while `T-147` is open, so the criterion cannot be satisfied and a qualification job written against it could not be tested. Not a `Q-###`: no product decision is missing, only the ownership decision `T-147` carries.
- **Spec:** §17.1, §7.2, §8.3 steps 7–10, §8.2
- **Objective:** Complete the cascade to the point §8.3 says it must stop, and express drafting as approval-triggered rather than chained.
- **Scope (in):** `qualification.qualify_candidate` chained from capture, moving the candidate `researched → review_pending`, where the automatic chain **ends** (§8.3 step 8); `drafts.draft_message` and `drafts.validate_revision` as job types whose trigger is a candidate approval, not the completion of qualification; how a handler obtains a model gateway, given `build_provider` returns `EchoModelAdapter` rather than `T-052`'s fixture-keyed adapter; idempotency for each, including the two that are not naturally idempotent (a second qualification run and a second revision must not be created); the shadow slice driven end to end by the worker.
- **Scope (out):** Candidate approval itself, which is the Stage 2 dashboard behind gate **G-02**; any send.
- **Acceptance criteria:**
  1. The automatic chain stops with the candidate in `review_pending` and no draft; test-proven that qualification enqueues no drafting job.
  2. Replaying every job in the slice produces no second qualification run and no second revision.
  3. `tests/test_shadow_slice.py` reaches the same terminal state through the worker as by direct composition, asserted against the same counts.
- **Verification:** `uv run pytest -q tests/test_shadow_slice.py tests/test_pipeline_jobs.py`
- **Files:** `backend/app/qualification/jobs.py`, `backend/app/drafts_and_approvals/jobs.py`, `backend/tests/test_shadow_slice.py`
- **Blocker / Q:** none
- **Status note (2026-07-31):** **Split into `T-058b2b1` and `T-058b2b2`.** The scope holds three separable things: how a handler obtains a model gateway, the qualification job, and the approval-triggered drafting pair plus the slice rewrite. The first is a decision of the same weight as ADR-020 — `build_provider` is deliberately "the only way to obtain an adapter, so there is a single place to audit", and the fixture-keyed `FakeModelAdapter` needs a directory under `app/fixtures/` that `T-040` forbids production code to import. Settling that and proving it on one job is a change set; the drafting pair is another, and it is the one that must express §8.3 step 9's "on candidate approval" without a dashboard to produce an approval. This parent stays as the acceptance-intent record and becomes `DONE` only when both children are. Criteria map: 1 and the qualification half of 2 → `T-058b2b1`; the revision half of 2 and 3 → `T-058b2b2`.

#### T-058b2b1 — Model-gateway resolution for job handlers, and qualification as a chained job
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058b2a, T-147
- **Spec:** §17.1, §7.2 ("validate policy and input version"), §8.3 steps 7–8, §10.1 stage 2, §14.5, §18.4, ADR-017, ADR-020
- **Objective:** Let a job handler obtain the deterministic fake model without production code importing fixtures, and run §8.3 step 7 as a chained job that ends the automatic cascade where step 8 says it must.
- **Scope (in):** A resolution path for the fake provider's adapter that keeps `build_provider` the single audited entry point and leaves the default unchanged; `qualification.qualify_candidate` as a job type owned by `qualification`, resolving the current prompt, schema, and model-config versions itself so the run cites what it used (§14.5); `campaigns.complete_research` chaining into it; the `researched → review_pending` transition, which `qualification` may perform because it is already a `LIFECYCLE_OWNERS` member; idempotency — a replay must create no second `QualificationRun`.
- **Scope (out):** Drafting and validation (`T-058b2b2`); the shadow slice rewrite (`T-058b2b2`); any real provider (gate **G-03**, `Q-012`).
- **Acceptance criteria:**
  1. `build_provider` remains the only way to obtain a model adapter and still returns the echo adapter by default; test-proven, and no module under `app/` outside `app/fixtures/` imports `app.fixtures`.
  2. The automatic chain stops with the candidate in `review_pending` and enqueues nothing further; test-proven that no drafting job is queued.
  3. Replaying the qualification job creates no second `QualificationRun` and performs no second transition.
- **Verification:** `uv run pytest -q tests/test_pipeline_jobs.py tests/test_model_gateway.py tests/test_qualification.py`
- **Files:** `backend/app/model_gateway/registry.py`, `backend/app/qualification/jobs.py`, `backend/app/campaigns/jobs.py`, `backend/tests/test_pipeline_jobs.py`
- **Blocker / Q:** none
- **Decision:** the *fake* provider's construction became a hook (`set_fake_adapter_factory`) that the CLI and tests install into, defaulting to `EchoModelAdapter`. `build_provider` stays the only way to obtain an adapter and the only place to audit; the hook changes **which fake** is built and cannot make a real provider appear, because all three **G-03** locks sit on the other branch. The same shape `T-058b2a` used for source adapters, chosen over a `Settings` fixture-directory field — which production would leave unset, silently falling back to the echo adapter and producing output that fails §10.4 validation with no indication why.
- **Completion evidence:** `uv run pytest -q tests/test_pipeline_jobs.py` -> **76 passed**; `tests/test_model_gateway.py` **34 passed** unchanged; full suite **1623 passed** (was 1604); `ruff check app tests` clean; `mypy app` clean on 93 source files. No migration.
  1. **`build_provider` still the single entry point, default unchanged** — `test_build_provider_returns_the_echo_adapter_by_default`, `test_the_hook_changes_which_fake_is_built`, `test_the_hook_cannot_make_a_real_provider_appear` (`REAL_PROVIDER_ADAPTERS` still empty), `test_build_provider_is_still_the_only_entry_point` (the gateway constructs no adapter of its own), and `test_no_production_module_installs_a_fake_adapter`. `tests/test_fixtures.py` unchanged.
  2. **The chain ends at review, and enqueues nothing** — `test_the_full_chain_reaches_review_pending` (one enqueue, six jobs, candidate `review_pending`), `test_the_chain_stops_there_and_queues_nothing`, and `test_no_revision_exists_after_the_automatic_chain`, which asserts the same guarantee against the database rather than the queue. This is the load-bearing one: §8.3 step 9 creates a draft *on candidate approval*, and a chain that drafted here would encode "draft without approval" into the production path, producing a draft that looks perfectly well-formed.
  3. **Replay creates no second run** — `test_replaying_the_qualify_job_creates_no_second_run` (`qualify_candidate` writes a `QualificationRun` on every call, so the state guard is the only thing between a replay and a duplicate judgement), `test_replaying_the_qualify_job_does_not_transition_twice`, `test_a_replayed_qualify_job_succeeds_rather_than_failing`.
- **Also proven:** the run cites its versions (`test_the_run_cites_the_versions_it_used`, §14.5/§17.5), a missing version dead-letters rather than retrying (`test_a_missing_model_config_version_is_permanent`), and `test_the_qualify_payload_cannot_carry_a_verdict` — structural, so the §10.1 judgement stays beyond a caller's reach the way `test_the_eligibility_payload_has_no_field_that_could_force_an_outcome` does for step 4.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, suite re-verified green):** qualification chaining onward instead of stopping at review -> 1 failed; the qualification replay guard removed -> 3 failed; a missing version raising a retryable error instead of `PermanentFailure` -> 1 failed (observed `outcome=retry` where it must dead-letter); `complete_research` no longer chaining into qualification -> 7 failed; the fake-adapter hook defaulting to something other than echo -> 1 failed.

#### T-058b2b2 — Approval-triggered drafting and validation, and the slice through the worker
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31 — reconciled: `T-058b2b2a` and `T-058b2b2b` are both `DONE`)
- **Depends on:** T-058b2b1
- **Spec:** §17.1, §7.2, §8.3 steps 9–11, §8.2, §10.5
- **Objective:** Express drafting as approval-triggered rather than chained, and drive the whole shadow slice through the worker.
- **Scope (in):** `drafts.draft_message` and `drafts.validate_revision` as job types whose trigger is a candidate approval, not the completion of qualification — §8.3 step 9 says "on candidate approval", and chaining them off qualification would encode "draft without approval" into the production path; idempotency for both (a second revision must not be created); a test-only way to produce the candidate approval that Stage 2 will produce for real, without anticipating the dashboard's authority; `tests/test_shadow_slice.py` driven by the worker.
- **Scope (out):** The dashboard and real approval authority, which are Stage 2 behind gate **G-02**; any send.
- **Acceptance criteria:**
  1. Neither drafting nor validation can be reached from the automatic chain; test-proven that only an approval enqueues them.
  2. Replaying either job creates no second revision and performs no second transition.
  3. `tests/test_shadow_slice.py` reaches the same terminal state through the worker as by direct composition, asserted against the same counts.
- **Verification:** `uv run pytest -q tests/test_shadow_slice.py tests/test_pipeline_jobs.py`
- **Files:** `backend/app/drafts_and_approvals/jobs.py`, `backend/tests/test_shadow_slice.py`
- **Blocker / Q:** none
- **Status note (2026-07-31):** **Split into `T-058b2b2a` and `T-058b2b2b`.** Two pieces with a clean seam. The job types answer "what triggers a draft, and how does it fail closed if something else tries" — new production code and its tests. The slice rewrite answers "does the whole thing still hold when the worker drives it" — it replaces `run_slice`'s direct composition and must keep all 28 existing assertions honest, which is a different kind of care. Doing both at once would mean changing the harness that proves the pipeline in the same change set that changes the pipeline. Criteria map: 1 and 2 → `T-058b2b2a`; 3 → `T-058b2b2b`.

#### T-058b2b2a — Approval-triggered drafting and validation as job types
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058b2b1
- **Spec:** §8.3 steps 9–11, §10.5, §8.2, §17.1, §7.2, ADR-008, ADR-020
- **Objective:** Make a draft reachable only from a candidate approval, and prove it fails closed if anything else tries.
- **Scope (in):** `drafts.draft_message` and `drafts.validate_revision` as job types owned by `drafts_and_approvals`; the drafting handler refusing any candidate not in `approved`, so the guarantee is a precondition rather than a property of who happens to enqueue it; a `campaigns`-owned approval entry point that transitions `review_pending → approved` and enqueues the drafting job in the same transaction, whose *authority* Stage 2 supplies and which is called only by tests today; version resolution as `T-058b2b1` does it; idempotency for both jobs.
- **Scope (out):** The dashboard, real approver authority, and any notion of who may approve — Stage 2 behind gate **G-02**; the shadow-slice rewrite (`T-058b2b2b`); any send.
- **Acceptance criteria:**
  1. The automatic chain still reaches `review_pending` and enqueues no drafting job; only an approval does. Test-proven from both directions.
  2. A drafting job for a candidate that is not `approved` fails closed rather than drafting; test-proven for every other state the candidate can be in.
  3. Replaying either job creates no second revision and performs no second transition.
- **Verification:** `uv run pytest -q tests/test_pipeline_jobs.py tests/test_drafting.py tests/test_revision_validation.py`
- **Files:** `backend/app/drafts_and_approvals/jobs.py`, `backend/app/campaigns/approval.py`, `backend/tests/test_pipeline_jobs.py`
- **Blocker / Q:** none
- **Design:** the guarantee is a **precondition on the handler**, not a convention about who enqueues. `drafts.draft_message` refuses any candidate that is not `approved` and dead-letters rather than returning quietly — a stray enqueue, a replayed payload from a queue dump, or a future chain added without reading §8.3 must all get nothing, and a convention holds none of them. `campaigns.approval.approve_candidate` is the ordinary path to it: it transitions `review_pending -> approved` and enqueues the drafting job in the same transaction (§7.2). It is the *mechanism*, not the authority — who may approve is `Q-005` and where is the Stage 2 dashboard; the function takes an `Actor`, records it, checks no roles, and must not grow to. The recipient is an **argument**, because ADR-008 approves an exact recipient and an exact revision together, so which address was approved is part of the approver's decision rather than something the system derives and they ratify unseen; it also keeps `campaigns` from importing `prospects`, which `test_no_import_cycles` refuses.
- **Completion evidence:** `uv run pytest -q tests/test_pipeline_jobs.py` -> **103 passed**; full suite **1650 passed** (was 1623); `ruff check app tests` clean; `mypy app` clean on 95 source files. No migration.
  1. **The automatic chain never reaches drafting** — `test_the_automatic_chain_queues_no_drafting_job` (counted in *any* job state, not just `queued`, because `drain` would otherwise have run and failed the job and left the queue empty), `test_only_an_approval_enqueues_a_drafting_job` from the other direction, and `test_the_approval_and_the_job_land_together` for §7.2.
  2. **A drafting job fails closed for every other candidate state** — `test_a_drafting_job_for_an_unapproved_candidate_fails_closed` parametrized over `eligible`, `ineligible`, `research_pending`, `researched`, and `review_pending`; `test_the_refusal_is_permanent_rather_than_silent`. Approval itself is refused outside `review_pending` (`test_approving_a_candidate_that_is_not_in_review_is_refused`, `test_a_refused_approval_queues_nothing`).
  3. **Replay creates no second revision** — `test_replaying_the_drafting_job_creates_no_second_revision`, `test_a_replayed_drafting_job_requeues_the_validation` (deliberate: a crash between writing the revision and enqueueing would otherwise strand it in `draft` forever, and a duplicate validation job is harmless because that job is idempotent), `test_replaying_the_validation_job_does_not_transition_twice`, `test_a_replayed_validation_job_succeeds_rather_than_failing`.
- **Also proven:** the approved path reaches a `review_pending` revision citing an approved claim; drafting queues its own validation (§8.3 step 10 before step 11); nothing is queued after validation; and no `SendCommand`, `SendAttempt`, or `OutboxEvent` exists — Stage 1 ends where §8.3 step 12's second approval would begin.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, suite re-verified green):** the drafting handler no longer requiring an approved candidate -> 6 failed; the drafting replay guard removed -> 1 failed; the validation replay guard removed -> 2 failed; drafting no longer queueing its validation -> 3 failed; approval no longer checking the candidate is in review -> 5 failed.
- **The key control found a weak test, twice over.** On its first run, removing the approval precondition failed only *one* test: the five parametrized cases used a world with no draft model-config version registered, so the job still died — for the wrong reason — and the assertion stayed green. Both tests now use `draftable_world`, where every version drafting needs exists, so the approval precondition is the only thing standing between the job and a revision. Separately, the fixture-keyed fake needed a `TaskRoutingFake` wrapper: `match: "default"` answers *any* prompt, so a directory holding only the qualification default answered the **draft** prompt with qualification-shaped JSON, surfacing two layers downstream as a schema escalation rather than as "wrong fixture".

#### T-058b2b2b — The shadow slice driven by the worker
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058b2b2a
- **Spec:** §19.6 Stage 1 exit, §24 item 5, §7.2
- **Objective:** Replace `run_slice`'s direct composition with the worker, keeping every assertion that made `T-058a` worth having.
- **Scope (in):** `tests/test_shadow_slice.py` enqueuing the first jobs and draining the queue instead of calling module entry points in order; the approval step made explicit where §8.3 step 9 requires it; every existing assertion kept or replaced by a stronger one, with any that is dropped named and justified.
- **Scope (out):** New pipeline behaviour of any kind — if the rewrite needs a code change, that is a finding and its own task.
- **Acceptance criteria:**
  1. The slice runs entirely through `runner.execute`, with no direct call to a pipeline entry point.
  2. It reaches the same terminal state and the same entity counts as the direct composition did.
  3. The network guard still covers the whole run, and the "stopped before the send" assertions still hold.
- **Verification:** `uv run pytest -q tests/test_shadow_slice.py`
- **Files:** `backend/tests/test_shadow_slice.py`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_shadow_slice.py` -> **34 passed** (was 28); full suite **1656 passed** (was 1650); `ruff check app tests` clean; `mypy app` clean on 95 source files. **No production code changed** — scope (out) required that, and `git status` confirms it. No migration.
  1. **Entirely through `runner.execute`** — `test_the_slice_calls_no_pipeline_entry_point` parses `run_slice`'s AST for calls to the six entry points the direct composition used, and `test_the_slice_module_imports_no_pipeline_entry_point` is the stronger form: it cannot call what it never imported. `test_every_pipeline_step_ran_as_a_job` asserts all **eight** job types succeeded, and `test_no_job_died_or_is_still_queued` that none died or stalled. `import_csv` is deliberately excluded from the list — an operator uploading a CSV is a request, not background work (`T-058b1`).
  2. **Same terminal state and counts** — the 28 pre-existing assertions all still run, including `test_each_campaign_reaches_at_least_one_review_pending_revision`, `test_every_intermediate_entity_exists`, `test_the_slice_is_deterministic`, and the audit-chain tests. `SliceResult` now *observes* the database instead of accumulating what the harness itself did, which is the point: the old version could only report its own actions, so an assertion about it was partly an assertion about the test.
  3. **The guard and the no-send assertions hold** — `test_the_whole_slice_runs_under_the_guard`, the three guard controls, `test_nothing_was_queued_for_sending`, and `test_no_revision_was_approved` are unchanged and green.
- **The approval gap is now visible, and asserted** — `test_no_draft_exists_before_the_approval` drains only the automatic half and proves the candidate sits in `review_pending` with no revision, no queued job, and **no drafting job in any state**. `test_the_worker_did_the_work_in_two_waves` names the shape. A slice that ran straight through would have hidden the one place §8.3 requires a person.
- **Three assertions changed, each for a stated reason:** correlation is enqueued per *(row, campaign)* rather than per row, so a both-campaigns row still gives two candidates two chains and §8.1's independent judgements do not share a trail; evidence recency is checked against the wall clock rather than the fixture `NOW`, because a job handler takes no `at=` — it is running for real — and what still matters is that no snapshot is future-dated; and the paused-campaign control now drives the **job** instead of calling `create_memberships`, which is the version that matters since the job is what production runs.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, suite re-verified green):** chaining qualification straight into drafting -> 2 failed, including the approval-gap test; calling a pipeline entry point from the slice again -> 2 failed and 24 errors. Removing the drafting approval precondition does **not** fail this file, correctly — the slice approves, so it never exercises the refusal; that guarantee is `T-058b2b2a`'s and its control fails 6 tests in `tests/test_pipeline_jobs.py`, re-confirmed this cycle.
- **The first control passed when it should not have.** Chaining qualification into drafting left the approval-gap test green, because the injected drafting job failed on a bad recipient and so produced neither a revision nor a queued job. The assertion now counts drafting jobs in **any** state. This is the third time a "count what is left in the queue" assertion has read past a job that was created and then died; the pattern is recorded here so the next one is written the right way round.

#### T-058c — Stage 1 exit evidence record and the G-02 gate change
- **Stage / Priority:** 1 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058a, T-058b, T-148
- **Was blocked because:** `T-058a` and `T-058b` are both `DONE` and the slice passes end to end, but `T-148` found that `app/worker.py` registers no job types — so the pipeline this gate would certify runs in the test harness and **in no started worker**. Opening the Stage 1 exit gate over that would record evidence that is true of the tests and false of the system. Not a `Q-###`: nothing is undecided, one wiring change is missing.
- **Spec:** §19.6 Stage 1 exit gate, §23
- **Objective:** Record the observed Stage 1 exit evidence and open gate **G-02** against it.
- **Scope (in):** `docs/stage1-exit-evidence.md` recording the verification commands, their real output, entity counts, and the zero-external-write proof; the §5 gate row changed to **OPEN** with a link to that record; the parent `T-058` closed.
- **Scope (out):** Any Stage 2 work, which the gate merely unblocks.
- **Acceptance criteria:**
  1. The document records commands and output that were actually observed, not reconstructed.
  2. Gate **G-02** is marked **OPEN** in §5 with a link to the document.
  3. `T-058` is `DONE` with all three children `DONE`.
- **Verification:** full canonical command set from `process.md` §5.
- **Files:** `docs/stage1-exit-evidence.md`, `tasks.md`
- **Blocker / Q:** none
- **Completion evidence:** the canonical set, run 2026-07-31 from `backend/`: `ruff check .` -> All checks passed; `ruff format --check .` -> 168 files already formatted; `mypy app` -> no issues in 95 source files; `pytest -q` -> **1664 passed**; `alembic check` -> No new upgrade operations detected. `pytest -q tests/test_shadow_slice.py` -> **34 passed**.
  1. **Observed, not reconstructed** — every number in the document came from one instrumented slice run whose probe was removed afterwards (`tests/test_shadow_slice.py` re-verified **34 passed** with it gone). `ruff format --check` genuinely failed on the first run of this cycle — `tests/test_jobs.py`, left unformatted by `T-148`'s final edit — and the document records that the printed result is the second run rather than quietly showing only the clean one.
  2. **Gate opened with a link** — §5's **G-02** row is now **OPEN** (2026-07-31, `T-058c`) and links `docs/stage1-exit-evidence.md`, with the headline counts inline so the row is readable without following it. It states explicitly that it opens Stage 2 scope only: every other gate stays locked and **G-08** still governs any live outreach.
  3. **`T-058` closed** — all three children `DONE` (`T-058a` harness, `T-058b` job types, `T-058c` this).
- **Observed Stage 1 outcome:** 15 candidates, **5** reaching `review_pending` and **10** refused — the `T-041` corpus is mostly refusal cases, so a slice that advanced all fifteen would be one whose eligibility gate did nothing. 64 jobs across 8 types, every one `succeeded`, none dead or left queued. Two waves, 54 jobs then 10, with the human approval between them. `Approval=0`, `SendCommand=0`, `SendAttempt=0`, `OutboxEvent=0`.
- **The document says what the evidence does *not* claim**, in its own section: nothing about a real model's behaviour (**G-03** locked; `T-083` owns that), nothing about deliverability or DNS (Stage 5, **G-07**), no stakeholder acceptance (`T-009` open, `R-002` records that the Stage 0 record does not exist and was not fabricated), and no quality measurement (Stage 3). A gate record that overstates is worse than none.
- **No production code changed.** The only source edit this cycle was `ruff format` on `tests/test_jobs.py`.

---

## 4. Stage 2 — Review dashboard (next stage, decomposed; entry gate G-02)

All Stage 2 tasks stay `PLANNED` until **G-02** is open. Stage 2 exit gate is **G-10**: a non-engineer
completes reviews without understanding the agent stack.

#### T-060 — Next.js dashboard scaffold and typed API client
- **Stage / Priority:** 2 / P0 · **Status:** `DONE` (2026-07-31 — `T-060a` and `T-060b` are both `DONE`) · **Depends on:** G-02, T-004
- **Spec:** §18.1, §12.3 · **Objective:** `frontend/` Next.js app with lint/type/test, and an API client generated from the FastAPI OpenAPI document.
- **Acceptance:** app builds; client types are generated, not hand-written; a drift test fails if OpenAPI and client disagree; no data-fetching against anything but the local API.
- **Verification:** `npm run lint`, `npm run typecheck`, `npm run build`, client-drift test. · **Files:** `frontend/*` · **Q:** none
- **Status note (2026-07-31):** **Split into `T-060a` and `T-060b`.** Three things, and the first is a decision rather than code: ADR-018 fixes the Python toolchain and names `frontend/` in the layout, but settles **nothing** about what goes in it — package manager, Next.js version and router, linter, test runner. Choosing those is this repository's first frontend commitment and deserves the same record ADR-018 got. The scaffold that proves the choice is the rest of `T-060a`; the generated client and its drift test are `T-060b`, and they need a running OpenAPI document rather than a working toolchain. Criteria map: "app builds" → `T-060a`; "types are generated, not hand-written", the drift test, and "no data-fetching against anything but the local API" → `T-060b`.

#### T-060a — Frontend toolchain decision and a `frontend/` scaffold that builds
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** G-02, T-004
- **Spec:** §18.1 (Next.js thin internal dashboard), §12.3, ADR-018 (which this extends)
- **Objective:** Decide the frontend toolchain, record it, and prove the choice with an app that lints, typechecks, builds, and tests.
- **Scope (in):** An ADR fixing package manager, Next.js version and router, TypeScript strictness, linter, and test runner, with what was rejected; `frontend/` with a committed lockfile; `npm run lint`, `typecheck`, `build`, and `test` scripts that all pass; one page that renders without fetching anything; a test asserting the app makes no network call at build time.
- **Scope (out):** The generated API client and its drift test (`T-060b`); authentication (`T-061`); any review-queue UI (`T-062` onwards); CI wiring (`T-007`).
- **Acceptance criteria:**
  1. `npm run lint`, `npm run typecheck`, `npm run build`, and `npm run test` all pass from `frontend/`, with observed output.
  2. An ADR records the toolchain choice, the rejected alternatives, and what would justify revisiting it.
  3. The scaffold fetches nothing: no data-fetching code and no network call reachable from the rendered page; test-proven.
- **Verification:** `npm run lint && npm run typecheck && npm run build && npm run test` from `frontend/`.
- **Files:** `frontend/*`, `docs/adr/ADR-021-*.md`
- **Blocker / Q:** none
- **Completion evidence:** all four scripts observed passing from `frontend/` on 2026-07-31 — `npm run lint` (eslint, no output), `npm run typecheck` (`tsc --noEmit`, no output), `npm run test` (**8 passed**), `npm run build` (both routes prerendered `○ (Static)`). Backend re-verified unaffected: `ruff check .` clean, `ruff format --check .` 168 files already formatted, `mypy app` clean on 95 files, `pytest -q` **1664 passed**. No migration.
  1. **All four scripts pass** — output above. Node v24.16.0, npm 11.13.0; installed Next.js 16.2.12, React 19.2.8, TypeScript 6.0.3, ESLint 10.8.0, Vitest 4.1.10.
  2. **The decision is recorded** — `docs/adr/ADR-021-frontend-toolchain-defaults.md`, registered in `docs/adr/README.md`. It states the choices, the rejected alternatives (`create-next-app`, exact-pinning in `package.json`, a placeholder that fetches), the cost in plain terms (248 locked packages to render two paragraphs), and what would justify revisiting each.
  3. **The scaffold fetches nothing** — `frontend/tests/no-network.test.ts` reads the source for `fetch(`, `XMLHttpRequest`, `new WebSocket`, `new EventSource`, `node:http`/`node:https` imports, and any absolute `http(s)://` URL, and asserts the only runtime dependencies are `next`, `react`, `react-dom`. Asserted over source rather than by rendering, because a build-time fetch, a module-scope socket, and a remote `<img src>` would each escape a render-and-watch test differently.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, re-verified green):** adding a `fetch("https://example.com/…")` to `app/page.tsx` -> 2 failed (`contains no fetch`, `contains no absolute URL`); emptying the directory walk so discovery finds nothing -> 1 failed (`finds the files it claims to be checking`), which is the guard on the guard.
- **Three toolchain frictions, each resolved rather than worked around:** `eslint-plugin-react-hooks` v7 exports its flat config at `configs.flat["recommended-latest"]` — the top-level key is still the eslintrc shape and ESLint 10 refuses it; `eslint.config.mjs` sits outside `tsconfig.json`, so type-aware rules report `error`-typed values on every line of it and it is exempted with `disableTypeChecked` scoped to that one file; and Vitest warned that `vitest.config.ts` used ESM syntax while loaded as CommonJS, fixed by declaring `"type": "module"` rather than suppressing the warning.
- **The first `package.json` named five versions that did not exist.** They were guesses written before checking the registry. Replaced by installing and letting npm resolve, with `package-lock.json` committed as the actual pin — recorded in ADR-021 under what was rejected, because the instinct to hand-pin came from ADR-018 and is wrong here.

#### T-060b — Generated typed API client and an OpenAPI drift test
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-060a
- **Spec:** §18.1, §12.3, §23 (typed contracts)
- **Objective:** The dashboard's types come from the backend's OpenAPI document, and disagreement between them fails a test rather than surfacing at runtime.
- **Scope (in):** A generator run against the FastAPI OpenAPI document, its output committed and marked generated; a drift test that regenerates and fails on any difference; a check that the client's base URL is the local API and nothing else.
- **Scope (out):** Endpoints the dashboard will need but the backend does not expose yet — each is its own task; authentication (`T-061`).
- **Acceptance criteria:**
  1. Client types are generated, not hand-written; test-proven that the checked-in output matches a fresh generation.
  2. A drift test fails when the OpenAPI document and the committed client disagree.
  3. No data-fetching targets anything but the local API; test-proven.
- **Verification:** `npm run typecheck && npm run test` from `frontend/`.
- **Files:** `backend/scripts/export_openapi.py`, `backend/tests/test_fixtures.py`, `frontend/openapi.json`, `frontend/lib/*`, `frontend/tests/*`
- **Blocker / Q:** none
- **Design:** the chain is **application -> `openapi.json` -> `lib/api-types.ts`, with a test on each arrow.** Only Python can ask the FastAPI app what it exposes, so `backend/tests/test_fixtures.py` asserts the committed document still matches `create_app().openapi()`; only Node can run the generator, so `frontend/tests/api-types.test.ts` asserts the committed types still match a fresh generation from that document. Either arrow rots silently without its own test: a backend change nobody re-exports leaves a stale document that every frontend check still passes against, and a hand-edited type file compiles perfectly while describing an API that does not exist.
- **Completion evidence:** `npm run lint`, `npm run typecheck`, `npm run build` (both routes prerendered `○ (Static)`), and `npm run test` (**19 passed**) from `frontend/`; backend `ruff check .` clean, `ruff format --check .` 169 files already formatted, `mypy app` clean on 95 files, `pytest -q` **1667 passed**. No migration.
  1. **Generated, not hand-written** — `test_the_generated_client > matches a fresh generation from the committed document` regenerates to **stdout** and compares, because a test that rewrote the file it checks would pass on the second run regardless of the first; plus `says it is generated` and `describes the endpoints the backend exposes` as a guard on the guard against an empty file matching an equally empty regeneration.
  2. **Drift fails a test** — the frontend half above, and the backend half `test_the_committed_openapi_document_matches_the_application`, whose failure message names the command to fix it. `test_the_exported_document_is_byte_stable` keeps the committed file diffable: sorted keys, so key order moving between runs cannot show as a change nobody made.
  3. **Only the local API** — `assertLocal` refuses any non-local host **at module load**, so a misconfigured environment is a startup error rather than a page that half works; `tests/api-types.test.ts` parametrizes it over three remote URLs and a non-URL. `tests/no-network.test.ts` was **narrowed rather than deleted**: fetching is now permitted in `lib/api.ts` and nowhere else, and every absolute URL literal even inside it must be one `assertLocal` would accept.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, re-verified green):** hand-editing the generated types -> 1 failed; the committed document drifting from the application -> 1 failed (backend); a component fetching directly instead of through the client -> 1 failed; pointing the client at `https://api.example.com` -> the module failed to load *and* 1 test failed, which is the fail-closed behaviour `assertLocal` exists for.
- **Two mistakes the checks caught, not inspection.** The export first lived in `app/cli.py`, and `tests/test_module_boundaries.py` failed it — nothing under `app/` may import the application factory, because `main` wires every module together. It moved to `backend/scripts/export_openapi.py`, which is a build tool rather than application code and is not scanned. Separately, the drift test first spawned `npx`, which Node 24 on Windows refuses for a `.cmd` shim; it now runs the generator's entry point through `process.execPath`, rather than reaching for `shell: true` to work around it.
- **ADR-021 amended:** TypeScript 5.9, not 6. `openapi-typescript` requires `typescript@^5.x` in every published version, and the alternatives were `--force` (npm's own message calls the result "potentially broken") or `@hey-api/openapi-ts`, which generates a runtime SDK rather than types. Recorded as a dated amendment rather than a quiet edit, because the original line was a real decision made without knowing what the generator required.

#### T-061 — Authentication: OIDC integration with a local development stub
- **Stage / Priority:** 2 / P0 · **Status:** `PLANNED` (parent; see the split note) · **Depends on:** T-060, T-012
- **Spec:** §12.2 (managed SSO/OIDC; custom passwords rejected), §15.1 · **Objective:** Session handling through a managed identity provider, with a clearly-marked local stub for development.
- **Acceptance:** no password authentication exists; the stub is unusable when `APP_ENV != local` (test-proven); sessions are short and revocable; service identities are separate from human identities.
- **Verification:** authz test suite; a test asserting the stub is refused outside local. · **Files:** `backend/app/identity/auth*`, `frontend/*`
- **Q:** **`Q-026`** (identity provider and roster) blocks the real provider; the local stub is implementable now but only after G-02.
- **Status note (2026-07-31):** **Split into `T-061a` and `T-061b`.** `Q-026` asks *which business identity provider and user roster* back OIDC — a provider commitment nobody has made. It does not block the **session mechanism**: what a session is, how long it lasts, how it is revoked, how the actor on it reaches an audit event, and how a developer gets one locally are all decidable now, and `T-062`'s RBAC needs a resolved actor before any provider exists. So the session layer and the local stub are `T-061a`; the managed-provider integration is `T-061b` and stays `BLOCKED` on `Q-026`. Criteria map: "no password authentication exists", "the stub is unusable when `APP_ENV != local`", "sessions are short and revocable", and "service identities separate" → `T-061a`; the real OIDC flow → `T-061b`.

#### T-061a — Session layer and the local development identity stub
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-060, T-012
- **Spec:** §12.2, §15.1, §14.1, ADR-006
- **Objective:** A session a request can be authenticated by and an actor resolved from, with a local-only stub that issues one — and no password anywhere.
- **Scope (in):** A `Session` table with an expiry and an explicit revocation, keyed by a hashed token rather than the token itself; resolving a request to a `User` and their roles; a stub sign-in usable **only** when `APP_ENV == local`, refused everywhere else and test-proven; the actor an audit event records coming from the session rather than from a request field.
- **Scope (out):** The managed OIDC flow, provider metadata, and any roster (`T-061b`, `Q-026`); the RBAC matrix and per-endpoint enforcement (`T-062`); the frontend sign-in screen (`T-063`); CSRF, which belongs with the first cookie-bearing mutating endpoint.
- **Acceptance criteria:**
  1. No password authentication exists anywhere: no password column, no hash, no verify function; test-proven against the migrated schema and the source.
  2. The stub refuses to issue a session when `APP_ENV != local`; test-proven for every other environment.
  3. Sessions expire and can be revoked, and an expired or revoked session resolves to nobody; test-proven for each.
  4. A session resolves to a human `User` and never to a `ServiceIdentity`.
- **Verification:** `uv run pytest -q tests/test_sessions.py`; `uv run alembic check`
- **Files:** `backend/app/identity/sessions.py`, `backend/app/identity/stub.py`, `backend/alembic/versions/55202db10b03_user_session.py`, `backend/tests/test_sessions.py`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_sessions.py` -> **34 passed**; full suite **1728 passed** (was 1694); `ruff check .` clean; `ruff format --check .` 176 files formatted; `mypy app` clean on 98 source files; `alembic check` -> No new upgrade operations detected; migration `55202db10b03` reverses and re-applies cleanly.
  1. **No password authentication anywhere** — `test_no_session_or_identity_table_stores_a_secret` queries `information_schema` rather than the models, because what must stay clean is the *database* and a later migration could add a column no model names; `test_the_identity_module_contains_no_password_verification` covers the other half, since a `verify_password` helper with the hash kept elsewhere would pass a schema check and be exactly what §12.2 rejects. `token_hash` is excluded from the first by name and only by name — a hash *of a session token* is not a credential the user knows, and a test that could not tell them apart would be useless.
  2. **The stub is refused outside `local`** — `test_the_stub_is_refused_outside_local` and `test_a_refused_stub_issues_no_session` parametrized over `test`, `staging`, and `production`; `test_the_allow_list_names_only_local` pins the allow-list shape (a new `preview` environment is refused until someone decides otherwise, rather than permitted by a `!= production` test); `test_the_refusal_names_what_would_be_needed` asserts the message names `Q-026`. **`AppEnv.TEST` is deliberately not permitted**, and every test that exercises the stub passes `Settings(app_env=AppEnv.LOCAL)` explicitly — a suite that relied on its own environment being allowed would be establishing that the stub works somewhere it must not.
  3. **Sessions expire and can be revoked** — `test_an_expired_session_resolves_to_nobody`, `test_a_revoked_session_resolves_to_nobody`, `test_an_unknown_token_resolves_to_nobody`, `test_a_deactivated_user_stops_resolving`, `test_revoking_twice_keeps_the_first_decision`, `test_every_session_a_user_holds_can_be_ended_at_once`, plus the two database checks (`expires_at > issued_at`, revocation must name who). `resolve` returns `None` for every failure so a caller cannot distinguish them — telling them apart is how an attacker learns which tokens once existed.
  4. **A session belongs to a human** — `test_a_service_identity_cannot_hold_a_session`, refused by the foreign key to `app_user` rather than by a check someone could forget to call, and `test_the_actor_is_derived_from_the_session_not_supplied`, since an `Actor` a caller could pass in is attribution they chose for themselves (§12.2).
- **Design:** the **token is never stored** — the row keys on `sha256(token)`, so a database dump, a backup, or a careless log contains nothing replayable. Expiry and revocation are **separate columns and separately checked**: an expiry is a fact about time, a revocation is a decision someone made, and collapsing them would leave an administrator unable to tell a session they ended from one that aged out.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, re-verified green):** the stub no longer checking the environment -> 7 failed; `AppEnv.TEST` added to the allow-list -> 3 failed; `is_live` always true -> 3 failed; `resolve` no longer checking the user is active -> 1 failed; the `user_id` foreign key removed **from the migration** -> 2 failed.
- **A safety invariant caught me.** `tests/test_sessions.py` first declared its own `NOW`, and `test_no_test_module_declares_its_own_clock` failed — that rule exists because `T-142` had one stale hard-coded date redden 89 tests. It now imports `tests.factories.NOW`. Separately, the last control's first attempt did not match the reformatted migration and its `assert` refused rather than writing nothing and reading as a pass; it was re-applied by locating the constraint's span.

#### T-061b — Managed OIDC provider integration
- **Stage / Priority:** 2 / P0
- **Status:** `BLOCKED`
- **Depends on:** T-061a
- **Spec:** §12.2, §15.1
- **Objective:** Sessions issued from a real business identity provider rather than the local stub.
- **Scope (in):** The OIDC authorization-code flow against the provider `Q-026` names; mapping the provider subject to `User.subject`; provider-side multi-factor and revocation honoured; the stub disabled by the same switch that enables this.
- **Scope (out):** Everything `T-061a` owns.
- **Acceptance criteria:**
  1. A session can be issued only through the provider outside `local`.
  2. The provider's subject maps to exactly one `User`; an unknown subject is refused rather than auto-provisioned.
  3. Provider-side revocation ends the application session.
- **Verification:** authz test suite against a provider test tenant.
- **Blocker / Q:** **`Q-026`** — no business identity provider or user roster has been named. Choosing one would be committing Matrix Power to a vendor, which `AGENTS.md` rule 10 forbids inventing.

#### T-062 — Server-side RBAC enforcement on every action
- **Stage / Priority:** 2 / P0 · **Status:** `DONE` (2026-07-31) · **Depends on:** T-061a (dependency narrowed 2026-07-31: `T-061` is a split parent, and this needs the session layer `T-061a` provides, not the managed provider `T-061b` is blocked on)
- **Spec:** §12.1, §12.2, §15.1, §7.4 (autonomy tiers) · **Objective:** A role matrix enforced server-side per endpoint, mapped to the §7.4 tiers.
- **Acceptance:** every mutating endpoint has an authorization test for allowed and denied roles; a route with no declared permission fails a test; approval endpoints require the reviewer/approver role and are never reachable by a service identity.
- **Verification:** `uv run pytest -q tests/test_authz.py` · **Files:** `backend/app/identity/rbac.py`, `backend/tests/test_authz.py` · **Q:** `Q-005` for real approver assignment.
- **Scope note (2026-07-31):** the application serves **two routes today**, both operational `GET`s, so "every mutating endpoint has an authorization test" is satisfied vacuously and would stay that way however little was built. The substantive criterion is the second one — *a route with no declared permission fails a test* — so that is what this task delivers: the matrix, the tier mapping, and a coverage check `T-063`'s first real endpoint cannot ship past. Recorded rather than quietly reinterpreted, because a criterion met by absence is not the same as one met by construction.
- **Completion evidence:** `uv run pytest -q tests/test_authz.py` -> **40 passed**; full suite **1768 passed** (was 1728); `ruff check .` clean; `ruff format --check .` 178 files; `mypy app` clean on 99 source files; `alembic check` clean. No migration, and **no production route changed**.
  1. **An undeclared route fails a test** — `test_every_route_declares_a_permission` walks the real application and fails on anything missing from `ROUTE_PERMISSIONS`; `permission_for` raises `UndeclaredRoute` rather than defaulting, because a default — public *or* administrator-only — would be a decision nobody made and the public one would be silent. `test_the_coverage_check_can_detect_a_violation` is the guard on the guard: a coverage check that cannot fail reports success forever. `test_the_declared_routes_are_all_routes_the_app_serves` catches the other direction, since stale entries are how a reviewer comes to distrust the table.
  2. **Approvals need the reviewer role and are unreachable by a service** — `test_only_the_operator_reviewer_may_approve` parametrized over **every** role against **every** approval, rather than one allowed and one denied; a matrix tested at two points has holes in the middle. `test_an_approval_is_granted_only_by_human_only_roles` checks the grant table against `T-012`'s `HUMAN_ONLY_ROLES`, which is the third independent guard on §3.5's invariant — the other two being `T-012`'s composite foreign key and `T-061a`'s session foreign key to `app_user`.
  3. **The maps are total** — `test_every_permission_has_a_tier` and `test_every_permission_has_a_grant`, so a permission added without either fails rather than defaulting to whatever a reader assumed; the safe assumption and the dangerous one look identical in a diff. `test_every_role_grants_something` keeps §12.1's six roles meaningful, and `test_no_permission_is_granted_to_nobody` catches the reverse.
- **Design:** `PUBLIC` is a **type**, not `None`, so "nobody decided" and "somebody decided this is open" cannot be the same value — the coverage check treats the first as a failure and the second as an answer. `authorize` returns `None` and raises, rather than returning a boolean: a caller who forgets to check a returned `False` has authorized everything, and an exception cannot be ignored by accident. The health probes are `PUBLIC` deliberately — a probe needing a session would report the application unhealthy exactly when the identity provider was down, the moment an operator most needs the truth. The system administrator is deliberately **denied** message approval: administering identity is not the authority to approve an outbound message, which is why §7.4 puts them on different tiers.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, re-verified green):** adding a route to `main.py` without declaring a permission -> 1 failed (the load-bearing one); granting the system administrator message approval -> 1 failed; granting an approval to `VIEWER`, a machine-assignable role -> 3 failed; `authorize` no longer refusing an anonymous caller -> 1 failed; a permission losing its tier -> 1 failed.
- **Not decided here:** *who* holds which role. That is `Q-005` (approver assignment) and `Q-026` (the roster), both open. This maps roles to permissions, which §12.1 already decided; inventing the roster would be fabricating an authority.

#### T-063 — Review queue API
- **Stage / Priority:** 2 / P0 · **Status:** `DONE` (2026-07-31 — `T-063a` and `T-063b` are both `DONE`) · **Depends on:** T-062 · **Spec:** §12.3, §17.5
- **Objective:** Paginated, filterable review queue endpoints for candidates and revisions with backlog age.
- **Acceptance:** filters by campaign, state, opportunity type, and age; deterministic ordering; every response carries the record version used for optimistic concurrency.
- **Verification:** `uv run pytest -q tests/test_review_api.py` · **Files:** `backend/app/drafts_and_approvals/api*` · **Q:** none
- **Status note (2026-07-31):** **Split into `T-063a` and `T-063b`.** Two resources, and the first one carries work the second does not: these are the repository's **first authenticated endpoints**, so whichever comes first has to build the FastAPI dependency that turns a request into a `Principal` — the piece `T-062` deliberately left until there was something to depend on it. It also has to re-export `frontend/openapi.json` and regenerate the client types, because `T-060b`'s drift tests fail the moment the route table changes. Bundling the revision queue behind all of that would put two resources in one change set where the interesting part is the plumbing. Criteria map: filters, ordering, pagination, and the record version → both, each for the resource it owns; the auth dependency and the OpenAPI regeneration → `T-063a`; backlog age → `T-063b`, which is where a revision's waiting time becomes meaningful.

#### T-063a — Authenticated requests and the candidate review queue
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-062
- **Spec:** §12.3 (the review card's first four items), §17.5, §15.1
- **Objective:** Turn a request into a `Principal`, enforce `T-062`'s matrix on it, and serve the candidate review queue.
- **Scope (in):** A FastAPI dependency resolving the session token to a `Principal` and applying `authorize`; `GET /api/review/candidates` filtered by campaign and state, deterministically ordered, paginated; each row carrying its record version (`updated_at`, the convention `T-035c`'s §11.4 recheck already uses); the route declared in `ROUTE_PERMISSIONS`; `frontend/openapi.json` re-exported and the client types regenerated so `T-060b`'s drift tests stay honest.
- **Scope (out):** The revision queue and backlog age (`T-063b`); any mutation — approving, correcting, or editing is `T-065` onwards; the UI (`T-064`).
- **Acceptance criteria:**
  1. The endpoint refuses an absent, expired, or revoked session, and refuses a session whose roles do not grant `VIEW_REVIEW_QUEUE`; test-proven for each.
  2. Filters by campaign and state; ordering is deterministic under ties; pagination does not skip or repeat a row.
  3. Every row carries the record version a later optimistic-concurrency check would compare.
  4. The route is declared, and `frontend/openapi.json` plus the generated client match the application again.
- **Verification:** `uv run pytest -q tests/test_review_api.py tests/test_authz.py`; `npm run test` from `frontend/`
- **Files:** `backend/app/identity/dependencies.py`, `backend/app/drafts_and_approvals/api.py`, `backend/app/main.py`, `backend/tests/test_review_api.py`, `frontend/openapi.json`, `frontend/lib/api-types.ts`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_review_api.py` -> **23 passed**; `tests/test_authz.py` **40 passed**; full backend suite **1791 passed** (was 1768); `ruff check .` clean; `ruff format --check .` 181 files; `mypy app` clean on 101 source files; `alembic check` clean (no migration). Frontend: `npm run lint`, `typecheck`, `build` clean, `npm run test` **19 passed**.
  1. **Refuses everyone it should** — `test_an_unauthenticated_request_is_refused` (401 with `WWW-Authenticate`), `test_an_unknown_token_is_refused`, `test_an_expired_session_is_refused`, `test_a_revoked_session_is_refused`, and `test_a_session_without_the_role_is_forbidden_not_unauthorized` — **403, not 401**, because signing in again would not help and a login loop that can never succeed is worse than a clear refusal. `test_a_role_that_grants_the_queue_may_read_it` covers the three roles that do hold it, and `test_a_token_in_the_query_string_does_not_authenticate` pins that a token in a URL — where access logs, browser history, and any leaked `Referer` would carry it — authenticates nobody.
  2. **Filters, ordering, pagination** — `test_filtering_by_campaign`, `test_filtering_by_state`, `test_an_unknown_state_is_rejected_rather_than_ignored` (a typo silently returning the default queue would be a filter that lied), `test_pagination_covers_every_row_exactly_once`, `test_ordering_is_stable_across_identical_requests`, `test_the_page_size_is_capped`, `test_a_negative_offset_is_rejected`, `test_the_page_reports_its_own_window`.
  3. **Record version on every row** — `test_every_row_carries_a_record_version` and `test_the_record_version_is_the_rows_updated_at`, which pins it to the *same* `updated_at` stamp `T-035c`'s §11.4 recheck already compares rather than a second concurrency mechanism to keep in step. `test_the_row_does_not_carry_a_decision` keeps the list a list: §12.3's card is `T-064`, and a list returning everything a decision needs invites deciding from the list.
  4. **Declared and regenerated** — the route is in `ROUTE_PERMISSIONS`, `tests/test_authz.py` passes, `frontend/openapi.json` was re-exported and `lib/api-types.ts` regenerated, so `T-060b`'s drift tests are green on both arrows.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, re-verified green):** the endpoint dropping its authorization dependency -> 6 failed; the ordering losing its `id` tiebreak -> 1 failed; the dependency also reading a query-string token -> 1 failed; a missing role answering 401 instead of 403 -> 1 failed; the route declaration removed -> 1 failed.
- **Two controls passed when they should not have, and both were my fault rather than the code's.** Removing the ordering tiebreak left *every* pagination test green — the set is small and Postgres returned a stable order anyway. Behaviour cannot prove that mechanism, so `QUEUE_ORDER` is now a named constant and `test_the_ordering_is_a_total_order` compiles it and asserts both keys, which is what `process.md` §5 prescribes for exactly this shape. The query-token control was simply written wrong (it injected an invalid token, so the refusal came from the wrong place); rewritten to actually read a query parameter, it fails.
- **An intermittent full-suite failure, diagnosed and fixed.** One run failed **18 dispatch tests**; `tests/test_dispatch.py` passed alone and alongside `tests/test_review_api.py`, and the next two full runs were clean. The cause is the app's lifespan calling `dispose_engines()` on shutdown — which is *process-wide* — so every `TestClient` context exit disposes pooled engines other fixtures may hold. `tests/test_health.py` already calls `dispose_engines()` after its own client for exactly this reason and mine did not; it now does, and three consecutive full-suite runs are clean (**1791 passed** each). Stated with its limit: the failing output was not captured before the fix, so this is a diagnosis consistent with the evidence rather than a demonstrated cause, and a recurrence would deserve its own task.
- **Found while wiring:** `T-062`'s route walk missed the first router this repository mounted. FastAPI presents an included router as a `_IncludedRouter` whose `path` and `methods` are absent and whose real routes hang off `original_router`, so the flat walk found nothing — and "found nothing" reads exactly like "nothing undeclared", which is how a coverage check comes to certify an endpoint it never saw. The walk is now recursive and handles both spellings.

#### T-063b — Revision review queue and backlog age
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-063a
- **Spec:** §12.3, §17.5
- **Objective:** The same queue for message revisions awaiting review, with how long each has been waiting.
- **Scope (in):** `GET /api/review/revisions` filtered by campaign, state, and opportunity type; backlog age per row and a filter on it; the same ordering, pagination, and record-version guarantees `T-063a` establishes.
- **Scope (out):** Any mutation; the UI.
- **Acceptance criteria:**
  1. Filters by campaign, state, opportunity type, and age.
  2. Backlog age is computed from the row rather than stored, and is stable for a fixed clock.
  3. The same authorization, ordering, pagination, and record-version tests pass for this resource.
- **Verification:** `uv run pytest -q tests/test_review_api.py`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_review_api.py` -> **42 passed** (was 23); full backend suite **1810 passed** (was 1791); `ruff check .` clean; `ruff format --check .` 181 files; `mypy app` clean on 101 source files; `alembic check` clean (no migration). Frontend: lint, typecheck, build clean, `npm run test` **19 passed** after re-exporting `openapi.json` and regenerating the client.
  1. **Filters by campaign, state, opportunity type, and age** — `test_filtering_revisions_by_campaign`, `test_filtering_revisions_by_state`, `test_filtering_revisions_by_opportunity_type`, `test_filtering_by_minimum_age`, plus `test_an_unknown_revision_state_is_rejected` and `test_a_negative_minimum_age_is_rejected` — a typo silently returning the default queue would be a filter that lied.
  2. **Backlog age is computed and stable** — `test_backlog_age_is_computed_not_stored` asserts there is no such column *and* that the field exists on the response, `test_backlog_age_is_stable_for_a_fixed_clock` pins criterion 2 exactly, and `test_a_future_stamp_reports_zero_rather_than_a_negative_age` covers clock skew between the database and the API: "-3 hours waiting" would be worse than no number, because a reviewer would believe it.
  3. **The same guarantees as the candidate queue** — authorization (`test_the_revision_queue_refuses_an_unauthenticated_request`, `..._refuses_a_session_without_the_role`), a compiled-SQL assertion on the total order (`test_the_revision_ordering_is_a_total_order`), `test_revision_pagination_covers_every_row_exactly_once`, `test_every_revision_row_carries_a_record_version`, and `test_the_revision_page_size_is_capped`.
- **Design:** the age **filter is expressed as a cutoff on the stamp**, not as arithmetic per row, so the database can use the index and — more importantly — the filter means the same thing as the number the row reports. A reviewer chasing everything older than a day must not be shown rows that say they are younger; `test_filtering_by_minimum_age` asserts both halves. The qualification join is **outer**: a revision whose candidate has no qualification run is reported with `opportunity_type: null` rather than dropped, because hiding work from a reviewer is worse than showing it with a missing field. And the row carries the subject but not the body, claims, or evidence — a queue is for choosing what to open, and a list showing the whole message would invite approving from the list (`T-064` owns the card).
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, re-verified green):** backlog age no longer flooring at zero -> 1 failed; the revision ordering losing its `id` tiebreak -> 1 failed (caught by the compiled-SQL assertion, which is the shape `T-063a` learned to use after a behavioural test passed the same control); the age filter reversed so it disagrees with the reported age -> 1 failed; the qualification join made inner, hiding unqualified work -> 2 failed; the route declaration removed -> 1 failed.

#### T-149 — Candidate review detail endpoint
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-063
- **Spec:** §12.3 items 1–5, §10.5, §14.3, §17.5
- **Found by:** `T-064`. The review card must show evidence with source quality and retrieval time, product readiness, approved claims, suppression warnings, and the exact revision — and **no endpoint returns any of it**. `T-063` deliberately kept the queue a list ("a list that returned everything a decision needs would invite deciding from the list"), which was right, and left the card's data source unbuilt. `T-064` is a UI task with nothing to render.
- **Objective:** One endpoint returning everything §12.3's card needs to *show*, and nothing it needs to *do*.
- **Scope (in):** `GET /api/review/candidates/{candidate_id}` under `VIEW_REVIEW_QUEUE`; account, contact, campaign, and opportunity type; the candidate's current evidence with source quality and retrieval time, ordered strongest first; the campaign product's effective readiness and its currently valid approved claims; suppression warnings for the contact and account; the current message revision if one exists, with what would happen next; `404` for an unknown candidate; the route declared and the OpenAPI client regenerated.
- **Scope (out):** Every mutation — approve, reject, defer, edit, request-more-research are `T-065` onwards, and this returns no action; the UI (`T-064`); CRM relationship, which needs an adapter `Q-001` and gate **G-05** govern — reported as unknown, never guessed.
- **Acceptance criteria:**
  1. The response carries §12.3 items 1–5 for a candidate that has them, each test-proven.
  2. Evidence rows carry source quality and retrieval time, ordered deterministically.
  3. A suppressed contact is flagged, and an unsuppressed one is not; test-proven both ways.
  4. CRM relationship is reported as unknown rather than absent or invented, and a test says why.
  5. Unknown candidate is `404`; the same authorization tests as the queue pass.
- **Verification:** `uv run pytest -q tests/test_review_api.py tests/test_authz.py`
- **Files:** `backend/app/drafts_and_approvals/api.py`, `backend/tests/test_review_api.py`, `frontend/openapi.json`, `frontend/lib/api-types.ts`
- **Blocker / Q:** none
- **Completion evidence:** `uv run pytest -q tests/test_review_api.py` -> **62 passed** (was 42); full backend suite **1830 passed** (was 1810); `ruff check .` clean; `ruff format --check .` 181 files; `mypy app` clean on 101 source files; `alembic check` clean (no migration). Frontend lint, typecheck, build clean and `npm run test` **19 passed** after regenerating the client.
  1. **§12.3 items 1-5** — item 1 `test_the_card_identifies_the_account_contact_campaign_and_opportunity` (and `test_an_unqualified_candidate_reports_no_opportunity_type`); item 3 `test_the_card_shows_product_readiness_and_approved_claims` plus `test_a_product_with_no_readiness_reports_none_rather_than_a_guess` — GP-12 makes absent readiness `null`, never a default, because a card implying availability would be the worst possible one; item 5 `test_the_card_shows_the_exact_revision`, which carries the **body** unlike the queue row, because ADR-008 exists to stop anyone approving without seeing exactly what would be sent, and `test_a_candidate_with_no_revision_reports_none`.
  2. **Evidence carries provenance and is ordered** — `test_evidence_rows_carry_source_quality_and_retrieval_time`, `test_the_strongest_evidence_comes_first` (§12.3 says "strongest evidence"; a card led by whatever the database returned first would make a reviewer hunt for the reason to act), `test_evidence_of_equal_quality_is_newest_first`, and `test_a_candidate_with_no_evidence_reports_an_empty_list` — GP-02: missing facts remain missing.
  3. **Suppression both ways** — `test_a_suppressed_contact_is_flagged` and `test_an_unsuppressed_candidate_is_not_flagged`. Contact and account scopes are reported separately because they mean different things.
  4. **CRM relationship is unknown, not invented** — `test_the_crm_relationship_is_reported_as_unknown`, whose docstring records why: there is no CRM adapter, ADR-004 makes HubSpot conditional on `Q-001`, and gate **G-05** is locked. `null` means *nobody asked a CRM*; reporting "no relationship" would be an answer this system cannot give and a reviewer might act on.
  5. **Missing and malformed are different answers** — `test_an_unknown_candidate_is_404` and `test_a_malformed_candidate_id_is_422`, plus the same authorization pair the queue has.
- **Also asserted:** `test_the_card_says_nothing_will_be_sent` — shadow mode sends nothing (§19.6, gate **G-07**), and a card that did not say so would let a reviewer believe they had just sent an email; `test_the_card_offers_no_actions`, because §12.3 items 6 and 7 are things a reviewer *does* and a read endpoint shipping an action list would describe authority it does not enforce (`T-065` onwards owns the mutations); `test_the_card_carries_a_record_version`, the same optimistic-concurrency stamp the queue returns.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, re-verified green):** evidence no longer ordered strongest-first -> 2 failed; an unknown candidate returning an empty card instead of 404 -> 1 failed; suppression no longer checked -> 1 failed; the shadow-mode sentence losing its warning -> 1 failed; the route declaration removed -> 1 failed.

#### T-150 — The OpenAPI drift test is intermittently flaky
- **Stage / Priority:** 2 / P1
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-060b
- **Spec:** §23 (typed contracts)
- **Found by:** `T-064`. `frontend/tests/api-types.test.ts::the generated client > matches a fresh generation from the committed document` failed **once in three consecutive full `npm run test` runs**, then passed six times in a row, and passes five out of five when run alone. Nothing in that cycle touched `openapi.json` or the generated types when it failed — the edit under test was a React component. **Seen again (`T-065b`, 2026-07-31):** one failure in the first four full runs of that cycle, then four consecutive clean runs, and it passed alone immediately after failing in a full run. Attempts to capture the assertion diff failed because it stopped reproducing — the same wall `T-064` hit. Suite size at the time: 62 tests across 4 files. **Unattributed observation (`T-151b`, 2026-07-31):** one full-suite run reported `1 failed | 81 passed` and the failing test's name was not captured before the run scrolled; eight consecutive full runs immediately afterwards were clean and every file passed in isolation. Recorded here because this is the only known intermittent test, **not** because it was identified as this one — do not treat it as a reproduction. **Third unattributed sighting (`T-153`, 2026-07-31):** a full frontend run reported `1 failed | 120 passed` with the frontend untouched that cycle — nothing in the diff was TypeScript — and two immediately following runs were clean. The failing test's name was again not captured. Three cycles have now seen a single unexplained frontend failure that does not reproduce; that pattern is itself evidence, and reproducing it under a repeat runner is this task's first acceptance criterion.
- **Why it matters more than a rare red run:** this is the test that keeps the dashboard's types honest against the backend (`T-060b`). A check that cries wolf occasionally is a check people learn to re-run rather than read, and the one time it is right will look like the times it was not.
- **Hypothesis, now DISPROVEN (2026-07-31, `T-153`→`T-150`):** the guess was that the generator's stdout was truncated or interleaved under parallel workers, producing a bad *comparison*. It was not. Captured at last, the failure is `Error: Test timed out in 5000ms` — the assertion never ran, so nothing about drift was ever wrong. Recorded here rather than deleted: the wrong hypothesis is why four cycles looked at the diff instead of the clock.
- **Objective:** Either make the comparison deterministic under parallel execution, or establish that the flake is something else.
- **Scope (in):** Reproducing it (a repeat runner, or forcing single-file concurrency); reading the actual diff when it fails; the fix — likely generating to a temporary file rather than capturing stdout, or isolating the test file.
- **Scope (out):** Changing what the drift test *checks*; weakening it, or marking it `skip`, which would remove the guarantee rather than the flake.
- **Acceptance criteria:**
  1. The failure is reproduced and its actual diff recorded, or the search is recorded as exhausted with what was ruled out.
  2. Twenty consecutive full `npm run test` runs pass.
  3. The test still fails when the committed types are hand-edited — the `T-060b` control still bites.
- **Verification:** `npm run test` twenty times from `frontend/`
- **Files:** `frontend/tests/api-types.test.ts`, `frontend/vitest.config.ts`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** All three criteria, with the diagnosis correcting four cycles of guesswork.
  1. *Reproduced, and the actual failure recorded* — a repeat runner writing each run to its own file caught it **twice in twelve consecutive full runs**. The failure is `Error: Test timed out in 5000ms`, not a mismatch: **the comparison never ran**. Every earlier attempt to "capture the diff" was chasing something that never existed, which is why it kept looking unreproducible — the diff was not there to find. The `Hypothesis` line above is kept and marked disproven rather than deleted.
  2. *Twenty consecutive full runs pass* — two batches of ten, `121 passed` each, every run captured to a file and checked by pattern rather than by eye. The longest run took 30.57 s, against 30.56 s for the run that failed before the fix: the same load, absorbed.
  3. *The `T-060b` control still bites* — two controls against hand-edited committed types: renaming a path (`/healthz` → `/healthz-tampered`) failed 2 tests, and renaming a schema field (`contact_points` → `contact_pointz`) failed 1. Restored green after each.
  **The fix, and why it is not a weakening.** The generator spawns a Node process that parses `openapi.json` and emits ~42 KB of TypeScript; measured at **2.0–2.4 s idle**, comfortably inside Vitest's 5 s default — which is why this looked fine for four cycles. Under a full run it competes with six other files holding `jsdom` environments and crosses the line. The test now carries an explicit 30 s timeout, ten times the measured cost, with the measurement in the file. What is compared and what would fail are unchanged; the scope's "do not change what it checks, do not weaken it, do not skip it" is intact. Nothing else was touched — the diff is one file.
  **Observed:** twelve pre-fix runs (2 failed, both the same timeout), twenty post-fix runs (0 failed), `npx vitest run tests/api-types.test.ts` → 10 passed, `npm run lint`, `npm run typecheck`, and `npm run build` clean. Backend untouched and re-confirmed: `pytest -q` → 1971 passed.

#### T-064 — Candidate review card UI
- **Stage / Priority:** 2 / P0 · **Status:** `DONE` (2026-07-31) · **Depends on:** T-063, T-149 · **Spec:** §12.3 items 1–7
- **Was blocked because:** the card must render evidence, source quality, retrieval time, product readiness, approved claims, and suppression warnings, and no endpoint returns any of them — `T-063` kept the queue a list on purpose. Filed as `T-149`. Not a `Q-###`: nothing is undecided, one endpoint is missing.
- **Objective:** Render all seven required review-card elements including evidence with source quality and retrieval time, product readiness, approved claims, suppression/CRM warnings, the exact revision, and what happens next.
- **Acceptance:** a component test asserts all seven elements are present; evidence rows show retrieval time and source quality; the card states explicitly that no send will occur in shadow mode.
- **Verification:** frontend component tests; manual walkthrough recorded in the loop report. · **Files:** `frontend/app/review/*` · **Q:** none
- **Completion evidence:** `npm run test` from `frontend/` -> **40 passed** (was 19); `npm run lint`, `npm run typecheck` clean; `npm run build` renders `/review/[candidateId]` as a dynamic route. Backend untouched: `uv run pytest -q` **1830 passed**. **No new npm dependency.**
  1. **All seven §12.3 elements** — `test_the_review_card_shows_...` is a table of the seven, each parametrized with the strings that must appear, plus `checks every one of the seven`, a guard on the guard: dropping a row would quietly stop checking an element while the suite stayed green.
  2. **Evidence shows retrieval time and source quality** — asserted in the item-2 row and again in `shows retrieval time as a date a reviewer can judge staleness by`, which requires an absolute date rather than a relative phrase: "last week" and "last month" round toward each other, and whether evidence is stale is exactly the judgement item 2 asks for. The machine-readable `<time datetime>` is matched case-insensitively — React 19 emits `dateTime` verbatim where older versions lowercased it, and pinning the casing would break on an upgrade with nothing actually wrong.
  3. **The card states no send will occur** — `states that no send will occur` requires "Nothing is sent", "shadow mode", and "G-07". It is the one sentence whose absence would let a reviewer believe they had just sent an email.
- **Design:** rendered with `react-dom/server`'s `renderToStaticMarkup`, **not** a DOM testing library. The card is static — no state, no effects — so that exercises everything there is, and `jsdom` plus `@testing-library/react` would be dependencies bought against a need nobody has; ADR-021 says nothing is added before a screen needs it, and `T-065` giving the actions behaviour is when a DOM renderer earns its place. Assertions are about **the reviewer's information**, never markup: a test on class names would pass while the card told a reviewer nothing.
- **Items 6 and 7 are shown and disabled, deliberately.** §12.3 requires the card to *offer* approve, edit, reject, defer, and request-more-research, and to carry a structured correction reason; `T-065` onwards builds what they do. Each button carries the reason in its `title` (`Not yet wired (T-066)`), because a button that looked live and did nothing would be worse than one that says why it is not — `offers the actions but leaves every one disabled` counts them and asserts every one is disabled.
- **Nothing is invented to fill a gap** — `what the card refuses to invent`: absent readiness renders "Not stated" rather than a guess (GP-12: technical relevance is not availability); absent evidence renders "None recorded" (GP-02); the CRM line reads "not checked" and names `Q-001`, and the test asserts the card never says "No CRM relationship" — an answer nobody asked a system that could give it.
- **Negative controls (applied, `grep`-confirmed, observed failing, restored, re-verified green):** dropping the shadow-mode sentence -> 2 failed; the suppression warning disappearing -> 2 failed; an action button becoming live -> 1 failed; absent readiness rendering as `sellable_now` -> 1 failed (plus an unrelated flake, below); evidence losing its source quality and retrieval time -> 1 failed.
- **Filed, not dismissed: `T-150`.** `tests/api-types.test.ts::matches a fresh generation` failed **once in three** consecutive full runs during the control sweep, then passed six in a row and five of five alone. Nothing in this task touches the OpenAPI document or the generated types. I could not reproduce it on demand and did not capture the diff, so the cause is a hypothesis (the test spawns the generator and compares stdout while vitest runs files in parallel) rather than a finding — recorded as its own task with that stated plainly, because a drift test that cries wolf is one people learn to re-run rather than read.
- **Manual walkthrough:** not performed. The task's verification line asks for one, and running `next dev` against a live backend would need a database, a seeded candidate, and a session — none of which this cycle established as a repeatable procedure. The component tests cover every acceptance criterion; the walkthrough would add confidence about layout, which no criterion names. Stated rather than quietly skipped.

#### T-065 — Editing creates a new immutable revision
- **Stage / Priority:** 2 / P0 · **Status:** `DONE` (2026-07-31 — `T-065a` and `T-065b` are both `DONE`) · **Depends on:** T-064, T-020 · **Spec:** §10.5, §12.3, §8.4
- **Objective:** Dashboard edits create revision N+1, supersede N, invalidate any prior approval, and re-run T-055 validation.
- **Acceptance:** editing an approved revision invalidates the approval; the prior revision remains byte-identical; validation re-runs and can block; three tests.
- **Verification:** `uv run pytest -q tests/test_review_edit.py` · **Files:** `backend/app/drafts_and_approvals/*`, `frontend/app/review/*` · **Q:** none
- **Status note (2026-07-31):** **Split into `T-065a` and `T-065b`.** The acceptance criteria are all backend facts — an approval invalidated, a prior revision byte-identical, validation re-run and able to block — and `tests/test_review_edit.py` is where they are proven. The dashboard half is a form and a submit, and it needs the endpoint to exist first. Splitting also isolates a safety question the parent hides: this is the repository's **first mutating endpoint**, and `T-061a` deferred CSRF to exactly this moment while `T-070` owns it. `T-065a` resolves that by refusing cookie authentication on mutations — a CSRF attack needs the browser to attach credentials by itself, which a bearer token never does — so the exposure does not exist until `T-070` lands rather than being accepted on trust. Criteria map: all three → `T-065a`; the editing UI → `T-065b`.

#### T-065a — Editing creates a new immutable revision (backend)
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-020, T-055, T-149
- **Spec:** §10.5, §12.3, §8.4, §8.2, §15.1
- **Objective:** An edit that creates revision N+1, supersedes N, retires any approval N held, and re-runs validation — with the prior revision untouched.
- **Scope (in):** An `edit_revision` operation composing `T-020`'s `create_revision`/`supersede`, approval retirement, and `T-055`'s `apply_validation`; `POST /api/review/revisions/{revision_id}/edit` under a permission the matrix already defines; **mutations refuse cookie authentication** until `T-070` adds CSRF, with a test; the route declared and the client regenerated.
- **Scope (out):** The editing UI (`T-065b`); CSRF itself (`T-070`); approving, rejecting, deferring (`T-066`, `T-067`).
- **Acceptance criteria:**
  1. Editing an approved revision leaves that approval no longer usable; test-proven.
  2. The prior revision is byte-identical afterwards — same body, subject, citations, and content hash; test-proven field by field.
  3. Validation re-runs on the new revision and can block it; test-proven in both directions.
- **Verification:** `uv run pytest -q tests/test_review_edit.py tests/test_authz.py`
- **Files:** `backend/app/drafts_and_approvals/editing.py`, `backend/app/drafts_and_approvals/api.py`, `backend/tests/test_review_edit.py`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_review_edit.py`.
  1. *Approval no longer usable* — `test_editing_an_approved_revision_revokes_its_approval` (approved → revoked), `test_editing_expires_a_pending_approval_rather_than_revoking_it` (pending → expired, because §8.2 has no `pending → revoked` edge), and `test_a_blocked_edit_still_retires_the_old_approval` for the dangerous case where the *new* revision fails validation.
  2. *Prior revision byte-identical* — `test_the_prior_revision_is_unchanged_field_by_field` compares subject, body, content hash, revision number, recipient, claims, and evidence against a snapshot taken before the edit; `test_the_prior_revision_is_superseded` and `test_the_edit_creates_revision_two` cover the chain. The database trigger from `T-020` enforces this independently: two test helpers had to be rewritten because it refused their shortcut.
  3. *Validation re-runs and can block* — `test_validation_reruns_on_the_new_revision` and `test_validation_can_block_the_edit` (a citation to a claim that does not exist lands the revision in `validation_failed` — saved, so the reviewer can see why), plus `test_the_response_reports_a_blocked_edit_with_its_checks`.
  Also proven: `test_a_cookie_cannot_authenticate_a_mutation` and `test_a_bearer_token_can` (the CSRF deferral `T-061a` left for this task), `test_a_stale_record_version_is_refused`, `test_the_actor_comes_from_the_session_not_the_body`, `test_a_superseded_revision_cannot_be_edited`, and `test_a_refused_edit_changes_nothing`.
  **Observed:** `uv run pytest -q tests/test_review_edit.py` → 22 passed; `tests/test_authz.py tests/test_fixtures.py` → 58 passed; full backend suite 1852 passed; `ruff check .`, `ruff format --check .`, `mypy app` (102 files), `alembic check` all clean; frontend `lint`/`typecheck`/`test` clean at 40 tests. Four negative controls each failed the right tests and the suite returned green after each restore: approvals not retired (3 failed), the prior revision mutated (3 failed), validation not re-run (4 failed), the mutation accepting cookie authentication (1 failed). No migration was added; no external effect occurred.

#### T-065b — The dashboard editing form
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-065a, T-064
- **Spec:** §12.3, §10.5
- **Objective:** A reviewer edits a draft in the dashboard and sees the new revision.
- **Scope (in):** The card's Edit action wired to `T-065a`'s endpoint; the resulting revision shown; validation failures surfaced as the reason they are, not as a generic error.
- **Scope (out):** Everything `T-065a` owns.
- **Acceptance criteria:**
  1. Submitting an edit shows revision N+1 and marks the previous one superseded.
  2. A validation failure is shown with its specific check, not a generic message.
  3. The form cannot be submitted without a correction reason (§12.3 item 7).
- **Verification:** `npm run test` from `frontend/`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `frontend/tests/edit-form.test.tsx` (22 tests, `jsdom`).
  1. *Revision N+1 shown, previous superseded* — `shows the new revision number and says the previous one is superseded`, plus `reports the approval the edit retired` and `counts a revoked and an expired approval together`, because §10.5's invalidated approval is the part a reviewer would otherwise assume carried across.
  2. *A validation failure names its check* — `names the check that failed, not a generic error`, `lists every failed check`, and `says the edit was saved, because it was` (the revision exists in `validation_failed`; a reviewer told only "failed" would retype text that was never lost). `backend/tests/test_review_edit.py::test_every_validation_check_has_a_reviewer_explanation` asserts the explanation map covers every backend `Check` — the only place both facts exist.
  3. *No submission without a correction reason* — `is required on the field itself` (the native `required` attribute, with `T-065a`'s server refusal behind it), `offers §12.3's structured reasons rather than a free-text box`, and `is sent with the edit`.
  Also proven: `sends the session token as a bearer, never as a cookie` (`T-065a` refuses cookie auth on mutations), `sends the record version the reviewer was shown`, `shows the backend's own reason, not a generic failure`, and `refuses to send at all when there is no session` — which is what surfaced `T-151`.
  **Observed:** `npx vitest run tests/edit-form.test.tsx` → 22 passed; full frontend suite → 62 passed (see the flake note below); `npm run lint`, `npm run typecheck`, and `npm run build` clean, with `/review/[candidateId]` still server-rendered on demand; backend `ruff check .`, `ruff format --check .`, `mypy app` (102 files), `alembic check`, and `pytest -q` → 1853 passed. Six negative controls each failed the right tests and everything returned green after each restore: the outcome not naming the superseded revision (1 failed), a generic validation message (2 failed), the correction reason not `required` (1 failed), the token not sent as a bearer (1 failed), a missing session posting anyway (1 failed), and an explanation removed from the map (the backend coverage test failed). No migration; no external effect — `fetch` is stubbed in every test and `assertLocal` still refuses a non-local base URL.
  **Known flake, not caused here:** `api-types.test.ts::matches a fresh generation` failed once in the first four full runs and then passed four consecutive times; it passes alone. That is `T-150`, whose block now records this cycle's observation.


#### T-066 — Candidate decisions with structured correction reasons
- **Stage / Priority:** 2 / P1 · **Status:** `DONE` (2026-07-31 — all four acceptance criteria shipped in `T-066a`, reachable over HTTP in `T-066b1`, and on the card in `T-066b2`. Two *actions* named in the objective left this task rather than shipping under it: approval is `T-154` (`DONE`) and request-more-research is `T-153`, still `READY` — see the split note) · **Depends on:** T-064 · **Spec:** §10.6 (eleven categories), §12.3 item 7
- **Objective:** Approve, reject, defer, and request-more-research decisions, each requiring a structured reason from the §10.6 category list with optional notes.
- **Acceptance:** the eleven categories are a database enum; a rejection without a category is refused; "defer until date/event" stores the date/event; feedback is stored as evaluation data and never rewrites policy (test-proven).
- **Verification:** `uv run pytest -q tests/test_corrections.py` · **Files:** `backend/app/qualification/corrections*`, `frontend/app/review/*` · **Q:** none
- **Status note (2026-07-31):** **Split into `T-066a` and `T-066b`, and one action removed from both.** All four acceptance criteria — the eleven categories as a database enum, a rejection refused without one, defer-until storing its date or event, and feedback that never rewrites policy — are backend facts, and the dashboard buttons are a separate change set. Preflight also found that **"request more research" has no lifecycle edge**: §8.2's candidate machine allows `review_pending → approved/rejected/deferred/invalidated` and nothing back to `research_pending`, so the action cannot be a transition without changing the architecture. Deciding what it *is* instead is `T-153`, filed rather than improvised. Criteria map: all four → `T-066a`; the buttons → `T-066b`; request-more-research → `T-153`.

#### T-066a — Structured decision reasons for candidate rejections and deferrals
- **Stage / Priority:** 2 / P1
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058b2b2a, T-012
- **Spec:** §10.6 (eleven categories), §12.3 item 7, §8.2, §17.5
- **Objective:** A reviewer's reject or defer decision is recorded with a structured category, optional notes, and — for a deferral — the date or event it waits on.
- **Scope (in):** The eleven §10.6 categories as a database enum; a `CandidateDecision` record carrying category, notes, actor, and decided-at; `reject_candidate` and `defer_candidate` composing the `T-058b2b2a` approval pattern; a refusal when no category is given; the deferral's `defer_until` date or event text; a migration.
- **Scope (out):** The dashboard actions (`T-066b`); request-more-research (`T-153`); the message approval transaction (`T-067`); anything that consumes this feedback — it is stored as evaluation data and read by nobody yet, which is the point.
- **Acceptance criteria:**
  1. The eleven §10.6 categories exist as a database enum, and the enum is the migration's, not just the model's; test-proven against the migrated schema.
  2. A rejection without a category is refused; test-proven, and refused by the database as well as the code.
  3. A deferral stores the date or the event it waits on; test-proven for both, and a deferral with neither is refused.
  4. Recording feedback changes no campaign policy — no policy version is created or modified by any decision; test-proven.
- **Verification:** `uv run pytest -q tests/test_corrections.py`
- **Files:** `backend/app/campaigns/decisions.py`, `backend/alembic/versions/*`, `backend/tests/test_corrections.py`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_corrections.py` (25 tests).
  1. *The eleven categories are a database enum* — `test_the_eleven_categories_are_a_database_enum` reads `pg_enum` on the **migrated** schema rather than asking the Python class about itself, and `test_the_enum_matches_the_specification_list` compares against §10.6 transcribed by hand into `SPEC_CATEGORIES`. Two copies on purpose: a test that imported the enum would agree with whatever the enum said. `test_a_category_outside_the_enum_is_refused_by_the_database` is the point of an enum over a string column.
  2. *A rejection without a category is refused* — `test_rejecting_without_a_category_is_a_type_error` (the argument has no default) and `test_a_null_category_is_refused_by_the_database`, which inserts around the module entirely. Also `test_rejecting_for_a_deferral_reason_is_refused` and `test_a_refused_rejection_leaves_the_candidate_in_review`.
  3. *A deferral stores its date or event* — `test_deferring_stores_a_date`, `test_deferring_stores_an_event`, `test_deferring_with_neither_is_refused`, `test_deferring_with_a_blank_event_is_refused`, and `test_a_waypointless_deferral_is_refused_by_the_database` at the constraint. `test_a_rejection_cannot_carry_a_waypoint` holds the other side.
  4. *No policy is rewritten* — `test_a_rejection_rewrites_no_policy` and `test_a_deferral_rewrites_no_policy` compare every policy version by identity, number, and serialized content either side of a decision; `test_no_decision_creates_a_policy_version` counts as well, since a version appended after the snapshot's last row would leave the earlier rows identical. The absence is the behaviour, so it is asserted rather than left to be noticed.
  **Two bugs caught before they shipped, both by reading the generated migration rather than trusting it.** The autogenerated constraint names came out doubled (`ck_candidate_decision_ck_candidate_decision_…`) because the model names already carried the prefix the naming convention adds. And the check constraints compared `kind` against `'defer'` while SQLAlchemy stores the enum member's *name* — `'DEFER'` — so the deferral guard would have matched nothing and never fired, passing every happy-path test. The constraint now uses the stored form, and control 3 proves it fires.
  **Observed:** `uv run pytest -q tests/test_corrections.py` → 25 passed; full backend suite 1899 passed; `ruff check .`, `ruff format --check .` (188 files), `mypy app` (104 files), `alembic check` all clean; `alembic downgrade -1` then `upgrade head` round-trips cleanly — the migration drops both enum types on downgrade, without which the next upgrade fails with "type already exists" (the trap `ba1a2b2420a4` hit). Frontend untouched, 82 tests still passing. Six negative controls each failed the right tests with a green restore: a category missing from the **migration's** enum (1 failed), the category column made nullable in the migration (1), the code no longer refusing a deferral category on a rejection (2), the waypoint constraint removed from the migration (1), the code accepting a waypointless deferral (2), and a decision republishing campaign policy (2). Three of the six mutate the migration, because that is what the suite builds its schema from. No external effect occurred.

#### T-066b — The dashboard's approve, reject, and defer actions
- **Stage / Priority:** 2 / P1
- **Status:** `DONE` (2026-07-31 — `T-066b1` and `T-066b2` are all `DONE`); split, see the note below
- **Depends on:** T-066a, T-151b, T-065b
- **Spec:** §12.3 items 6 and 7
- **Objective:** The three decision buttons on the review card do what they say, each carrying its structured reason.
- **Scope (in):** Endpoints for the `T-066a` decisions; the card's Approve, Reject, and Defer actions wired to them; the category list offered as §10.6's eleven; the deferral's date or event captured.
- **Scope (out):** Everything `T-066a` owns; request-more-research (`T-153`).
- **Acceptance criteria:**
  1. Rejecting from the card records the category the reviewer chose; test-proven.
  2. The form cannot submit a rejection with no category; test-proven.
  3. Deferring captures a date or an event and shows it back; test-proven.
- **Verification:** `npm run test` from `frontend/`
- **Blocker / Q:** none
- **Status note (2026-07-31):** **Split into `T-066b1` and `T-066b2`, and Approve removed from both.** The layer split follows the precedent `T-065` and `T-151` set: endpoints and React are separate change sets in this repository, and bundling them puts the interesting part — a mutating route and its authorization — in the same review as a form. **Approve is a different matter.** ADR-008 approves an exact recipient and an exact revision together, so `approve_candidate` requires a `recipient_contact_point_id` — and `CandidateDetail` exposes no contact points at all, so a reviewer has nothing to choose from. Building the button anyway would mean the system picked the address and the approver ratified something they were never shown, which is the failure ADR-008 exists to prevent. That is `T-154`. Note that all three of this task's acceptance criteria are about rejecting and deferring; none mentions approval, so nothing is lost by moving it. Criteria map: the endpoints they need → `T-066b1`; all three criteria → `T-066b2`; approval → `T-154`.

#### T-066b1 — Reject and defer endpoints
- **Stage / Priority:** 2 / P1
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-066a, T-063a
- **Spec:** §10.6, §12.3 item 7, §15.1, §8.2
- **Objective:** `T-066a`'s two decisions reachable over HTTP, under the permission the matrix already defines.
- **Scope (in):** `POST /api/review/candidates/{candidate_id}/reject` and `.../defer`; the §10.6 category as a typed request field; the deferral's date or event; both declared in `ROUTE_PERMISSIONS` and refusing cookie authentication as mutations do until `T-070`; the record version checked as `T-065a` does; `frontend/openapi.json` re-exported and the client types regenerated.
- **Scope (out):** The card's buttons (`T-066b2`); approval (`T-154`); request-more-research (`T-153`).
- **Acceptance criteria:**
  1. Rejecting over HTTP records the category and moves the candidate; test-proven end to end through the API.
  2. A request with no category, or a category outside §10.6's eleven, is refused by the schema before any handler runs; test-proven.
  3. A deferral with neither a date nor an event is refused; test-proven, and one with either is accepted.
  4. Both routes require the decision permission and refuse cookie-only authentication; test-proven.
- **Verification:** `uv run pytest -q tests/test_decision_api.py tests/test_authz.py`
- **Files:** `backend/app/drafts_and_approvals/api.py`, `backend/app/identity/rbac.py`, `backend/tests/test_decision_api.py`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_decision_api.py` (33 tests).
  1. *Rejecting over HTTP records and moves* — `test_rejecting_records_the_decision` asserts the row in the database rather than the echo in the response, `test_rejecting_moves_the_candidate`, and `test_the_response_reports_what_was_recorded`. `test_the_actor_comes_from_the_session` proves attribution is the session's user, and `test_supplying_an_actor_is_refused_rather_than_ignored` proves `extra="forbid"` refuses the attempt outright — silently ignoring it is what makes someone believe it was honoured.
  2. *A bad category is refused by the schema* — `test_no_category_is_refused_by_the_schema` and `test_a_category_outside_the_eleven_is_refused_by_the_schema`, both asserting `422` specifically rather than "not 200", since a `500` would also be "not 200" and would mean the opposite. `test_every_specification_category_is_accepted` is parametrized over all eleven, so a schema that accepted only the categories somebody thought to test would fail.
  3. *A deferral needs a waypoint* — `test_deferring_with_a_date`, `test_deferring_with_an_event`, and `test_deferring_with_neither_is_a_conflict`, which checks the route turns `T-066a`'s refusal into a `409` a dashboard can show rather than a `500`. Plus the default and override of the category.
  4. *Permission, and no cookie* — `test_a_cookie_cannot_authenticate_a_decision`, `test_no_session_is_401`, and `test_a_role_without_the_permission_is_forbidden`, each parametrized over both routes rather than one of them. `test_a_stale_record_version_is_refused` and `test_rejecting_outside_review_is_a_conflict` cover the two `409`s.
  **Observed:** `uv run pytest -q tests/test_decision_api.py` → 33 passed; with `tests/test_authz.py tests/test_fixtures.py` → 91 passed; full backend suite 1932 passed; `ruff check .`, `ruff format --check .` (189 files), `mypy app` (104 files), `alembic check` all clean; frontend `lint`, `typecheck`, and 82 tests clean after regenerating the client types. Six negative controls each failed the right tests with a green restore: the decision never committed (3 failed), the category as an untyped string (2), the deferral refusal not caught (1), the record version unchecked (1), mutations accepting cookie auth (2), and the route left undeclared in `ROUTE_PERMISSIONS` (`test_authz.py` failed). No migration was added; no external effect occurred.
  **Note on the controls:** the first attempt failed its own pattern assertion because `ruff format` had reflowed the region — the no-op the protocol warns about, caught rather than silently passed. The controls were rewritten to mutate by line index with the line's content asserted first.

#### T-066b2 — The card's Reject and Defer actions
- **Stage / Priority:** 2 / P1
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-066b1, T-065b
- **Spec:** §12.3 items 6 and 7, §10.6
- **Objective:** A reviewer rejects or defers from the card, choosing a structured reason.
- **Scope (in):** The Reject and Defer actions wired to `T-066b1`; §10.6's eleven categories offered as a list; the deferral's date or event captured and shown back.
- **Scope (out):** Everything `T-066b1` owns; approval (`T-154`).
- **Acceptance criteria:**
  1. Rejecting from the card records the category the reviewer chose; test-proven.
  2. The form cannot submit a rejection with no category; test-proven.
  3. Deferring captures a date or an event and shows it back; test-proven.
- **Verification:** `npm run test` from `frontend/`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `frontend/tests/decision-form.test.tsx` (21 tests).
  1. *Rejecting records the chosen category* — `sends the category the reviewer picked`, `offers §10.6's categories, minus the one that is a deferral` (ten plus the empty option: `T-066a` refuses "defer until a date or event" as a *rejection* reason, so offering it would show a reviewer an option the server rejects), `labels each category in words rather than identifiers`, `shows the recorded category back in words`, and the notes and record-version tests.
  2. *No rejection without a category* — `is required on the field itself`, `leaves Reject disabled until a category is chosen`, and `sends nothing when submitted with no category`.
  3. *Deferring captures a date or an event and shows it back* — `sends a date`, `sends an event`, `leaves Defer disabled until there is a date or an event`, `does not treat whitespace as an event`, `sends nothing when submitted with no waypoint`, `shows the date it was deferred until`, `shows the event it was deferred until`, and `defaults the category to §10.6's eleventh`.
  **The category list is derived, not restated.** `CATEGORY_LABELS` is typed as `Record<DecisionCategory, string>` against the generated type, so a category added on the backend is a **compile error** here rather than an option a reviewer never sees. This file owns the wording a human reads; the backend owns which categories exist, and neither can drift without the other failing.
  **Observed:** `npx vitest run tests/decision-form.test.tsx` → 21 passed; full frontend suite → 121 passed across 7 files, three consecutive runs; `npm run lint`, `npm run typecheck`, and `npm run build` clean. Backend untouched and re-confirmed: `pytest -q` → 1951 passed, `ruff check .` and `mypy app` (105 files) clean. Ten negative controls each failed the right tests with a green restore: the chosen category not sent (1 failed), the deferral reason offered as a rejection (1), the outcome showing an identifier instead of a label (1), the category not `required` (1), reject submitting with no category (1), defer submitting with no waypoint (1), whitespace counting as an event (1), the deferral outcome hiding what it waits for (1), the token not sent as a bearer (1), and the card no longer offering the decisions (2). No migration; no external effect.
  **Card status after this task:** four of §12.3 item 6's five actions are live — edit (`T-065b`), approve (`T-154b`), reject and defer (here). Only request-more-research remains disabled, and `T-153` has to decide what it *is* before it can be wired, since §8.2 offers no edge from `review_pending` back to `research_pending`. `review-card.test.tsx`'s disabled-set assertion was updated to say so explicitly: the three other disabled buttons are the live forms' own submits, each waiting on the choice its action requires, not three unbuilt actions.

#### T-154 — Approving a candidate needs a recipient the reviewer can see
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31 — `T-154a` and `T-154b` are both `DONE`); split, see the note below
- **Depends on:** T-149, T-058b2b2a
- **Spec:** §12.3 items 1 and 6, §8.1, ADR-008
- **Found by:** `T-066b`. `approve_candidate` requires a `recipient_contact_point_id` because ADR-008 approves an exact recipient and an exact revision together — but `CandidateDetail` returns no contact points, so the review card cannot offer one. The Approve action has nothing to name.
- **Why it matters:** the tempting shortcut is to derive the recipient server-side from the contact's verified address. That would mean the system chose the address and the approver ratified something they were never shown, which is precisely the failure ADR-008's "exact recipient" clause exists to prevent — and `campaigns.approval` already documents the recipient as "an argument, not something this derives".
- **Objective:** The card shows the contact points a candidate could be approved for, and approval names the one the reviewer picked.
- **Scope (in):** Contact points on `CandidateDetail` with their verification state; `POST /api/review/candidates/{candidate_id}/approve` taking the chosen one; the card's Approve action; a refusal when the chosen point does not belong to this candidate's contact.
- **Scope (out):** The message approval transaction (`T-067`), which approves a *revision*; rejection and deferral (`T-066b1`, `T-066b2`).
- **Acceptance criteria:**
  1. The card lists the candidate's contact points with verification state; test-proven.
  2. Approving names a recipient the reviewer chose, and a point belonging to another contact is refused; test-proven.
  3. An unverified address cannot be approved; test-proven.
- **Verification:** `uv run pytest -q tests/test_decision_api.py` and `npm run test`
- **Blocker / Q:** none
- **Status note (2026-07-31):** **Split into `T-154a` and `T-154b`**, on the same layer boundary as `T-065`, `T-151`, and `T-066b`. The backend half carries the safety question: this is the first **tier-4** endpoint — `APPROVE_CANDIDATE` is "the approval that lets an external effect happen at all" (§7.4) — and it is the point where ADR-008's "exact recipient" either holds or quietly stops holding. Criteria map: the contact points on the detail endpoint and both refusals → `T-154a`; the card listing them and the Approve action → `T-154b`.

#### T-154a — Contact points on the review card, and the approve endpoint
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-149, T-058b2b2a, T-063a
- **Spec:** §12.3 items 1 and 6, §8.1, §7.4, ADR-008
- **Objective:** The detail endpoint returns the contact points a candidate could be approved for, and an approve endpoint accepts exactly one of them.
- **Scope (in):** Contact points with type, value, and verification state on `CandidateDetail`; `POST /api/review/candidates/{candidate_id}/approve` under `APPROVE_CANDIDATE`, refusing cookie authentication as every mutation does until `T-070`; a refusal when the chosen point belongs to another contact; a refusal when it is not verified; the record version checked; the client contract re-exported.
- **Scope (out):** The card's Approve action (`T-154b`); the message approval transaction (`T-067`), which approves a *revision*.
- **Acceptance criteria:**
  1. `CandidateDetail` returns the candidate's contact points with their verification state; test-proven, including a candidate with none.
  2. Approving names a recipient the reviewer chose, and a contact point belonging to another contact is refused with nothing written; test-proven.
  3. An unverified address cannot be approved; test-proven.
  4. The route requires `APPROVE_CANDIDATE` — not `CORRECT_CANDIDATE` — and refuses cookie-only authentication; test-proven, including that a role holding only the tier-3 permission is refused.
- **Verification:** `uv run pytest -q tests/test_decision_api.py tests/test_review_api.py tests/test_authz.py`
- **Files:** `backend/app/drafts_and_approvals/api.py`, `backend/app/identity/rbac.py`, `backend/tests/test_decision_api.py`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_decision_api.py` (52 tests total, 24 of them new here).
  1. *Contact points on the detail* — `test_the_detail_returns_the_contact_points`, `test_a_candidate_with_no_contact_points_returns_an_empty_list`, `test_the_contact_points_are_deterministically_ordered` (a list that reordered itself would move the option under a reviewer's cursor between renders), and `test_another_contacts_points_are_not_listed`, which holds §8.1's scope. `test_an_unverified_point_is_shown_and_marked_unapprovable` pins the choice to show-and-refuse rather than hide: a reviewer who cannot see the mailbox they expected cannot tell "unusable" from "unknown", and those want different actions.
  2. *Approving names a chosen recipient* — `test_approving_names_the_chosen_recipient` (the address echoed back, not only its id — an approval confirmed as a UUID is one nobody can check by reading), `test_approving_queues_the_drafting_job` asserting the job carries the chosen point, `test_another_contacts_recipient_is_refused`, `test_an_unknown_recipient_and_a_strangers_are_indistinguishable` so the endpoint is not an id oracle, `test_a_refused_approval_queues_nothing`, and `test_no_recipient_is_refused_by_the_schema`.
  3. *An unverified address cannot be approved* — `test_an_unverified_recipient_is_refused` and `test_an_unverified_recipient_queues_nothing`.
  4. *Tier 4, and no cookie* — `test_the_route_is_declared_at_tier_four` is **structural on purpose**: `ROLE_GRANTS` gives both `CORRECT_CANDIDATE` and `APPROVE_CANDIDATE` to the operator/reviewer alone, so no role exists that would be allowed one and refused the other, and behaviour cannot show the difference. The declaration is what keeps approval from quietly becoming a tier-3 action. `test_a_role_without_the_approval_permission_is_refused`, `test_a_cookie_cannot_authenticate_an_approval`, and `test_no_session_cannot_approve` cover the rest.
  **A defect found and fixed because the endpoint could not work without it:** `create_app` registered **no job types**, so `approve_candidate`'s `enqueue` raised `UnknownJobType` in the API process while every unit test of the same path passed, because each test registers types itself. Fixing it moved `JOB_TYPE_MODULES` and `register_job_types` out of `app/worker.py` into a new `app/job_types.py` — twice, because `tests/test_module_boundaries.py` refused both the obvious homes: nothing may import `worker`, and `jobs_and_outbox` may not import a domain module (§17.1, the queue is a generic mechanism). Both refusals are right, and together they identify what the list is — a composition fact belonging beside the entry points, not inside the mechanism or any one domain.
  **Observed:** `uv run pytest -q tests/test_decision_api.py` → 52 passed; with `tests/test_authz.py` → 92 passed; full backend suite 1951 passed; `ruff check .`, `ruff format --check .` (190 files), `mypy app` (105 files), `alembic check` all clean. Frontend `lint`, `typecheck`, `build`, and 82 tests clean after regenerating the client types — the generated type did its job, breaking the build on two fixtures until `contact_points` was added rather than rendering blank (§23). Seven negative controls each failed the right tests with a green restore: the detail returning no contact points (4 failed), unverified points hidden (1), the recipient not checked against the candidate (2), an unverified recipient accepted (2), approval declared at tier 3 (1), approval accepting cookie auth (1), and the app registering no job types (2). **Control 1 passed on its first attempt and was wrong, not the tests** — the mutation `contact_points=[] or [...]` evaluates to the second operand — so it was rewritten to replace the comprehension outright and then failed correctly. No migration was added; no external effect occurred, and approval queues drafting only, with sending still behind **G-07**.
  **Known flake:** `api-types.test.ts::matches a fresh generation` failed once in a full run and then passed alone and in three consecutive full runs. That is `T-150`.

#### T-154b — The card's Approve action
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-154a, T-065b
- **Spec:** §12.3 items 1 and 6, ADR-008
- **Objective:** A reviewer picks the recipient and approves, having seen the address they approved.
- **Scope (in):** The card listing contact points with verification state; the recipient chosen explicitly, never pre-selected in a way that lets an approval happen without a choice; the Approve action wired to `T-154a`.
- **Scope (out):** Everything `T-154a` owns.
- **Acceptance criteria:**
  1. The card lists the candidate's contact points with verification state; test-proven.
  2. Approve cannot be submitted without a recipient chosen; test-proven.
  3. An unverified address is shown as unusable rather than silently absent; test-proven.
- **Verification:** `npm run test` from `frontend/`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `frontend/tests/approve-form.test.tsx` (18 tests).
  1. *The card lists contact points with verification state* — `shows each address with its verification state` (asserted per row, see the note below), `offers one option per address`, and `says so plainly when there is no address at all` — which is a different problem from "the address is unusable" and needs a different fix. `states that approving sends nothing` holds the shadow-mode sentence.
  2. *Approve cannot be submitted without a recipient* — `selects nothing by default` (ADR-008 approves an address the reviewer *chose*; a pre-selected one is an address the system chose and the approver ratified without deciding), `leaves Approve disabled until one is picked`, and `sends nothing when submitted with no choice`. `sends the address the reviewer picked`, `sends the record version the reviewer was shown`, and `sends the token as a bearer` cover the request.
  3. *An unverified address is shown as unusable, not absent* — `is listed rather than hidden`, `cannot be chosen`, `says why it cannot be used`, `warns when no address is usable`, and `does not warn when one is usable`.
  Also proven: `names the address that was approved` — an approval confirmed as "done" is one nobody can check, while one confirmed as "approved for `…@example.com`" is one a reviewer can catch themselves having got wrong — plus `shows the backend's own refusal` and `refuses to send at all when there is no session`.
  **A weak assertion of my own, found by a control that failed to bite:** the first version checked `toContain("verified")` against the whole page, which is satisfied by the substring inside "unverified" — so it would have passed with the verified row's state missing entirely. It now asserts per row with a word boundary, and the control fails as it should. A second control also missed because its `-t` filter matched no test; both were re-run rather than accepted.
  **Observed:** `npx vitest run tests/approve-form.test.tsx` → 18 passed; full frontend suite → 100 passed across 6 files, three consecutive runs; `npm run lint`, `npm run typecheck`, and `npm run build` clean. Backend untouched and re-confirmed: `pytest -q` → 1951 passed, `ruff check .` and `mypy app` (105 files) clean. Eight negative controls each failed the right tests with a green restore: unverified points filtered out (3 failed), the verification state not shown (1), a recipient pre-selected (1 for the default, 1 for the button), approve submitting with no choice (1), an unverified option selectable (1), a generic refusal message (1), the token not sent as a bearer (1), and the card no longer offering approval (1). No migration; no external effect — approval queues drafting only, and sending stays behind **G-07**.
  **One neighbouring test tightened rather than left drifting:** `review-card.test.tsx`'s button assertion counted 5 buttons with 4 disabled, and those counts stayed true by coincidence when Approve went live (its submit starts disabled until a recipient is chosen). It now asserts the disabled set by label, so a future action going live cannot pass unnoticed.



#### T-155 — The card's Request-more-research action
- **Stage / Priority:** 2 / P2
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-153, T-065b
- **Spec:** §12.3 item 6, ADR-022
- **Found by:** `T-153`, which decided what the action *is* and built it, deliberately stopping short of the button. Its own acceptance criteria named the ADR and the backend behaviour and not the card.
- **Objective:** The last of §12.3 item 6's five actions works from the review card.
- **Scope (in):** An endpoint for `campaigns.decisions.request_more_research` declared in `ROUTE_PERMISSIONS` under `CORRECT_CANDIDATE` and refusing cookie authentication as every mutation does; the card's Request-more-research action wired to it with a §10.6 category; the refusal when a pass is already in flight shown as the sentence it is.
- **Scope (out):** ADR-022's decision, which is made; showing evidence as it arrives, which is `T-149`'s existing read.
- **Acceptance criteria:**
  1. Requesting more research from the card records the category and queues one pass; test-proven.
  2. A second request while one is in flight shows the backend's refusal rather than queueing another; test-proven.
  3. The card no longer shows a disabled Request-more-research button; test-proven.
- **Verification:** `uv run pytest -q tests/test_decision_api.py` and `npm run test`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it. Done in one cycle rather than split: the endpoint mirrors `T-066b1`'s reject/defer exactly and the action mirrors `T-066b2`'s form, so neither half carried a decision of its own.
  1. *The category is recorded and one pass is queued* — backend `test_requesting_more_research_records_the_category` and `test_requesting_more_research_queues_one_pass` in `tests/test_decision_api.py`; frontend `sends the category the reviewer picked` in `tests/decision-form.test.tsx`. `test_the_candidate_stays_in_review` holds ADR-022's decision at the route, and `says the candidate stays in review` puts it in the sentence a reviewer reads — the card not vanishing from their queue is the one thing they would notice.
  2. *A second request shows the refusal rather than queueing another* — `test_a_second_request_while_one_is_in_flight_is_a_conflict` (asserting the queued count is still 1) and `shows the backend refusal when a pass is already in flight`.
  3. *No disabled Request-more-research button* — `shows no disabled placeholder buttons at all` in `tests/review-card.test.tsx`, which asserts `Not yet wired` appears nowhere and that every remaining disabled button carries a `title` naming the choice it waits for. `offers all five of §12.3 item 6's actions, every one of them live` replaces the old "unbuilt actions" test, whose premise no longer exists.
  **Three test weaknesses found by controls, two of them mine.** (a) A control mutating `session.commit()` hit the *reject* endpoint rather than this one — `replace(…, 1)` on a pattern that appears five times — and was redone by line index. (b) `never submits the rejection form` checked only `calls[0]`, which passed against exactly the `type="submit"` mistake it exists to catch; it now asserts over every call and pins the count at one. (c) Deleting the `category === ""` guard in `askForResearch` failed no test — but `tsc` then failed, because the guard is a **type narrowing** (`DecisionCategory | ""` to `DecisionCategory`) whose runtime branch is genuinely unreachable behind a disabled button. Kept, and the comment now says which of the two it is so nobody reads it as a proven check.
  **One small change outside the new code:** the Reject button had no `title` while disabled, alone among the four. Added, because criterion 3's test asserts every disabled button explains itself and relaxing the test would have been the wrong direction.
  **Observed:** `uv run pytest -q tests/test_decision_api.py` → 60 passed; full backend suite 2019 passed; `ruff check .`, `ruff format --check .` (195 files), `mypy app` (108 files), `alembic check` all clean. Frontend `lint`, `typecheck`, `build`, and 127 tests clean. Ten negative controls — five backend, five frontend, plus three re-runs — each failed the right tests with a green restore. No migration; no external effect: the pass reads a local fixture document and stores a snapshot.
  **Note on a shadowed test:** appending these tests introduced a second `test_no_category_is_refused_by_the_schema`, which silently replaced the reject-route test of the same name. `ruff`'s F811 caught it; the new one is `test_research_without_a_category_is_refused_by_the_schema` and both now run.


#### T-156 — Validation drags the model gateway into every path that validates
- **Stage / Priority:** 2 / P2
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-055
- **Spec:** §11.3, §3.5, §18.2
- **Found by:** `T-067a`, writing the structural "no agent callback in the approval path" test. The walk reports `outreach_and_replies.approve_message` → `drafts_and_approvals.validation` → `drafts_and_approvals.drafting` → `model_gateway.gateway`. Nothing in the approval path *calls* the model; the edge exists because `validation` imports `PURPOSE_TEMPLATES` and `TEMPLATE_DIR` from `drafting` to check compliance boilerplate, and `drafting` is also the module that talks to the gateway.
- **Why it matters:** §11.3 ends "no agent callback is required" and §3.5 forbids external execution authority held only by the agent runtime. Those are properties worth testing structurally, and today they cannot be — any transitive assertion over the approval path is false because of this one edge. `T-067a`'s test is scoped to the modules that make the decision and says so explicitly; that is a narrower guarantee than the specification's sentence deserves.
- **Objective:** Validation can check boilerplate without importing the module that calls the model.
- **Scope (in):** Moving the template constants (`PURPOSE_TEMPLATES`, `TEMPLATE_DIR`, and whatever else validation reads) to a module that holds templates and nothing else; repointing both importers; widening `T-067a`'s test from `DECISION_MODULES` to the full transitive walk once the edge is gone.
- **Scope (out):** Changing what validation checks or how drafting renders.
- **Acceptance criteria:**
  1. A transitive import walk from `outreach_and_replies.approve_message` reaches no `model_gateway` module; test-proven by the widened assertion in `tests/test_approval_transaction.py`.
  2. The same walk from `drafts_and_approvals.validation` reaches none either.
  3. Every `T-055` validation test still passes unchanged — the templates moved, the rules did not.
- **Verification:** `uv run pytest -q tests/test_approval_transaction.py tests/test_revision_validation.py tests/test_drafting.py`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_approval_transaction.py`.
  1. *The approval path reaches no `model_gateway`* — `test_the_approval_path_reaches_no_model_gateway`, now over the **whole transitive walk** rather than the five hand-listed modules `T-067a` had to settle for. That widening is the task: the specification's sentence is about the path, and the assertion now says the same thing.
  2. *Neither does validation on its own* — `test_validation_reaches_no_model_gateway`, separate because `validation` is imported by more than this path; the edge would return for every other caller and only this test would notice.
  3. *Every `T-055` test still passes unchanged* — `uv run pytest -q tests/test_revision_validation.py tests/test_drafting.py` → 63 passed, with no test edited. The templates moved; the rules did not.
  Also added: `test_the_template_registry_stays_a_registry`, which is what keeps the edge gone. `templates_registry` exists to hold two constants, and the moment it imports a provider, a client, or a session the whole chain is back — the two walks above would simply start reporting a different module, so the property needs its own assertion.
  **The change is two constants and three import lines.** `TEMPLATE_DIR` and `PURPOSE_TEMPLATES` moved from `drafting.py` — which also calls the model gateway — into `templates_registry.py`, which imports only `DraftPurpose`. `drafting` re-exports them so its own callers are untouched. Walk results after: 25 modules reachable from `approve_message` and 19 from `validation`, `model_gateway` in neither.
  **A control found a hole in the test's own machinery.** Adding `from app.model_gateway import gateway` to the registry did **not** fail anything: `_app_imports` recorded only `model_gateway`, which is a directory, so the walk found no file and stopped — the assertion could be evaded by choosing that import form. The walk now records `pkg` *and* `pkg.submodule` for every `from app.pkg import name`; names that are classes rather than modules resolve to no file and cost nothing. Re-run afterwards, the control failed 3 tests as it should. Without that control the widened assertion would have looked like a guarantee and been a gap.
  **Observed:** `uv run pytest -q tests/test_approval_transaction.py` → 40 passed; full backend suite 2011 passed; `ruff check .`, `ruff format --check .` (195 files), `mypy app` (108 files), `alembic check` all clean; frontend untouched, 121 tests passing. Four negative controls plus two re-runs each failed the right tests with a green restore: validation importing `drafting` again — the original edge — (2 failed), the registry importing the gateway package-style (3) and validation the same (2), a template name pointing at a missing file (5 errors), and a wrong template directory (5 errors). No migration; no external effect.


#### T-153 — "Request more research" has no lifecycle edge
- **Stage / Priority:** 2 / P2
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-058b2b1, T-066a
- **Spec:** §12.3 item 6, §8.2, §6.2, ADR-020
- **Found by:** `T-066`. §12.3 item 6 requires the review card to offer "request more research", and §6.2 lists it among OpenClaw's allowed responsibilities — but §8.2's candidate lifecycle permits `review_pending → approved/rejected/deferred/invalidated` and offers no edge back to `research_pending`. The action as written cannot be a state transition.
- **Why it matters:** the plausible-looking fix is to add the missing edge, which would be improvising the architecture — and it would also let a candidate leave review while a reviewer believed it was still there. The likely correct shape is the `ADR-020` pattern: queue another evidence pass while the candidate stays `review_pending`, so the lifecycle owner brackets a step it does not perform. That is a decision to make deliberately, with the alternative recorded.
- **Objective:** Decide what requesting more research *is*, record it as an ADR, and implement it.
- **Scope (in):** The decision and its ADR; whatever the decision implies — most likely enqueuing a research job against a candidate that stays in `review_pending`, and surfacing that a pass is running; the reviewer's reason for asking, since §10.6 already structures every other decision.
- **Scope (out):** Adding a lifecycle edge without an ADR that argues for it.
- **Acceptance criteria:**
  1. An ADR records the decision and what was rejected.
  2. Requesting more research produces evidence the reviewer can see, without the candidate silently leaving review; test-proven.
  3. Two requests do not queue two overlapping passes for the same candidate; test-proven.
- **Verification:** `uv run pytest -q tests/test_corrections.py tests/test_pipeline_jobs.py`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and where it is proven.
  1. *An ADR records the decision and what was rejected* — [ADR-022](adr/ADR-022-requesting-more-research-adds-evidence-without-moving-the-candidate.md), indexed in `docs/adr/README.md`. **Decision:** requesting more research captures additional evidence for a candidate that stays in `review_pending`; it is not a transition. **Rejected:** adding a `review_pending → research_pending` edge (it edits inherited specification, takes the candidate out of the reviewer's queue while they believe they are still looking at it, and needs a second invented edge to come back); re-using `research.capture_evidence` (its chained `campaigns.complete_research` would attempt an invalid transition and dead-letter); recording no reason.
  2. *Evidence appears without the candidate silently leaving review* — in `tests/test_pipeline_jobs.py`: `test_a_re_research_pass_leaves_the_candidate_in_review`, `test_a_re_research_pass_queues_nothing_after_itself` (the whole difference from `handle_capture`), `test_a_re_research_pass_stores_evidence`, and `test_a_re_research_pass_is_skipped_once_the_candidate_left_review` — moot, not broken, so it returns rather than dead-lettering. `test_capture_evidence_still_refuses_review_pending_by_default` pins that serving the second situation did not loosen the first.
  3. *Two requests do not queue two overlapping passes* — in `tests/test_corrections.py`: `test_a_second_request_while_one_is_in_flight_is_refused`, `test_a_leased_pass_still_counts_as_in_flight` (`leased` is precisely the state a job is in while a reviewer waits and clicks again), `test_a_finished_pass_does_not_block_a_new_request` (one at a time, not one ever), and `test_another_candidates_pass_does_not_block_this_one` — without the payload filter the check would serialize the whole review queue behind whoever asked first.
  Also proven: the request records who asked and why (§10.6), `REQUEST_RESEARCH` exists in the **migrated** `decisionkind` enum, a request carries no waypoint (the `6fee8153160a` constraint predates the kind), requesting outside review is refused, a refused request queues nothing, and no policy is rewritten.
  **Two invariants caught this, and both were right.** `test_only_the_owning_package_names_a_lifecycle` refused `campaigns` naming `JobState` — so the in-flight query moved to `jobs_and_outbox.queue.in_flight_for`, which is where "is this job still coming" belongs anyway. And `research_and_evidence.jobs.register()` had an early return on its first job type, so adding a second would have registered **nothing** in any process that already had the first — `T-148` in miniature; it now guards each type separately.
  **The migration is hand-written** because Alembic does not autogenerate a new enum *value*: autogenerate produced an empty migration, which would have left the model able to write a value the column could not store. Its downgrade recreates the type — PostgreSQL has no `ALTER TYPE ... DROP VALUE` — and drops and restores the two check constraints around the swap, without which the rename fails with `operator does not exist: decisionkind <> decisionkind_old`.
  **Observed:** `uv run pytest -q tests/test_corrections.py tests/test_pipeline_jobs.py` → 148 passed; full backend suite 1971 passed; `ruff check .`, `ruff format --check .` (191 files), `mypy app` (105 files), `alembic check` clean; `alembic downgrade -1` then `upgrade head` round-trips with the enum back to `{REJECT, DEFER}` and all three check constraints intact. Nine negative controls each failed the right tests with a green restore: the pass transitioning the candidate (1 failed), the pass chaining a follow-on job (1), the capture default widened instead of parameterised (1), the capture handler's own guard removed (1), the in-flight check removed (2), counting only queued jobs (1), ignoring which candidate (1), and the migration not adding the enum value (1). **One control passed on its first attempt and was wrong, not the test** — it targeted `capture_evidence`'s default set, but the test it ran drove `handle_capture`, whose own guard returns first; a direct test of `capture_evidence` was added and the control then failed correctly. No external effect: the pass reads a local fixture document and stores a snapshot.
  **Not in scope, and not done:** the card's Request-more-research button. `T-155` owns it.


#### T-067 — Message approval transaction (dashboard → outbox, fake adapter only)
- **Stage / Priority:** 2 / P0 · **Status:** `DONE` (2026-07-31 — `T-067a` and `T-067b` are both `DONE`) · **Depends on:** T-066, T-021, T-034, T-035 · **Spec:** §11.3 steps 1–6, §11.4, §3.5
- **Objective:** The §11.3 six-step approval transaction, ending in one atomic write of approval plus immutable send command plus outbox event, dispatched only to the fake adapter.
- **Acceptance:** identity, role, session, CSRF, record version, and scope are all verified before approval; approval and send command commit in one transaction or not at all; with shadow mode ON no effect occurs beyond the fake; no agent callback exists anywhere in the path (test-proven).
- **Verification:** `uv run pytest -q tests/test_approval_transaction.py` · **Files:** `backend/app/drafts_and_approvals/approve*` · **Q:** `Q-005`; real sending stays behind **G-07**/**G-08**.

- **Status note (2026-07-31):** **Split into `T-067a` and `T-067b`**, on the layer boundary `T-065`, `T-151`, `T-066b`, and `T-154` all used. §11.3's six steps divide cleanly: step 1 is *"verify user identity, role, session, CSRF protection, record versions, and approval scope"*, which is entirely about the request — and steps 2–6 are the transaction, which is about the database and holds every safety property worth its own change set. Bundling them would put the atomic write and the shadow-mode guarantee in the same review as an HTTP handler. Criteria map: "identity, role, session, CSRF, record version, and scope verified before approval" → `T-067b`; "approval and send command commit in one transaction or not at all", "with shadow mode ON no effect occurs beyond the fake", and "no agent callback exists anywhere in the path" → `T-067a`.

#### T-067a — The message approval transaction (steps 2–6)
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-021, T-034, T-035, T-055
- **Spec:** §11.3 steps 2–6, §11.4, §3.5, §7.2
- **Objective:** One function that turns a reviewed revision into an approval, an immutable send command, and an outbox event — atomically, or not at all.
- **Scope (in):** Confirming the exact recipient and immutable `message_revision_id` (step 2); the step 3 recheck of campaign, product status, approved claims, suppression, sender, and limits; the single transaction creating the approval and the send command (step 4); the outbox event (step 5); the §11.4 field set carried on the command; refusal that leaves nothing behind.
- **Scope (out):** The endpoint and its step 1 verification (`T-067b`); dispatch itself, which `T-035` owns and the worker performs (step 6); real sending, behind **G-07**/**G-08**.
- **Acceptance criteria:**
  1. The approval, the send command, and the outbox event are written in one transaction — a failure at any point leaves none of them; test-proven by forcing a failure after the approval.
  2. The step 3 recheck refuses a revision whose campaign, product status, claims, suppression, or recipient verification has changed since review; test-proven for each.
  3. With shadow mode ON no external effect occurs beyond the fake adapter, and the outbox event is still written; test-proven.
  4. No agent callback exists anywhere in the path — no model gateway call, no OpenClaw reference; test-proven structurally, not by inspection.
- **Verification:** `uv run pytest -q tests/test_approval_transaction.py`
- **Files:** `backend/app/drafts_and_approvals/approve_message.py`, `backend/tests/test_approval_transaction.py`
- **Blocker / Q:** `Q-005` names who may approve; this builds the mechanism, not the authority. Real sending stays behind **G-07**/**G-08**.
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_approval_transaction.py` (20 tests).
  1. *One transaction or none of it* — `test_a_failure_after_the_approval_leaves_nothing` writes all three rows inside a savepoint, asserts `(1, 1, 1)`, rolls back, and asserts `(0, 0, 0)`: the atomicity claim proven by breaking it rather than by reading the code. `test_an_approval_writes_all_three_rows`, `test_the_outbox_event_carries_the_commands_idempotency_key`, `test_a_refusal_writes_nothing_at_all`, and `test_the_thread_is_created_once_per_candidate`.
  2. *The step 3 recheck* — one test per thing that can change between reading the card and approving it: `test_a_superseded_revision_cannot_be_approved`, `test_a_suppressed_recipient_is_refused`, `test_an_unverified_recipient_is_refused`, `test_a_recipient_the_revision_was_not_written_to_is_refused` (ADR-008 approves a recipient and a revision *together*), and `test_a_paused_campaign_is_refused`. `test_the_recheck_runs_at_approval_time_not_review_time` states the property once.
  3. *Shadow mode* — `test_shadow_mode_leaves_this_path_unchanged` asserts no `SendAttempt` exists, which is what an external effect would leave behind; `test_the_outbox_event_is_written_under_shadow_mode` (suppressing the record would lose the audit trail for a decision a human really made); `test_the_thread_never_leaves_not_started_here` — ordering is not sending.
  4. *No agent callback* — `test_no_module_in_the_approval_decision_imports_the_model_gateway` over the five modules that make and record the decision, `test_the_approval_path_names_no_agent_runtime` over the transitive walk for `openclaw`/`nemoclaw`/`agent_callback`, plus two guards on the guard: `test_the_walk_would_catch_an_agent_import` (the walk traverses at all) and `test_a_module_that_imports_the_gateway_is_detected` (the detector fires on a module that genuinely reaches the gateway). **This criterion is met more narrowly than the wording suggests, and the test says so:** a transitive walk from the approval path *does* reach `model_gateway`, through `validation → drafting`, and `T-156` is filed to remove that edge.
  **Three findings, all from tests rather than from reading.** (a) The transaction never moved the revision to `approved` — an `Approval` row would have read `approved` while the revision it named still read `review_pending`, and a second approval failed on `uq_approval_live_per_revision` as an integrity error instead of a refusal. (b) A control proved my recipient-verification check was **unreachable** — `T-055`'s `recipient_contactable` already refuses it — so the duplicate was deleted rather than left as a rule that can disagree with itself. (c) `apply_validation` was the wrong recheck: it *moves* the revision, and from `review_pending` the failing edge does not exist, so a safety check would have crashed instead of refusing; `validate_revision` is the read-only form.
  **Two invariants moved this code, both correctly.** `test_no_import_cycles` refused `drafts_and_approvals` importing `outreach_and_replies`, so the transaction lives in `outreach_and_replies` — which is right anyway, since what it produces is a send order and the approval is its authorization. Then `test_only_the_owning_package_names_a_lifecycle` refused it naming `MessageRevisionState`, so `require_approvable` and `mark_approved` went to `drafts_and_approvals.revisions`, where the revision lifecycle lives (ADR-015).
  **Observed:** `uv run pytest -q tests/test_approval_transaction.py` → 20 passed; full backend suite 1991 passed; `ruff check .`, `ruff format --check .` (193 files), `mypy app` (106 files), `alembic check` all clean. Frontend untouched, 121 tests passing. Ten negative controls each failed the right tests with a green restore: the outbox event not written (10 failed), the send command row never added (3), the recheck skipped (4), the campaign-paused check removed (1), the recipient/revision pairing unchecked (1), the approvable-state guard removed (3), `mark_approved` not transitioning (1), and the revision left in `review_pending` (10). **Three controls did not bite on their first attempt** — one mutated nothing semantically, one produced a collection error, and one exposed the unreachable check above; all three were rewritten and re-run. No migration was added; no external effect occurred, and dispatch remains the worker's (step 6) behind **G-07**/**G-08**.

#### T-067b — The message approval endpoint (step 1)
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-067a, T-063a
- **Spec:** §11.3 step 1, §12.2, §15.1
- **Objective:** The transaction reachable from the dashboard, with every step 1 check in front of it.
- **Scope (in):** `POST /api/review/revisions/{revision_id}/approve` under `APPROVE_MESSAGE`; identity, role, and session from `T-063a`'s dependency; the record version checked; the approval scope — that this revision belongs to a candidate the approver may act on; cookie authentication refused, which is the CSRF answer until `T-070`.
- **Scope (out):** Everything `T-067a` owns; the card's action, which needs the message-approval flow designed on top of candidate approval.
- **Acceptance criteria:**
  1. Identity, role, session, and record version are each verified before any write; test-proven one at a time.
  2. Cookie-only authentication is refused, and the refusal is recorded as the CSRF measure `T-070` will replace; test-proven.
  3. A revision outside the approver's scope is refused with nothing written; test-proven.
- **Verification:** `uv run pytest -q tests/test_approval_transaction.py tests/test_authz.py`
- **Blocker / Q:** `Q-005`.
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_approval_transaction.py` (38 tests total, 18 new here).
  1. *Identity, role, session, record version — each on its own* — §11.3 step 1 lists six things and a test exercising them together would pass with five missing, so: `test_no_session_is_refused` (identity), `test_a_role_without_the_permission_is_refused` (role, `403` naming `approve_message`), `test_a_revoked_session_is_refused` (session — a token that *was* valid is not one that *is*, and the dependency resolves against the row), and `test_a_stale_record_version_is_refused` plus `test_the_current_record_version_is_accepted` — the second because without it the first would pass against a version nobody could ever satisfy. `test_the_approver_comes_from_the_session` and `test_an_extra_field_is_refused` hold §12.2's attribution.
  2. *Cookie authentication refused* — `test_a_cookie_cannot_authenticate_an_approval`, with `counts() == (0, 0, 0)` after it. This is the CSRF measure `T-070` replaces, and this is the single action where it matters most (§3.5). `test_the_route_is_declared_at_tier_four_under_its_own_permission` pins the §12.1 distinction structurally: approving a *candidate* for outreach and approving *the exact words* are different authorities, so different tier-4 permissions, even though one role holds both today.
  3. *Out-of-scope revisions refused with nothing written* — `test_a_revision_whose_candidate_was_already_decided_is_refused` parametrized over `rejected`, `deferred`, and `invalidated` rather than one of them; `test_a_recipient_belonging_to_another_contact_is_refused`; `test_an_unknown_recipient_is_refused`; `test_an_unknown_revision_is_404`; `test_a_second_approval_is_refused`. Every one asserts the three-row count either side, so "refused" means "wrote nothing" rather than "returned an error".
  **The import graph moved this code, for the second time in two cycles.** `T-067a`'s transaction had to live in `outreach_and_replies`; this endpoint calls it, and putting the handler in `drafts_and_approvals.api` with the rest of the review API re-created the cycle immediately. It is a router of its own in `outreach_and_replies`, sharing the `/api/review` prefix — the path is about where a reviewer acts, not about which package owns the code. Then `test_only_the_owning_package_names_a_lifecycle` refused the response model naming `MessageRevisionState`, so `revision_state` is typed as the string JSON carries anyway.
  **Observed:** `uv run pytest -q tests/test_approval_transaction.py` → 38 passed; with `tests/test_authz.py` → 78 passed; full backend suite 2009 passed; `ruff check .`, `ruff format --check .` (194 files), `mypy app` (107 files), `alembic check` all clean. Frontend `lint` clean and 121 tests passing after regenerating the client types. Seven negative controls each failed the right tests with a green restore: the record version unchecked (1 failed), the route under a read permission (1), the approver taken from the request (1), cookie authentication accepted (1), the route declared under `APPROVE_CANDIDATE` (1), the approval-scope check removed (3), and an unknown recipient passed through (1). One control errored on a missing import first and was re-run properly. No migration; **no external effect** — the endpoint records an approval and a send command, and dispatch stays the worker's behind **G-07**/**G-08**.


#### T-068 — Approval expiry, revocation, and invalidation surfacing
- **Stage / Priority:** 2 / P1 · **Status:** `SPLIT` (2026-07-31) · **Depends on:** T-067, T-056 · **Spec:** §7.5, §8.4, §17.6
- **Objective:** Show stale approvals, invalidated drafts, and expired claims in the dashboard and allow revocation.
- **Acceptance:** an invalidated item appears with the triggering version; revocation requires the correct role and writes an audit event; a revoked approval can never dispatch (test-proven).
- **Verification:** `uv run pytest -q tests/test_approval_lifecycle_ui.py` · **Files:** `backend/app/drafts_and_approvals/*`, `frontend/app/review/*` · **Q:** none

- **Status note (2026-07-31):** **Split into `T-068a` and `T-068b`**, on the layer boundary every Stage 2 task has used. Preflight also sharpened what the backend half owes: `invalidation_reason` already checks every §8.4 trigger, but it answers in **prose with no identifier** — "approved claim set has been superseded" does not say *which* set superseded it, and this task's first acceptance criterion is that an invalidated item appears **with the triggering version**. That is the gap, and it is a backend one. Criteria map: the structured reason carrying its triggering version, the revocation endpoint and its audit event, and the never-dispatch proof → `T-068a`; showing them on the card → `T-068b`.

#### T-068a — Structured invalidation reasons, revocation, and the never-dispatch proof
- **Stage / Priority:** 2 / P1
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-067, T-056, T-021
- **Spec:** §7.5, §8.4, §17.6, §11.4
- **Objective:** Why an approval no longer authorizes a send, answered with the identifier that made it so — plus revocation, and proof that neither state can dispatch.
- **Scope (in):** A structured invalidation detail carrying the §8.4 trigger *and* the version or record id behind it; `invalidation_reason` kept as its prose form so no caller changes; an endpoint listing approvals needing attention; `POST /api/review/approvals/{approval_id}/revoke` under `APPROVE_MESSAGE`, writing an audit event; a test that a revoked or invalidated approval cannot pass the dispatch precondition.
- **Scope (out):** The dashboard (`T-068b`); changing *which* triggers §8.4 lists; expiring approvals on a schedule, which is a worker concern.
- **Acceptance criteria:**
  1. Every §8.4 trigger yields a structured reason naming the triggering version or record id, not prose alone; test-proven one trigger at a time.
  2. Revocation requires `APPROVE_MESSAGE`, refuses cookie-only authentication, and writes an audit event naming the actor; test-proven.
  3. A revoked approval can never dispatch, and neither can an invalidated one; test-proven at the dispatch precondition rather than at the caller.
  4. The attention list returns exactly the approvals that no longer authorize a send, and omits the ones that still do; test-proven in both directions.
- **Verification:** `uv run pytest -q tests/test_approval_lifecycle.py tests/test_authz.py`
- **Files:** `backend/app/drafts_and_approvals/approval.py`, `backend/app/drafts_and_approvals/api.py`, `backend/tests/test_approval_lifecycle.py`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_approval_lifecycle.py` (31 tests).
  1. *Every trigger names the record that caused it* — `Invalidation` carries the §8.4 trigger and the `triggering_id` behind it, one test each: `test_a_revoked_approval_reports_its_state`, `test_an_expired_approval_reports_when`, `test_a_retired_revision_names_the_revision`, `test_a_superseded_product_status_names_the_version`, `test_a_superseded_claim_set_names_the_set`. `test_a_live_approval_has_no_invalidation` is the baseline without which all of them could pass against a function that always reported a problem, and `test_the_prose_form_still_answers_for_every_trigger` holds `invalidation_reason` to being *derived* rather than a second implementation.
  **Two triggers have no positive case, and that is recorded rather than hidden:** `content_changed` and `recipient_changed` are unreachable because `T-020` revision-content trigger and `approval_pins_immutable` both refuse the mutation that would cause them. `test_the_approved_content_hash_cannot_be_repointed` and `test_the_approved_recipient_cannot_be_repointed` assert that refusal, so a reader sees why those checks have no happy path instead of concluding they went untested.
  2. *Revocation, its authority, and its audit event* — `test_revoking_moves_the_approval`, `test_revoking_writes_an_audit_event_naming_the_actor`, `test_a_role_without_the_permission_cannot_revoke` (the same permission that granted it: a role able to withdraw but not grant could stop any outreach it disliked), `test_a_cookie_cannot_authenticate_a_revocation`, `test_a_reason_is_required`, `test_a_blank_reason_is_refused`, `test_a_stale_record_version_is_refused`, `test_revoking_twice_is_refused`, `test_an_unknown_approval_is_404`.
  3. *Neither a revoked nor an invalidated approval can dispatch* — asserted at `require_valid`, which is what the dispatch transaction calls, not at a caller that might forget to ask: `test_a_revoked_approval_cannot_dispatch`, `test_an_invalidated_approval_cannot_dispatch`, `test_an_expired_approval_cannot_dispatch`, and `test_a_live_approval_still_dispatches` — the last because a `require_valid` that refused everything would satisfy the other three and stop every send. `test_a_revoked_approval_still_cannot_dispatch` closes it end to end through the endpoint.
  4. *The attention list, both directions* — `test_a_live_approval_needs_no_attention`, `test_an_invalidated_approval_appears_with_its_trigger`, `test_a_revoked_approval_is_not_an_attention_item` (somebody dealt with it; listing handled approvals buries the ones nobody has looked at), `test_an_expired_approval_is_an_attention_item` — the case a state filter alone would miss — and the endpoint own three.
  **A real gap found and filed, not fixed here:** `approve_message` pins neither the product status version nor the claim set, so §11.4 field list is incomplete and two §8.4 triggers cannot fire in production at all. This task tests reach them by building approvals through `request_approval` with pins supplied. That is `T-157`.
  **Observed:** `uv run pytest -q tests/test_approval_lifecycle.py` → 31 passed; with `tests/test_authz.py` → 71 passed; the existing `tests/test_approval.py tests/test_invalidation.py tests/test_dispatch.py` → 126 passed with no test edited; full backend suite 2050 passed; `ruff check .`, `ruff format --check .` (196 files), `mypy app` (108 files), `alembic check` all clean; frontend `lint` clean and 127 tests passing. Eight negative controls each failed the right tests with a green restore. No migration; no external effect.

#### T-068b — Surfacing stale approvals and invalidated drafts on the card
- **Stage / Priority:** 2 / P1
- **Status:** `READY` (2026-07-31 — corrected by checkpoint audit: both dependencies were `DONE` but the `T-068a` cycle never promoted this, while the header claimed it ready)
- **Depends on:** T-068a, T-065b
- **Spec:** §7.5, §12.3
- **Objective:** A reviewer sees that an approval went stale, why, and can revoke it.
- **Scope (in):** The attention list rendered; the triggering version shown, not just the category of failure; a Revoke action wired to `T-068a`.
- **Scope (out):** Everything `T-068a` owns.
- **Acceptance criteria:**
  1. An invalidated approval appears with its triggering version; test-proven.
  2. Revoking from the card removes it from the attention list; test-proven.
  3. An approval that still authorizes a send is not shown as needing attention; test-proven.
- **Verification:** `npm run test` from `frontend/`
- **Blocker / Q:** none


#### T-157 — The approval transaction pins no version, so two §8.4 triggers can never fire
- **Stage / Priority:** 2 / P1
- **Status:** `READY` (2026-07-31)
- **Depends on:** T-067a
- **Spec:** §11.4, §8.4
- **Found by:** `T-068a`, building the invalidation tests. `approve_message` calls `request_approval` without `product_status_version_id` or `approved_claim_set_id`, so every approval it creates pins **neither** — and `create_send_command` copies both from the approval, so the send command carries nulls too.
- **Why it matters:** §11.4 lists `product_status_version` and `approved_claim_set_version` among the fields every consequential action contains, and §8.4 makes a changed product status or claim version invalidate an approval. With nothing pinned, `invalidation_detail` skips both checks — the approval stays valid through exactly the changes §8.4 says must invalidate it, and the dispatch recheck reads the same nulls. `T-068a`'s tests reach these triggers by building approvals through `request_approval` with the pins supplied, which is why they pass while the production path would not produce such an approval at all.
- **Objective:** An approval created by the §11.3 transaction pins the product status and claim set it was granted against.
- **Scope (in):** Resolving the effective product status version and the campaign current approved claim set at approval time; passing both to `request_approval`; the send command carrying them; a test that an approval created through the endpoint has both pins non-null, and that superseding either then invalidates it.
- **Scope (out):** Changing what `invalidation_detail` checks — it is already correct; changing how claim sets are versioned (`T-056`).
- **Acceptance criteria:**
  1. An approval created through `POST /api/review/revisions/{revision_id}/approve` has both pins set; test-proven.
  2. Superseding the pinned claim set invalidates that approval, end to end from the endpoint; test-proven.
  3. The send command carries both versions, satisfying §11.4 field list; test-proven.
- **Verification:** `uv run pytest -q tests/test_approval_transaction.py tests/test_approval_lifecycle.py`
- **Blocker / Q:** none


#### T-158 — The entire implementation is uncommitted working-tree state
- **Stage / Priority:** 2 / P1
- **Status:** `BLOCKED` (2026-07-31)
- **Depends on:** none
- **Spec:** process.md §9 (git policy)
- **Found by:** checkpoint audit 2026-07-31 ([report](docs/checkpoints/2026-07-31_stage2_checkpoint.md), finding M1). 118 paths — 31 modified, 87 untracked — sit on `main` with no commit since `62514a4904cc`. Effectively all Stage 1 and Stage 2 work exists only in the working tree.
- **Why it matters:** a crash, a bad script, or one accidental `git checkout --` loses the work with no recovery; there is no reviewable history; and audits have no stable baseline commit. The loop cannot fix this itself: process.md §9 forbids commit/push without explicit user authorization in the current session.
- **Objective:** The user decides a commit policy; the work is then committed under it.
- **Scope (in):** Obtaining the user's authorization; if granted, checkpoint commits per process.md §9 (one scoped commit per completed task where separable, or a documented baseline commit), on a branch if the user prefers.
- **Scope (out):** Push, PR, or any remote write unless separately authorized; rewriting history.
- **Acceptance criteria:**
  1. The user has explicitly authorized (or declined) a commit policy, recorded here.
  2. If authorized: `git status` shows a clean tree or only deliberate exclusions, and the ledger records the baseline commit hash.
- **Verification:** `git status --short` and `git log --oneline`
- **Blocker / Q:** user authorization required by process.md §9 — no `Q-###` exists for repository governance; this blocks on a direct user decision.


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


#### T-151 — The dashboard sign-in screen
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31 — `T-151a` and `T-151b` are both `DONE`); split, see the note below
- **Depends on:** T-061a, T-062
- **Spec:** §12.2, §12.3, §17.5
- **Found by:** `T-065b`. Nothing puts a session token in the browser. `T-061a` explicitly deferred "the frontend sign-in screen" to "`T-063`" — but `T-063` then split into `T-063a` and `T-063b`, both API tasks, and the screen was left unowned by either. The gap only became visible when `T-065b` needed a bearer token to send.
- **Why it matters:** every authenticated route in the dashboard is currently unreachable from a real browser. `T-064`'s review page sends no credentials at all and would take a 401; `T-065b`'s form detects the missing token and refuses to submit, which is honest but not usable. Stage 2's exit gate **G-10** is a non-engineer completing reviews — which is not possible if nobody can sign in.
- **Objective:** A reviewer signs in and the dashboard holds a session token that `lib/api.ts` sends.
- **Scope (in):** A sign-in route calling `T-061a`'s stub sign-in (`local` only, which is where Stage 2 runs); storing the token where `lib/session.ts` reads it; the review pages sending it on reads as well as writes; a signed-out state that says so rather than rendering an error page.
- **Scope (out):** The managed OIDC flow (`T-061b`, `BLOCKED` on `Q-026`) — this wires the stub only, and must be as unusable outside `local` as the stub it calls; CSRF (`T-070`).
- **Acceptance criteria:**
  1. Signing in locally produces a session the review page uses; test-proven.
  2. The dashboard refuses to attempt sign-in when the backend is not `local`, matching `T-061a`'s own refusal; test-proven.
  3. A signed-out reviewer sees a sign-in prompt, not a 401 or a blank card; test-proven.
- **Verification:** `npm run test` from `frontend/`
- **Files:** `frontend/app/sign-in/*`, `frontend/lib/session.ts`, `frontend/lib/api.ts`
- **Blocker / Q:** none — the stub is `T-061a`'s and already exists. `Q-026` blocks only `T-061b`.
- **Status note (2026-07-31):** **Split into `T-151a` and `T-151b`.** Preflight found the reason: `stub_sign_in` is a Python function with **no HTTP endpoint at all**, so this task is not "a screen" — it is a session API plus a screen. The API half carries a safety question the screen does not: it is the repository's first **public, unauthenticated endpoint that mints a session**, and `PUBLIC` in `ROUTE_PERMISSIONS` means exactly "no session required to call this". That has to be locked to `local` at the route as well as inside the stub, and it deserves its own change set and its own negative controls rather than being reviewed alongside React. Criteria map: criterion 2 (refused outside `local`) → `T-151a`, where the refusal is actually enforced; criteria 1 and 3 (a reviewer signs in; a signed-out reviewer sees a prompt) → `T-151b`.

#### T-151a — The session API: sign in, sign out, and who am I
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-061a, T-062, T-063a
- **Spec:** §12.2, §15.1, §17.5
- **Objective:** HTTP endpoints for the session lifecycle, with the stub's `local`-only refusal enforced at the route.
- **Scope (in):** `POST /api/auth/stub-sign-in` (`PUBLIC`, refused outside `local` before any lookup), `DELETE /api/auth/session` (revokes the caller's own session), `GET /api/auth/session` (the current principal, or `401`); all three declared in `ROUTE_PERMISSIONS`; the token returned in the body and never logged; `frontend/openapi.json` re-exported and the client types regenerated.
- **Scope (out):** The sign-in screen and anything React (`T-151b`); the managed OIDC flow (`T-061b`, `BLOCKED` on `Q-026`); CSRF (`T-070`); cookies — the dashboard holds a bearer token, which is what `T-065a` requires on mutations.
- **Acceptance criteria:**
  1. Signing in locally returns a usable session token that authenticates a subsequent request; test-proven end to end through the API.
  2. The endpoint is refused outside `local` — with the environment set to anything else it answers an error and issues no session; test-proven, and proven at the route rather than only inside `stub_sign_in`.
  3. An unknown email is refused and creates nobody; test-proven that the user table is unchanged.
  4. Signing out makes the token stop working, and the token appears in no log line; test-proven.
- **Verification:** `uv run pytest -q tests/test_session_api.py tests/test_authz.py`
- **Files:** `backend/app/identity/api.py`, `backend/app/main.py`, `backend/app/identity/rbac.py`, `backend/tests/test_session_api.py`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `backend/tests/test_session_api.py` (21 tests).
  1. *A usable token* — `test_signing_in_returns_a_token_that_authenticates` and `test_the_token_authenticates_a_protected_route`, which calls `/api/review/candidates` with it: a token that only worked on the auth resource would authenticate nothing a reviewer came for. `test_reading_the_session_never_re_issues_the_token` keeps a read from making a stolen session self-renewing.
  2. *Refused outside `local`* — `test_the_endpoint_is_refused_outside_local` parametrized over `test`, `staging`, and `production` rather than one of them, since `ALLOWED_ENVIRONMENTS` is an allow-list and a `production`-only test would pass while `staging` minted sessions. It asserts the session count is unchanged, and `test_the_refusal_does_not_reveal_whether_the_email_exists` asserts a known and an unknown address are byte-identical responses — otherwise the endpoint is a user-enumeration oracle in exactly the environments where it is refused.
  3. *Creates nobody* — `test_an_unknown_email_creates_nobody` compares the user count either side; `test_an_unknown_email_is_refused`, `test_a_deactivated_user_gets_no_usable_session` (`403`, because the row is kept for attribution and must not be a row that can sign in), and `test_an_extra_field_is_refused` (a request carrying `role` fails loudly rather than being silently ignored).
  4. *Sign-out, and no token in a log* — `test_signing_out_stops_the_token_working`, `test_signing_out_revokes_rather_than_deletes` (§17.5 wants the history), `test_signing_out_revokes_only_the_callers_own_session` (two sessions are two devices), `test_signing_out_without_a_session_is_not_an_error`, and `test_the_token_appears_in_no_log_line`, which searches everything the request logged rather than one line and then asserts something *was* logged so it cannot pass against silence.
  Also proven: `test_no_cookie_is_set` — issuing one would recreate the CSRF exposure `T-065a` removed.
  **Observed:** `uv run pytest -q tests/test_session_api.py` → 21 passed; with `tests/test_authz.py tests/test_fixtures.py` → 79 passed; full backend suite 1874 passed; `ruff check .`, `ruff format --check .`, `mypy app` (103 files), `alembic check` all clean; frontend `lint`, `typecheck`, and 62 tests clean after regenerating the client types. Six negative controls each failed the right tests with a green restore after every one: the issued token replaced (2 failed), the route's `local` refusal removed (4 failed), an unknown email auto-provisioned (1 failed), sign-out not revoking (3 failed), the token logged beside the actor (1 failed), and the route left undeclared in `ROUTE_PERMISSIONS` (`test_authz.py` failed — the coverage guard doing its job). No migration was added; no external effect occurred.

#### T-151b — The sign-in screen and the signed-out state
- **Stage / Priority:** 2 / P0
- **Status:** `DONE` (2026-07-31)
- **Depends on:** T-151a, T-064
- **Spec:** §12.2, §12.3
- **Objective:** A reviewer signs in, and every dashboard page behaves sensibly when nobody is.
- **Scope (in):** A sign-in route calling `T-151a`'s endpoint; storing the token where `lib/session.ts` reads it; `lib/api.ts` sending it on reads as well as writes; a signed-out state that prompts rather than erroring.
- **Scope (out):** Everything `T-151a` owns.
- **Acceptance criteria:**
  1. Signing in produces a session the review page uses; test-proven.
  2. A signed-out reviewer sees a sign-in prompt, not a 401 or a blank card; test-proven.
  3. A rejected sign-in shows the reason the backend gave, not a generic failure; test-proven.
- **Verification:** `npm run test` from `frontend/`
- **Blocker / Q:** none
- **Completion evidence (2026-07-31):** Each criterion, and the test that proves it, in `frontend/tests/sign-in.test.tsx` (20 tests).
  1. *A session the review page uses* — `takes the review page from signed out to showing the candidate` is the criterion end to end: no token, sign in on the page itself, card appears without a reload. Plus `stores the token the backend issued`, `sends the token as a bearer when reading a candidate`, and `sends the email and nothing resembling a password` (§12.2 — the form has no password field, asserted rather than assumed).
  2. *A prompt, not a 401 or a blank card* — `prompts on the review page instead of fetching` (and asserts no request was made), `prompts on the sign-in page`, `shows the prompt again when the backend rejects a stored token`, `forgets a token the backend has stopped honouring`, and `does not offer the form for a 403, which signing in again cannot fix` — a missing role is not a missing session, and offering sign-in there is a loop that can never succeed.
  3. *The backend's own reason* — `shows the refusal for a backend where the stub is not allowed` (the `503` is the one worth reading: it means the dashboard is pointed somewhere this cannot work), `shows the refusal for an unknown user`, `stores no token when the sign-in was refused`, `says the backend was unreachable rather than blaming the reviewer`, and `lets the reviewer try again after a refusal`.
  Also proven: `revokes server-side before forgetting the token` and `keeps the token when signing out could not reach the backend` — clearing first would leave a live session nobody holds, usable by anyone who copied the token and invisible to the person who thought they had signed out.
  **Design note:** the review page changed from a server component to a client one. That was forced, not preferred — the token lives in `sessionStorage`, which a server render cannot see, and the alternative of putting it in a cookie is exactly the exposure `T-065a` removed. The token is read through `useSyncExternalStore` (`lib/useSessionToken.ts`) so signing in updates every component without prop threading and no component keeps a stale copy after a `401`.
  **Observed:** `npx vitest run tests/sign-in.test.tsx` → 20 passed; full frontend suite → 82 passed across 5 files; `npm run lint`, `npm run typecheck`, and `npm run build` clean, with `/sign-in` static and `/review/[candidateId]` dynamic. Backend untouched and re-confirmed: `pytest -q` → 1874 passed, `ruff check .` and `mypy app` (103 files) clean. Seven negative controls each failed the right tests with a green restore after every one: the token never stored (2 failed), the page fetching while signed out (1), a `401` leaving the stale token (2), a `403` offering the form (1), a generic refusal message (3), sign-out forgetting before revoking (1), and reads dropping the `Authorization` header (1). No migration; no external effect.

#### T-152 — Seven high-severity advisories in the frontend dependency tree
- **Stage / Priority:** 2 / P2
- **Status:** `READY` (2026-07-31)
- **Depends on:** T-060a
- **Spec:** §15.6, §19.4
- **Found by:** `T-065b`, while adding two dev dependencies. `npm audit` reports `{"high": 7, "critical": 0}` against `@redocly/openapi-core`, `brace-expansion`, `minimatch`, `next`, `openapi-typescript`, `postcss`, and `sharp`. **None come from the two packages that cycle added** (`jsdom`, `@testing-library/react`); all seven predate it and arrived with `T-060a`'s scaffold.
- **Why it matters, and why it is P2 rather than P0:** the dashboard is not deployed and reaches only a local backend (`assertLocal`), so no advisory here is currently exploitable by anyone who is not already on this machine. That changes the day there is a deployed environment, and §19.4 puts the check before deployment rather than after.
- **Objective:** Each advisory resolved or recorded as accepted with the reason.
- **Scope (in):** `npm audit fix` where it is non-breaking; a deliberate upgrade where it is not; for anything unfixable, a written note saying which advisory, why it cannot be fixed, and what it would take.
- **Scope (out):** `npm audit fix --force`, which resolves advisories by installing breaking major versions and would silently undo `ADR-021`'s pinned toolchain decisions.
- **Acceptance criteria:**
  1. `npm audit --audit-level=high` is clean, or every remaining advisory is listed with its reason for being accepted.
  2. `npm run lint`, `typecheck`, `test`, and `build` all still pass afterwards.
- **Verification:** `npm audit --audit-level=high` and the four scripts, from `frontend/`
- **Files:** `frontend/package.json`, `frontend/package-lock.json`
- **Blocker / Q:** none
- **Checkpoint note (2026-07-31):** Audit re-measured `npm audit`: `{high: 3, critical: 0}` — down from the 7 recorded above; the dependency tree drifted with later installs. The local-only exposure reasoning stands. Re-measure before acting rather than trusting either count.

---

## 5. Stage gates and prohibited starts

Every gate below is **LOCKED** unless marked **OPEN** in the table (G-01 and G-02 are open). A task
behind a locked gate must be `PLANNED` or `BLOCKED`, never `READY`. Only the user may unlock a gate, and only by recording the required evidence in the repository.

| Gate | Unlocks | Required before unlocking | State |
|---|---|---|---|
| **G-01** | Stage 1 engineering | v0.3 specification approved for buildout (spec header) and vendored into the repo (`T-001`). Written stakeholder acceptance record (`T-009`) is still outstanding and is tracked, not assumed. | **OPEN** (document-satisfied) |
| **G-02** | Stage 2 dashboard work (`T-060`…`T-071`) | `T-058` passes: full import→review-ready-draft slice on synthetic fixtures, zero external writes, evidence recorded in [docs/stage1-exit-evidence.md](stage1-exit-evidence.md). Note: spec §1.3 authorizes dashboard work as scope ("GO now"); spec §19.6 sequences it after Stage 1, which this gate enforces. | **OPEN** (2026-07-31, `T-058c`) — evidence: [docs/stage1-exit-evidence.md](stage1-exit-evidence.md). Slice runs entirely through the worker: 15 candidates, 5 to `review_pending`, 10 refused; 64 jobs, none dead or queued; zero `SendCommand`/`SendAttempt`/`OutboxEvent`, under a socket guard. Opens Stage 2 scope **only** — every other gate stays locked, and **G-08** still governs any live outreach. |
| **G-03** | Production-like or real model-provider data use | `Q-012` answered (approved baseline model, provider, and data-handling settings); `Q-016` answered (approved materials for model processing); §15.9 provider review recorded; `T-050` budget enforcement `DONE`; no real contact data before `Q-019` retention policy. | **LOCKED** |
| **G-04** | Messaging-provider integration (`T-091`, `T-092`) | **G-10** open (Stage 2 complete); `Q-027` answered (WhatsApp Business account/phone or approved iMessage path); `Q-008` overlay role confirmed; channel-neutral gateway (`T-090`) `DONE`; gateway holds no approval authority. | **LOCKED** |
| **G-05** | CRM integration (`T-093`) | `Q-001` answered yes (a commercial owner will actually use HubSpot); `Q-010` answered (fields, owners, pipeline stages); field-ownership map recorded to prevent sync loops. | **LOCKED** |
| **G-06** | OpenClaw/NemoClaw spike (`T-095`, `T-096`) | Stage 1 exposes a useful API vertical slice (**G-02** open); separate Linux VM available; commit and image digest pinned; egress restricted; no production secret on the VM; spec §6.5 controls recorded. | **LOCKED** |
| **G-07** | Email-provider execution, even in test mode | `Q-004` answered (mailbox, provider, sender identity, reply address, domain); **G-10** open; SPF/DKIM/DMARC verified; suppression and opt-out paths `DONE`; `Q-015` reply owner named; §15.8 checklist complete. | **LOCKED** |
| **G-08** | Any live outreach to a real recipient | Every Stage 5 exit condition in spec §19.6; `Q-002`, `Q-004`, `Q-005`, `Q-013`, `Q-014`, `Q-015`, `Q-017`, `Q-018`, `Q-020` answered; approved versioned claim set exists; U.S.-only; ~5 individually approved sends/day; legal/commercial owner authorization recorded; all §3.5 safety invariants demonstrated. | **LOCKED** |
| **G-09** | Automatic follow-ups and scoped automation (`T-120`, `T-121`) | Multiple completed live review cycles showing reliable behavior and clear value; `Q-009` decided; §8.4 explicitly amended by an approved decision record. | **LOCKED** |
| **G-10** | Stage 3 evaluation/staging work and (with other conditions) Stages 4–5 | `T-071` passes: a non-engineer completes reviews unaided; evidence in `docs/stage2-exit-evidence.md`. | **LOCKED** **Checkpoint 2026-07-31 (H1):** do not evaluate this gate while `T-157` is open — null version pins leave two §8.4 invalidation triggers unreachable on the production path. |

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

## 9. Progress log (append-only index)

**A chronological index, not a second copy of the evidence.** One row per completed run, under about
200 characters: what shipped, and nothing that belongs elsewhere. Verification detail lives in the
task block's **Completion evidence** in §3; design rationale lives in the module docstring, where it
travels with the code. Writing all three is what took this file to 277 KB.

Rows dated on or before 2026-07-29 were condensed from verbose entries; the originals are preserved
verbatim in [`docs/ledger/progress-log-verbatim-2026-07-29.md`](docs/ledger/progress-log-verbatim-2026-07-29.md).

| Date | Task | Result | What shipped |
|---|---|---|---|
| 2026-07-27 | — (loop initialization) | `—` | Repository assessed; `tasks.md` and `process.md` created |
| 2026-07-27 | `T-001` | `DONE` | Spec confirmed repo-local and hash-verified; `AGENTS.md` created; `README.md` expanded; ledge… |
| 2026-07-27 | `T-002` | `DONE` | `backend/` project scaffolded: pyproject with pinned toolchain, `uv.lock`, `app/` package, sm… |
| 2026-07-27 | `T-003` | `DONE` | `DONE` for the configuration and compose definition; live-container reachability not verified… |
| 2026-07-27 | `T-008` | `DONE` | Added `docs/adr/README.md` (ADR-001…017 indexed as inherited and binding, plus the never-reus… |
| 2026-07-27 | `T-004` | `DONE` | `DONE` except the database-dependent half of criterion 2, split to `T-135`. Added the FastAPI… |
| 2026-07-27 | `T-005` | `DONE` | Created the thirteen §18.2 module packages with ownership docstrings, a `ast`-based import-bo… |
| 2026-07-27 | `T-134` | `DONE` | Docker engine 29.4.3 now available |
| 2026-07-27 | `T-006` | `DONE` | Alembic environment, declarative `Base` with naming convention, `TimestampMixin`, initial emp… |
| 2026-07-27 | `T-010` | `DONE` | Five independent lifecycle enums with explicit transition tables, `assert_transition`, termin… |
| 2026-07-27 | `T-011` | `DONE` | First real table: `audit_event` with database-enforced append-only guarantees, `record_audit_… |
| 2026-07-27 | `T-013` | `DONE` | `Product`, `ProductStatusVersion`, `SourceDocument`, migration `259218227532`, readiness reso… |
| 2026-07-27 | `T-015` | `DONE` | `Campaign`, `TargetSegment`, `CampaignPolicyVersion`, a typed `CampaignPolicy` model, policy… |
| 2026-07-27 | `T-014` | `DONE` | `ApprovedClaim`, campaign allow-list, `ApprovedClaimSet` + members, fail-closed resolution se… |
| 2026-07-27 | `T-016` | `DONE` | `Account`, `Contact`, `ContactPoint`, `CRMMapping`, a normalization module, migration `9c7510… |
| 2026-07-27 | `T-017` | `DONE` | `Suppression` model with four scopes, permanence trigger, precedence-aware check functions, m… |
| 2026-07-27 | `T-018` | `DONE` | `CampaignCandidate` with the §8.1 identity triple, `create_candidate`/`transition` services r… |
| 2026-07-27 | `T-019` | `DONE` | `EvidenceSnapshot` with the full §14.3 provenance set, excerpt cap, staleness-aware read help… |
| 2026-07-27 | `T-020` | `DONE` | `MessageDraft` and immutable `MessageRevision` with claim/evidence citation arrays, content h… |
| 2026-07-27 | `T-021` | `DONE` | `Approval` pinning revision, recipient, content hash, product status version and claim set; a… |
| 2026-07-27 | `T-022` | `DONE` | `OutreachThread`, immutable `SendCommand` carrying the whole §11.4 contract, `SendAttempt`, `… |
| 2026-07-27 | `T-023` | `DONE` | `PromptVersion`, `SchemaVersion`, `ModelConfigVersion`, `PolicyVersion` with content hashing,… |
| 2026-07-29 | `T-030` | `DONE` | Durable PostgreSQL job queue: `Job` model, migration `63876c821f52`, per-instance `JobRegistr… |
| 2026-07-29 | `T-031` | `DONE` | Explicit per-job-type retry policy: `RetryPolicy` (validated at declaration), `classify()` re… |
| 2026-07-29 | `T-034` | `DONE` | Transactional outbox: `OutboxEvent` with a unique sha256 idempotency key and a partial pendin… |
| 2026-07-29 | `T-033` | `DONE` | Operational kill switches: `OperationalFlag` store with audited changes, the composed resolve… |
| 2026-07-29 | `T-035` | `SPLIT` | Split into `T-035a` / `T-035b` / `T-035c` and left `PLANNED` as the acceptance-intent record. |
| 2026-07-29 | `T-035a` | `DONE` | The external-effect boundary: `EffectOutcome`, frozen `EffectRequest`/`EffectResult`, `Suppor… |
| 2026-07-29 | `T-035b` | `DONE` | The outbox dispatcher: `OutboxState.DELIVERY_UNKNOWN`, a local `OUTBOX_TRANSITIONS` state mac… |
| 2026-07-29 | `T-035c` | `DONE` | The §11.4 dispatch-time rechecks: `preconditions.py` in `outreach_and_replies`, an injected `… |
| 2026-07-29 | `T-032` | `DONE` | Lease expiry recovery: `find_expired_leases` + `reclaim_expired_leases` in a new `recovery.py… |
| 2026-07-29 | `T-138` | `DONE` | Outbox dispatch-lease recovery: `find_expired_dispatch_leases` + `reclaim_expired_dispatch_le… |
| 2026-07-29 | `T-139` | `DONE` | `one_pass()` + `PassResult` in `worker.py` compose both reclaims, `run_once`, and `dispatch_o… |
| 2026-07-29 | `T-036` | `DONE` | Webhook intake: `WebhookEvent` with a unique `(provider, external_event_id)`, HMAC-SHA256 ver… |
| 2026-07-29 | `T-024` | `DONE` | `tests/test_invariants.py` — 23 tests across all six cross-entity invariants, no production c… |
| 2026-07-29 | `T-140` | `DONE` | Approval now consults its candidate's state at both layers: `require_approvable_candidate` in… |
| 2026-07-29 | `T-141` | `DONE` | `ThreadNotStartable` + `require_send_command` in `commands.py`, called from `transition_threa… |
| 2026-07-30 | `T-040` | `DONE` | `app/fixtures/` + `python -m app.cli seed_synthetic`: two idempotent synthetic campaign worlds, refused outside local/test |
| 2026-07-30 | `T-041` | `DONE` | `app/fixtures/prospects.csv`: 15 labeled rows on reserved example domains, 22 tests checking each edge case is real |
| 2026-07-30 | `T-142` | `FILED` | Pre-existing: `factories.NOW` + 72h TTL lapsed, 89 DB tests fail the approval-expiry check constraint |
| 2026-07-30 | `T-142` | `DONE` | One derived test clock in `factories.py`, 12 duplicate literals removed, `test_fixture_clock.py` guards it; suite 1054 passed |
| 2026-07-30 | `T-042` | `DONE` | `app/prospects/imports.py` + migration `e94c35cb931f`: typed CSV import, per-row rejections, content-hash idempotency, injection text inert |
| 2026-07-30 | `T-043` | `DONE` | `app/prospects/dedup.py` + ADR-019: two exact match rules, merge carries suppression forward, role matching rejected |
| 2026-07-30 | `T-044` | `DONE` | `app/campaigns/membership.py`: one membership per campaign with independent state, idempotent, paused campaigns skipped |
| 2026-07-30 | `T-045` | `DONE` | `app/qualification/eligibility.py`: 5 of §10.1's 8 hard rules, all failures recorded, no model path; 3 deferred as T-143/144/145 |
| 2026-07-30 | `T-046` | `DONE` | Offline evidence capture: §9.5 adapter contract, fixture source adapter, immutable snapshots, hostile document stored as data; `R-004` opened |
| 2026-07-30 | `T-050` | `DONE` | Model gateway + migration `c1b7f16c23f2`: `ModelRun`, three §18.7 budgets refusing pre-invocation, three locks on real-provider construction |
| 2026-07-30 | `T-051` | `DONE` | §10.4 output schema as a Pydantic contract + exported artefact, bounded retry then human-review escalation, registered and tamper-checked |
| 2026-07-30 | `T-052` | `DONE` | Fixture-keyed deterministic fake model with the five §19.2 failure modes; cross-process determinism proven under two hash seeds |
| 2026-07-30 | `T-053` | `DONE` | Qualification task + migration `f5eafa7d8ad9`: versioned prompt, citations checked against the database, human review forced by check constraint |
| 2026-07-30 | `T-054` | `DONE` | Drafting: model returns citations and personalization only, claim wording copied verbatim, boilerplate from a template, revisions immutable |
| 2026-07-30 | `T-055` | `DONE` | Revision validation: nine deterministic checks, all failures reported, expired claim fails on unchanged wording, no model in the path |
| 2026-07-30 | `T-056` | `DONE` | Claim/readiness invalidation job: pending revisions invalidated and approvals retired, idempotent, sent messages flagged not altered; `R-005` opened |
| 2026-07-30 | `T-057` | `DONE` | Untrusted content: 12-payload corpus, typed facts, fenced prompt assembly; instruction region byte-identical under every payload; fact type moved to satisfy §5.1 |
| 2026-07-30 | `T-146` | `DONE` | Importer carries the declared contact-point verification state, failing closed on anything but `verified`; found by `T-058a` |
| 2026-07-30 | `T-058a` | `DONE` | Shadow slice: empty DB to review-ready draft per campaign under a socket guard; 15 candidates, 5 advanced; `T-058` split into a/b/c |
| 2026-07-30 | `T-058b1` | `DONE` | Membership and eligibility as chained job types, idempotent under replay, next job committed with the state change; `T-058b` split into b1/b2 |
| 2026-07-31 | `T-058b2a` | `DONE` | Empty-by-default source-adapter registry and evidence capture as a chained job; `T-147` filed after the handler broke ADR-015's reader rule |
| 2026-07-31 | `T-147` | `DONE` | ADR-020: `campaigns` brackets the research step with its own job types; `research_and_evidence` stays a lifecycle reader; both xfails removed |
| 2026-07-31 | `T-058b2b1` | `DONE` | Fake-adapter hook keeps `build_provider` the single audited entry point; qualification chained, ending the cascade at `review_pending` |
| 2026-07-31 | `T-058b2b2a` | `DONE` | Drafting refuses any candidate that is not `approved`; `campaigns.approve_candidate` is the only path to it, and queues the draft |
| 2026-07-31 | `T-058b2b2b` | `DONE` | Shadow slice now runs entirely through the worker, eight job types, approval gap asserted; `T-148` filed — the worker registers nothing |
| 2026-07-31 | `T-148` | `DONE` | The worker now registers every job type, proven by AST discovery rather than a list; `claims.invalidate_by_version` had been unwired since `T-056` |
| 2026-07-31 | `T-058c` | `DONE` | Stage 1 exit evidence recorded and gate **G-02** opened; `T-058` closed; 15 candidates, 5 to review, 64 jobs, zero external writes |
| 2026-07-31 | `T-060a` | `DONE` | `frontend/` scaffold builds, lints, typechecks, and tests; ADR-021 records the toolchain; the app fetches nothing, test-proven |
| 2026-07-31 | `T-060b` | `DONE` | Types generated from the backend's OpenAPI document, drift tested on both arrows; client refuses any non-local host; ADR-021 amended to TS 5 |
| 2026-07-31 | `T-012` | `DONE` | Identity tables with the six §12.1 roles seeded by migration; a composite FK stops a service holding any role that decides something |
| 2026-07-31 | `T-061a` | `DONE` | Sessions keyed by token hash, expiring and revocable; sign-in stub refused outside `local`; no password anywhere; `T-061` split on `Q-026` |
| 2026-07-31 | `T-062` | `DONE` | Permission matrix mapped to §7.4 tiers; an undeclared route fails the suite; approvals restricted to human-only reviewer roles |
| 2026-07-31 | `T-063a` | `DONE` | First authenticated endpoint: session dependency, candidate review queue, 401-vs-403 split; `T-062`'s route walk missed included routers |
| 2026-07-31 | `T-063b` | `DONE` | Revision review queue with computed backlog age; the age filter and the reported age agree; unqualified revisions shown, not hidden |
| 2026-07-31 | `T-149` | `DONE` | Review card detail endpoint: §12.3 items 1-5, evidence strongest-first, CRM reported unknown not invented; found by `T-064` having no data source |
| 2026-07-31 | `T-064` | `DONE` | Review card renders §12.3's seven elements, actions shown disabled with reasons, nothing invented; `T-150` filed for a flaky drift test |
| 2026-07-31 | `T-065a` | `DONE` | Edit endpoint creates revision N+1, retires the old approval, re-runs validation; mutations refuse cookie auth. |
| 2026-07-31 | `T-065b` | `DONE` | Editing form wired to the endpoint; failures named by check; sign-in gap filed as `T-151` |
| 2026-07-31 | `T-151a` | `DONE` | Session API over the `T-061a` stub: sign in, read, sign out; refused outside `local` at the route; `T-151` split |
| 2026-07-31 | `T-151b` | `DONE` | Sign-in screen, signed-out prompt, and sign-out; review page now client-side and token-aware |
| 2026-07-31 | `T-066a` | `DONE` | §10.6's eleven categories as a database enum; rejections need one, deferrals need a waypoint; no policy rewritten |
| 2026-07-31 | `T-066b1` | `DONE` | Reject and defer endpoints under `correct_candidate`, bearer-only; approval gap filed as `T-154` |
| 2026-07-31 | `T-154a` | `DONE` | Contact points on the review card and a tier-4 approve endpoint; app now registers job types |
| 2026-07-31 | `T-154b` | `DONE` | Card lists contact points and approves for a chosen recipient; unverified shown and disabled |
| 2026-07-31 | `T-066b2` | `DONE` | Reject and defer wired to the card with §10.6 categories; deferral needs a date or event |
| 2026-07-31 | `T-153` | `DONE` | ADR-022: more research adds evidence without moving the candidate; one pass at a time |
| 2026-07-31 | `T-150` | `DONE` | Flake was a 5s test timeout, not a diff; generation measured at 2.0-2.4s and given a 30s bound |
| 2026-07-31 | `T-067a` | `DONE` | Approval, send command, and outbox event in one transaction; step 3 rechecks at approval time |
| 2026-07-31 | `T-067b` | `DONE` | Message approval endpoint under `approve_message`, bearer-only, scope and record version checked before any write |
| 2026-07-31 | `T-156` | `DONE` | Template constants split out of `drafting`; the approval path's "no agent callback" walk now covers every module |
| 2026-07-31 | `T-155` | `DONE` | Request-more-research wired end to end; all five §12.3 item 6 actions now live on the card |
| 2026-07-31 | `T-068a` | `DONE` | Invalidation reasons now name the triggering record; revocation endpoint; `T-157` filed for the missing version pins |
| 2026-07-31 | checkpoint | `PASS_WITH_ACTIONS` | Independent audit: all checks re-run green (2050+127 tests, 27-migration round trip); H1=`T-157`; `T-158` filed; see [report](docs/checkpoints/2026-07-31_stage2_checkpoint.md) |

> Every run updates both this index and the task entry. The task entry carries the evidence; this
> carries the order things happened in.
