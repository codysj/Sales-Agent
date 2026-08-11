<div align="center">

# Matrix Power — Always-On AI Sales Agent

**An application-owned sales workflow for product-specific prospecting, evidence-backed
qualification, and human-approved outreach.**

The application owns the workflow. The model is a bounded service inside it.
A person approves every message, or nothing goes out.

[![CI](https://github.com/codysj/Sales-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/codysj/Sales-Agent/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](backend/app/main.py)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](docker-compose.yml)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](frontend/package.json)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

</div>

> [!IMPORTANT]
> **This build runs in shadow mode, and every screenshot below was taken with sending switched
> off.** No email, message, CRM mutation, production credential, deployment, or LinkedIn
> automation is permitted until the matching gate in [`tasks.md`](tasks.md) §5 is explicitly
> unlocked. Every record in this repository is synthetic, prefixed `SYNTHETIC-`, and addressed to
> IANA-reserved example domains.

---

## Demo

A reviewer opens a candidate, reads the evidence behind it, picks the address it would go to, and
approves. Approving records a decision and queues a draft — it sends nothing.

![Reviewing and approving a candidate](docs/media/review-approval.gif)

<table>
<tr>
<td width="50%"><img src="docs/media/review-queue.png" alt="The review queue: candidates awaiting review and messages awaiting approval"></td>
<td width="50%"><img src="docs/media/operations-panel.png" alt="The operations panel: safety posture, switches, work in flight, dead jobs"></td>
</tr>
<tr>
<td><b>Review queue</b> — what is waiting on a person, split by lifecycle: candidates to decide on, and drafted messages to approve word-for-word.</td>
<td><b>Operations</b> — the safety posture first, because during an incident that is the only question. Then queue depth, review backlog, and dead jobs with the reason each one stopped.</td>
</tr>
</table>

### Every claim on the card is traceable

The review card exists so a reviewer can approve *responsibly*. Product statements cite a
versioned approved claim; prospect statements cite stored evidence with its source quality and
retrieval time.

![Approved claims, each with its key and version](docs/media/approved-claims.png)

Evidence is rendered as **data, never as instructions**. The fixture set deliberately includes a
stored prompt-injection string; it is displayed as text, and nothing in the pipeline treats it as
a command.

![Evidence with source quality and retrieval time, including a stored prompt-injection string](docs/media/evidence.png)

The reviewer approves the exact bytes that would be sent, and the card states plainly what happens
next — which, in this build, is nothing.

![The exact drafted message, with a statement of what happens next](docs/media/exact-message.png)

<details>
<summary><b>The whole review card, top to bottom</b></summary>

<br>

Specification §12.3 lists seven things a review card must show, and every one is asserted by a
test. This is all of them on one candidate: who it is, the evidence, product readiness and
approved claims, suppression and CRM warnings, the exact revision, the actions, and the
structured reason each action requires.

<img src="docs/media/review-card-full.png" alt="The complete candidate review card">

</details>

> Styling is deliberately deferred (ADR-021): the dashboard is an internal review tool, and no
> screen has yet needed a design system more than it needed to be correct and legible.

---

## What this is

An always-on sales assistant that discovers prospective companies, researches and qualifies them
against real product readiness, drafts personalized outreach from approved claims, and puts a
person in front of every message before it leaves.

The architectural thesis is that **"AI sales agent" is mostly not an AI problem**. Scheduling,
state, retries, idempotency, approvals, suppression, and auditability are ordinary application
concerns, and giving them to a model is how such systems become unreviewable. So:

| Concern | Owner |
|---|---|
| Workflow state, scheduling, jobs, retries, approvals, policy, execution | The FastAPI application |
| Research synthesis, classification, qualification support, drafting | A bounded, provider-neutral model gateway invoked through typed, schema-validated tasks |
| Evidence review and exact approval | The authenticated dashboard — the only approval authority |
| Alerts and status questions | A messaging overlay, deliberately off the critical path |

A model never approves and never executes. That is enforced structurally: `model_gateway` is
forbidden by an import-boundary test from importing any domain module, so it *cannot* reach the
eligibility, suppression, approval, or execution rules it is not allowed to decide.

## How the pipeline runs

```mermaid
flowchart LR
  A["Prospect import<br/><i>CSV, content-hashed</i>"] --> B["Campaign membership<br/><i>hard eligibility</i>"]
  B --> C["Research<br/><i>evidence capture</i>"]
  C --> D["Qualification<br/><i>opportunity type</i>"]
  D --> E["Drafting<br/><i>approved claims only</i>"]
  E --> F["Validation<br/><i>citations, claims, suppression</i>"]
  F --> G(["Human review"])
  G -->|approve| H["Approval record<br/><i>pins revision + claim set</i>"]
  H -.->|"gate G-07 — locked"| I["Send"]
  style G fill:#1f6feb,stroke:#1f6feb,color:#fff
  style I stroke-dasharray: 5 5,color:#888
```

Each box is a job type on a durable PostgreSQL queue with leases, explicit per-type retry
policies, and a dead-letter state that always records *why* it stopped. Delivery goes through a
transactional outbox keyed by an idempotency hash, so the effectively-once guarantee survives a
worker dying mid-pass.

The dashed edge is the point of the whole design: it is the only path to an external effect, and
it is closed.

## The safety model

This is the part worth reading the code for.

**Fail-closed by default.** `SHADOW_MODE=true`, `OUTBOUND_EMAIL_ENABLED=false`,
`MODEL_PROVIDER=fake`. None may be flipped until the matching gate is unlocked.

**Three locks on ever calling a real model.** `ModelProvider` has one member, so adding a real
provider is a reviewable code change rather than a config edit. Even then the registry requires
`ALLOW_REAL_MODEL_PROVIDER`, and then looks the provider up in `REAL_PROVIDER_ADAPTERS`, which is
empty. Three, because the first two are each one edit away from being wrong.

**Deterministic where it matters.** Hard eligibility, suppression, approval, product readiness,
budgets, and execution never depend on model output.

**An approval that cannot prove its currency does not authorize a send.** An approval pins the
revision, recipient, content hash, product status version, and claim set. Editing a draft
supersedes it; a superseded claim set invalidates it. A null version pin refuses rather than
skipping the check (ADR-029), which turned out to matter — 66 tests had been building an approval
the production path cannot actually make.

**Five lifecycles stay independent.** Campaign candidate, message revision, approval, outreach
thread, and background job each have their own states and transition table. There is no global
workflow enum, because the day two of them need to disagree, one enum cannot.

**All external content is untrusted data.** Webpages, emails, attachments, CRM notes, messages,
model output, file contents — rendered and stored as data, never interpreted as instructions.

**Every consequential action writes an audit event** with a correlation ID, against an
append-only table enforced by database triggers.

## Quick start

Everything runs offline against synthetic fixtures. No provider account, credential, or network
service is required — or permitted.

**Prerequisites:** [uv](https://docs.astral.sh/uv/) (which manages the Python 3.12 toolchain
itself), Node.js 20+, and Docker for local PostgreSQL.

```bash
cp .env.example .env
docker compose up -d db
```

```bash
cd backend && uv sync --all-groups
```

Then seed the world, start a campaign, import prospects, and drain the queue — in that order,
from `backend/`:

```bash
uv run alembic upgrade head
uv run python -m app.cli seed_synthetic
uv run python -m app.cli start_campaign synthetic-sodium-battery
uv run python -m app.cli import_prospects
uv run python -m app.cli run_worker
uv run python -m app.cli grant_local_reviewer
```

Seeded campaigns arrive **paused** on purpose — starting one is a deliberate act. `run_worker`
drains the queue with the Stage 1 fakes installed and then stops, unlike `python -m app.worker`,
which is the production entry point and deliberately installs neither the fixture source adapter
nor the fixture-keyed model.

Now the two servers, one per terminal:

```bash
cd backend && uv run uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000> and sign in as `synthetic-reviewer@example.invalid`. There is no
password: managed SSO is specified but not yet wired, and the local stub issues a session for a
known user and refuses to run outside a local environment.

Approving a candidate queues the drafting job; it does not run it. Re-run
`uv run python -m app.cli run_worker` to see the drafted message appear for approval.

> [!WARNING]
> **The walkthrough does not yet work end to end in a browser** ([`T-195`](tasks.md)). The
> dashboard fetches from the browser and the API registers no CORS middleware, so cross-origin
> requests from `localhost:3000` to `localhost:8000` are refused and a reviewer cannot get past
> sign-in. The fix is to serve both behind one origin — a dev-server rewrite, rather than a CORS
> allowance, so that the `SameSite` session cookie keeps working and the API gains no permissive
> header path. Until then, the API is exercisable directly and the dashboard is not.

### Verification

The canonical gate, from `backend/`:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q
```

And from `frontend/`:

```bash
npm run lint && npm run typecheck && npm test
```

That is 2,401 backend tests and 186 dashboard tests at the time of writing. The backend suite runs
against a real PostgreSQL — each session creates a throwaway database and drops it afterwards —
under a socket guard that fails the suite if anything reaches a non-database address. It takes
about an hour; there are no mocked database semantics to make it faster, deliberately.

## Repository layout

```text
backend/          FastAPI application, worker, and CLI
  app/            the thirteen modules of spec §18.2, boundaries enforced by an AST test
  alembic/        migrations, including hand-written triggers and exclusion constraints
  tests/          invariants, module boundaries, pipeline jobs, and a full shadow slice
frontend/         Next.js review dashboard; API types generated from openapi.json
docs/             specification, ADRs, architecture notes, stage-exit evidence, media
```

Notable tests, if you want the short tour: `test_module_boundaries.py` parses imports with `ast`
and fails the suite on a forbidden edge; `test_invariants.py` covers the six cross-entity
invariants; `test_shadow_slice.py` runs import → review-ready draft and asserts zero external
writes; `test_fixtures.py` asserts no fixture string contains a digit, so no placeholder can be
mistaken for a real product fact.

## Documentation

| Document | Purpose |
|---|---|
| [Specification v0.3](docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md) | Architecture, workflow, safety model, launch gates — the source of truth |
| [`tasks.md`](tasks.md) | Work ledger: stage gates, acceptance criteria, decision register, progress log |
| [`process.md`](process.md) | The development-loop operating procedure this repo is built under |
| [`AGENTS.md`](AGENTS.md) | Repository instructions and the hard safety rules |
| [Module boundaries](docs/architecture/modules.md) | Which module may import which, and why each rule exists |
| [Local development](docs/development.md) | Setup, fixtures, migrations, and the port-collision trap |
| [ADRs](docs/adr/) | Decision records, numbered from 018 |
| [Stage 1 exit evidence](docs/stage1-exit-evidence.md) · [Stage 2](docs/stage2-exit-evidence.md) | What was actually demonstrated at each gate |

## Status

**Stage 1 — core shadow backend: complete.** Gate **G-02** opened on evidence of a full
import → review-ready-draft slice running entirely through the worker, with zero external writes
under a socket guard.

**Stage 2 — review dashboard: built.** Queue, review card, approval, editing, rejection and
deferral, the attention queue for stale approvals, and the operations panel are implemented and
tested.

**Next: `T-195`, then gate G-10.** The gate asks for a non-engineer completing reviews unaided,
with no explanation of the agent stack, and the [rehearsal running sheet](docs/stage2-rehearsal-script.md)
is written. One implementation task stands in front of it: the dashboard's API calls are blocked
cross-origin, so nobody can rehearse anything yet.

The gate then takes evidence from two rehearsals
([ADR-030](docs/adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md)). An agent-team pass
opens Stage 3 scope only; a person's observed session opens the gate in full and remains a
precondition of live email and live outreach. The gate's words are not reinterpreted — *a
non-engineer* means a person — but partial evidence now buys a stated, bounded amount instead of
nothing.

Recommendations for every open non-engineering decision are recorded in
[docs/decisions/2026-08-11-recommended-actions.md](docs/decisions/2026-08-11-recommended-actions.md).

Everything beyond it — real model providers, email execution, CRM sync, messaging integration,
live outreach — sits behind its own locked gate with recorded unlock conditions. Nothing here is
"almost ready to send"; not sending is the current, deliberate state.

## License

[Apache-2.0](LICENSE).
