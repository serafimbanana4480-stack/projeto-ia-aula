import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { RoomComposer, type ComposerModel, type MentionAgent } from "../../../../components/bots/chat/Composer";
import { COMPOSER_FIELD_MIN, composerFieldHeight, slashTokenAtCaret } from "../../../../components/bots/chat/composerMetrics";

const agents: MentionAgent[] = [
  { id: "forge", name: "FORGE", role: "Programação" },
  { id: "debug", name: "Debugger", role: "Diagnóstico" },
];

const models: ComposerModel[] = [
  { id: "forge", name: "FORGE", model: "kilo-free", provider: "kilo", project: "", status: "Inferência ainda não verificada." },
];

function Harness({
  busy = false,
  disabled = false,
  onSubmit = vi.fn(),
  onStop = vi.fn(),
  initial = "",
  withAgents = false,
  withModels = false,
  maxLength,
}: {
  busy?: boolean;
  disabled?: boolean;
  onSubmit?: () => void;
  onStop?: () => void;
  initial?: string;
  withAgents?: boolean;
  withModels?: boolean;
  maxLength?: number;
}) {
  const [value, setValue] = useState(initial);
  return (
    <RoomComposer
      label="Mensagem para o grupo"
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      onStop={onStop}
      busy={busy}
      disabled={disabled}
      placeholder="Escreve para o grupo…"
      hint="Um run por mensagem."
      footnote="O projeto selecionado limita as ferramentas de ficheiro."
      agents={withAgents ? agents : []}
      models={withModels ? models : []}
      sendLabel="Enviar ao grupo"
      stopLabel="Pedir paragem do grupo"
      maxLength={maxLength}
    />
  );
}

describe("composerFieldHeight", () => {
  it("fica na altura mínima com uma linha e limita-se a 40% da viewport", () => {
    expect(composerFieldHeight(0, 800)).toEqual({ height: COMPOSER_FIELD_MIN, overflow: false });
    expect(composerFieldHeight(80, 800)).toEqual({ height: 80, overflow: false });
    expect(composerFieldHeight(500, 800)).toEqual({ height: 320, overflow: true });
    expect(composerFieldHeight(500, 800, 40)).toEqual({ height: 280, overflow: true });
  });

  it("reconhece um comando / junto do cursor", () => {
    expect(slashTokenAtCaret("/rever", 6)).toBe(true);
    expect(slashTokenAtCaret("olá /", 5)).toBe(true);
    expect(slashTokenAtCaret("@FORGE", 6)).toBe(false);
  });
});

describe("RoomComposer", () => {
  it("cresce com várias linhas e passa a fazer scroll no limite", () => {
    vi.stubGlobal("innerHeight", 500);
    render(<Harness />);
    const area = screen.getByRole("textbox", { name: "Mensagem para o grupo" }) as HTMLTextAreaElement;
    Object.defineProperty(area, "scrollHeight", { configurable: true, get: () => 400 });
    fireEvent.change(area, { target: { value: "linha\n".repeat(12), selectionStart: 60 } });
    expect(area.style.height).toBe("200px");
    expect(area.dataset.overflow).toBe("true");
    vi.unstubAllGlobals();
  });

  it("desliga o envio quando está vazio ou bloqueado e envia com Enter", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const area = screen.getByRole("textbox", { name: "Mensagem para o grupo" });
    const send = screen.getByRole("button", { name: "Enviar ao grupo" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.keyDown(area, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(area, { target: { value: "olá", selectionStart: 3 } });
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    expect(onSubmit).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(area, { key: "Enter", shiftKey: true });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(area, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });

  it("transforma o envio num botão de paragem enquanto responde", () => {
    const onSubmit = vi.fn();
    const onStop = vi.fn();
    render(<Harness busy initial="texto a meio" onSubmit={onSubmit} onStop={onStop} />);
    const stop = screen.getByRole("button", { name: "Pedir paragem do grupo" });
    expect(screen.queryByRole("button", { name: "Enviar ao grupo" })).toBeNull();
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("texto a meio");
  });

  it("mantém o campo desligado e não envia", () => {
    const onSubmit = vi.fn();
    render(<Harness disabled onSubmit={onSubmit} />);
    const area = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(area.disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Enviar ao grupo" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Anexar ficheiros de texto" }) as HTMLButtonElement).disabled).toBe(true);
    expect(area.placeholder).toBe("Escreve para o grupo…");
    fireEvent.keyDown(area, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("abre o popover de menção e insere o participante", () => {
    render(<Harness withAgents />);
    const area = screen.getByRole("textbox");
    fireEvent.change(area, { target: { value: "@Fo", selectionStart: 3 } });
    const list = screen.getByRole("listbox", { name: "Mencionar participante" });
    expect(list).toBeTruthy();
    expect(screen.getByText("Mencionar")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /FORGE/ }));
    expect((area as HTMLTextAreaElement).value).toBe("@FORGE ");
  });

  it("mostra a dica de comandos / e o chip do modelo", () => {
    render(<Harness withAgents withModels />);
    const area = screen.getByRole("textbox");
    fireEvent.change(area, { target: { value: "/rever", selectionStart: 6 } });
    expect(screen.getByRole("note").textContent).toContain("não há comandos /");
    expect(screen.getByRole("note").textContent).toContain("@");

    fireEvent.click(screen.getByRole("button", { name: "Modelo: kilo-free" }));
    const dialog = screen.getByRole("dialog", { name: "Provedor e projeto" });
    expect(dialog.textContent).toContain("Provedor: kilo");
    expect(dialog.textContent).toContain("Sem projeto selecionado");
    expect(dialog.textContent).toContain("Inferência ainda não verificada.");
  });

  it("só mostra a linha do teclado quando o campo tem foco", () => {
    render(<Harness />);
    const hint = screen.getByText("Enter envia · Shift+Enter muda de linha.");
    expect(hint.className).toContain("sr-only");
    const area = screen.getByRole("textbox");
    fireEvent.focus(area);
    expect(hint.className).toContain("nx-composer-focusline");
    expect(area.getAttribute("placeholder")).toBe("Escreve para o grupo…");
    expect(area.getAttribute("title")).toContain("Enter envia");
    expect(screen.getByText("Um run por mensagem.").className).toContain("sr-only");
    fireEvent.blur(area);
    expect(hint.className).toContain("sr-only");
  });
});
