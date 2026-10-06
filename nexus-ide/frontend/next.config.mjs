/**
 * @file next.config.mjs
 *
 * NOTE: WebSocket connections are NOT proxied here.
 *
 * Next.js `rewrites()` only performs HTTP(S) proxying; it does not perform a
 * WebSocket upgrade. A `/ws/:path*` rewrite therefore looked like it worked
 * (the browser connected to the frontend origin, so no CORS error) while every
 * frame went nowhere. The rewrite has been removed rather than left as a
 * trap; see `rewrites()` below.
 *
 * How WS actually reaches the backend:
 *   - dev:  the client connects directly to the backend WS URL
 *           (NEXT_PUBLIC_API_URL with an http->ws scheme swap).
 *   - prod: put a reverse proxy (nginx, caddy) in front of BOTH http and the WS
 *           upgrade on the same origin. `connect-src` in the CSP below already
 *           allows that origin.
 */

import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backendUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Keep `next dev` and `next build` out of each other's output directory.
 *
 * Both commands mutate their dist directory. Running them concurrently used
 * to corrupt the live dev server: production build cleanup removed webpack
 * packs and manifests while `next dev` was serving them, producing ENOENT,
 * MODULE_NOT_FOUND, and HTTP 500 responses.
 *
 * @param {string} phase
 * @returns {import('next').NextConfig}
 */
const createNextConfig = (phase) => ({
  distDir: process.env.NEXUS_NEXT_DIST_DIR ?? (phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next"),
  reactStrictMode: true,
  typedRoutes: true,
  devIndicators: false,

  // Without this, Next infers the tracing root by walking up for a lockfile.
  // A stray `C:\Users\rodri\package-lock.json` (two levels above this project)
  // made it resolve to the home directory, which produced a warning on every
  // `next dev` / `next build` / `next lint` and, worse, mis-scoped standalone
  // output tracing so a Docker image could miss real dependencies. Pin it to
  // this directory explicitly.
  outputFileTracingRoot: __dirname,

  // ESLint during `next build`: run the flat config through the real CLI
  // instead of Next's built-in integration, which only understands eslintrc and
  // whose bridge is removed in Next 16. `pnpm run lint` is the real gate; this
  // only stops `next build` from silently re-deriving its own (narrower) set.
  eslint: {
    ignoreDuringBuilds: true,
  },

  compiler: {
    removeConsole:
      process.env.NODE_ENV === "production"
        ? { exclude: ["error", "warn"] }
        : false,
  },
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts", "framer-motion"],
  },
  // Security headers applied to every route.
  // CSP mirrors backend/middleware/security.py DEFAULT_CSP so the browser
  // policy matches what the ASGI layer sets for API responses. Monaco editor
  // (web workers + eval-based AMD loader) and Next.js hydration require
  // 'unsafe-eval' / 'unsafe-inline'; tighter nonce-based policy is a
  // documented follow-up.
  //
  // connect-src includes the backend API URL so browser fetch/XHR/WS to the
  // backend is not blocked by CSP. Without this, the browser silently fails
  // with "Failed to fetch" / TypeError: Failed to fetch.
  async headers() {
    const apiUrl = backendUrl;
    const wsUrl = apiUrl.replace(/^http/, "ws");
    const csp = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-eval' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob: https://imgs.search.brave.com",
      "font-src 'self' data:",
      `connect-src 'self' ${apiUrl} ${wsUrl}`,
      "worker-src 'self' blob:",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "object-src 'none'",
    ].join("; ");

    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
  async rewrites() {
    // The `/ws/:path*` rewrite that used to live here was removed. Next's
    // rewrites do not perform a WebSocket upgrade, so it could never have
    // worked; it only made the browser connect to the frontend origin and fail
    // silently. WS traffic goes direct to `backendUrl` (see the file header).
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${backendUrl}/health`,
      },
    ];
  },
});

export default createNextConfig;
