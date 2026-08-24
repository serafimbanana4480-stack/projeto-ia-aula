import { describe, expect, it, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useThemeStore } from "../../stores/themeStore";

describe("themeStore", () => {
  beforeEach(() => {
    act(() => {
      useThemeStore.setState({ theme: "dark" });
    });
  });

  it("starts with dark theme", () => {
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("setTheme changes theme to light", () => {
    act(() => {
      useThemeStore.getState().setTheme("light");
    });
    expect(useThemeStore.getState().theme).toBe("light");
  });

  it("setTheme changes theme to system", () => {
    act(() => {
      useThemeStore.getState().setTheme("system");
    });
    expect(useThemeStore.getState().theme).toBe("system");
  });

  it("setTheme changes theme to dark", () => {
    act(() => {
      useThemeStore.setState({ theme: "light" });
      useThemeStore.getState().setTheme("dark");
    });
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("toggleTheme switches dark to light", () => {
    act(() => {
      useThemeStore.setState({ theme: "dark" });
      useThemeStore.getState().toggleTheme();
    });
    expect(useThemeStore.getState().theme).toBe("light");
  });

  it("toggleTheme switches light to dark", () => {
    act(() => {
      useThemeStore.setState({ theme: "light" });
      useThemeStore.getState().toggleTheme();
    });
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("toggleTheme on system goes to dark (only dark/light toggle)", () => {
    act(() => {
      useThemeStore.setState({ theme: "system" });
      useThemeStore.getState().toggleTheme();
    });
    // system !== "dark" so toggleTheme goes to "dark"
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("toggleTheme multiple times cycles", () => {
    act(() => {
      useThemeStore.setState({ theme: "dark" });
      useThemeStore.getState().toggleTheme();
    });
    expect(useThemeStore.getState().theme).toBe("light");
    act(() => {
      useThemeStore.getState().toggleTheme();
    });
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("setTheme accepts all valid theme values", () => {
    for (const theme of ["dark", "light", "system"] as const) {
      act(() => {
        useThemeStore.getState().setTheme(theme);
      });
      expect(useThemeStore.getState().theme).toBe(theme);
    }
  });
});
