/**
 * The mode indicator is the only place the chat header shows how many advanced
 * modes are running. It had an unused `showPanel` state left over from a panel
 * it never rendered, and it labelled the count with the bare English
 * "{n} active" — which also read "1 active" for a single mode.
 */
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import AdvancedModeHeaderIndicator from "../../../components/chat/AdvancedModeHeaderIndicator";
import { useAdvancedModeStore } from "../../../stores/advancedModeStore";

describe("AdvancedModeHeaderIndicator", () => {
  const loadModes = vi.fn();

  beforeEach(() => {
    loadModes.mockReset();
    useAdvancedModeStore.setState({
      activeModeIds: [],
      loadModes,
    } as never);
  });

  it("não renderiza nada sem modos activos", () => {
    const { container } = render(<AdvancedModeHeaderIndicator />);
    expect(container.innerHTML).toBe("");
    expect(loadModes).toHaveBeenCalledTimes(1);
  });

  it("conta os modos activos em pt-PT, com plural correcto", () => {
    const { rerender } = render(<AdvancedModeHeaderIndicator />);

    act(() => useAdvancedModeStore.setState({ activeModeIds: ["sentinel"] } as never));
    rerender(<AdvancedModeHeaderIndicator />);
    expect(screen.getByText("1 configurado")).toBeTruthy();

    act(() => useAdvancedModeStore.setState({ activeModeIds: ["sentinel", "autonomous"] } as never));
    rerender(<AdvancedModeHeaderIndicator />);
    expect(screen.getByText("2 configurados")).toBeTruthy();
  });

  it("expõe a contagem num title legível por um leitor de ecrã", () => {
    const { rerender } = render(<AdvancedModeHeaderIndicator />);

    act(() => useAdvancedModeStore.setState({ activeModeIds: ["sentinel"] } as never));
    rerender(<AdvancedModeHeaderIndicator />);
    expect(screen.getByTitle("1 modo configurado; atividade não medida")).toBeTruthy();

    act(() => useAdvancedModeStore.setState({ activeModeIds: ["sentinel", "autonomous"] } as never));
    rerender(<AdvancedModeHeaderIndicator />);
    expect(screen.getByTitle("2 modos configurados; atividade não medida")).toBeTruthy();
  });

  it("mostra no máximo três ícones e um para o resto", () => {
    useAdvancedModeStore.setState({
      activeModeIds: ["sentinel", "advisor-infinity", "autonomous", "forge"],
    } as never);
    const { container } = render(<AdvancedModeHeaderIndicator />);

    // `.slice(0, 3)` on the icon strip: the 4th mode has no avatar by design.
    expect(container.querySelectorAll(".rounded-full.bg-purple-500\\/20")).toHaveLength(3);
  });

  it("encaminha o clique para o botão flutuante que detém o painel", () => {
    const toggle = document.createElement("button");
    toggle.setAttribute("data-advanced-mode-toggle", "");
    const onClick = vi.fn();
    toggle.addEventListener("click", onClick);
    document.body.appendChild(toggle);

    useAdvancedModeStore.setState({ activeModeIds: ["sentinel"] } as never);
    render(<AdvancedModeHeaderIndicator />);
    screen.getByText("1 configurado").click();

    expect(onClick).toHaveBeenCalledTimes(1);
    document.body.removeChild(toggle);
  });

  it("não rebenta quando o botão flutuante ainda não existe", () => {
    useAdvancedModeStore.setState({ activeModeIds: ["sentinel"] } as never);
    render(<AdvancedModeHeaderIndicator />);
    expect(() => screen.getByText("1 configurado").click()).not.toThrow();
  });
});
