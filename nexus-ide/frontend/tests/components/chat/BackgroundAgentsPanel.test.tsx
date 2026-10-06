import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BackgroundAgentsPanel from "../../../components/chat/BackgroundAgentsPanel";
import type { AgentInstance } from "../../../lib/api";

const getAgentInstances = vi.fn();
const pauseAgentInstance = vi.fn();
const resumeAgentInstance = vi.fn();
const abortAgentInstance = vi.fn();

vi.mock("../../../lib/api", () => ({
  getAgentInstances: (...args: unknown[]) => getAgentInstances(...args),
  pauseAgentInstance: (...args: unknown[]) => pauseAgentInstance(...args),
  resumeAgentInstance: (...args: unknown[]) => resumeAgentInstance(...args),
  abortAgentInstance: (...args: unknown[]) => abortAgentInstance(...args),
}));

function agent(overrides: Partial<AgentInstance> = {}): AgentInstance {
  return {
    id: "instance-1",
    name: "ARCHITECT",
    instance_id: "instance-1",
    agent_type: "ARCHITECT",
    status: "running",
    objective: "Inspecionar o projeto",
    start_time: Date.now() / 1_000 - 10,
    mission_id: "session-1",
    parent_task_id: "task-actual-7",
    ...overrides,
  };
}

