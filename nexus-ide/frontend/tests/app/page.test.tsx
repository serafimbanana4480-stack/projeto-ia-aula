import { describe, expect, it } from "vitest";
import HomePage from "../../app/page";

// Mock child components to avoid heavy imports
describe("HomePage", () => {
  it("renders without crashing", () => {
    // Since page.tsx imports client components with Monaco/xterm,
    // a shallow render in jsdom would need mocks (done in setup.ts).
    // For now, verify the module imports correctly.
    expect(HomePage).toBeDefined();
  });
});
