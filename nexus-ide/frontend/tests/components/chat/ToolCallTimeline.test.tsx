/**
 * `ToolCallTimeline` is 507 lines of the operator-facing surface for tool
 * execution — arguments, results, errors, retries, HITL confirmation — and it
 * had ZERO tests. It is also the component that used to hand tool arguments to
 * `dangerouslySetInnerHTML`, so the XSS cases below are the ones that matter.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import ToolCallTimeline from "../../../components/chat/ToolCallTimeline";
import type { ToolCallItem } from "../../../lib/types";

const executeTool = vi.fn();
const confirmTool = vi.fn();

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  return { ...actual, executeTool: (...args: unknown[]) => executeTool(...args), confirmTool: (...args: unknown[]) => confirmTool(...args) };
});

let seq = 0;
function call(overrides: Partial<ToolCallItem> = {}): ToolCallItem {
  seq += 1;
  return {
    id: `call-${seq}`,
    name: "read_file",
    args: { path: "src/index.ts" },
    status: "success",
    timestamp: "2026-01-01T00:00:00Z",
    ...overrides,
  } as ToolCallItem;
}

function calls(n: number, overrides: Partial<ToolCallItem> = {}): ToolCallItem[] {
  return Array.from({ length: n }, () => call(overrides));
}

function expand(): void {
  fireEvent.click(screen.getByRole("button", { expanded: false }));
}

describe("ToolCallTimeline — header, counters and overflow", () => {
  beforeEach(() => {
    executeTool.mockReset();
    confirmTool.mockReset();
  });

  it("não renderiza nada sem chamadas", () => {
    const { container } = render(<ToolCallTimeline calls={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("compacta chamadas adjacentes da mesma ferramenta no resumo", () => {
    render(<ToolCallTimeline calls={calls(7)} />);

    expect(screen.getByText("Ler ficheiro × 7")).toBeTruthy();
    expect(screen.queryByText(/^\+\d+$/)).toBeNull();
  });

  it("não mostra o pill de overflow com 4 ou menos chamadas", () => {
    render(<ToolCallTimeline calls={calls(4)} />);
    expect(screen.queryByText(/^\+\d+$/)).toBeNull();
  });

  it("conta os estados por categoria", () => {
    render(
      <ToolCallTimeline
        calls={[
          call({ status: "running" }),
          call({ status: "running" }),
          call({ status: "success" }),
          call({ status: "error" }),
          call({ status: "awaiting_confirmation" }),
        ]}
      />,
    );

    expect(screen.getByText("2 a correr")).toBeTruthy();
    expect(screen.getByText("1 ok")).toBeTruthy();
    expect(screen.getByText("1 erro")).toBeTruthy();
    expect(screen.getByText("1 aprovação")).toBeTruthy();
  });

  it("pluraliza erros e aprovações em pt-PT", () => {
    // Was `{errorCount} erro` / `{confirmationCount} aprovação` unconditionally,
    // so 3 failures read "3 erro" and 2 pending confirmations "2 aprovação".
    render(
      <ToolCallTimeline
        calls={[
          call({ status: "error" }),
          call({ status: "error" }),
          call({ status: "error" }),
          call({ status: "awaiting_confirmation" }),
          call({ status: "awaiting_confirmation" }),
        ]}
      />,
    );

    expect(screen.getByText("3 erros")).toBeTruthy();
    expect(screen.getByText("2 aprovações")).toBeTruthy();
  });

  it("traduz o nome da ferramenta e mantém o identificador técnico", () => {
    render(<ToolCallTimeline calls={[call({ name: "write_file_absolute" })]} />);
    // The friendly label is the chip; the wire name is the badge in the body.
    expect(screen.getByText("Escrever ficheiro")).toBeTruthy();
    expand();
    expect(screen.getByText("write_file_absolute")).toBeTruthy();
  });

  it("mostra o nome cru de uma ferramenta desconhecida", () => {
    render(<ToolCallTimeline calls={[call({ name: "brand_new_tool" })]} />);
    expect(screen.getByText("brand new tool")).toBeTruthy();
  });
});

describe("ToolCallTimeline — expand toggle and accessibility", () => {
  it("expõe o estado de expansão e controla o corpo", async () => {
    const { container } = render(<ToolCallTimeline calls={calls(1)} />);

    const toggle = screen.getByRole("button", { expanded: false });
    const bodyId = toggle.getAttribute("aria-controls");
    expect(bodyId).toMatch(/^tool-call-timeline-/);
    // The body is genuinely unmounted while collapsed.
    expect(container.querySelector('[data-testid="tool-call-timeline-body"]')).toBeNull();

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { expanded: true })).toBeTruthy();
    expect(container.querySelector(`#${bodyId}`)).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { expanded: true }));
    // `AnimatePresence` keeps the body for the length of the exit animation,
    // then removes it — the result of a run stays out of the DOM when closed.
    await waitFor(() =>
      expect(container.querySelector(`#${bodyId}`)).toBeNull(),
    );
  });

  it("atribui um corpo único a cada timeline no mesmo chat", () => {
    render(
      <>
        <ToolCallTimeline calls={[call({ name: "read_file" })]} />
        <ToolCallTimeline calls={[call({ name: "todo_list" })]} />
      </>,
    );

    const controlledIds = screen.getAllByRole("button", { expanded: false })
      .map((button) => button.getAttribute("aria-controls"));
    expect(new Set(controlledIds).size).toBe(2);

    fireEvent.click(screen.getAllByRole("button", { expanded: false })[1]);
    const bodies = screen.getAllByTestId("tool-call-timeline-body");
    expect(bodies).toHaveLength(1);
    expect(bodies[0].id).toBe(controlledIds[1]);
  });
});

describe("ToolCallTimeline — ExecutionStages chips", () => {
  it("marca como concluídas as fases anteriores à mais alta atingida", () => {
    // `write_file` is phase 2 ("A executar"), so reading and searching are done.
    render(<ToolCallTimeline calls={[call({ name: "write_file" })]} />);

    const stages = screen.getByText("A ler").parentElement!;
    expect(stages.textContent).toContain("A ler");
    expect(stages.textContent).toContain("A pesquisar");
    expect(stages.textContent).toContain("A executar");
    expect(stages.textContent).toContain("A validar");
  });

  it("não marca como concluída uma fase que só corrreu", () => {
    const { container } = render(
      <ToolCallTimeline calls={[call({ name: "execute_terminal", status: "running" })]} />,
    );
    // A validar (the highest possible) must not be green when nothing ran there.
    const validating = [...container.querySelectorAll("span")].find(
      (el) => el.textContent === "A validar",
    );
    expect(validating?.className).toContain("bg-nexus-bg/60");
  });
});

describe("ToolCallTimeline — argument rendering is not an HTML sink", () => {
  it("NÃO interpreta HTML nos argumentos da ferramenta", () => {
    const { container } = render(
      <ToolCallTimeline
        calls={[call({ args: { note: '<img src="x" onerror="window.__pwned = true">' } })]}
      />,
    );
    expand();

    // The old implementation stringified the args, wrapped tokens in <span> and
    // assigned the result with `dangerouslySetInnerHTML` — so a model that was
    // talked into emitting an attribute ran script in the operator's browser.
    expect(container.querySelector("img")).toBeNull();
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined();
    // …and the argument is still fully readable.
    expect(container.textContent).toContain("onerror");
  });

  it("não interpreta um <script> nos argumentos", () => {
    const { container } = render(
      <ToolCallTimeline
        calls={[call({ args: { cmd: "<script>window.__pwned2 = true</script>" } })]}
      />,
    );
    expand();

    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as Record<string, unknown>).__pwned2).toBeUndefined();
  });

  it("preserva o texto do argumento byte a byte", () => {
    const args = { pattern: 'a "b" \\ c\nd', n: 12.5, ok: true, nil: null };
    const { container } = render(
      <ToolCallTimeline calls={[call({ args })]} />,
    );
    expand();

    // The strongest possible statement about a syntax highlighter: what it
    // shows is exactly the pretty-printed payload, with nothing added,
    // dropped or re-encoded.
    const pre = container.querySelector("pre")!;
    expect(pre.textContent).toBe(JSON.stringify(args, null, 2));
  });

  it("não rebenta com um resultado circular em vez de derrubar a timeline", () => {
    const circular: Record<string, unknown> = { name: "loop" };
    circular.self = circular;

    render(
      <ToolCallTimeline
        calls={[call({ status: "error", error: "boom", result: circular })]}
      />,
    );
    expand();

    expect(screen.getByText("boom")).toBeTruthy();
  });

  it("não mostra o painel de argumentos quando não há argumentos", () => {
    render(<ToolCallTimeline calls={[call({ args: {} })]} />);
    expand();
    expect(screen.queryByText("Argumentos")).toBeNull();
  });
});

describe("ToolCallTimeline — results", () => {
  it("mostra o resultado de uma chamada bem sucedida", () => {
    render(
      <ToolCallTimeline calls={[call({ status: "success", result: "conteúdo do ficheiro" })]} />,
    );
    expand();

    expect(screen.getByText("Resultado")).toBeTruthy();
    expect(screen.getByText("conteúdo do ficheiro")).toBeTruthy();
  });

  it("mostra fontes da pesquisa como links externos seguros", () => {
    render(
      <ToolCallTimeline
        calls={[
          call({
            name: "web_search",
            args: { query: "nexus" },
            result: { sources: [{ url: "https://example.org/source" }] },
          }),
        ]}
      />,
    );
    expand();
    fireEvent.click(screen.getByText("Pesquisou na web"));
    fireEvent.click(screen.getByText("nexus"));

    const sourceLink = screen.getByRole("link", { name: "https://example.org/source" });
    expect(sourceLink.getAttribute("href")).toBe("https://example.org/source");
    expect(sourceLink.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("não transforma uma fonte não HTTP num link", () => {
    render(
      <ToolCallTimeline
        calls={[
          call({
            name: "web_search",
            args: { query: "nexus" },
            result: { sources: [{ url: "javascript:alert(1)" }] },
          }),
        ]}
      />,
    );
    expand();
    fireEvent.click(screen.getByText("Pesquisou na web"));
    fireEvent.click(screen.getByText("nexus"));

    expect(screen.queryByRole("link", { name: "javascript:alert(1)" })).toBeNull();
    expect(screen.getByText("javascript:alert(1)")).toBeTruthy();
  });

  it("serializa um resultado objecto", () => {
    render(
      <ToolCallTimeline calls={[call({ status: "success", result: { linhas: 12 } })]} />,
    );
    expand();
    expect(screen.getByText(/"linhas": 12/)).toBeTruthy();
  });

  it("mostra resultados de todo_write como checklist com estados e contagens", () => {
    render(
      <ToolCallTimeline
        calls={[
          call({
            name: "todo_write",
            status: "success",
            result: {
              ok: true,
              result: {
                ok: true,
                operation: "add",
                session_id: "session-1",
                todos: [
                  { id: 1, content: "Rever a dashboard", priority: "high", status: "pending" },
                  { id: 2, content: "Corrigir a pesquisa", priority: "normal", status: "in_progress" },
                  { id: 3, content: "Validar o chat", priority: "low", status: "completed" },
                ],
                counts: { pending: 1, in_progress: 1, completed: 1, cancelled: 0, total: 3 },
              },
            },
          }),
        ]}
      />,
    );
    expand();

    expect(screen.getByRole("region", { name: "Lista de tarefas" })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Tarefas" }).children.length).toBe(3);
    expect(screen.getByText("Rever a dashboard")).toBeTruthy();
    expect(screen.getByText("Corrigir a pesquisa")).toBeTruthy();
    expect(screen.getByText("Validar o chat")).toBeTruthy();
    expect(screen.getByText("3 tarefas")).toBeTruthy();
    expect(screen.getByText("1 marcada como concluída")).toBeTruthy();
    expect(screen.getByRole("note").textContent).toMatch(/declarados pelo agente.*não verifica/i);
    expect(screen.getByText("0 canceladas")).toBeTruthy();
    expect(screen.queryByText(/"todos"/)).toBeNull();
  });

  it("mostra uma lista todo_list vazia sem despejar JSON", () => {
    render(
      <ToolCallTimeline
        calls={[
          call({
            name: "todo_list",
            status: "success",
            result: {
              ok: true,
              result: {
                ok: true,
                session_id: "session-1",
                todos: [],
                counts: { pending: 0, in_progress: 0, completed: 0, cancelled: 0, total: 0 },
              },
            },
          }),
        ]}
      />,
    );
    expand();

    expect(screen.getByText("Sem tarefas nesta lista.")).toBeTruthy();
    expect(screen.getByText("0 tarefas")).toBeTruthy();
    expect(screen.queryByText(/"todos"/)).toBeNull();
  });

  it("mantém JSON como fallback se o resultado de uma todo_list for inválido", () => {
    render(
      <ToolCallTimeline
        calls={[
          call({
            name: "todo_list",
            status: "success",
            result: { ok: true, todos: [{ id: 1, content: "sem estado" }], counts: {} },
          }),
        ]}
      />,
    );
    expand();

    expect(screen.getByText(/"todos":/)).toBeTruthy();
    expect(screen.getByText(/"sem estado"/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Lista de tarefas" })).toBeNull();
  });

  it("virtualiza o DOM para um resultado com 10 mil linhas e pesquisa linhas fora da janela", () => {
    const content = Array.from({ length: 10_000 }, (_, index) => `linha-${index + 1}`).join("\n");
    const { container } = render(
      <ToolCallTimeline calls={[call({ result: content })]} />,
    );
    expand();

    const output = screen.getByRole("log", { name: "Resultado" });
    expect(container.querySelectorAll("[data-output-line]").length).toBeLessThan(30);
    expect(screen.getByText(/10.*000 linhas/)).toBeTruthy();

    fireEvent.scroll(output, { target: { scrollTop: 18 * 5_000 } });
    expect(container.querySelector('[data-output-line="5001"]')).not.toBeNull();
    expect(container.querySelector('[data-output-line="1"]')).toBeNull();

    fireEvent.change(screen.getByLabelText("Pesquisar em Resultado"), {
      target: { value: "linha-9999" },
    });
    expect(container.querySelector('[data-output-line="9999"]')).not.toBeNull();
    expect(container.querySelector('[data-output-line="1"]')).toBeNull();
  });

  it("separa stdout/stderr, interpreta ANSI como texto colorido e mostra a hora recebida", () => {
    const { container } = render(
      <ToolCallTimeline
        calls={[
          call({
            timestamp: "2026-01-01T10:11:12Z",
            result: { stdout: "\u001b[31mERRO\u001b[0m\nok", stderr: "aviso", exit_code: 2 },
          }),
        ]}
      />,
    );
    expand();

    const stdout = screen.getByRole("log", { name: "stdout" });
    const stderr = screen.getByRole("log", { name: "stderr" });
    expect(stdout.textContent).toContain("ERRO");
    expect(stderr.textContent).toContain("aviso");
    expect(stdout.querySelector("span[style]")?.getAttribute("style")).toContain("color");
    expect(container.querySelector("time")?.getAttribute("datetime")).toBe("2026-01-01T10:11:12Z");
    fireEvent.click(screen.getByText("Metadados do resultado"));
    expect(screen.getByText(/"exit_code": 2/)).toBeTruthy();
  });

  it("mostra a duração quando a chamada a traz", () => {
    render(
      <ToolCallTimeline calls={[call({ status: "success", durationMs: 128 })]} />,
    );
    expand();
    expect(screen.getByText("128ms")).toBeTruthy();
  });

  it("etiqueta as origens de memória de um recall", () => {
    render(
      <ToolCallTimeline
        calls={[
          call({
            name: "recall_context",
            status: "success",
            result: {
              memories: [
                { type: "project", project_id: "nexus" },
                { type: "session" },
                { type: "project", project_id: "outro" },
                { type: "session" },
              ],
            },
          }),
        ]}
      />,
    );
    expand();

    // Duplicated origins collapse; the first label for each wins.
    expect(screen.getAllByText("Memória: projeto")).toHaveLength(1);
    expect(screen.getAllByText("Memória: sessão")).toHaveLength(1);
  });
});

describe("ToolCallTimeline — errors, suggestions and retry", () => {
  beforeEach(() => {
    executeTool.mockReset();
    confirmTool.mockReset();
  });

  it("mostra o erro e sugere a ferramenta correcta para um alias antigo", () => {
    render(
      <ToolCallTimeline
        calls={[call({ name: "search_web", status: "error", error: "tool not found" })]}
      />,
    );
    expand();

    expect(screen.getByText("tool not found")).toBeTruthy();
    expect(
      screen.getByText(/Usa web_search ou search_web_v2/),
    ).toBeTruthy();
  });

  it("não sugere nada para um erro sem padrão conhecido", () => {
    render(
      <ToolCallTimeline
        calls={[call({ status: "error", error: "qualquer coisa" })]}
      />,
    );
    expand();
    expect(screen.queryByText(/^Sugestão:/)).toBeNull();
  });

  it("repete a ferramenta e mostra o resultado da repetição", async () => {
    executeTool.mockResolvedValue({ ok: true });
    render(
      <ToolCallTimeline
        calls={[call({ name: "read_file", status: "error", error: "transient" })]}
        sessionId="s-42"
      />,
    );
    expand();

    fireEvent.click(screen.getByText("Repetir ferramenta"));

    await waitFor(() => expect(executeTool).toHaveBeenCalledTimes(1));
    expect(executeTool).toHaveBeenCalledWith("read_file", { path: "src/index.ts" }, "s-42", undefined);
    expect(await screen.findByText("Resultado da repetição")).toBeTruthy();
    expect(screen.getByText(/"ok": true/)).toBeTruthy();
  });

  it("mostra a falha da repetição em vez de a engolir", async () => {
    // `void retryTool(call)` used to discard the rejection, so a failed retry
    // was a button that silently did nothing (plus an unhandled rejection).
    executeTool.mockRejectedValue(new Error("backend fora do ar"));
    render(
      <ToolCallTimeline
        calls={[call({ status: "error", error: "transient" })]}
        sessionId="s-42"
      />,
    );
    expand();

    fireEvent.click(screen.getByText("Repetir ferramenta"));

    expect(await screen.findByText(/A repetição falhou: backend fora do ar/)).toBeTruthy();
  });

  it("limpa o erro anterior quando uma repetição volta a ser tentada", async () => {
    executeTool.mockRejectedValueOnce(new Error("primeira falha"));
    render(
      <ToolCallTimeline
        calls={[call({ status: "error", error: "transient" })]}
        sessionId="s-42"
      />,
    );
    expand();

    fireEvent.click(screen.getByText("Repetir ferramenta"));
    expect(await screen.findByText(/primeira falha/)).toBeTruthy();

    executeTool.mockResolvedValueOnce({ ok: 1 });
    fireEvent.click(screen.getByText("Repetir ferramenta"));
    await waitFor(() =>
      expect(screen.queryByText(/primeira falha/)).toBeNull(),
    );
  });

  it("oferece confirmar a repetição quando o backend volta a pedir confirmação", async () => {
    executeTool.mockResolvedValue({ confirmation_required: true, confirmation_id: "c-1" });
    render(
      <ToolCallTimeline
        calls={[call({ status: "error", error: "precisa de aviso" })]}
        sessionId="s-42"
      />,
    );
    expand();

    fireEvent.click(screen.getByText("Repetir ferramenta"));
    expect(await screen.findByText("Autorizar e executar")).toBeTruthy();

    fireEvent.click(screen.getByText("Autorizar e executar"));
    await waitFor(() => expect(confirmTool).toHaveBeenCalledWith("c-1", true));
    await waitFor(() => expect(executeTool).toHaveBeenLastCalledWith(
      "read_file",
      { path: "src/index.ts" },
      "s-42",
      "c-1",
    ));
  });

  it("não renderiza o erro de uma chamada que não está em erro", () => {
    render(<ToolCallTimeline calls={[call({ status: "success" })]} />);
    expand();
    expect(screen.queryByText("Repetir ferramenta")).toBeNull();
  });
});

describe("ToolCallTimeline — human-in-the-loop confirmation", () => {
  beforeEach(() => {
    executeTool.mockReset();
    confirmTool.mockReset();
  });

  const pending = () =>
    call({
      name: "execute_terminal",
      status: "awaiting_confirmation",
      confirmationId: "conf-9",
      suggestion: "Vai apagar a pasta de testes.",
    });

  it("explica o risco e mostra a sugestão do agente", () => {
    render(<ToolCallTimeline calls={[pending()]} />);
    expand();

    expect(screen.getByText(/pode alterar ficheiros/)).toBeTruthy();
    expect(screen.getByText("Vai apagar a pasta de testes.")).toBeTruthy();
  });

  it("confirma com o confirmationId da chamada", async () => {
    confirmTool.mockResolvedValue(undefined);
    render(<ToolCallTimeline calls={[pending()]} />);
    expand();

    fireEvent.click(screen.getByText("Confirmar"));
    await waitFor(() => expect(confirmTool).toHaveBeenCalledWith("conf-9", true));
  });

  it("recusa com o confirmationId da chamada", async () => {
    confirmTool.mockResolvedValue(undefined);
    render(<ToolCallTimeline calls={[pending()]} />);
    expand();

    fireEvent.click(screen.getByText("Recusar"));
    await waitFor(() => expect(confirmTool).toHaveBeenCalledWith("conf-9", false));
  });

  it("mostra a falha da confirmação em vez de a engolir", async () => {
    confirmTool.mockRejectedValue(new Error("sessão expirada"));
    render(<ToolCallTimeline calls={[pending()]} />);
    expand();

    fireEvent.click(screen.getByText("Confirmar"));
    expect(await screen.findByText(/A confirmação falhou: sessão expirada/)).toBeTruthy();
  });

  it("não chama a API quando a chamada não tem confirmationId", async () => {
    render(
      <ToolCallTimeline
        calls={[call({ status: "awaiting_confirmation" })]}
      />,
    );
    expand();

    fireEvent.click(screen.getByText("Confirmar"));
    await Promise.resolve();
    expect(confirmTool).not.toHaveBeenCalled();
  });
});
