import type { NextConfig } from "next";

/**
 * Next.js configuration for the internal review dashboard.
 *
 * `reactStrictMode` is on because this app will render evidence and drafts a reviewer acts on,
 * and a double-invoked render surfacing an accidental side effect during development is cheaper
 * than finding it once an approval depends on it.
 *
 * There is deliberately no `rewrites`, `redirects`, `images.remotePatterns`, or external origin
 * anywhere in this file. `T-060b` adds the generated API client and points it at the local API;
 * until then the dashboard talks to nothing at all, which `tests/no-network.test.ts` enforces.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
