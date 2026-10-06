import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const mocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  connectionStatus: "offline",
  backendOnline: false,
  mode: {
    currentMode: "auto",
    setMode: vi.fn(),
    modes: [
      { id: "auto", description: "Escolha automática" },
      { id: "coder", description: "Implementação" },
      { id: "swarm", description: "Vários agentes" },
      { id: "auto_swarm", description: "Swarm automático" },
    ],
    modesLoaded: true,
    modesLoading: false,
    modesError: null,
    loadModes: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.routerPush }),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children: ReactNode; href: string; className?: string }) => (
    <a {...props}>{children}</a>
  ),
}));

vi.mock("../../../stores/metricsStore", () => ({
  useMetricsStore: (selector: (state: Record<string, unknown>) => unknown) => selector({
    metrics: null,
    history: [],
    backendOnline: mocks.backendOnline,
    connectionStatus: mocks.connectionStatus,
    connectionMode: "none",
    lastUpdate: "—",
  }),
}));

vi.mock("../../../stores/modeStore", () => ({
  useModeStore: () => mocks.mode,
}));

vi.mock("../../../components/ui/Surface", () => ({
  Surface: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SurfaceHeader: ({
    title,
    subtitle,
    action,
  }: { title: string; subtitle?: string; action?: ReactNode }) => (
    <header>
      <h2>{title}</h2>
      {subtitle ? <p>{subtitle}</p> : null}
      {action}
    </header>
  ),
}));

vi.mock("../../../components/ui/KpiCard", () => ({
  KpiCard: ({ label, value }: { label: string; value: string }) => <div>{label}: {value}</div>,
  GaugeCard: ({ label }: { label: string }) => <div>{label}</div>,
}));

vi.mock("../../../components/ui/Card", () => ({
  Card: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CardEmpty: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  CardStat: ({ label, value }: { label: string; value: ReactNode }) => <div>{label}: {value}</div>,
}));

vi.mock("../../../components/dashboard/UsageWidget", () => ({ default: () => <div>Consumo</div> }));
vi.mock("../../../components/dashboard/ProviderStatusWidget", () => ({ default: () => <div>Providers</div> }));
vi.mock("../../../components/dashboard/MCPStatusWidget", () => ({ default: () => <div>MCP</div> }));
vi.mock("../../../components/dashboard/SubagentsWidget", () => ({ default: () => <div>Subagentes</div> }));
vi.mock("../../../components/dashboard/AdvisorWidget", () => ({ default: () => <div>Advisor</div> }));
vi.mock("../../../components/dashboard/MissionPanel", () => ({ default: () => <div>Missão</div> }));
vi.mock("../../../components/dashboard/InfinitySuiteWidget", () => ({ default: () => <div>Modos avançados</div> }));

import DashboardClient from "../../../app/dashboard/DashboardClient";

describe("DashboardClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.mode.currentMode = "auto";
    mocks.connectionStatus = "offline";
    mocks.backendOnline = false;
  });

  it("expõe navegação com secções e encaminha o objetivo para o chat selecionado", () => {
    render(<DashboardClient />);

    expect(screen.getByRole("heading", { name: "Painel de Operações" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Navegação rápida da dashboard" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Agentes" }).getAttribute("href")).toBe("#agentes");
    expect(screen.getByText("Débito: —")).toBeTruthy();
    expect(screen.getByText("P95 aprox. das médias: —")).toBeTruthy();
    expect(screen.getByText("Subagentes")).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "O que queres fazer?" }), {
      target: { value: "Analisa a pesquisa" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preparar no chat" }));

    expect(mocks.routerPush).toHaveBeenCalledWith("/?prompt=Analisa%20a%20pesquisa");
    expect(mocks.mode.loadModes).toHaveBeenCalledTimes(1);
  });

  it("manda objetivos de execução swarm para a rota SWARM", () => {
    mocks.mode.currentMode = "swarm";
    render(<DashboardClient />);

    fireEvent.change(screen.getByRole("textbox", { name: "O que queres fazer?" }), {
      target: { value: "Revê a arquitetura" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preparar no SWARM" }));

    expect(mocks.routerPush).toHaveBeenCalledWith("/swarm?prompt=Rev%C3%AA%20a%20arquitetura");
  });

  it("moves focus and selection through the execution mode radio group with arrow keys", () => {
    render(<DashboardClient />);

    const automatic = screen.getByRole("radio", { name: /Escolha automática/ });
    const coder = screen.getByRole("radio", { name: /Implementação/ });
    expect(automatic.getAttribute("tabindex")).toBe("0");
    expect(coder.getAttribute("tabindex")).toBe("-1");

    fireEvent.keyDown(automatic, { key: "ArrowRight" });

    expect(mocks.mode.setMode).toHaveBeenCalledWith("coder");
    expect(document.activeElement).toBe(coder);
  });

  it("distinguishes an expired session from a backend connectivity failure", () => {
    mocks.connectionStatus = "auth_required";
    mocks.backendOnline = true;

    render(<DashboardClient />);

    expect(screen.getByText(/Sistema Sessão expirada/)).toBeTruthy();
  });
});
