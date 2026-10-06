import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import TasksPage from "../../../app/dashboard/tasks/page";
import { authenticatedFetch } from "../../../lib/auth";

vi.mock("../../../components/layout/AppShell", () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("../../../lib/api", () => ({
  apiUrl: (path: string) => `http://localhost:8000${path}`,
}));

vi.mock("../../../lib/auth", () => ({
  authenticatedFetch: vi.fn(),
}));

function apiResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

const sampleTasks = {
  active: [
    {
      id: "run-1",
      title: "Corrigir a pesquisa de ficheiros",
      agent: "NEXUS",
      status: "running",
      progress: 42,
      created_at: "2026-09-27T09:30:00Z",
    },
  ],
  queued: [
    {
      id: "run-2",
      title: "Rever a documentação",
      agent: "Researcher",
      status: "pending",
      progress: 0,
      created_at: null,
    },
  ],
  failed: [
    {
      id: "run-4",
      title: "Validar resultado do agente",
      agent: "Verifier",
      status: "failed",
      progress: 65,
      created_at: "2026-09-27T10:15:00Z",
    },
  ],
  completed: [
    {
      id: "run-3",
      title: "Atualizar dependências",
      agent: "Coder",
      status: "completed",
      progress: 100,
      created_at: "2026-09-26T17:15:00Z",
    },
  ],
};

describe("Dashboard tasks page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("carrega e apresenta os quatro grupos a partir do endpoint", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue(apiResponse(sampleTasks));

    render(<TasksPage />);

    expect(await screen.findByText("Corrigir a pesquisa de ficheiros")).toBeTruthy();
    expect(screen.getByText("Rever a documentação")).toBeTruthy();
    expect(screen.getByText("Validar resultado do agente")).toBeTruthy();
    expect(screen.getByText("Atualizar dependências")).toBeTruthy();
    expect(screen.getByText("42% reportado")).toBeTruthy();
    expect(screen.queryByRole("progressbar", { name: /0%/ })).toBeNull();
    expect(authenticatedFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/tasks/list?limit=50&offset=0",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );

    fireEvent.click(screen.getByRole("button", { name: /Na fila/ }));
    expect(screen.getByText("Rever a documentação")).toBeTruthy();
    expect(screen.queryByText("Corrigir a pesquisa de ficheiros")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Falhadas/ }));
    expect(screen.getByText("Validar resultado do agente")).toBeTruthy();
    expect(screen.getByText("Falhou")).toBeTruthy();
    expect(screen.queryByText("Atualizar dependências")).toBeNull();
  });

  it("identifica a contagem ativa como incluindo tarefas pausadas", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue(apiResponse({
      active: [
        { id: "running-1", title: "A executar", status: "running" },
        { id: "paused-1", title: "Em pausa", status: "paused" },
        { id: "retrying-1", title: "A tentar outra vez", status: "retrying" },
      ],
      queued: [],
      failed: [],
      completed: [],
      cancelled: [],
    }));

    render(<TasksPage />);

    expect(await screen.findByText("Em pausa")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Ativas ou pausadas 3/ })).toBeTruthy();
    expect(screen.getByText("Em curso, a tentar novamente ou em pausa")).toBeTruthy();
    expect(screen.getByText("Pausada")).toBeTruthy();
  });

  it("permite atualizar os dados sem sair da página", async () => {
    vi.mocked(authenticatedFetch)
      .mockResolvedValueOnce(apiResponse(sampleTasks))
      .mockResolvedValueOnce(apiResponse({ active: [sampleTasks.active[0]], queued: [], failed: [], completed: [] }));

    render(<TasksPage />);
    expect(await screen.findByText("Corrigir a pesquisa de ficheiros")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Atualizar tarefas" }));
    await waitFor(() => expect(screen.queryByText("Rever a documentação")).toBeNull());
    expect(authenticatedFetch).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: /Falhadas/ }));
    expect(screen.getByText("Sem tarefas com falhas")).toBeTruthy();
    expect(screen.getByText(/A lista verifica automaticamente a cada 10 segundos/)).toBeTruthy();
  });

  it("mostra os passos e os agentes atribuídos num plano à espera de aprovação", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue(apiResponse({
      active: [],
      queued: [{
        id: "plan-review-1",
        title: "Plano de pesquisa",
        agent: "",
        kind: "plan",
        status: "awaiting_approval",
        approval_status: "awaiting_approval",
        completed_steps: 1,
        total_steps: 2,
        progress: null,
        created_at: "2026-09-27T10:15:00Z",
        steps: [
          { id: "step-1", title: "Pesquisar fontes", agent: "RESEARCHER", status: "completed" },
          { id: "step-2", title: "Comparar resultados", agent: "ANALYST", status: "pending" },
        ],
      }],
      failed: [],
      completed: [],
      cancelled: [],
      warnings: [],
    }));

    render(<TasksPage />);

    expect(await screen.findByText("Plano de pesquisa")).toBeTruthy();
    expect(screen.getByText("A aguardar aprovação")).toBeTruthy();
    expect(screen.getByText("Revê este plano e aprova-o no chat antes da execução.")).toBeTruthy();
    expect(screen.getByText("1 de 2 etapas concluídas")).toBeTruthy();
    expect(screen.queryByText("Agente não identificado")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Ver 2 etapas do plano" }));
    expect(screen.getByText("Pesquisar fontes")).toBeTruthy();
    expect(screen.getByText("RESEARCHER")).toBeTruthy();
    expect(screen.getByText("ANALYST")).toBeTruthy();
  });

  it("mantém à vista os dados da fonte que falhou durante uma atualização parcial", async () => {
    vi.mocked(authenticatedFetch)
      .mockResolvedValueOnce(apiResponse({ ...sampleTasks, sources: {
        workflows: { available: true }, plans: { available: true },
      } }))
      .mockResolvedValueOnce(apiResponse({
        active: [],
        queued: [{
          id: "plan-new", title: "Plano novo", kind: "plan", status: "approved", progress: null,
          completed_steps: 0, total_steps: 1, steps: [], created_at: "2026-09-27T10:20:00Z",
        }],
        failed: [], completed: [], cancelled: [],
        warnings: ["Os workflows não estão disponíveis neste momento."],
        sources: { workflows: { available: false }, plans: { available: true } },
      }));

    render(<TasksPage />);
    expect(await screen.findByText("Corrigir a pesquisa de ficheiros")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Atualizar tarefas" }));

    expect(await screen.findByText("Plano novo")).toBeTruthy();
    expect(screen.getByText("Corrigir a pesquisa de ficheiros")).toBeTruthy();
    expect(screen.getByText(/os dados que chegaram continuam visíveis/i)).toBeTruthy();
  });

  it("consulta novamente a lista através do polling automático", async () => {
    // This test invokes the captured callback manually below, so keep the
    // scheduled interval from also firing during the assertions.
    const intervalSpy = vi
      .spyOn(window, "setInterval")
      .mockImplementation(() => 0 as unknown as ReturnType<typeof window.setInterval>);
    vi.mocked(authenticatedFetch)
      .mockResolvedValueOnce(apiResponse(sampleTasks))
      .mockResolvedValueOnce(apiResponse({ ...sampleTasks, active: [] }));

    try {
      render(<TasksPage />);
      expect(await screen.findByText("Corrigir a pesquisa de ficheiros")).toBeTruthy();
      const pollCall = intervalSpy.mock.calls.find(([, delay]) => delay === 10_000);
      expect(pollCall).toBeTruthy();
      await act(async () => {
        (pollCall?.[0] as () => void)();
      });
      await waitFor(() => expect(authenticatedFetch).toHaveBeenCalledTimes(2));
      expect(screen.queryByText("Corrigir a pesquisa de ficheiros")).toBeNull();
    } finally {
      intervalSpy.mockRestore();
    }
  });

  it("faz o carregamento inicial logo após a repetição de efeitos do Strict Mode", async () => {
    vi.mocked(authenticatedFetch)
      .mockImplementationOnce((_input, init) => new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        const abort = () => reject(new DOMException("Aborted", "AbortError"));
        if (signal?.aborted) abort();
        else signal?.addEventListener("abort", abort, { once: true });
      }))
      .mockResolvedValueOnce(apiResponse(sampleTasks));

    render(<StrictMode><TasksPage /></StrictMode>);

    expect(await screen.findByText("Corrigir a pesquisa de ficheiros")).toBeTruthy();
    expect(authenticatedFetch).toHaveBeenCalledTimes(2);
  });

  it("carrega a página seguinte sem duplicar itens já visíveis", async () => {
    vi.mocked(authenticatedFetch)
      .mockResolvedValueOnce(apiResponse({
        ...sampleTasks,
        queued: [{ ...sampleTasks.queued[0], id: "page-1", title: "Tarefa 1" }],
        pagination: {
          active: { offset: 0, limit: 1, total: 0, has_more: false },
          queued: { offset: 0, limit: 1, total: 2, has_more: true },
          failed: { offset: 0, limit: 1, total: 0, has_more: false },
          completed: { offset: 0, limit: 1, total: 0, has_more: false },
          cancelled: { offset: 0, limit: 1, total: 0, has_more: false },
        },
      }))
      .mockResolvedValueOnce(apiResponse({
        active: [],
        queued: [{ ...sampleTasks.queued[0], id: "page-2", title: "Tarefa 2" }],
        failed: [], completed: [], cancelled: [],
        pagination: {
          active: { offset: 1, limit: 1, total: 0, has_more: false },
          queued: { offset: 1, limit: 1, total: 2, has_more: false },
          failed: { offset: 1, limit: 1, total: 0, has_more: false },
          completed: { offset: 1, limit: 1, total: 0, has_more: false },
          cancelled: { offset: 1, limit: 1, total: 0, has_more: false },
        },
      }));

    render(<TasksPage />);
    expect(await screen.findByText("Tarefa 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Carregar mais tarefas" }));

    expect(await screen.findByText("Tarefa 2")).toBeTruthy();
    expect(screen.getByText("Tarefa 1")).toBeTruthy();
    expect(
      screen.getByText("Tarefa 1").compareDocumentPosition(screen.getByText("Tarefa 2"))
        & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(authenticatedFetch).toHaveBeenLastCalledWith(
      "http://localhost:8000/api/tasks/list?limit=50&offset=50",
      expect.objectContaining({ method: "GET" }),
    );
    expect(screen.queryByRole("button", { name: "Carregar mais tarefas" })).toBeNull();
  });

  it("preserva a cauda e o cursor após polling e refresh com mais de 500 tarefas", async () => {
    const total = 700;
    const requests: string[] = [];
    // Hundreds of rendered rows can exceed one real 10-second interval on a
    // busy runner. This test invokes polling manually below, so keep it
    // deterministic and avoid a refresh racing the pagination assertions.
    const intervalSpy = vi
      .spyOn(window, "setInterval")
      .mockImplementation(() => 0 as unknown as ReturnType<typeof window.setInterval>);
    vi.mocked(authenticatedFetch).mockImplementation(async (input) => {
      const url = new URL(String(input));
      const offset = Number(url.searchParams.get("offset"));
      const limit = Number(url.searchParams.get("limit"));
      requests.push(`${limit}:${offset}`);
      const count = Math.max(0, Math.min(limit, total - offset));
      const queued = Array.from({ length: count }, (_, index) => ({
        id: `task-${offset + index}`,
        title: `Tarefa ${offset + index}`,
        status: "pending",
        created_at: new Date(Date.UTC(2026, 0, total - offset - index)).toISOString(),
      }));
      return apiResponse({
        active: [],
        queued,
        failed: [],
        completed: [],
        cancelled: [],
        pagination: {
          active: { offset, limit, total: 0, has_more: false },
          queued: { offset, limit, total, has_more: offset + limit < total },
          failed: { offset, limit, total: 0, has_more: false },
          completed: { offset, limit, total: 0, has_more: false },
          cancelled: { offset, limit, total: 0, has_more: false },
        },
      });
    });

    try {
      render(<TasksPage />);
      expect(await screen.findByText("Tarefa 49")).toBeTruthy();

      for (let offset = 50; offset <= 500; offset += 50) {
        fireEvent.click(screen.getByRole("button", { name: "Carregar mais tarefas" }));
        expect(await screen.findByText(`Tarefa ${offset + 49}`)).toBeTruthy();
        expect(requests.at(-1)).toBe(`50:${offset}`);
      }
      expect(screen.getByText("Tarefa 549")).toBeTruthy();

      const refreshButton = screen.getByRole("button", { name: "Atualizar tarefas" }) as HTMLButtonElement;
      const beforeRefresh = requests.length;
      fireEvent.click(refreshButton);
      await waitFor(() => expect(refreshButton.disabled).toBe(false));
      expect(requests.slice(beforeRefresh)).toEqual(["500:0", "50:500"]);
      expect(screen.getByText("Tarefa 549")).toBeTruthy();

      const pollCall = intervalSpy.mock.calls.find(([, delay]) => delay === 10_000);
      const beforePoll = requests.length;
      await act(async () => {
        (pollCall?.[0] as () => void)();
      });
      await waitFor(() => expect(requests.length).toBe(beforePoll + 2));
      expect(requests.slice(beforePoll)).toEqual(["500:0", "50:500"]);
      expect(screen.getByText("Tarefa 549")).toBeTruthy();

      fireEvent.click(screen.getByRole("button", { name: "Carregar mais tarefas" }));
      expect(await screen.findByText("Tarefa 599")).toBeTruthy();
      expect(requests.at(-1)).toBe("50:550");
      expect(screen.getByText("Tarefa 549")).toBeTruthy();
    } finally {
      intervalSpy.mockRestore();
    }
  }, 30_000);

  it("mostra erro recuperável quando a API falha", async () => {
    vi.mocked(authenticatedFetch)
      .mockResolvedValueOnce(apiResponse({ detail: "Serviço temporariamente indisponível" }, 503))
      .mockResolvedValueOnce(apiResponse(sampleTasks));

    render(<TasksPage />);

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Serviço temporariamente indisponível")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    await waitFor(() => expect(screen.getByText("Corrigir a pesquisa de ficheiros")).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("explica em português quando o backend está desligado", async () => {
    vi.mocked(authenticatedFetch).mockRejectedValue(
      new TypeError("Failed to connect to the server"),
    );

    render(<TasksPage />);

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(
      "Não foi possível ligar ao serviço de tarefas. Confirma se o backend está ativo e tenta novamente.",
    )).toBeTruthy();
  });
});
