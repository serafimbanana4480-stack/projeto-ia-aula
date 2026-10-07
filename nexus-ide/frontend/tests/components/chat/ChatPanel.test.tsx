import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Smoke test for ChatPanel -- the app's root chat surface.
 *
 * This file used to be an `expect(true).toBe(true)` stub that imported NOTHING
 * from ChatPanel.tsx, while ChatPanel itself is ~2100 lines and is the single
 * most important component in the frontend. A stub like that is worse than no
 * test: it makes `pnpm test` report coverage of a component that is not
 * exercised at all, and it breaks silently the moment the component stops
 * being importable.
 *
 * SCOPE -- read this before trusting a green run
 * ----------------------------------------------
 * COVERED:
 *   - ChatPanel is importable and its default export is a component.
 *   - It mounts in jsdom without throwing.
 *   - It mounts CLEANLY: zero console.error / console.warn. In a component this
 *     size that is a real assertion -- React logs act() violations, missing
 *     keys, invalid nesting, uncontrolled->controlled switches and state
 *     updates after unmount through those channels, so silence means none of
 *     those fired.
 *   - It renders its core affordances structurally: a <form> composer containing
 *     a <textarea>, exactly one <h1>, and interactive controls.
 *   - It unmounts cleanly, and survives being mounted twice in one test
 *     (catches module-level singletons or leaked listeners that only break the
 *     second instance).
 *
 * NOT COVERED (and cannot be, here):
 *   - Message send/receive, streaming, the event-ordering contract
 *     (lib/eventOrdering.ts <-> backend/runtime/events.py), tool calls, plan
 *     approval, session switching, model/tier selection. Those need a live
 *     backend, a WebSocket server and user interaction, i.e. the Playwright
 *     e2e suite in e2e/, not jsdom.
 *   - Monaco and xterm are stubbed to null by tests/setup.ts; neither mounts in
 *     jsdom.
 *   - No assertion here touches ChatPanel's internals, state shape or copy, so
 *     this file will not fail when the component is refactored internally --
 *     that is deliberate. It is a canary, not a specification.
 *
 * `next/navigation` is mocked because ChatPanel calls useRouter() and
 * useSearchParams(), which throw outside an App Router context. The mock
 * returns inert values: this test never navigates.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));

import ChatPanel from "../../../components/chat/ChatPanel";

describe("ChatPanel", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;
  let consoleWarn: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
    consoleWarn.mockRestore();
  });

  it("exporta um componente por omissão", () => {
    expect(ChatPanel).toBeDefined();
    expect(typeof ChatPanel).toBe("function");
  });

  it("monta sem lançar", () => {
    expect(() => render(<ChatPanel />)).not.toThrow();
  });

  it("monta sem erros nem avisos de consola", () => {
    // React reports act() violations, key warnings, bad DOM nesting,
    // controlled/uncontrolled flips and post-unmount updates via these two.
    const { unmount } = render(<ChatPanel />);
    unmount();

    const noise = [
      ...consoleError.mock.calls.map((c) => `error: ${String(c[0])}`),
      ...consoleWarn.mock.calls.map((c) => `warn: ${String(c[0])}`),
    ];
    expect(noise).toEqual([]);
  });

  it("renderiza o compositor de chat como um formulário com textarea", () => {
    const { container } = render(<ChatPanel />);

    const form = container.querySelector("form");
    expect(form).not.toBeNull();

    // The composer must live inside the form, otherwise Enter-to-send and the
    // form submit handler are not wired to it.
    const textarea = form?.querySelector("textarea");
    expect(textarea).not.toBeNull();
    expect((textarea as HTMLTextAreaElement).disabled).toBe(false);
    expect((textarea as HTMLTextAreaElement).placeholder).toBe(
      "Escreve o que queres fazer…  (/ comandos · @ contexto)",
    );
  });

  it("renderiza exactamente um título de nível 1", () => {
    const { container } = render(<ChatPanel />);

    expect(container.querySelectorAll("h1")).toHaveLength(1);
  });

  it("renderiza controlos interactivos", () => {
    const { container } = render(<ChatPanel />);

    // A chat surface with no buttons at all would mean every control failed to
    // render; the threshold is deliberately loose to survive internal churn.
    expect(container.querySelectorAll("button").length).toBeGreaterThan(0);
  });

  it("desmonta sem erro", () => {
    const { unmount } = render(<ChatPanel />);

    expect(() => unmount()).not.toThrow();
    expect(consoleError.mock.calls).toEqual([]);
  });

  it("suporta duas instâncias no mesmo teste", () => {
    // Catches module-level singletons, non-idempotent init or leaked global
    // listeners, which only manifest on the second mount.
    const first = render(<ChatPanel />);
    const second = render(<ChatPanel />);

    expect(first.container.querySelector("form")).not.toBeNull();
    expect(second.container.querySelector("form")).not.toBeNull();

    first.unmount();
    second.unmount();
    expect(consoleError.mock.calls).toEqual([]);
  });
});
