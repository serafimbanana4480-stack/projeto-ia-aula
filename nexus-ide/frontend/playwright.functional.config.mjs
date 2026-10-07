import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const envFile = path.join(frontendRoot, ".env.local");
const sanitizedPublicEnv = {};

// Next loads .env.local itself. Blank every client-visible value from that
// file in the dedicated fixture process so a browser smoke cannot inherit a
// provider key or start the dev auto-login flow.
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*(NEXT_PUBLIC_[A-Z0-9_]+)\s*=/i);
    if (match) sanitizedPublicEnv[match[1]] = "";
  }
}

const appPort = "3222";
const existingOrigin = process.env.NEXUS_VISUAL_ORIGIN;

export default defineConfig({
  testDir: "./e2e/functional",
  testMatch: "**/*.spec.mjs",
  outputDir: "./test-results-functional/playwright-output",
  timeout: 60_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: existingOrigin || `http://127.0.0.1:${appPort}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    reducedMotion: "reduce",
  },
  webServer: existingOrigin ? undefined : {
    command: `pnpm exec next dev --turbopack --port ${appPort}`,
    url: `http://127.0.0.1:${appPort}/login`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      ...sanitizedPublicEnv,
      NEXT_PUBLIC_API_URL: "http://127.0.0.1:8000",
      NEXT_PUBLIC_AUTO_LOGIN: "false",
      NEXT_PUBLIC_DEV_EMAIL: "",
      NEXT_PUBLIC_DEV_PASSWORD: "",
      NEXT_TELEMETRY_DISABLED: "1",
      PORT: appPort,
    },
  },
});
