import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3000',
    storageState: 'test-results/.auth/user.json',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    // pnpm, not npm. This is a pnpm-only project (packageManager:
    // pnpm@11.17.0, pnpm-lock.yaml, AGENTS.md mandates pnpm), and `npm run dev`
    // in a pnpm workspace resolves binaries and env differently -- it worked by
    // accident locally and would not work under `pnpm exec playwright test`.
    // Reachable now via `pnpm run test:e2e` (added to package.json); before
    // that, no script existed and these 3 specs could not be run at all.
    command: 'pnpm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
