# ADR-028 — A development seed registers the prompt, schema, and model-config versions

**Status:** ACCEPTED (2026-08-01, `T-172b`) — decided and applied by the loop. Unlike ADR-027 this
amends no invariant and takes no option away from a deployment; it records where a **local**
registration lives and, more usefully, what it does not solve.
**Spec:** §7.2, §10.2, §14.5, §17.5, §19.6 Stage 1/2

## The problem

`handle_qualify` and `handle_draft` each resolve three versions — prompt, output schema, model
configuration — with `require_effective_version`, and fail **permanently** when any is missing. A
run that cited no version would be a decision nobody could later explain (§17.5), so failing is
right.

Nothing outside `tests/` ever registered one. `register_prompt_versions` and
`register_schema_versions` are called only from test modules; every `ModelConfigVersion` row in the
repository is constructed in a test. So a database built by the documented commands produced
candidates, researched them, and stopped — with the reason inside a dead job's `reason` column.
`T-172a` had just removed the *previous* last obstacle; this was the next one behind it.

## What is actually being registered

Two different kinds of thing, and conflating them is how this gets filed in the wrong place:

| Artefact | What it is | Where it comes from |
|---|---|---|
| `PromptVersion` | The bounded task's prompt | `app/model_gateway/prompts/*.txt`, hashed |
| `SchemaVersion` | The §10.4 output contract | `app/model_gateway/schemas/*.json`, hashed |
| `ModelConfigVersion` | Which provider, which model, which parameters | **A choice**, not a file |

The first two are **production artefacts**. Registering them is not seeding synthetic data; it is
publishing a hash of a file that ships in the image. Both registrars are content-hash idempotent
and publish a next version only when the file's text has changed.

The third names a provider. Today `ModelProvider` has exactly one member, `FAKE`, gate **G-03** is
locked, and `Q-012` has approved no provider or its data-handling terms — so the only configuration
that can be written is a fake one, which *is* a development choice.

## Decision

`seed_synthetic` registers all three, from `_seed_versions`.

- It is the first command in the documented order, so nothing else has to be run first.
- It already refuses outside `local`/`test` before touching the database, so the fake model
  configuration cannot be written where real data lives.
- It is already a get-or-create throughout, which is the property the registrars need.
- The walkthrough gains no step, and gate **G-10** is measured on a non-engineer completing that
  walkthrough.

## What this does not solve, and it matters

**A deployment still has no path that registers a prompt or schema version.** `seed_synthetic`
refuses to run outside `local`/`test`, by design — so the first real deployment would hit exactly
the failure this record is about. That is filed as **`T-185`** and is not solvable here: `Q-018`
has not said what a deployment is, and the answer ("a migration", "a release step", "an idempotent
call at startup") depends on it.

Recording the gap is the point of writing this down. A reader who finds prompt registration inside
the *fixtures* package could reasonably conclude it is fixture data and that production is handled
elsewhere. It is not handled elsewhere.

## Rejected

- **A `register_versions` CLI command.** Explicit, and the walkthrough gains a fifth step whose
  purpose a non-engineer cannot evaluate. It also does not reach production either — every CLI
  command refuses outside `local`/`test` — so it buys ceremony, not coverage.
- **Registering at application or worker startup**, beside `register_job_types()`. That call is
  in-process wiring; this one **writes to the database**. Two processes starting together would
  both try to publish version 1, and a process that writes versioned business records on boot is a
  migration wearing a startup hook.
- **An Alembic migration.** The content hash would be frozen at migration time and drift silently
  from the file it claims to hash, which defeats the reason the hash exists.

## Revisit when

`Q-018` answers what a deployment is, or a real provider is approved (`Q-012`, gate **G-03**). Both
change where the model configuration comes from, and the second means a real config version must
never be written by anything under `app/fixtures/`.
