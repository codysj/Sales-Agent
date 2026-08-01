# ADR-021 — Frontend toolchain defaults

- **Status:** ACCEPTED (2026-07-31), **amended 2026-07-31** by `T-060b` — see *Amendment: TypeScript 5, not 6*.
- **Scope:** Local to this repository. Extends [ADR-018](ADR-018-toolchain-defaults.md), which
  fixed the Python toolchain and named `frontend/` in the layout while deciding nothing about what
  goes in it. Does not modify any inherited specification ADR.
- **Specification basis:** §18.1 decides "Next.js thin internal dashboard" and nothing further;
  §12.3 makes the dashboard the authoritative review and approval interface; §23 requires typed
  contracts; GP-10 asks for minimal operational burden. This ADR fills the gap between "Next.js"
  and a repository someone can run.
- **Implemented by:** `T-060a` (`frontend/`).

## Decision

| Concern | Choice |
|---|---|
| Package manager | `npm`, with a committed `frontend/package-lock.json` |
| Framework | Next.js 16, **App Router**, React 19 |
| Module system | ESM (`"type": "module"`) |
| Language | TypeScript 5.9, `strict` **plus** `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitOverride`, `noFallthroughCasesInSwitch` |
| Lint | ESLint 10 flat config, `typescript-eslint` **type-aware** (`recommendedTypeChecked`), `eslint-plugin-react-hooks` |
| Tests | Vitest |
| Styling | None yet — deferred to the first screen that needs it (`T-062`) |
| Data fetching | None yet — `T-060b` generates a typed client; until then the app fetches nothing, enforced by a test |

Scripts are `lint`, `typecheck`, `build`, `test`, and all four must pass.

## Why

**npm, not pnpm or yarn.** It ships with Node, so a future maintainer needs no second install step
— the same reasoning ADR-018 used to choose `uv`, and it matters for the same reason: `Q-018`
leaves the post-internship maintenance owner unnamed. pnpm's disk savings are real and irrelevant
at one small app.

**App Router, not Pages Router.** It is the documented default for new Next.js applications, and
the dashboard's shape — server-rendered review pages reading backend state — is what server
components are for. Choosing the older router to avoid learning the newer one would be choosing
the one that will be legacy first.

**Type-aware linting, not the syntactic-only default.** The point of TypeScript here is the typed
contract with the backend (§23), and the rules that enforce it — `no-floating-promises`,
`no-misused-promises`, the `no-unsafe-*` family — all need type information. A linter that cannot
see types would pass exactly the mistakes that contract exists to prevent. It costs a slower lint
run and two config concessions, both commented where they are made.

**Strict beyond `strict`.** `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` are off by
default and both bite in this application's shape: a review card indexes into evidence and claim
lists, and "the array had fewer items than I assumed" should be a compile error rather than a blank
panel in front of an approver. ADR-018's argument applies — strict-from-empty is far cheaper than
strict-from-legacy.

**Vitest, not Jest.** One test runner that reads the same ESM and TypeScript the app does, with no
separate transform configuration to keep in step.

**No styling library, no state manager, no component kit.** Nothing is added before a screen needs
it. §2 item 13 forbids infrastructure without a measured requirement, and a design system chosen
before the first review card exists would be chosen against imagined requirements.

## What was rejected

**`create-next-app`.** Rejected in favour of writing the files. It generates a working app, but
also a font loader, a CSS baseline, an SVG set, and a landing page — none of which this dashboard
needs, all of which would arrive uncommented and stay. Fifteen hand-written lines of config are
reviewable; a generated tree is inherited.

**Pinning exact versions in `package.json`.** ADR-018 pins Python exactly, and the first draft of
this scaffold tried to match — and named five versions that did not exist, because they were
guesses. The lockfile is the pin, and it is the one npm actually enforces; `package.json` carries
caret ranges and `package-lock.json` is committed.

**A placeholder that fetches something.** Rejected because it would make this task's "the scaffold
fetches nothing" criterion untestable, and would put the repository's first data-fetching code in
before there was a typed contract to fetch against.

## Cost, stated plainly

`frontend/package-lock.json` locks **248** packages for an application that currently renders two
paragraphs. That is the floor for a Next.js app with type-aware linting, and it does not shrink;
the alternative is not a smaller dependency tree but a different framework, which §18.1 already
decided against.

Type-aware linting also means `npm run lint` needs a TypeScript program, so it is seconds rather
than milliseconds.

## Amendment: TypeScript 5, not 6 (2026-07-31, `T-060b`)

The decision above originally read TypeScript 6.0, chosen because it was current. `T-060b` then
tried to install `openapi-typescript`, the standard types-only generator for an OpenAPI document,
and hit a hard peer conflict: it requires `typescript@^5.x`, and every published version does.

Three options, and why the others lost:

- **`--force` or `--legacy-peer-deps`.** npm's own message calls the result "incorrect and
  potentially broken". Accepting that to keep a version number would be choosing the number over
  the working toolchain.
- **`@hey-api/openapi-ts`**, which does support TypeScript 6. Rejected because it generates a
  runtime SDK, not types — more than the task needs, and a dependency the dashboard would then be
  coupled to. `openapi-typescript` emits one file of types and no runtime at all.
- **TypeScript 5.9.** Taken. The ecosystem has not caught up with 6, which is a measured
  constraint rather than a preference, and it is exactly the situation this ADR's "revisit if"
  section contemplates.

Recorded as an amendment rather than a quiet edit because the original line was a real decision
made on real reasoning; it was simply made without knowing what the generator required.

## Amendment (2026-07-31, `T-065b`): a DOM renderer, once a screen needed one

This ADR chose Vitest and deliberately added no DOM environment, on the reasoning that `T-064`'s
review card was static — `renderToStaticMarkup` exercised everything there was to exercise, and
`jsdom` plus a testing library would have been dependencies bought against a need nobody had.

`T-065b` is the need. The editing form has a submit, a request, and three outcomes, and its
acceptance criteria are about what a reviewer sees *after* interacting. Testing that by matching
strings in server-rendered HTML would test the markup and not the behaviour.

Added: **`jsdom`** and **`@testing-library/react`**. Not added: `@testing-library/user-event`,
because `fireEvent` covers a select, a text field, and a submit, which is the whole form.

The environment is set **per file** with `// @vitest-environment jsdom` rather than globally. The
other three suites are genuinely node-only — a type check, a source scan, and a static render —
and running them in a simulated browser would cost time for nothing and hide a component that
accidentally depended on `window`.

## Revisit if

- The dashboard needs a styling approach — that is a decision, not a default, and belongs in its
  own ADR at `T-062`.
- CI (`T-007`) finds the type-aware lint too slow to run on every push, in which case split it
  rather than weaken it.
- A second frontend appears, at which point the package manager choice deserves re-examination
  under workspace requirements it was not chosen for.
- `openapi-typescript` supports TypeScript 6, at which point the amendment above can be reversed
  — it is the only thing holding the version down.
- A second interactive surface needs `user-event`'s more faithful input simulation, at which
  point add it there rather than pre-emptively here.
