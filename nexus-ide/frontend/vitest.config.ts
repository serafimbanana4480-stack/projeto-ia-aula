import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // Playwright specs live in `e2e/` and must run through the Playwright
    // runner, not Vitest. Without this exclusion, `pnpm test` imports
    // `test.describe()` outside a Playwright worker and fails before running
    // the unit suite.
    exclude: ["e2e/**", "node_modules/**"],
  },
});
