import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SubagentsWidget from "../../../components/dashboard/SubagentsWidget";

vi.mock("../../../lib/api", () => ({
  apiUrl: (path: string) => `http://localhost:8000${path}`,
}));

vi.mock("../../../lib/auth", () => ({
  authenticatedFetch: (input: RequestInfo | URL, init?: RequestInit) => fetch(input, init),
}));

vi.mock("../../../components/ui/Surface", () => ({
  Surface: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
  SurfaceHeader: ({ title, subtitle, action }: { title: string; subtitle: string; action?: React.ReactNode }) => (
    <header><h2>{title}</h2><p>{subtitle}</p>{action}</header>
  ),
}));

vi.mock("../../../components/ui/Card", () => ({
  CardEmpty: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  CardStat: ({ label, value }: { label: string; value: React.ReactNode }) => <div><span>{label}</span><span>{value}</span></div>,
}));

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

const statusBody = {
  running: true,
  total_cycles: 3,
  consecutive_failures: 0,
  circuit_open: false,
};

function telemetry(recent: Array<Record<string, unknown>> = []) {
  return {
    stats: {
      total_subagents: recent.length,
      successful: recent.length,
      failed: 0,
      success_rate: recent.length ? 1 : 0,
      retried: 0,
      context_degraded: 0,
      total_tokens: recent.length * 10,
    },
    recent,
  };
}

function run(index: number): Record<string, unknown> {
  return {
    subagent_id: `subagent-${index}`,
    phase: "RESEARCH",
    success: true,
    error: null,
    tokens_used: 10,
    duration_seconds: 1.5,
    retries: 0,
    resumed: false,
    context_degraded: false,
    started_at: `2026-09-27T10:${String(index).padStart(2, "0")}:00Z`,
    completed_at: null,
  };
}

describe("SubagentsWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("mostra o estado de carregamento e apresenta resultados reais paginados", async () => {
    const recent = Array.from({ length: 7 }, (_, index) => run(index));
    vi.mocked(fetch).mockImplementation(async (input) => response(
      String(input).endsWith("/status") ? statusBody : telemetry(recent),
    ));

    render(<SubagentsWidget />);

    expect(screen.getByText("A carregar telemetria de subagentes…")).toBeTruthy();
    expect(await screen.findByText("3 ciclos")).toBeTruthy();
    expect(screen.getAllByText("RESEARCH")).toHaveLength(6);
    const firstRecentRow = screen.getAllByText("RESEARCH")[0].closest(".nx-inset");
    expect(firstRecentRow?.className).toContain("sm:flex-row");
    fireEvent.click(screen.getByRole("button", { name: "Ver mais 1 de 7 execuções" }));
    expect(screen.getAllByText("RESEARCH")).toHaveLength(7);
    expect(screen.getByText(/Atualizado às/)).toBeTruthy();
  });

  it("não sobrepõe polling a uma chamada em curso e permite refresh manual depois", async () => {
    let resolveStatus!: (value: Response) => void;
    let resolveTelemetry!: (value: Response) => void;
    vi.mocked(fetch)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveStatus = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveTelemetry = resolve; }))
      .mockImplementation(async (input) => response(
        String(input).endsWith("/status") ? statusBody : telemetry([run(1)]),
      ));
    const interval = vi.spyOn(window, "setInterval");

    render(<SubagentsWidget />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const poll = interval.mock.calls.find(([, delay]) => delay === 10_000)?.[0] as () => void;
    await act(async () => { poll(); });
    expect(fetch).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveStatus(response(statusBody));
      resolveTelemetry(response(telemetry([run(0)])));
    });
    expect(await screen.findByText("3 ciclos")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Atualizar telemetria de subagentes" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
    expect(await screen.findByText("RESEARCH")).toBeTruthy();
  });

  it("preserva a última telemetria e assinala dados desatualizados quando o refresh falha", async () => {
    vi.mocked(fetch)
      .mockImplementationOnce(async () => response(statusBody))
      .mockImplementationOnce(async () => response(telemetry([run(0)])))
      .mockImplementation(async () => response({ detail: "indisponível" }, 503));

    render(<SubagentsWidget />);
    expect(await screen.findByText("RESEARCH")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Atualizar telemetria de subagentes" }));

    expect(await screen.findByText("A mostrar dados anteriores; atualização falhou.")).toBeTruthy();
    expect(screen.getAllByText("RESEARCH")).toHaveLength(1);
    expect(screen.queryByText("Sem ligação ao backend — telemetria indisponível.")).toBeNull();
  });

  it("não apresenta métricas inválidas como se fossem verdadeiras", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => response(
      String(input).endsWith("/status") ? statusBody : {
        ...telemetry(),
        stats: { ...telemetry().stats, success_rate: 1.4 },
      },
    ));

    render(<SubagentsWidget />);
    expect(await screen.findByText("Sem ligação ao backend — telemetria indisponível.")).toBeTruthy();
    expect(screen.getAllByText("—")).toHaveLength(5);
  });

  it("cancela os pedidos pendentes quando o widget sai do dashboard", async () => {
    vi.mocked(fetch).mockImplementation(() => new Promise(() => {}));
    const { unmount } = render(<SubagentsWidget />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const signals = vi.mocked(fetch).mock.calls.map(([, init]) => init?.signal);

    unmount();

    expect(signals.every((signal) => signal?.aborted)).toBe(true);
  });
});
