import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AgentActivity from "../../../components/dashboard/AgentActivity";
import { useMetricsStore } from "../../../stores/metricsStore";

vi.mock("recharts", () => ({
  BarChart: () => null,
  Bar: () => null,
  Cell: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  LineChart: () => null,
  Line: () => null,
  AreaChart: () => null,
  Area: () => null,
  PieChart: () => null,
  Pie: () => null,
  RadarChart: () => null,
  Radar: () => null,
  PolarGrid: () => null,
  PolarAngleAxis: () => null,
  PolarRadiusAxis: () => null,
}));

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

describe("AgentActivity", () => {
  beforeEach(() => {
    useMetricsStore.setState({
      metrics: null,
      backendOnline: true,
      history: [],
      historySeries: {},
      historyLoading: false,
      historyError: null,
    });
  });

  it("renderiza o título PT e o carregamento quando não há métricas", () => {
    render(<AgentActivity />);
    expect(screen.getByText("Utilização por perfil")).toBeDefined();
    expect(
      screen.getByRole("status", { name: "A carregar utilização por perfil" }),
    ).toBeDefined();
  });

  it("mostra o placeholder PT quando não há respostas recentes", () => {
    useMetricsStore.setState({ metrics: makeMetrics() });
    render(<AgentActivity />);
    expect(screen.getByText("Sem respostas recentes")).toBeDefined();
    expect(
      screen.getByText(/As respostas com perfil de execução aparecem aqui/),
    ).toBeDefined();
  });

  it("mostra perfis e contagem de respostas sem tratar erros de sessão como tarefas", () => {
    useMetricsStore.setState({
      metrics: makeMetrics({
        agent_activity: [
          {
            agent: "CODER",
            status: "active",
            tasks_completed: 5,
            tasks_failed: 1,
            avg_latency_ms: 120,
            last_activity: new Date().toISOString(),
          },
        ],
      }),
    });
    render(<AgentActivity />);
    expect(screen.getByText("CODER")).toBeDefined();
    expect(screen.getByText("5")).toBeDefined();
    expect(screen.getByText("5 no total")).toBeDefined();
    expect(screen.getByText("1 em execução")).toBeDefined();
    expect(screen.queryByLabelText("Falhadas")).toBeNull();
  });
});
