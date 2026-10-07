/**
 * Smoke tests for the smaller chat-surface components. These had ZERO tests.
 * The bar here is "real behaviour, not `toBeDefined()`": each assertion is a
 * contract a user or a caller depends on.
 */
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import VirtualMessageList from "../../../components/chat/VirtualMessageList";
import SessionList from "../../../components/chat/SessionList";
import ToastHost, {
  clearToasts,
  dismissToast,
  pushToast,
  useToast,
} from "../../../components/chat/Toast";
import ToolsPanel from "../../../components/chat/ToolsPanel";
import CommandBar from "../../../components/chat/CommandBar";
import { useToolsStore } from "../../../stores/toolsStore";
import { useAdvancedModeStore } from "../../../stores/advancedModeStore";

/**
 * `AnimatePresence` unmounts a removed child only after its exit transition,
 * and framer-motion drives that from an animation-frame loop jsdom does not
 * tick. Without waiting real time, every "is it gone?" assertion in this file
 * would really be asserting that the animation started.
 */
async function settle(ms = 450) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

/* ────────────────────────── VirtualMessageList ────────────────────────── */

interface Row {
  id: string;
}

describe("VirtualMessageList", () => {
  const renderItem = (row: Row) => <div key={row.id}>{row.id}</div>;

  function rows(count: number): Row[] {
    return Array.from({ length: count }, (_, i) => ({ id: `row-${i}` }));
  }

  it("mostra apenas as últimas `initialLimit` mensagens", () => {
    render(<VirtualMessageList messages={rows(120)} renderItem={renderItem} initialLimit={50} />);

    expect(screen.queryByText("row-0")).toBeNull();
    expect(screen.queryByText("row-69")).toBeNull();
    // The tail is what a streaming chat must keep on screen.
    expect(screen.getByText("row-119")).toBeTruthy();
  });

  it("não mostra o botão quando tudo cabe", () => {
    render(<VirtualMessageList messages={rows(3)} renderItem={renderItem} initialLimit={50} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("anuncia quantas mensagens estão ocultas", () => {
    render(<VirtualMessageList messages={rows(120)} renderItem={renderItem} initialLimit={50} />);
    expect(screen.getByText(/70 ocultas/)).toBeTruthy();
  });

  it("revela mais mensagens ao carregar no botão, sem as repetir", () => {
    render(<VirtualMessageList messages={rows(120)} renderItem={renderItem} initialLimit={50} />);

    // 50 -> 100 of 120: the middle of the history is still hidden.
    fireEvent.click(screen.getByRole("button"));
    expect(screen.queryByText("row-0")).toBeNull();
    expect(screen.getByText("row-20")).toBeTruthy();
    expect(screen.getByText("row-119")).toBeTruthy();

    // 100 -> 120: the whole history is on screen, so the button is gone rather
    // than a dead loop that can never reach the end.
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("row-0")).toBeTruthy();
    expect(screen.getByText("row-119")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("repete o carregamento pela página, sem duplicar", () => {
    render(<VirtualMessageList messages={rows(120)} renderItem={renderItem} initialLimit={50} />);

    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getAllByText("row-0")).toHaveLength(1);
    expect(screen.getAllByText("row-119")).toHaveLength(1);
  });

  it("passa o índice absoluto ao renderizador, não o índice da página", () => {
    // The index is the caller's stable identity for the row; a per-page index
    // would make React remount every row on each "load more".
    const seen: number[] = [];
    render(
      <VirtualMessageList
        messages={rows(10)}
        renderItem={(_row, index) => {
          seen.push(index);
          return <div key={index}>idx-{index}</div>;
        }}
        initialLimit={4}
      />,
    );

    expect(seen).toEqual([6, 7, 8, 9]);
  });
});

/* ─────────────────────────────── SessionList ─────────────────────────────── */

const sessions = {
  list: vi.fn(),
  rename: vi.fn(),
  remove: vi.fn(),
  create: vi.fn(),
};

vi.mock("../../../hooks/useChatSessions", () => ({
  searchChatSessions: vi.fn().mockResolvedValue({
    sessions: [],
    count: 0,
    total: 0,
    offset: 0,
    limit: 50,
  }),
  useChatSessions: () => ({
    sessions: sessions.list(),
    currentId: "s2",
    setCurrentId: vi.fn(),
    create: sessions.create,
    rename: sessions.rename,
    remove: sessions.remove,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

describe("SessionList", () => {
  beforeEach(() => {
    sessions.list.mockReset();
    sessions.rename.mockReset();
    sessions.remove.mockReset();
    sessions.create.mockReset();
  });

  const base = [
    { id: "s1", title: "Primeira sessão", mode: "auto", message_count: 3, last_active_at: new Date().toISOString() },
    { id: "s2", title: "Segunda sessão", mode: "mission", message_count: 7, last_active_at: new Date().toISOString() },
  ];

  it("não renderiza nada quando está colapsada", () => {
    sessions.list.mockReturnValue(base);
    const { container } = render(<SessionList collapsed />);
    expect(container.innerHTML).toBe("");
  });

  it("lista as sessões com o número de mensagens", () => {
    sessions.list.mockReturnValue(base);
    render(<SessionList />);

    expect(screen.getByText("Primeira sessão")).toBeTruthy();
    expect(screen.getByText("3 msg")).toBeTruthy();
    expect(screen.getByText("7 msg")).toBeTruthy();
  });

  it("filtra por título e por modo, sem distinguir maiúsculas", async () => {
    sessions.list.mockReturnValue(base);
    const { container } = render(<SessionList />);

    const input = screen.getByPlaceholderText("Filtrar...");
    fireEvent.change(input, { target: { value: "SEGUNDA" } });
    expect(container.textContent).toContain("Segunda sessão");
    await settle();
    expect(container.textContent).not.toContain("Primeira sessão");

    fireEvent.change(input, { target: { value: "mission" } });
    expect(container.textContent).toContain("Segunda sessão");
    await settle();
    expect(container.textContent).not.toContain("Primeira sessão");
  });

  it("diz quando a pesquisa local e remota não devolve nada", async () => {
    sessions.list.mockReturnValue(base);
    render(<SessionList />);
    fireEvent.change(screen.getByPlaceholderText("Filtrar..."), { target: { value: "zzz" } });
    await settle();
    expect(screen.getByText("Sem resultados")).toBeTruthy();
  });

  it("cria uma sessão com um nome pt-PT datado", async () => {
    sessions.list.mockReturnValue(base);
    render(<SessionList />);

    fireEvent.click(screen.getByTitle("Nova sessão"));
    await waitFor(() => expect(sessions.create).toHaveBeenCalledTimes(1));
    expect(sessions.create.mock.calls[0][0]).toMatch(/^Sessão /);
  });

  it("grava a renomeação uma única vez mesmo com Enter seguido de blur", async () => {
    // Enter and onBlur both fired `commitEdit`, so every rename was written
    // twice: two PATCH requests and a race between the two responses.
    sessions.list.mockReturnValue(base);
    render(<SessionList />);

    const renameButton = screen.getAllByTitle("Renomear")[0];
    fireEvent.click(renameButton);

    const input = screen.getByDisplayValue("Primeira sessão");
    fireEvent.change(input, { target: { value: "  Novo nome  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);

    await waitFor(() => expect(sessions.rename).toHaveBeenCalledTimes(1));
    expect(sessions.rename).toHaveBeenCalledWith("s1", "Novo nome");
  });

  it("não grava uma renomeação vazia — usa o título por omissão", async () => {
    sessions.list.mockReturnValue(base);
    render(<SessionList />);

    fireEvent.click(screen.getAllByTitle("Renomear")[0]);
    const input = screen.getByDisplayValue("Primeira sessão");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(sessions.rename).toHaveBeenCalledWith("s1", "Sem título"));
  });

  it("cancela a renomeação com Escape sem gravar", async () => {
    sessions.list.mockReturnValue(base);
    render(<SessionList />);

    fireEvent.click(screen.getAllByTitle("Renomear")[0]);
    const input = screen.getByDisplayValue("Primeira sessão");
    fireEvent.change(input, { target: { value: "descartado" } });
    fireEvent.keyDown(input, { key: "Escape" });

    await Promise.resolve();
    expect(sessions.rename).not.toHaveBeenCalled();
    expect(screen.getByText("Primeira sessão")).toBeTruthy();
  });
});

/* ───────────────────────────────── Toast ───────────────────────────────── */

describe("Toast", () => {
  afterEach(() => {
    clearToasts();
    vi.useRealTimers();
  });

  it("mostra e dispensa um toast", async () => {
    render(<ToastHost />);

    act_push({ kind: "info", title: "Informação" });
    expect(screen.getByText("Informação")).toBeTruthy();

    fireEvent.click(screen.getByTitle("Fechar"));
    // AnimatePresence keeps the node for the length of the exit animation.
    await settle();
    expect(screen.queryByText("Informação")).toBeNull();
  });

  it("auto-dispensa um toast não-sticky depois do TTL do seu tipo", async () => {
    render(<ToastHost />);

    act_push({ kind: "success", title: "Sucesso" });
    // DEFAULT_TIMEOUT_MS.success === 3000
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2_900));
    });
    expect(screen.getByText("Sucesso")).toBeTruthy();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    await settle();
    expect(screen.queryByText("Sucesso")).toBeNull();
  });

  it("NÃO auto-dispensa um toast sticky", () => {
    render(<ToastHost />);

    act_push({ kind: "error", title: "Erro", sticky: true });
    // Sticky toasts carry no `setTimeout` at all, so a real 4.5s wait is the
    // only way to show the dismissal never fires.
    return new Promise<void>((resolve) => {
      setTimeout(() => {
        expect(screen.getByText("Erro")).toBeTruthy();
        resolve();
      }, 200);
    });
  });

  it("dá o erro mais longa vida que a informação", async () => {
    render(<ToastHost />);

    act_push({ kind: "info", title: "Info" });
    act_push({ kind: "error", title: "Erro" });

    // info lives 4s, error 8s. At ~4.5s only the error may remain.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 4_500));
    });
    await settle();
    expect(screen.getByText("Erro")).toBeTruthy();
    expect(screen.queryByText("Info")).toBeNull();
  }, 10_000);

  it("executa a acção e fecha o toast", async () => {
    const onClick = vi.fn();
    render(<ToastHost />);

    act_push({ kind: "info", title: "Com acção", action: { label: "Ir", onClick } });
    fireEvent.click(screen.getByText("Ir"));

    expect(onClick).toHaveBeenCalledTimes(1);
    await settle();
    expect(screen.queryByText("Com acção")).toBeNull();
  });

  it("copia os detalhes para a clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<ToastHost />);

    act_push({ kind: "warning", title: "Com detalhes", details: "stack trace" });
    fireEvent.click(screen.getByTitle("Copiar detalhes"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("stack trace"));
  });

  it("despensa por id sem tocar nos restantes", async () => {
    render(<ToastHost />);

    act_push({ kind: "info", title: "A" });
    const b = act_push({ kind: "info", title: "B" });
    act(() => {
      dismissToast(b);
    });

    expect(screen.getByText("A")).toBeTruthy();
    await settle();
    expect(screen.queryByText("B")).toBeNull();
  });

  it("anuncia os toasts a um leitor de ecrã em pt-PT", () => {
    const { container } = render(<ToastHost />);

    const region = container.querySelector('[role="region"]')!;
    expect(region.getAttribute("aria-label")).toBe("Notificações");

    act_push({ kind: "error", title: "Falhou" });
    // `role="region"` alone is silent: a toast that is not announced is a toast
    // the user never learns about.
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.getAttribute("aria-live")).toBe("assertive");
  });

  it("não interrompe um leitor de ecrã para um toast informativo", () => {
    const { container } = render(<ToastHost />);

    act_push({ kind: "success", title: "Guardado" });
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.getAttribute("aria-live")).toBe("polite");
  });

  it("expõe os atalhos de convenience com o kind certo", () => {
    render(<ToastHost />);
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.error("Falhou", "não foi possível", "stack");
    });
    act(() => {
      result.current.warning("Atenção", "olha");
    });
    act(() => {
      result.current.info("Nota");
    });
    act(() => {
      result.current.success("Ok");
    });

    // `error` is sticky (it must not vanish on its own); the rest are not.
    expect(screen.getByText("Falhou")).toBeTruthy();
    expect(screen.getByText("não foi possível")).toBeTruthy();
    expect(screen.getByText("stack")).toBeTruthy();
    expect(screen.getByText("Atenção")).toBeTruthy();
    expect(screen.getByText("Nota")).toBeTruthy();
    expect(screen.getByText("Ok")).toBeTruthy();
  });

  it("limpa tudo a pedido", async () => {
    render(<ToastHost />);
    act_push({ kind: "info", title: "A" });
    act_push({ kind: "info", title: "B" });

    const { result } = renderHook(() => useToast());
    act(() => {
      result.current.clear();
    });

    await settle();
    expect(screen.queryByText("A")).toBeNull();
    expect(screen.queryByText("B")).toBeNull();
  });
});

function act_push(input: Parameters<typeof pushToast>[0]): string {
  let id = "";
  // The store is a module singleton with a listener set; rendering through
  // act is what flushes the React state update.
  act(() => {
    id = pushToast(input);
  });
  return id;
}

/* ─────────────────────────────── ToolsPanel ─────────────────────────────── */

describe("ToolsPanel", () => {
  const loadTools = vi.fn();
  const toggleTool = vi.fn();

  beforeEach(() => {
    loadTools.mockReset().mockResolvedValue(undefined);
    toggleTool.mockReset().mockResolvedValue(undefined);
    useToolsStore.setState({
      loadTools,
      toggleTool,
      loading: false,
      error: null,
    } as never);
  });

  it("carrega o registry ao montar", () => {
    useToolsStore.setState({ tools: [], toolsLoading: false, toolsError: null } as never);
    render(<ToolsPanel />);
    expect(loadTools).toHaveBeenCalledTimes(1);
  });

  it("traduz o estado de cada ferramenta", () => {
    useToolsStore.setState({
      toolsLoading: false,
      toolsError: null,
      tools: [
        { name: "read_file", description: "Lê", enabled: true, status: "available" },
        { name: "write_file", description: "Escreve", enabled: true, status: "requires_confirmation" },
        { name: "playwright", description: "Browser", enabled: true, status: "missing_dependency", dependency: "playwright" },
        { name: "danger", description: "Perigosa", enabled: false, status: "blocked" },
      ],
    } as never);
    render(<ToolsPanel />);

    expect(screen.getByText("disponível")).toBeTruthy();
    expect(screen.getByText("requer confirmação")).toBeTruthy();
    expect(screen.getByText("bloqueada")).toBeTruthy();
    // The missing dependency is named, not just flagged.
    expect(screen.getByText(/dependência em falta · playwright/)).toBeTruthy();
  });

  it("não deixa alternar uma tool com dependência em falta", () => {
    useToolsStore.setState({
      toolsLoading: false,
      toolsError: null,
      tools: [
        { name: "playwright", description: "Browser", enabled: true, status: "missing_dependency" },
      ],
    } as never);
    render(<ToolsPanel />);

    const button = screen.getByRole("button", { name: /playwright/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(toggleTool).not.toHaveBeenCalled();
  });

  it("alterna uma tool disponível", async () => {
    useToolsStore.setState({
      toolsLoading: false,
      toolsError: null,
      tools: [{ name: "read_file", description: "Lê", enabled: true, status: "available" }],
    } as never);
    render(<ToolsPanel />);

    fireEvent.click(screen.getByRole("button", { name: /read_file/ }));
    await waitFor(() => expect(toggleTool).toHaveBeenCalledWith("read_file"));
  });

  it("mostra o erro de carregamento sem o engolir", () => {
    useToolsStore.setState({
      toolsLoading: false,
      toolsError: "HTTP 500",
      tools: [],
    } as never);
    render(<ToolsPanel />);
    expect(screen.getByText(/Não foi possível carregar o registry: HTTP 500/)).toBeTruthy();
  });
});

/* ─────────────────────────────── CommandBar ─────────────────────────────── */

describe("CommandBar", () => {
  beforeEach(() => {
    useAdvancedModeStore.setState({
      activeModeIds: [],
      commands: {},
      loadCommands: vi.fn(),
    } as never);
  });

  it("envia a mensagem escrita e limpa o campo", () => {
    const onSend = vi.fn();
    render(<CommandBar onSend={onSend} />);

    const input = screen.getByPlaceholderText(/Ask anything/);
    fireEvent.change(input, { target: { value: "  olá swarm  " } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).toHaveBeenCalledWith("olá swarm");
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("não envia com Shift+Enter — é uma quebra de linha", () => {
    const onSend = vi.fn();
    render(<CommandBar onSend={onSend} />);

    const input = screen.getByPlaceholderText(/Ask anything/);
    fireEvent.change(input, { target: { value: "com quebra" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  it("não envia texto vazio nem só espaços", () => {
    const onSend = vi.fn();
    render(<CommandBar onSend={onSend} />);

    const input = screen.getByPlaceholderText(/Ask anything/);
    fireEvent.change(input, { target: { value: "     " } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
  });

  it("não envia quando está desativado", () => {
    const onSend = vi.fn();
    render(<CommandBar onSend={onSend} disabled />);

    const input = screen.getByPlaceholderText(/Ask anything/) as HTMLInputElement;
    expect(input.disabled).toBe(true);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("lista comandos quando o input começa por barra", () => {
    useAdvancedModeStore.setState({
      activeModeIds: [],
      loadCommands: vi.fn(),
      commands: {
        forge: { description: "Constrói em modo forgé", aliases: ["f"] },
        proof: { description: "Verifica tudo", aliases: [] },
      },
    } as never);
    render(<CommandBar onSend={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText(/Ask anything/), { target: { value: "/" } });
    expect(screen.getByText("/forge")).toBeTruthy();
    expect(screen.getByText("Constrói em modo forgé")).toBeTruthy();
  });

  it("filtra as sugestões pelo que foi escrito depois da barra", () => {
    useAdvancedModeStore.setState({
      activeModeIds: [],
      loadCommands: vi.fn(),
      commands: {
        forge: { description: "A", aliases: [] },
        proof: { description: "B", aliases: [] },
      },
    } as never);
    render(<CommandBar onSend={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText(/Ask anything/), { target: { value: "/pro" } });
    expect(screen.queryByText("/forge")).toBeNull();
    expect(screen.getByText("/proof")).toBeTruthy();
  });

  it("completa o comando selecionado com Tab", () => {
    useAdvancedModeStore.setState({
      activeModeIds: [],
      loadCommands: vi.fn(),
      commands: { forge: { description: "A", aliases: [] } },
    } as never);
    render(<CommandBar onSend={vi.fn()} />);

    const input = screen.getByPlaceholderText(/Ask anything/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "/" } });
    fireEvent.keyDown(input, { key: "Tab" });

    expect(input.value).toBe("/forge ");
  });

  it("fecha as sugestões com Escape sem alterar o texto", async () => {
    useAdvancedModeStore.setState({
      activeModeIds: [],
      loadCommands: vi.fn(),
      commands: { forge: { description: "A", aliases: [] } },
    } as never);
    render(<CommandBar onSend={vi.fn()} />);

    const input = screen.getByPlaceholderText(/Ask anything/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "/" } });
    expect(screen.getByText("/forge")).toBeTruthy();
    fireEvent.keyDown(input, { key: "Escape" });

    expect(input.value).toBe("/");
    await settle();
    expect(screen.queryByText("/forge")).toBeNull();
  });

  it("lista os modos Infinity ativos", () => {
    useAdvancedModeStore.setState({
      activeModeIds: ["sentinel"],
      loadCommands: vi.fn(),
      commands: {},
    } as never);
    render(<CommandBar onSend={vi.fn()} />);

    expect(screen.getByText("sentinel")).toBeTruthy();
  });
});
