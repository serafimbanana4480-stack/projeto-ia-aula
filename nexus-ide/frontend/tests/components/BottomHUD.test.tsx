import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import BottomHUD from "../../components/layout/BottomHUD";
import { useMetricsStore } from "../../stores/metricsStore";

function makeMetrics(diskPercent: number) {
  return {
    tokens_per_second: 0,
    active_model: "none",
    active_sessions: 0,
    queue_depth: 0,
    ram_used_bytes: 0,
    ram_total_bytes: 0,
    ram_percent: 0,
    cpu_percent: 0,
    disk_used_bytes: 0,
    disk_total_bytes: 100,
    disk_percent: diskPercent,
    uptime_seconds: 60,
    requests_total: 0,
    requests_successful: 0,
    requests_failed: 0,
    avg_latency_ms: 0,
    timestamp: Date.now(),
  };
}

describe("BottomHUD", () => {
  beforeEach(() => {
    useMetricsStore.setState({
      metrics: null,
      history: [],
      backendOnline: false,
      connectionStatus: "offline",
    });
  });

  it("descreve a ligação como resposta do backend, sem prometer saúde total", () => {
    useMetricsStore.setState({
      backendOnline: true,
      connectionStatus: "connected",
    });

    render(<BottomHUD />);

    expect(screen.getByText("A responder")).toBeDefined();
    expect(screen.getByText("Backend")).toBeDefined();
  });

  it("mostra o disco crítico no HUD compacto", () => {
    useMetricsStore.setState({
      metrics: makeMetrics(99),
      backendOnline: true,
      connectionStatus: "connected",
    });

    render(<BottomHUD />);

    expect(screen.getByRole("status", { name: "Disco 99%, crítico" })).toBeDefined();
    expect(screen.getByText("Crítico")).toBeDefined();
  });

  it("marca o disco em aviso antes do limiar crítico", () => {
    useMetricsStore.setState({
      metrics: makeMetrics(80),
      backendOnline: true,
      connectionStatus: "connected",
    });

    render(<BottomHUD />);

    expect(screen.getByRole("status", { name: "Disco 80%, em aviso" })).toBeDefined();
    expect(screen.queryByText("Crítico")).toBeNull();
  });
});
