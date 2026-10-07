import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ModeDropdown } from "../../../components/chat/ChatPanel";
import { useModeStore } from "../../../stores/modeStore";

const modes = [
  { id: "auto", description: "Escolha automática", default_agent: "ROUTER", default_model: "auto", router: "auto", tools_enabled: [] },
  { id: "coder", description: "Implementação", default_agent: "CODER", default_model: "local", router: "none", tools_enabled: [] },
  { id: "reviewer", description: "Revisão", default_agent: "ANALYZER", default_model: "local", router: "none", tools_enabled: [] },
];

const initialState = useModeStore.getState();

describe("ModeDropdown keyboard access", () => {
  beforeEach(() => {
    useModeStore.setState({ currentMode: "auto", modes, modesLoaded: true });
  });

  afterEach(() => {
    useModeStore.setState(initialState, true);
  });

  it("moves through options with arrow and boundary keys, and Escape restores focus", () => {
    render(<ModeDropdown />);
    const trigger = screen.getByRole("button", { name: "Escolher modo. Atual: Auto" });

    act(() => fireEvent.click(trigger));
    const auto = screen.getByRole("option", { name: /Auto/ });
    const coder = screen.getByRole("option", { name: /Coder/ });
    const reviewer = screen.getByRole("option", { name: /Review/ });
    expect(document.activeElement).toBe(auto);

    act(() => fireEvent.keyDown(auto, { key: "ArrowDown" }));
    expect(document.activeElement).toBe(coder);
    act(() => fireEvent.keyDown(coder, { key: "End" }));
    expect(document.activeElement).toBe(reviewer);
    act(() => fireEvent.keyDown(reviewer, { key: "Home" }));
    expect(document.activeElement).toBe(auto);
    act(() => fireEvent.keyDown(auto, { key: "Escape" }));

    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("seleciona o modo focado e devolve o foco ao acionador", () => {
    render(<ModeDropdown />);
    const trigger = screen.getByRole("button", { name: "Escolher modo. Atual: Auto" });

    fireEvent.click(trigger);
    act(() => fireEvent.click(screen.getByRole("option", { name: /Coder/ })));

    expect(useModeStore.getState().currentMode).toBe("coder");
    expect(document.activeElement).toBe(trigger);
  });
});
