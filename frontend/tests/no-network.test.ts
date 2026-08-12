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

  it("fetches only relative paths, so every request is same-origin", () => {
    // `T-195` criterion 2. The client used to fetch `new URL(path, apiBaseUrl)` — an absolute
    // `http://localhost:8000` from a page served on `:3000`, which the browser refuses because
    // the API sets no CORS headers. Nothing caught it: the component tests stub `fetch`, and the
    // exit-evidence run measured server-side rendering, where there is no browser to object. So
    // the check is on the source, and it fails on the shape that broke rather than on a symptom.
    const source = readFileSync(join(ROOT, NETWORK_OWNER), "utf8");
    const targets = [...source.matchAll(/\bfetch\(\s*([^,]+),/g)].map((match) =>
      match[1]?.trim(),
    );

    // Guard on the guard: a regex that matched nothing would pass this silently.
    expect(targets.length).toBeGreaterThanOrEqual(10);

    for (const target of targets) {
      // A relative literal, a template literal starting with one, or `path` — the one variable
      // holding a request path, asserted to be relative by the next test.
      expect(target).toMatch(/^(["`]\/|path$)/);
    }
  });

  it("builds its one computed request path relatively too", () => {
    // `decide()` passes a variable, so the check above cannot see its value.
    const source = readFileSync(join(ROOT, NETWORK_OWNER), "utf8");

    expect(source).toMatch(/const path = `\/api\//);
  });

  it("constructs no URL object outside the local-host check", () => {
    // The tripwire on the regression itself. `new URL(relative)` throws without a base, so the
    // way this defect comes back is somebody reintroducing `new URL(path, apiBaseUrl)` to fix
    // that throw — which silently restores absolute, cross-origin requests. The only permitted
    // `new URL` is `assertLocal`'s parse of the proxy target, which never reaches the browser.
    const source = readFileSync(join(ROOT, NETWORK_OWNER), "utf8");

    expect(source.match(/new URL\(/g)).toHaveLength(1);
    expect(source).toMatch(/parsed = new URL\(rawUrl\);/);
  });

  it("rewrites the paths those relative fetches depend on", async () => {
    // `T-200`. The other half of `T-195`'s contract, and the half that actually carries the
    // request. Relative paths are only same-origin *and useful* because `next.config.ts` proxies
    // them to the backend; delete that block and every test above still passes, the build still
    // succeeds, and every fetch quietly 404s against the Next server. No scan of `lib/api.ts`
    // can see it, because that half stays correct.
    const config = (await import("../next.config")).default;

    expect(typeof config.rewrites).toBe("function");
    const rules = (await config.rewrites!()) as Array<{ source: string; destination: string }>;
    const sources = (Array.isArray(rules) ? rules : []).map((rule) => rule.source);

    // `/api/:path*` carries every authenticated call; the health routes are not under `/api`
    // and would be missed by a rule that only covered it.
    expect(sources).toContain("/api/:path*");
    expect(sources).toContain("/healthz");
    expect(sources).toContain("/readyz");
  });

  it("sends those rewrites only to a local backend", async () => {
    // `T-200` criterion 2. The rewrite is the one place in the repository that names a backend
    // address, so it is the one place a remote one could be introduced without touching the
    // module `assertLocal` guards.
    const config = (await import("../next.config")).default;
    const rules = (await config.rewrites!()) as Array<{ source: string; destination: string }>;

    expect((Array.isArray(rules) ? rules : []).length).toBeGreaterThan(0);
    for (const rule of Array.isArray(rules) ? rules : []) {
      expect(new URL(rule.destination).hostname).toBe("localhost");
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
