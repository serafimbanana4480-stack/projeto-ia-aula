import { describe, expect, it, vi, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts";

function makeKeyboardEvent(key: string, modifiers: Record<string, boolean> = {}): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { key, ...modifiers });
  Object.defineProperty(event, "target", {
    value: document.body,
    configurable: true,
  });
  return event;
}

describe("useKeyboardShortcuts", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("registers keydown listener on mount", () => {
    const addSpy = vi.spyOn(window, "addEventListener");
    renderHook(() => useKeyboardShortcuts([]));
    expect(addSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
  });

  it("removes keydown listener on unmount", () => {
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = renderHook(() => useKeyboardShortcuts([]));
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
  });

  it("calls callback when key matches", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback, description: "Submit" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("Enter"));
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("does not call callback when key does not match", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback, description: "Submit" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("Escape"));
    expect(callback).not.toHaveBeenCalled();
  });

  it("matches key case-insensitively", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback, description: "Submit" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("enter"));
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("matches with ctrlKey", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "k", ctrlKey: true, callback, description: "Command K" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("k", { ctrlKey: true }));
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("does not match when ctrlKey is required but not pressed", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "k", ctrlKey: true, callback, description: "Command K" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("k", { ctrlKey: false }));
    expect(callback).not.toHaveBeenCalled();
  });

  it("matches with shiftKey", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "K", shiftKey: true, callback, description: "Shift+K" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("K", { shiftKey: true }));
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("matches with altKey", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "a", altKey: true, callback, description: "Alt+A" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("a", { altKey: true }));
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("matches with metaKey", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "b", metaKey: true, callback, description: "Meta+B" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("b", { metaKey: true }));
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("calls preventDefault on matched shortcut", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback, description: "Submit" },
      ]),
    );
    const event = makeKeyboardEvent("Enter");
    const preventSpy = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(preventSpy).toHaveBeenCalled();
  });

  it("ignores shortcuts when typing in input", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback, description: "Submit" },
      ]),
    );
    const input = document.createElement("input");
    const event = new KeyboardEvent("keydown", { key: "Enter" });
    Object.defineProperty(event, "target", { value: input, configurable: true });
    window.dispatchEvent(event);
    expect(callback).not.toHaveBeenCalled();
  });

  it("ignores shortcuts when typing in textarea", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback, description: "Submit" },
      ]),
    );
    const textarea = document.createElement("textarea");
    const event = new KeyboardEvent("keydown", { key: "Enter" });
    Object.defineProperty(event, "target", { value: textarea, configurable: true });
    window.dispatchEvent(event);
    expect(callback).not.toHaveBeenCalled();
  });

  it("ignores shortcuts when target is contentEditable", () => {
    const callback = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback, description: "Submit" },
      ]),
    );
    const div = document.createElement("div");
    Object.defineProperty(div, "isContentEditable", { value: true, configurable: true });
    const event = new KeyboardEvent("keydown", { key: "Enter" });
    Object.defineProperty(event, "target", { value: div, configurable: true });
    window.dispatchEvent(event);
    expect(callback).not.toHaveBeenCalled();
  });

  it("matches first shortcut in list that matches", () => {
    const callback1 = vi.fn();
    const callback2 = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback: callback1, description: "Submit" },
        { key: "Enter", ctrlKey: true, callback: callback2, description: "Ctrl+Enter" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("Enter"));
    expect(callback1).toHaveBeenCalledTimes(1);
    expect(callback2).not.toHaveBeenCalled();
  });

  it("handles multiple different shortcuts", () => {
    const cb1 = vi.fn();
    const cb2 = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "Enter", callback: cb1, description: "Submit" },
        { key: "Escape", callback: cb2, description: "Cancel" },
      ]),
    );
    window.dispatchEvent(makeKeyboardEvent("Enter"));
    window.dispatchEvent(makeKeyboardEvent("Escape"));
    expect(cb1).toHaveBeenCalledTimes(1);
    expect(cb2).toHaveBeenCalledTimes(1);
  });
});
