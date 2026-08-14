import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every review action the backend offers is reachable from the dashboard (T-205).
 *
 * `T-071c`'s rehearsal found that `POST /api/review/revisions/{revision_id}/approve` existed in
 * the API, was published in `openapi.json`, appeared in the generated `api-types.ts`, was granted
 * to the `operator_reviewer` role, and produced a queue entry reading "Messages awaiting
 * approval" — and **no code called it**. Three independent readers reached the drafted message,
 * decided on it, and had nowhere to record the decision. Half of §12.3 item 6 had no user
 * interface.
 *
 * Every existing check passed throughout. The backend suite tested the endpoint; the component
 * suite tested the queue that advertised it; `api-types.test.ts` proved the type chain intact.
 * Each arrow was verified and the last one — *something actually calls this* — was not an arrow
 * anybody had drawn. A generated type is not a caller, and a route in a document is not a button.
 *
 * So this test walks the **mutating** review routes in `openapi.json` and requires each to appear
 * in a `fetch` in `lib/api.ts`, and each of those client functions to be called from a component.
 * Two hops, because either one alone is satisfiable while the reviewer is still stuck: a client
 * function nothing imports is as unreachable as no client function at all.
 *
 * Scoped to `/api/review/**` on purpose. `/api/operations/**` is administrator-only and its panel
 * is separate; `/api/auth/**` is the session, not a review action. Widening this to every route
 * would demand callers for endpoints the dashboard is not the client for.
 *
 * **Where this file stops, and what carries on from there.** A component that calls a client
 * function but is never *rendered* still passes both checks here — measured, not assumed: removing
 * `<ApproveMessageForm />` from the card left this file green, because the component still existed
 * and still called `approveRevision`. That third hop belongs to
 * `review-card.test.tsx::offers all six of §12.3 item 6's actions`, which renders the card and
 * asserts the exact set of button labels. The two together cover the `T-071c` defect; neither does
 * alone, and the label assertion is the one that fails if a control silently leaves the card.
 */

const ROOT = join(import.meta.dirname, "..");
const CLIENT = join(ROOT, "lib", "api.ts");

/** Methods that change something. A reviewer's actions are all of these. */
const MUTATING = new Set(["post", "put", "patch", "delete"]);

/** The surface a reviewer works. See the note above on why this is not every route. */
const REVIEWED_PREFIX = "/api/review/";

type OpenApi = { paths: Record<string, Record<string, unknown>> };

function mutatingReviewRoutes(): string[] {
  const document = JSON.parse(readFileSync(join(ROOT, "openapi.json"), "utf8")) as OpenApi;
  return Object.entries(document.paths)
    .filter(([route]) => route.startsWith(REVIEWED_PREFIX))
    .filter(([, operations]) => Object.keys(operations).some((method) => MUTATING.has(method)))
    .map(([route]) => route)
    .sort();
}

/**
 * The route as it can appear in a template literal in the client.
 *
 * Segment by segment, because two different substitutions happen and a first attempt at this
 * missed the second. A path parameter (`{revision_id}`) is obviously `${…}`. But a **literal**
 * segment can be interpolated too: `decide()` builds
 * `/api/review/candidates/${candidateId}/${action}` and serves reject, defer, and
 * request-research from one template, so the literal `reject` never appears in the path at all.
 * Requiring literals to be literal reported three perfectly reachable routes as missing.
 *
 * So every segment matches either itself or an interpolation. That is deliberately loose — it
 * proves a fetch of that *shape* exists, not that this exact route is reachable. The second test
 * below carries the weight the looseness gives up.
 */
function fetchPattern(route: string): RegExp {
  const segments = route.split("/").filter(Boolean);
  const source = segments
    .map((segment) => {
      const interpolated = "\\$\\{[^}]*\\}";
      if (/^\{[^}]+\}$/.test(segment)) {
        return interpolated;
      }
      return "(?:" + segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "|" + interpolated + ")";
    })
    .join("/");
  return new RegExp("[\"`]/" + source);
}

function componentSources(): string[] {
  const found: string[] = [];
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      if (entry.endsWith(".tsx") || entry.endsWith(".ts")) {
        found.push(readFileSync(path, "utf8"));
      }
    }
  };
  walk(join(ROOT, "app"));
  return found;
}

/** Exported function names in `lib/api.ts`, paired with the body that follows each. */
function clientFunctions(): Array<[string, string]> {
  const source = readFileSync(CLIENT, "utf8");
  const found: Array<[string, string]> = [];
  const pattern = /export async function (\w+)\(/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(source)) !== null) {
    const next = source.indexOf("export ", match.index + 1);
    found.push([match[1] as string, source.slice(match.index, next === -1 ? undefined : next)]);
  }
  return found;
}

describe("every review action the backend offers is reachable", () => {
  it("finds the routes it claims to be checking", () => {
    // Guard on the guard: an empty route list would make the check below vacuously true, which is
    // precisely the shape of the bug it exists to catch.
    const routes = mutatingReviewRoutes();

    expect(routes.length).toBeGreaterThanOrEqual(5);
    expect(routes).toContain("/api/review/revisions/{revision_id}/approve");
  });

  it.each(mutatingReviewRoutes())("%s is fetched by lib/api.ts", (route) => {
    const client = readFileSync(CLIENT, "utf8");

    expect(fetchPattern(route).test(client)).toBe(true);
  });

  it("every client function that fetches a review route is called by a component", () => {
    // The second hop, and the one carrying the weight. A client function nothing imports leaves
    // the reviewer exactly as stuck as no client function would, and the route check above — now
    // deliberately loose about interpolation — cannot see the difference on its own.
    //
    // This is the check that fails on the actual `T-071c` defect: had `approveRevision` been
    // written and never rendered, it would be listed here.
    const components = componentSources().join("\n");
    const orphans = clientFunctions()
      .filter(([, body]) => new RegExp(`fetch\\(\\s*[\`"]${REVIEWED_PREFIX}`).test(body))
      .map(([name]) => name)
      .filter((name) => !new RegExp(`\\b${name}\\b`).test(components));

    expect(orphans).toEqual([]);
  });
});
