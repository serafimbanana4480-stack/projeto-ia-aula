import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import NexusTopBar from "../../../components/nexus/NexusTopBar";
import { useAgentStore } from "../../../stores/useAgentStore";
import { useTaskStore } from "../../../stores/useTaskStore";
import { useMetricsStore } from "../../../stores/metricsStore";

describe("NexusTopBar", () => {
  beforeEach(() => {
    useMetricsStore.setState({ metrics: null, backendOnline: false });
    useAgentStore.setState({ agents: {}, isLoading: false, hasFetchedAgents: false, error: null });
    useTaskStore.setState({ tasks: {}, tasksLoading: false, hasFetchedTasks: false, tasksError: null });
  });

  it("usa desconhecido antes de receber estado, em vez de mostrar zero", () => {
    render(<NexusTopBar />);

    expect(screen.getByText("agentes ativos").previousElementSibling?.textContent).toBe("—");
    expect(screen.getByText("— em execução")).toBeTruthy();
    expect(screen.getByText("— em fila")).toBeTruthy();
  });

  it("mostra zero quando a API confirmou uma lista de tarefas vazia", () => {
    useTaskStore.setState({ hasFetchedTasks: true });

    render(<NexusTopBar />);

    expect(screen.getByText("0 em execução")).toBeTruthy();
    expect(screen.getByText("0 em fila")).toBeTruthy();
  });

  it("mantém pedidos desconhecidos quando falta essa métrica", () => {
    useMetricsStore.setState({ backendOnline: true, metrics: {} as any });

    render(<NexusTopBar />);

    expect(screen.getByText("pedidos").previousElementSibling?.textContent).toBe("—");
    expect(screen.getByText("API ligada · sem dados")).toBeTruthy();
  });

  it("só conta agentes em execução e mostra zero após resposta válida vazia", () => {
    useMetricsStore.setState({ backendOnline: true, metrics: {
      tokens_per_second: 0,
      active_model: "test",
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
      timestamp: Date.now(),
    } });
    useAgentStore.setState({ agents: {
      active: { status: "executing" },
      running: { status: "running" },
      failed: { status: "failed" },
    } as any });
    useTaskStore.setState({ tasks: {
      active: { id: "active", status: "running" },
      retrying: { id: "retrying", status: "retrying" },
      awaiting: { id: "awaiting", status: "awaiting_approval" },
      paused: { id: "paused", status: "paused" },
    } as any });

    render(<NexusTopBar />);

    expect(screen.getByText("API ligada")).toBeTruthy();
    expect(screen.getByText("agentes ativos").previousElementSibling?.textContent).toBe("2");
    expect(screen.getByText("2 em execução")).toBeTruthy();
    expect(screen.getByText("1 em fila")).toBeTruthy();
  });

  it("marca os últimos valores como antigos quando a ligação cai", () => {
    useMetricsStore.setState({
      backendOnline: false,
      metrics: {
        cpu_percent: 0,
        ram_percent: 0,
      } as any,
    });

    render(<NexusTopBar />);

    expect(screen.getByText("Sem ligação · dados antigos")).toBeTruthy();
    expect(screen.getByText("cpu").previousElementSibling?.textContent).toBe("0%");
  });
});
