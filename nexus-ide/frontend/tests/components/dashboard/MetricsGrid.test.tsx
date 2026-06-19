import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import MetricsGrid from "../../../components/dashboard/MetricsGrid";
import { useMetricsStore } from "../../../stores/metricsStore";

function makeMetrics(overrides: Record<string, unknown> = {}) {
  return {
    tokens_per_second: 42.5,
    active_model: "nexus-pro",
    active_sessions: 3,
    queue_depth: 2,
    ram_used_bytes: 4e9,
    ram_total_bytes: 8e9,
    ram_percent: 50,
    cpu_percent: 35,
    disk_used_bytes: 100e9,
    disk_total_bytes: 500e9,
    disk_percent: 20,
    uptime_seconds: 120,
    requests_total: 7,
    requests_successful: 7,
    requests_failed: 0,
    avg_latency_ms: 150,
    timestamp: Math.floor(Date.now() / 1000),
    agent_activity: [],
    ...overrides,
  } as any;
}

describe("MetricsGrid", () => {
  beforeEach(() => {
    useMetricsStore.setState({
      metrics: null,
      backendOnline: false,
      history: [],
      historySeries: {},
      historyLoading: false,
      historyError: null,
    });
  });

  it("mostra o aviso PT de backend offline quando não há métricas nem backend", () => {
    render(<MetricsGrid />);
    expect(
      screen.getByText("Backend offline — a aguardar ligação…"),
    ).toBeDefined();
  });

  it("renderiza as células de métricas PT quando há dados", () => {
    useMetricsStore.setState({
      metrics: makeMetrics(),
      backendOnline: true,
    });
    render(<MetricsGrid />);
    expect(screen.getByText("Tokens/s")).toBeDefined();
    expect(screen.getByText("Modelo ativo")).toBeDefined();
    expect(screen.getByText("CPU")).toBeDefined();
    expect(screen.getByText("RAM")).toBeDefined();
    expect(screen.getByText("Latência")).toBeDefined();
  });

  it("mostra os valores formatados a partir das métricas", () => {
    useMetricsStore.setState({
      metrics: makeMetrics(),
      backendOnline: true,
    });
    render(<MetricsGrid />);
    expect(screen.getByText("42.5")).toBeDefined();
    expect(screen.getByText("nexus-pro")).toBeDefined();
    expect(screen.getByText("150 ms")).toBeDefined();
  });
});
