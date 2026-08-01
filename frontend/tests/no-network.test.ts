import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The dashboard reaches the local backend and nothing else (T-060a, narrowed by T-060b).
 *
 * `T-060a` asserted the scaffold contained no `fetch` at all, which was right while there was no
 * typed contract to fetch against. `T-060b` generated one, so the rule narrows rather than
 * disappears: **fetching is allowed in `lib/api.ts` and nowhere else**, and even there only
 * against a base URL `assertLocal` has approved.
 *
 * Narrowing it rather than deleting it is the point. "No network anywhere" stopped being true the
 * moment a real client existed, and a test deleted the first time it fails was never load-bearing.
 * What is still worth enforcing is that every request goes through one reviewed module — a
 * `fetch` in a component would bypass `assertLocal` and every type the generator produced.
 *
 * Asserted over source rather than by rendering: a build-time fetch, a module-scope `new
 * WebSocket`, and a remote `<img src="https://…">` each escape a render-and-watch test in a
 * different way.
 */

const ROOT = join(import.meta.dirname, "..");

/** Directories that are ours. `node_modules` and `.next` are not. */
const OWNED = ["app", "lib", "tests"];

const SOURCE_EXTENSIONS = [".ts", ".tsx", ".mjs", ".js", ".jsx"];

/** The one module permitted to reach the backend. */
const NETWORK_OWNER = join("lib", "api.ts");

/** Generated; its contents are the backend's, not ours to constrain. */
const GENERATED = join("lib", "api-types.ts");

/** The tests themselves name these patterns in order to look for them. */
const TEST_FILES = ["no-network.test.ts", "api-types.test.ts"];

function sourceFiles(): string[] {
  const found: string[] = [];
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      if (SOURCE_EXTENSIONS.some((extension) => entry.endsWith(extension))) {
        found.push(path);
      }
    }
  };
  for (const owned of OWNED) {
    walk(join(ROOT, owned));
  }
  for (const config of ["next.config.ts", "eslint.config.mjs", "vitest.config.ts"]) {
    found.push(join(ROOT, config));
  }
  return found;
}

/** Files the rules below apply to: ours, excluding the generated types and the tests. */
function constrainedFiles(): string[] {
  return sourceFiles().filter(
    (path) => !path.endsWith(GENERATED) && !TEST_FILES.some((name) => path.endsWith(name)),
  );
}

/** Every way this app could reach something, and the name each would go by. */
const NETWORK_PATTERNS: ReadonlyArray<readonly [string, RegExp]> = [
  ["fetch", /\bfetch\s*\(/],
  ["XMLHttpRequest", /\bXMLHttpRequest\b/],
  ["WebSocket", /\bnew\s+WebSocket\b/],
  ["EventSource", /\bnew\s+EventSource\b/],
  ["node:http", /from\s+["']node:https?["']/],
];

describe("only the API client reaches the network", () => {
  it("finds the files it claims to be checking", () => {
    const files = constrainedFiles();

    // A guard on the guard: a walk that found nothing would make every assertion below
    // vacuously true, which is the same failure mode as having no test at all.
    expect(files.length).toBeGreaterThanOrEqual(6);
    expect(files.some((path) => path.endsWith("page.tsx"))).toBe(true);
    expect(files.some((path) => path.endsWith(NETWORK_OWNER))).toBe(true);
  });

  it.each(NETWORK_PATTERNS)("uses no %s outside the API client", (_name, pattern) => {
    const offenders = constrainedFiles().filter(
      (path) => !path.endsWith(NETWORK_OWNER) && pattern.test(readFileSync(path, "utf8")),
    );

    expect(offenders).toEqual([]);
  });

  it("hard-codes no absolute URL outside the API client", () => {
    const offenders = constrainedFiles().filter(
      (path) => !path.endsWith(NETWORK_OWNER) && /["']https?:\/\//.test(readFileSync(path, "utf8")),
    );

    expect(offenders).toEqual([]);
  });

  it("names only local hosts even inside the API client", () => {
    // The client may fetch; it may not know about a remote host. Every absolute URL literal in
    // it has to be one `assertLocal` would accept.
    const source = readFileSync(join(ROOT, NETWORK_OWNER), "utf8");
    const urls = source.match(/["']https?:\/\/[^"']+["']/g) ?? [];

    expect(urls.length).toBeGreaterThan(0);
    for (const raw of urls) {
      expect(new URL(raw.slice(1, -1)).hostname).toBe("localhost");
    }
  });

  it("declares no dependency whose purpose is fetching", () => {
    const manifest = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8")) as {
      dependencies?: Record<string, string>;
    };

    expect(Object.keys(manifest.dependencies ?? {}).sort()).toEqual([
      "next",
      "react",
      "react-dom",
    ]);
  });
});
