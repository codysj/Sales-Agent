import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every route is styled, and the parts of the style that carry meaning are still there (T-217).
 *
 * `T-217` criterion 1 asks for this to be test-proven, and the failure it guards against is not
 * "the CSS is ugly" — it is a route rendering as browser defaults in front of the one non-engineer
 * whose first impression is not repeatable (`T-071b`). That happens in exactly two ways: the
 * import disappears from the layout, or a page renders something other than a `main`, which is
 * where the sheet is drawn.
 *
 * Three of the acceptance criteria are properties of the stylesheet itself rather than of a
 * rendered tree, and they are the three most likely to be quietly dropped by a later edit that is
 * only trying to change a colour:
 *
 * - the alert state is carried by more than colour (criterion 3),
 * - every control has a visible keyboard focus state (criterion 5),
 * - motion is suppressed under `prefers-reduced-motion` (criterion 5).
 *
 * Asserted over the source, because there is nothing to render: jsdom parses no stylesheet, and a
 * headless assertion about computed colour would test jsdom rather than the design.
 */

const ROOT = join(import.meta.dirname, "..");
const APP = join(ROOT, "app");
const STYLESHEET = join(APP, "globals.css");

/**
 * Every route the dashboard serves.
 *
 * `not-found.tsx` counts, and it is the reason it exists: Next serves its own 404 otherwise, with
 * inline styles this stylesheet cannot override, which on this design's desk is black text on
 * graphite. A route rendered by the framework is still a route a reviewer can reach.
 */
function routeFiles(): string[] {
  const found: string[] = [];
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      if (entry === "page.tsx" || entry === "not-found.tsx") {
        found.push(path);
      }
    }
  };
  walk(APP);
  return found;
}

/** Every `layout.tsx` under `app/`. There is one; a second could bypass the import. */
function layoutFiles(): string[] {
  const found: string[] = [];
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      if (entry === "layout.tsx") {
        found.push(path);
      }
    }
  };
  walk(APP);
  return found;
}

describe("every route is styled", () => {
  it("finds the routes it claims to be checking", () => {
    // The guard on the guard: a walk that found nothing would pass everything below.
    expect(routeFiles().length).toBeGreaterThanOrEqual(5);
  });

  it("imports the stylesheet from the root layout", () => {
    const layouts = layoutFiles();

    expect(layouts).toHaveLength(1);
    // Anchored to the start of a line: the first version of this matched anywhere in the file,
    // and the negative control walked straight through it — commenting the import out left the
    // words `import "./globals.css"` on the line, and the test went on passing while every page
    // rendered unstyled. That is precisely the failure this exists to catch.
    expect(readFileSync(layouts[0]!, "utf8")).toMatch(/^import\s+["']\.\/globals\.css["'];/m);
  });

  it.each(routeFiles().map((path) => [path.slice(ROOT.length + 1)] as const))(
    "renders %s inside a main, which is where the sheet is drawn",
    (route) => {
      expect(readFileSync(join(ROOT, route), "utf8")).toMatch(/<main[\s>]/);
    },
  );
});

describe("the stylesheet keeps the parts that carry meaning", () => {
  const css = readFileSync(STYLESHEET, "utf8");

  it("signals an alert with more than colour", () => {
    // Criterion 3. A reader on a monochrome screen, or one who cannot separate the accent from
    // the ink, still has the bar and the weight.
    const rule = /\[role="alert"\]\s*\{([^}]*)\}/.exec(css);

    expect(rule).not.toBeNull();
    expect(rule![1]).toMatch(/border-left:/);
    expect(rule![1]).toMatch(/font-weight:/);
  });

  it("gives every control a visible keyboard focus state", () => {
    // Criterion 5. `:focus-visible` unqualified, so it reaches every control rather than the
    // list of selectors somebody remembered.
    expect(css).toMatch(/^:focus-visible\s*\{/m);
    expect(/:focus-visible\s*\{([^}]*)\}/.exec(css)![1]).toMatch(/outline:\s*\d/);
  });

  it("suppresses motion when the reader has asked for less of it", () => {
    // Criterion 5. There is one transition in the file — the button hover — and this is what
    // turns it off. It is written to cover whatever is added next, too.
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(css).toMatch(/transition-duration:\s*0\.01ms\s*!important/);
  });

  it("draws no connector between a sentence and its evidence", () => {
    // Criterion 4, as far as a source check can reach: the card places the message beside what it
    // cites, and adjacency is the whole claim. A rule that drew a line, an arrow, or a tick
    // between one sentence and one source would assert entailment the system has never checked
    // (§19.3, `T-082`). Nothing generates content here, so nothing can say it.
    expect(css).not.toMatch(/content:\s*["'][^"']/);
  });
});
