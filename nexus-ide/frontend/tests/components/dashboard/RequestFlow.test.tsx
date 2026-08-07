import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import RequestFlow from "../../../components/dashboard/RequestFlow";
import { useMetricsStore } from "../../../stores/metricsStore";

vi.mock("../../../lib/api", () => ({
  getMetricsFlow: vi.fn().mockResolvedValue({
    summary: { throughput_tps: 12 },
  }),
  getMetricsHistory: vi.fn().mockResolvedValue([]),
  getAlerts: vi.fn().mockResolvedValue({}),
  apiUrl: (p: string) => p,
  authHeaders: () => ({}),
}));

const emptyMetrics = null;

function makeMetrics(overrides: Record<string, unknown> = {}) {
  return {
    tokens_per_second: 0,
    active_model: "test-model",
    active_sessions: 0,
    queue_depth: 0,
    ram_used_bytes: 0,
    ram_total_bytes: 0,
    ram_percent: 0,
    cpu_percent: 0,
    disk_used_bytes: 0,
    disk_total_bytes: 0,
    disk_percent: 0,
    uptime_seconds: 0,
    requests_total: 0,
    requests_successful: 0,
    requests_failed: 0,
    avg_latency_ms: 0,
    timestamp: Math.floor(Date.now() / 1000),
    agent_activity: [],
    ...overrides,
  } as any;
}

describe("RequestFlow", () => {
  beforeEach(() => {
    useMetricsStore.setState({
      metrics: emptyMetrics as any,
      backendOnline: true,
      connectionStatus: "connected",
      history: [],
      historySeries: {},
      historyLoading: false,
      historyError: null,
    });
  });

  it("renderiza o título PT e o placeholder quando não há métricas", async () => {
    render(<RequestFlow />);
    expect(screen.getByText("Fluxo de Pedidos")).toBeDefined();
    expect(screen.getByText("Dados de fluxo indisponíveis")).toBeDefined();
    await waitFor(() => {
      expect(
        screen.getByText(
          "O backend não está a fornecer métricas de fluxo de pedidos.",
        ),
      ).toBeDefined();
    });
  });

  it("mostra aviso de backend offline quando backendOnline é false", async () => {
    useMetricsStore.setState({ backendOnline: false });
    render(<RequestFlow />);
    await waitFor(() => {
      expect(
        screen.getByText(
          "Backend offline — os dados apresentados podem estar desatualizados.",
        ),
      ).toBeDefined();
    });
  });

  it("mostra valores e agentes quando o store tem métricas", async () => {
    useMetricsStore.setState({
      metrics: makeMetrics({
        tokens_per_second: 12,
        requests_total: 5,
        requests_successful: 4,
        requests_failed: 1,
        avg_latency_ms: 200,
        agent_activity: [
          {
            agent: "CODER",
            status: "active",
            tasks_completed: 3,
            tasks_failed: 0,
            avg_latency_ms: 50,
            last_activity: new Date().toISOString(),
          },
        ],
      }),
    });
    render(<RequestFlow />);
    expect(screen.getByText("Utilizador")).toBeDefined();
    expect(screen.getByText("Router")).toBeDefined();
    expect(screen.getByText("LLM")).toBeDefined();
    expect(screen.getByText("Resposta")).toBeDefined();
    expect(
      screen.getByLabelText("Taxa de sucesso: 80.0 por cento, aceitável"),
    ).toBeDefined();
    // The agent name ``CODER`` is rendered both in the active-agents list
    // and in the request flow node, so multiple elements match. Use
    // ``getAllByText`` to assert the agent label is present at least once.
    await waitFor(() => {
      expect(screen.getAllByText("CODER").length).toBeGreaterThan(0);
    });
  });
});
