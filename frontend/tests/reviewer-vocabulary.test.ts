import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The dashboard speaks the reviewer's vocabulary, not the repository's (T-215, T-216).
 *
 * Two defects with one shape, both found by rehearsal readers and both filed on evidence anybody
 * can read without running anything:
 *
 * - **`T-216`** — the sign-in page said "Managed single sign-on is not wired up yet (T-061b)" to
 *   whoever was signing in. A reader asked *"What is T-061b?"* on the first screen they ever saw.
 *   It is a row in a backlog they have no access to, and on a page whose job is to let somebody
 *   in it reads as a fault code.
 * - **`T-215`** — one section of the card promised approving "queues a draft" while another said
 *   it "creates no outbound message". Both true. Two nouns for what a reader takes to be one
 *   object, and the reconciliation nowhere on screen.
 *
 * **Asserted over source rather than over a rendered tree, and that is the whole reason this file
 * exists rather than three more cases in the component suites.** `T-210` swept the review card for
 * exactly this and missed the four pages around it, because a render test can only check what
 * somebody remembered to render. Reading every file under `app/` cannot miss a page — including
 * the ones nobody has written a test for yet.
 *
 * Comments are stripped first, because they are where these identifiers *belong*: a docstring
 * saying which task built a component is how this repository stays navigable. What is left after
 * stripping is code and the strings a reviewer reads.
 */

const ROOT = join(import.meta.dirname, "..");
const APP = join(ROOT, "app");

/** Every component and page. Not `lib/`, which no reviewer reads, and not the tests. */
function appSources(): string[] {
  const found: string[] = [];
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      if (entry.endsWith(".tsx") || entry.endsWith(".ts")) {
        found.push(path);
      }
    }
  };
  walk(APP);
  return found;
}

/**
 * The file with every comment removed: block comments — which covers docstrings and the
 * `{...}`-wrapped JSX form, since both are a block comment underneath — and line comments.
 *
 * Line comments are stripped only where the `//` starts a line or follows whitespace, which is
 * crude but safe here: `tests/no-network.test.ts` already forbids an absolute URL anywhere in this
 * application, so there is no `https://` in a string for this to cut in half.
 */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/[^\n]*/g, "$1");
}

/** A task identifier: `T-` and three digits, optionally with a letter suffix like `T-061b`. */
const TASK_ID = /\bT-\d{3}[a-z]?\b/g;

describe("no reviewer reads a task identifier", () => {
  it("finds the files it claims to be checking, and finds identifiers in them", () => {
    // The guard on the guard, and it has two halves. An empty walk would pass everything; so
    // would a `withoutComments` that stripped the entire file. Before stripping, these
    // identifiers are everywhere — that is the docstring convention — so their presence proves
    // the pattern matches and their absence afterwards proves the stripping is what removed them.
    const files = appSources();
    const before = files.filter((path) => TASK_ID.test(readFileSync(path, "utf8")));

    expect(files.length).toBeGreaterThanOrEqual(10);
    expect(before.length).toBeGreaterThanOrEqual(5);
  });

  it.each(appSources().map((path) => [path.slice(ROOT.length + 1)] as const))(
    "%s names no task identifier outside a comment",
    (relative) => {
      const code = withoutComments(readFileSync(join(ROOT, relative), "utf8"));

      expect(code.match(TASK_ID) ?? []).toEqual([]);
    },
  );
});

describe("one noun for the thing approving produces", () => {
  /**
   * `T-215` criterion 1. The card may call it a draft; it may not also call it something else.
   *
   * A synonym is banned rather than a phrasing mandated, because the defect was never that a
   * particular sentence was missing — both sentences were accurate. It was that the second noun
   * existed at all, and a reader had to guess whether the two named the same object.
   */
  const ALTERNATE_NOUNS = ["outbound message", "outbound email", "outgoing message"];

  /**
   * Scoped to the review card, which is where the two sentences sat.
   *
   * The operations panel labels a safety switch "Outbound email disabled", and that is the switch's
   * actual name — `OUTBOUND_EMAIL_ENABLED`. It is not a second word for a draft, and a check that
   * flagged it would be one somebody eventually turns off. What is banned is the alternate noun
   * *where the product of approval is named*.
   */
  const CARD_SOURCES = appSources().filter((path) => path.includes(join("app", "review")));

  it.each(ALTERNATE_NOUNS)("no string on the card says %s", (noun) => {
    expect(CARD_SOURCES.length).toBeGreaterThanOrEqual(5);

    const offenders = CARD_SOURCES.filter((path) =>
      withoutComments(readFileSync(path, "utf8")).toLowerCase().includes(noun),
    );

    expect(offenders).toEqual([]);
  });

  it("says what a draft is where it says approving makes one", () => {
    // The other half, and the half a ban cannot give you: having removed the second noun, the
    // first has to carry the meaning on its own. "Delivered to nobody" is the part a reader was
    // reconstructing for themselves.
    const approve = readFileSync(join(APP, "review", "ApproveForm.tsx"), "utf8");

    expect(approve).toMatch(/delivered to nobody/);
  });
});
