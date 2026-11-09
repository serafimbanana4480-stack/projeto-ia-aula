import { defineConfig, devices } from "@playwright/test";

const port = process.env.OVERHAUL_WEB_PORT || "3010";
const apiPort = process.env.OVERHAUL_API_PORT || "8765";

export default defineConfig({
  testDir: "./e2e/overhaul",
  testIgnore: "**/backend.spec.ts",
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
  webServer: [
    {
      command: "node e2e/overhaul/fixture-server.mjs",
      url: `http://127.0.0.1:${apiPort}/api/auth/me`,
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      command: `pnpm exec next dev --turbopack -p ${port}`,
      url: `http://127.0.0.1:${port}/login`,
      reuseExistingServer: true,
      timeout: 180_000,
      env: {
        NEXT_PUBLIC_API_URL: `http://127.0.0.1:${apiPort}`,
        NEXT_PUBLIC_DEV_EMAIL: "dev@nexus.local",
        NEXT_PUBLIC_DEV_PASSWORD: "fixture-only",
        NEXT_PUBLIC_AUTO_LOGIN: "true",
      },
    },
  ],
});
