import { defineConfig, devices } from "@playwright/test";

/**
 * Frontend against the real FastAPI process on :8000.
 * The API is started separately with no cloud keys and background services off.
 */
const port = process.env.BACKEND_WEB_PORT || "3011";

export default defineConfig({
  testDir: "./e2e/overhaul",
  testMatch: "**/backend.spec.ts",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm exec next dev --turbopack -p ${port}`,
    url: `http://127.0.0.1:${port}/login`,
    reuseExistingServer: true,
    timeout: 180_000,
    env: {
      NEXT_PUBLIC_API_URL: "http://127.0.0.1:8000",
      NEXT_PUBLIC_DEV_EMAIL: "dev@example.com",
      NEXT_PUBLIC_DEV_PASSWORD: "fixture-only1",
      NEXT_PUBLIC_AUTO_LOGIN: "true",
    },
  },
});
