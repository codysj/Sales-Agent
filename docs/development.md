# Local development

Everything here runs offline against synthetic data. No provider account, credential, or
network service is required or permitted — see [AGENTS.md](../AGENTS.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages the Python 3.12 toolchain itself)
- Docker Desktop or another Docker engine, for local PostgreSQL

## Setup

```bash
cp .env.example .env
docker compose up -d db
cd backend && uv sync --all-groups
```

`.env` is git-ignored. The values in `.env.example` are throwaway local defaults, not secrets.

## Checks

Run from `backend/`:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q
```

## Configuration

`app/core/settings.py` reads the repository-root `.env`, resolved from the module's own path so
it loads identically from any working directory. Three settings are fail-closed and must not be
flipped until the matching gate in [tasks.md](../tasks.md) §5 is unlocked:

| Setting | Safe default | Gate required to change |
|---|---|---|
| `SHADOW_MODE` | `true` | the relevant stage gate; blocks every external-effect adapter |
| `OUTBOUND_EMAIL_ENABLED` | `false` | **G-07** (email execution), then **G-08** (live outreach) |
| `MODEL_PROVIDER` | `fake` | **G-03** (production-like model data use), `Q-012` |

`ModelProvider` deliberately has one member. Adding a real provider is a reviewable code
change (task `T-050`), not a configuration tweak.

## Database

The `db` service is local-only; deployment topology is undecided pending `Q-018`. Reset it with:

```bash
docker compose down -v && docker compose up -d db
```

Migrations arrive with task `T-006`; there is no schema yet.