describe("BackgroundAgentsPanel", () => {
  beforeEach(() => {
    getAgentInstances.mockReset();
    pauseAgentInstance.mockReset();
    resumeAgentInstance.mockReset();
    abortAgentInstance.mockReset();
  });

  it("mostra apenas agentes da sessão e abre um inspector com campos reportados", async () => {
    getAgentInstances.mockResolvedValue([
      agent(),
      agent({ instance_id: "other-session", mission_id: "session-2", agent_type: "CODER" }),
    ]);
    render(<BackgroundAgentsPanel sessionId="session-1" />);

    const card = await screen.findByRole("button", { name: /ARCHITECT.*Em execução/ });
    expect(screen.queryByText("CODER")).toBeNull();
    fireEvent.click(card);

    expect(screen.getByRole("region", { name: "Inspector de ARCHITECT" })).toBeTruthy();
    expect(screen.getByText("Inspecionar o projeto")).toBeTruthy();
    expect(screen.getByText("task-actual-7")).toBeTruthy();
    expect(screen.queryByText(/Modelo|CPU|Memória|Tokens/)).toBeNull();
    expect(getAgentInstances).toHaveBeenCalledWith({ sessionId: "session-1", includeTerminal: true });
  });

  it("pausa e atualiza o card só após confirmação do backend", async () => {
    const running = agent();
    const paused = agent({ status: "paused" });
    getAgentInstances.mockResolvedValue([running]);
    pauseAgentInstance.mockResolvedValue({ success: true, action: "pause", instance: paused });
    render(<BackgroundAgentsPanel sessionId="session-1" />);

    fireEvent.click(await screen.findByRole("button", { name: /ARCHITECT.*Em execução/ }));
    fireEvent.click(screen.getByRole("button", { name: "Pausar" }));

    await waitFor(() => expect(pauseAgentInstance).toHaveBeenCalledWith("instance-1"));
    expect(await screen.findByRole("button", { name: /ARCHITECT.*Pausado/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retomar" })).toBeTruthy();
  });

  it("mostra o erro da ação sem trocar o estado atual", async () => {
    getAgentInstances.mockResolvedValue([agent()]);
    pauseAgentInstance.mockRejectedValue(new Error("pausa recusada"));
    render(<BackgroundAgentsPanel sessionId="session-1" />);

    fireEvent.click(await screen.findByRole("button", { name: /ARCHITECT.*Em execução/ }));
    fireEvent.click(screen.getByRole("button", { name: "Pausar" }));

    expect((await screen.findByRole("alert")).textContent).toContain("pausa recusada");
    expect(screen.getByRole("button", { name: /ARCHITECT.*Em execução/ })).toBeTruthy();
  });

  it("retoma um agente pausado quando a API confirma", async () => {
    const paused = agent({ status: "paused" });
    const running = agent({ status: "running" });
    getAgentInstances.mockResolvedValue([paused]);
    resumeAgentInstance.mockResolvedValue({ success: true, action: "resume", instance: running });
    render(<BackgroundAgentsPanel sessionId="session-1" />);

    fireEvent.click(await screen.findByRole("button", { name: /ARCHITECT.*Pausado/ }));
    fireEvent.click(screen.getByRole("button", { name: "Retomar" }));

    expect(await screen.findByRole("button", { name: /ARCHITECT.*Em execução/ })).toBeTruthy();
    expect(resumeAgentInstance).toHaveBeenCalledWith("instance-1");
  });

  it("pára um agente e esconde ações que já não se aplicam", async () => {
    const running = agent({ status: "running" });
    const aborted = agent({ status: "aborted", completed_at: Date.now() / 1_000 });
    getAgentInstances.mockResolvedValue([running]);
    abortAgentInstance.mockResolvedValue({ success: true, action: "abort", instance: aborted });
    render(<BackgroundAgentsPanel sessionId="session-1" />);

    fireEvent.click(await screen.findByRole("button", { name: /ARCHITECT.*Em execução/ }));
    fireEvent.click(screen.getByRole("button", { name: "Parar" }));

    expect(await screen.findByRole("button", { name: /ARCHITECT.*Parado/ })).toBeTruthy();
    expect(abortAgentInstance).toHaveBeenCalledWith("instance-1");
    expect(screen.queryByRole("button", { name: "Pausar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Parar" })).toBeNull();
  });

  it("não interpreta falha de carregamento como lista vazia", async () => {
    getAgentInstances.mockRejectedValue(new Error("lifecycle indisponível"));
    render(<BackgroundAgentsPanel sessionId="session-1" />);
    expect((await screen.findByRole("status")).textContent).toContain("lifecycle indisponível");
  });

  it("mostra carregamento e esconde imediatamente a atividade da sessão anterior", async () => {
    let resolveSessionTwo!: (agents: AgentInstance[]) => void;
    getAgentInstances.mockImplementation((options?: { sessionId?: string }) => {
      if (options?.sessionId === "session-1") return Promise.resolve([agent()]);
      return new Promise<AgentInstance[]>((resolve) => { resolveSessionTwo = resolve; });
    });
    const view = render(<BackgroundAgentsPanel sessionId="session-1" />);
    expect(await screen.findByRole("button", { name: /ARCHITECT.*Em execução/ })).toBeTruthy();

    view.rerender(<BackgroundAgentsPanel sessionId="session-2" />);
    expect(screen.getByRole("status").textContent).toContain("A carregar os agentes desta sessão");
    expect(screen.queryByRole("button", { name: /ARCHITECT.*Em execução/ })).toBeNull();

    await act(async () => {
      resolveSessionTwo([agent({
        instance_id: "instance-session-two",
        id: "instance-session-two",
        mission_id: "session-2",
        agent_type: "CODER",
      })]);
    });
    expect(await screen.findByRole("button", { name: /CODER.*Em execução/ })).toBeTruthy();
    expect(screen.queryByText("Inspecionar o projeto")).toBeNull();
  });

  it("não deixa um pedido pendente de uma sessão bloquear a seguinte", async () => {
    let resolveSessionOne!: (agents: AgentInstance[]) => void;
    getAgentInstances.mockImplementation((options?: { sessionId?: string }) => {
      if (options?.sessionId === "session-1") {
        return new Promise<AgentInstance[]>((resolve) => { resolveSessionOne = resolve; });
      }
      return Promise.resolve([agent({
        instance_id: "instance-session-two",
        id: "instance-session-two",
        mission_id: "session-2",
        agent_type: "CODER",
      })]);
    });
    const view = render(<BackgroundAgentsPanel sessionId="session-1" />);
    view.rerender(<BackgroundAgentsPanel sessionId="session-2" />);

    expect(await screen.findByRole("button", { name: /CODER.*Em execução/ })).toBeTruthy();
    expect(getAgentInstances).toHaveBeenCalledWith({ sessionId: "session-2", includeTerminal: true });

    await act(async () => { resolveSessionOne([agent()]); });
    expect(screen.queryByRole("button", { name: /ARCHITECT.*Em execução/ })).toBeNull();
  });

  it("ignora uma ação da sessão anterior que termina depois da troca", async () => {
    let resolvePause!: (response: { success: boolean; action: "pause"; instance: AgentInstance }) => void;
    getAgentInstances.mockImplementation((options?: { sessionId?: string }) =>
      options?.sessionId === "session-1"
        ? Promise.resolve([agent()])
        : Promise.resolve([agent({
            id: "instance-session-two",
            instance_id: "instance-session-two",
            mission_id: "session-2",
            agent_type: "CODER",
          })]),
    );
    pauseAgentInstance.mockImplementation(() => new Promise((resolve) => { resolvePause = resolve; }));
    const view = render(<BackgroundAgentsPanel sessionId="session-1" />);

    fireEvent.click(await screen.findByRole("button", { name: /ARCHITECT.*Em execução/ }));
    fireEvent.click(screen.getByRole("button", { name: "Pausar" }));
    await waitFor(() => expect(pauseAgentInstance).toHaveBeenCalledWith("instance-1"));

    view.rerender(<BackgroundAgentsPanel sessionId="session-2" />);
    expect(await screen.findByRole("button", { name: /CODER.*Em execução/ })).toBeTruthy();
    await act(async () => {
      resolvePause({ success: true, action: "pause", instance: agent({ status: "paused" }) });
    });

    expect(screen.getByRole("button", { name: /CODER.*Em execução/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /ARCHITECT/ })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("não deixa uma sessão sem subagentes ocupar espaço depois do primeiro carregamento", async () => {
    getAgentInstances.mockResolvedValue([]);
    const view = render(<BackgroundAgentsPanel sessionId="session-1" />);

    await waitFor(() => expect(view.container.querySelector('section[aria-label="Agentes desta sessão"]')).toBeNull());
  });
});
