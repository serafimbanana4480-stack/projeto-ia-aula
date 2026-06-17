import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import TokenTimeline from "../../../components/dashboard/TokenTimeline";
import { useMetricsStore } from "../../../stores/metricsStore";

vi.mock("recharts", () => ({
  AreaChart: () => null,
  Area: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  CartesianGrid: () => null,
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
}));

describe("TokenTimeline", () => {
  beforeEach(() => {
    useMetricsStore.setState({
      metrics: null,
      history: [],
      historySeries: {},
      historyLoading: false,
      historyError: null,
      loadHistory: vi.fn(),
    });
  });

  it("renderiza o título PT e o estado vazio quando não há dados", () => {
    render(<TokenTimeline />);
    expect(screen.getByText("Linha Temporal de Tokens")).toBeDefined();
    expect(screen.getByText("sem dados")).toBeDefined();
    expect(screen.getByText("Sem dados disponíveis")).toBeDefined();
  });

  it("mostra o spinner de carregamento PT quando historyLoading é true", () => {
    useMetricsStore.setState({ historyLoading: true });
    render(<TokenTimeline />);
    expect(screen.getByText("A carregar…")).toBeDefined();
  });

  it("mostra o alerta de erro PT quando historyError está definido", () => {
    useMetricsStore.setState({ historyError: "fail" });
    render(<TokenTimeline />);
    expect(screen.getByText("Erro ao carregar histórico")).toBeDefined();
  });

  it("mostra Pico e Média quando há série histórica", () => {
    const now = Math.floor(Date.now() / 1000);
    useMetricsStore.setState({
      historySeries: {
        tokens_per_second: [
          { t: now - 60, v: 10 },
          { t: now, v: 20 },
        ],
      },
    });
    render(<TokenTimeline />);
    expect(screen.getAllByText("Pico").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Média").length).toBeGreaterThan(0);
  });
});
