import type { NextConfig } from "next";

import { apiBaseUrl } from "./lib/api";

/**
 * Next.js configuration for the internal review dashboard.
 *
 * `reactStrictMode` is on because this app will render evidence and drafts a reviewer acts on,
 * and a double-invoked render surfacing an accidental side effect during development is cheaper
 * than finding it once an approval depends on it.
 *
 * **The rewrites are what make the dashboard usable at all (`T-195`).** The pages fetch from the
 * browser; before this, they fetched `http://localhost:8000` from a page served on
 * `localhost:3000`, which is cross-origin, and the API registers no CORS middleware — so the
 * browser refused every request and nobody could get past sign-in. Proxying here means the
 * browser only ever issues same-origin requests and there is no cross-origin request left to
 * permit. `lib/api.ts` records why this was chosen over a CORS allowance on the API.
 *
 * **The target comes from `apiBaseUrl`, so it is still `assertLocal`-checked.** A rewrite is the
 * one place in this repository that names a backend address, and hard-coding it here would put an
 * unvalidated URL outside the single module §2 item 14's local-only rule is enforced in.
 * Importing it keeps one answer to "where is the backend", and keeps a non-local value a startup
 * error rather than a silent proxy to somewhere real.
 *
 * `/healthz` and `/readyz` are listed because they are not under `/api` — they are the operational
 * probes at the application root, and `getLiveness` fetches the first of them.
 *
 * There is deliberately no `redirects`, `images.remotePatterns`, or external origin here. The
 * proxy target is local and validated; nothing else is reachable.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  rewrites: () =>
    Promise.resolve([
      { source: "/api/:path*", destination: `${apiBaseUrl.origin}/api/:path*` },
      { source: "/healthz", destination: `${apiBaseUrl.origin}/healthz` },
      { source: "/readyz", destination: `${apiBaseUrl.origin}/readyz` },
    ]),
};

export default nextConfig;
