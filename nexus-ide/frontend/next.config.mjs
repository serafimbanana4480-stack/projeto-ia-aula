/**
 * @file next.config.mjs
 *
 * NOTE: Next.js rewrites only support HTTP(S) destinations.
 * WebSocket connections cannot be proxied via rewrites.
 * In dev, the frontend connects to the backend WebSocket directly.
 * For production, use a reverse proxy (nginx, caddy) that handles
 * HTTP and WS upgrade on the same port.
 */

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  devIndicators: false,

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
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const wsUrl = apiUrl.replace(/^http/, "ws");
    const csp = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-eval' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob: https://ui-avatars.com",
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
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8003/api/:path*",
      },
      {
        source: "/health",
        destination: "http://localhost:8003/health",
      },
      // WebSocket connections are handled by connecting directly to
      // the backend. This rewrite is kept for non-WS fallback only;
      // Next.js rewrites do NOT support the WS protocol.
      {
        source: "/ws/:path*",
        destination: "http://localhost:8003/ws/:path*",
      },
    ];
  },
};

export default nextConfig;
