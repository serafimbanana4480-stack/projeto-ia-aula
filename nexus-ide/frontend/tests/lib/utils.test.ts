import { describe, expect, it } from "vitest";
import { stripAnsiCodes } from "../../lib/utils";

describe("lib/utils", () => {
  describe("stripAnsiCodes", () => {
    it("removes ANSI escape codes", () => {
      expect(stripAnsiCodes("\x1b[31mRed text\x1b[0m")).toBe("Red text");
    });

    it("handles multiple ANSI codes", () => {
      expect(stripAnsiCodes("\x1b[1;32mGreen\x1b[0m \x1b[34mBlue\x1b[0m")).toBe("Green Blue");
    });

    it("returns plain text unchanged", () => {
      expect(stripAnsiCodes("Hello, world!")).toBe("Hello, world!");
    });

    it("handles empty string", () => {
      expect(stripAnsiCodes("")).toBe("");
    });

    it("handles codes with various parameters", () => {
      const input = "\x1b[38;5;196mColored\x1b[39m text\x1b[0m";
      expect(stripAnsiCodes(input)).toBe("Colored text");
    });

    it("handles cursor movement codes", () => {
      const input = "text\x1b[1;1Hcursor\x1b[K";
      expect(stripAnsiCodes(input)).toBe("textcursor");
    });
  });
});
