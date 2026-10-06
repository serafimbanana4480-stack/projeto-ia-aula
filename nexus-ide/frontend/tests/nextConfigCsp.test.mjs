import { describe, expect, it } from "vitest";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";
import createNextConfig from "../next.config.mjs";

describe("Next Content Security Policy for Brave image previews", () => {
  it("allows only Brave's documented thumbnail proxy host", async () => {
    const config = createNextConfig(PHASE_DEVELOPMENT_SERVER);
    const headers = await config.headers();
    const csp = headers[0].headers.find((header) => header.key === "Content-Security-Policy").value;

    const imageDirective = csp.split(";").map((directive) => directive.trim()).find((directive) => directive.startsWith("img-src "));

    expect(imageDirective).toBe("img-src 'self' data: blob: https://imgs.search.brave.com");
    expect(imageDirective).not.toContain("*.search.brave.com");
  });
});
