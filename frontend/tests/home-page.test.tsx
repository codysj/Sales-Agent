// @vitest-environment jsdom

import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Home from "../app/page";

/**
 * The entry page tells the truth and is the way in (T-159; §12.3, §19.6).
 *
 * Two failures, and the second is the one that will come back. The copy went stale because
 * nothing checked it against what had been built — so the first group asserts the specific
 * sentences that were false, not the vague shape of the page. The second group does not enumerate
 * today's routes at all: it **walks `app/` for pages** and requires each static one to be linked,
 * so the next screen somebody adds without a link fails here rather than becoming unreachable and
 * being noticed months later.
 */

const APP = join(import.meta.dirname, "..", "app");

/**
 * Claims that were true when they were written and are not true now.
 *
 * The first two are `T-060a`'s scaffold copy, false since `T-063a`. The third is `T-159`'s own
 * honest note that no screen listed the queue — true for exactly one cycle, until `T-160` built
 * it. Both kinds belong in the same list: a page that under-claims sends a reviewer away just as
 * effectively as one that over-claims.
 */
const STALE_CLAIMS = [
  "The review queue is not built yet",
  "does not read them yet",
  "no page listing the queue yet",
];

/**
 * Static routes served by `app/**\/page.tsx`, as hrefs.
 *
 * Dynamic segments are excluded because a link to `/review/[candidateId]` is not a link a page
 * can render — there is no candidate to name. The entry page covers that case in prose instead,
 * and `test_the_card_route_is_explained` holds it.
 */
function staticRoutes(): string[] {
  const found: string[] = [];
  const walk = (directory: string, prefix: string): void => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (!statSync(path).isDirectory()) {
        continue;
      }
      if (entry.startsWith("[")) {
        continue;
      }
      const route = `${prefix}/${entry}`;
      if (readdirSync(path).includes("page.tsx")) {
        found.push(route);
      }
      walk(path, route);
    }
  };
  walk(APP, "");
  return found.sort();
}

function hrefs(): string[] {
  return screen
    .getAllByRole<HTMLAnchorElement>("link")
    .map((anchor) => anchor.getAttribute("href") ?? "");
}

afterEach(() => {
  cleanup();
});

// --- criterion 1: it no longer describes an unbuilt dashboard ------------------------------------

describe("what the entry page claims", () => {
  it.each(STALE_CLAIMS)("no longer says %s", (claim) => {
    render(<Home />);

    expect(document.body.textContent ?? "").not.toContain(claim);
  });

  it("says what the dashboard is for and that nothing is sent unapproved", () => {
    render(<Home />);

    const text = document.body.textContent ?? "";
    expect(text).toContain("reviewing candidates and approving exact message revisions");
    expect(text).toContain("G-07");
  });

  it("points at the queue rather than apologising for it", () => {
    // `T-159` had to say the queue index did not exist. `T-160` built it, so the honest sentence
    // became the stale one — asserted here as a link, not as prose, because that is what changed.
    render(<Home />);

    expect(screen.getByRole("link", { name: "Review queue" }).getAttribute("href")).toBe("/review");
  });
});

// --- criterion 2: every reviewer-facing route is reachable by a link -----------------------------

describe("navigation", () => {
  it("finds the pages it claims to be checking", () => {
    // A guard on the guard: a walk that found nothing would make the assertion below vacuous,
    // which is the same as having no test.
    const routes = staticRoutes();

    expect(routes.length).toBeGreaterThanOrEqual(2);
    expect(routes).toContain("/sign-in");
    expect(routes).toContain("/attention");
  });

  it("links to every static page the app serves", () => {
    render(<Home />);
    const linked = hrefs();

    for (const route of staticRoutes()) {
      expect(linked).toContain(route);
    }
  });

  it("names each link by what a reviewer would go there to do", () => {
    // Asserted on the accessible name, not the href: a link reading "click here" is reachable
    // and useless, and G-10 is about somebody who does not know the routes.
    render(<Home />);

    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Approvals needing attention" })).toBeTruthy();
  });

  it("explains the one route it cannot link", () => {
    render(<Home />);

    expect(document.body.textContent ?? "").toContain("/review/<candidate id>");
  });
});
