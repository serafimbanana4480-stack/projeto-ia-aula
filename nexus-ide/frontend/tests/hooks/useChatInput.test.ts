import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useChatInput } from "../../hooks/useChatInput";

describe("useChatInput", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("starts with empty draft", () => {
    const { result } = renderHook(() => useChatInput());
    expect(result.current.draft).toBe("");
  });

  it("loads draft from localStorage on mount", () => {
    localStorage.setItem("nexus.chat.draft", "saved draft text");
    const { result } = renderHook(() => useChatInput());
    expect(result.current.draft).toBe("saved draft text");
  });

  it("setValue updates draft and persists to localStorage", () => {
    const { result } = renderHook(() => useChatInput());
    act(() => {
      result.current.setValue("new text");
    });
    expect(result.current.draft).toBe("new text");
    expect(localStorage.getItem("nexus.chat.draft")).toBe("new text");
  });

  it("setValue dispatches custom event", () => {
    const eventSpy = vi.fn();
    window.addEventListener("nexus:chat-input", eventSpy);
    const { result } = renderHook(() => useChatInput());
    act(() => {
      result.current.setValue("some value");
    });
    expect(eventSpy).toHaveBeenCalledTimes(1);
    expect(eventSpy.mock.calls[0][0].detail).toBe("some value");
    window.removeEventListener("nexus:chat-input", eventSpy);
  });

  it("clear removes draft from state and localStorage", () => {
    localStorage.setItem("nexus.chat.draft", "saved");
    const { result } = renderHook(() => useChatInput());
    expect(result.current.draft).toBe("saved");
    act(() => {
      result.current.clear();
    });
    expect(result.current.draft).toBe("");
    expect(localStorage.getItem("nexus.chat.draft")).toBeNull();
  });

  it("handles localStorage errors gracefully on read", () => {
    const original = window.localStorage;
    const throwingStorage = {
      getItem: vi.fn(() => {
        throw new Error("Quota exceeded");
      }),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    };
    Object.defineProperty(window, "localStorage", {
      get: () => throwingStorage,
      configurable: true,
    });
    // Should not throw
    const { result } = renderHook(() => useChatInput());
    expect(result.current.draft).toBe("");
    Object.defineProperty(window, "localStorage", {
      get: () => original,
      configurable: true,
    });
  });

  it("handles localStorage errors gracefully on write", () => {
    const { result } = renderHook(() => useChatInput());
    const original = window.localStorage;
    const throwingStorage = {
      getItem: vi.fn(),
      setItem: vi.fn(() => {
        throw new Error("Quota exceeded");
      }),
      removeItem: vi.fn(),
      clear: vi.fn(),
    };
    Object.defineProperty(window, "localStorage", {
      get: () => throwingStorage,
      configurable: true,
    });
    // Should not throw
    act(() => {
      result.current.setValue("text");
    });
    expect(result.current.draft).toBe("text");
    Object.defineProperty(window, "localStorage", {
      get: () => original,
      configurable: true,
    });
  });
});
