# ADR-027 — Where a development process may register the fixture source adapter

**Status:** ACCEPTED (2026-08-01) — **option (b)**, decided by the user and recorded by the
loop at their direction. Proposed 2026-08-01 by `T-174`; the choice was the user's, not the
loop's (AGENTS.md rule 10).
**Nothing is implemented yet.** `T-172` carries the work and is now `READY`; this record only
fixes *which* design it implements. The amendment (b) requires — excluding `app/cli.py` from
the two adapter walks — is part of `T-172`, not of this decision, and must land with the
invariant docstrings updated so the rule and its enforcement still agree.
**Corrected 2026-08-01 (`T-175`):** option (b) originally claimed to amend **no** invariant. That
was wrong, and the correction is below rather than folded in silently, because the first version
was written to be decided on.
**Spec:** §19.6 Stage 1/2, §15.3, §18.4, §16

## The problem, in one paragraph

A worker run locally cannot complete research. Every `research.capture_evidence` job dead-letters
with *"no source adapter registered under 'fixture' … Stage 1 registers the fixture adapter from
the CLI or a test"* — and nothing does. `tests/test_shadow_slice.py` registers it itself, which is
why the pipeline is proven end to end while a real database never fills a review queue. Gate
**G-10** asks whether a non-engineer can complete reviews unaided; today there is nothing for them
to review, and the only sign of why is inside a dead job's reason.

## Why it is not a small fix

Two invariants close every obvious door, and both are deliberate:

| Invariant | Says |
|---|---|
| `tests/test_pipeline_jobs.py::test_no_production_module_registers_an_adapter` | **Nothing under `app/`** may call `register_source_adapter` — "registering it is the CLI's or a test's act" |
| `tests/test_module_boundaries.py` `FORBIDDEN_FOR_ALL` | **Nothing** may import `app.worker` |

So the CLI — the one sanctioned caller, and the only module allowed to import `app.fixtures`
(`tests/test_fixtures.py::test_only_the_cli_imports_the_fixtures`) — cannot run the worker, and the
worker cannot register an adapter.

`T-172` attempted the shape that looked safest: register in `worker.py` from a **configured**
directory, so no production module imports `app.fixtures` and §18.4's "provider locations live in
configuration" is honoured. The adapter invariant caught it anyway, because it is written more
broadly than its own stated rationale — it forbids the call, not the import. That attempt was
reverted in full.

## Options

### (a) Widen the adapter invariant for one guarded composition module

Allow exactly one module under `app/` to register, guarded on `app_env in {local, test}` **and** a
configured path being set.

- **For:** smallest change; the guard is testable and did bite when written.
- **Against:** the rule stops being "no production path wires fixtures" and becomes "no production
  path except this one", which is a sentence that invites a second exception. §15.3 puts network
  sources behind gate **G-06**; the adapter rule is the thing standing between a configured path
  and a production worker serving fixture evidence.

### (b) Move the pass loop so the CLI can drive it — **recommended**

`app/worker.py` holds three separable things: `PassResult` and `one_pass` (what one cycle does),
and `main` (signals, poll interval, logging). Move the first two into a composition module beside
`job_types.py` and `intake.py`. `worker.py` becomes a thin entry point that imports them; a new
`python -m app.cli run_worker` registers the fixture adapter — which the CLI is already allowed to
do, from `app.fixtures`, with no new setting — and loops over `one_pass`.

- **For:** `FORBIDDEN_FOR_ALL` is untouched — nothing imports `app.worker` — and the CLI keeps its
  existing licence to touch fixtures. The walkthrough gains one command a reader types instead of a
  caveat they have to understand.
- **Against:** it moves code in a production entry point, and `tests/test_cli.py` and
  `tests/test_shadow_slice.py` both import `one_pass` and would follow it.
- **Against, and this was missed in the first version of this ADR (`T-175`):** it **does** amend the
  adapter invariant. `test_no_production_module_registers_an_adapter` walks `app.rglob("*.py")` and
  excludes only `registry.py`, so `app/cli.py` is caught by it — even though the same test's
  docstring says *"registering it is the CLI's or a test's act"*. Proven, not read: a
  `register_source_adapter(` call added to `cli.py` fails it with `production modules registering a
  source adapter: ['cli.py']`. **The amendment (b) needs is to exclude `cli.py`**, which makes the
  test agree with its own recorded rationale.
- **Note:** the two commands stay distinct — `python -m app.worker` remains the production entry
  point and registers nothing, which is exactly the property the adapter invariant protects.

### (c) Accept it, and say so in the walkthrough

Leave the wiring absent; `T-071a` documents that a local worker stops at research.

- **For:** costs nothing, changes nothing.
- **Against:** gate **G-10** asks a non-engineer to complete a review, and the walkthrough would ask
  them to look at an empty queue. That is not a Stage 2 exit; it is a Stage 2 exit that has been
  written around.

## Recommendation

**(b)** — still, and the correction above sharpens rather than weakens the case.

Both (a) and (b) amend the adapter invariant, so the question is *which amendment*:

- **(b) makes the test say what it already means.** Its docstring names the CLI as a legitimate
  caller; the walk forbids it. Excluding `cli.py` closes a gap between a rule and its
  implementation, and the rule it protects — *no production path wires fixtures* — is untouched,
  because `cli.py` is a development entry point that already imports `app.fixtures` by explicit
  licence.
- **(a) creates an exception the rationale never contemplated**: a new module under `app/`, on the
  production import graph, permitted to register on the strength of a runtime `app_env` check. That
  is a genuinely weaker rule, and a weaker rule is not reviewable the way moved code is.

(c) remains not a resolution: it writes around gate **G-10** rather than passing it.

## If (b) is accepted

`T-172` becomes: exclude `cli.py` from the walks in **both** `test_no_production_module_registers_an_adapter`
and `test_no_production_module_installs_a_fake_adapter` (they carry the same mismatch, and a local
worker needs the fake model factory as well as the source adapter) and update their docstrings to
say why; move `PassResult` and `one_pass` into a composition module; add
`python -m app.cli run_worker` (local/test only, registering the fixture source adapter); point
`tests/test_cli.py` and `tests/test_shadow_slice.py` at the new home; and remove the
`xfail(strict=True)` marker `T-175` left beside the invariant, which will start failing as `XPASS`
the moment the exclusion lands. `T-071a` unblocks, and the walkthrough's step 5 becomes a command
instead of a caveat.

## Revisit when

A real source adapter exists (`Q-003`, gate **G-06**). At that point registration stops being a
development convenience and becomes configuration a deployment owns, and whichever option was
chosen here should be re-read against that.
