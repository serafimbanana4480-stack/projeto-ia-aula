import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { configDefaults } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // MUST start from `configDefaults.exclude`. A bare `exclude` array REPLACES
    // Vitest's defaults rather than extending them, which is how `.next*`,
    // `playwright-report/`, `test-results/` and `coverage/` became collectable:
    // a stray compiled chunk or an HTML report can satisfy the default
    // include globs and Vitest will try to run it as a test file.
    //
    // `node_modules/**` is already in configDefaults.exclude; it is repeated
    // below only to document that it must not be dropped.
    //
    // Playwright specs live in `e2e/` and must run through the Playwright
    // runner, not Vitest. Without this exclusion, `pnpm test` imports
    // `test.describe()` outside a Playwright worker and fails before running
    // the unit suite. Use `pnpm run test:e2e` for those (playwright.config.ts).
    exclude: [
      ...configDefaults.exclude,
      "e2e/**",
      ".next/**",
      ".next-dev/**",
      "node_modules/**",
      "playwright-report/**",
      "playwright_report/**",
      "test-results/**",
      "blob-report/**",
      "coverage/**",
    ],
  },
});
