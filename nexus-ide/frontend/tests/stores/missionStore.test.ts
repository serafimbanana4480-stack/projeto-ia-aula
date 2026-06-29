import { describe, expect, it, beforeEach } from "vitest";
import { useMissionStore, type Mission, type AgentInstance, type BusMessage } from "../../stores/missionStore";

describe("missionStore", () => {
  beforeEach(() => {
    useMissionStore.setState({
      missions: [],
      agents: [],
      busMessages: [],
      decisions: [],
      qualityGates: [],
      systemHealth: null,
      selectedMission: null,
      loading: false,
      error: null,
    });
  });

  it("sets missions", () => {
    const missions: Mission[] = [
      {
        id: "m1",
        objective: "Test mission",
        status: "RUNNING",
        progress: 50,
        active_agents: ["CODER"],
        elapsed_seconds: 120,
        tokens_used: 1024,
        phases: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ];
    useMissionStore.getState().setMissions(missions);
    expect(useMissionStore.getState().missions).toHaveLength(1);
    expect(useMissionStore.getState().missions[0].id).toBe("m1");
  });

  it("updates a mission", () => {
    const mission: Mission = {
      id: "m1",
      objective: "Test",
      status: "RUNNING",
      progress: 10,
      active_agents: [],
      elapsed_seconds: 0,
      tokens_used: 0,
      phases: [],
      created_at: "",
      updated_at: "",
    };
    useMissionStore.getState().setMissions([mission]);
    useMissionStore.getState().updateMission({ ...mission, progress: 99 });
    expect(useMissionStore.getState().missions[0].progress).toBe(99);
  });

  it("sets and updates agent status", () => {
    const agent: AgentInstance = {
      id: "a1",
      name: "CODER",
      status: "idle",
      tokens_used: 0,
    };
    useMissionStore.getState().setAgents([agent]);
    useMissionStore.getState().updateAgentStatus("a1", "running", { current_task: "fix bug" });
    const updated = useMissionStore.getState().agents[0];
    expect(updated.status).toBe("running");
    expect(updated.current_task).toBe("fix bug");
  });

  it("adds bus messages with a 500 limit", async () => {
    const store = useMissionStore.getState();
    for (let i = 0; i < 520; i++) {
      const msg: BusMessage = {
        message_id: `msg-${i}`,
        topic: "test",
        source_agent: "ROUTER",
        payload: {},
        timestamp: new Date().toISOString(),
      };
      store.addBusMessage(msg);
    }
    // Wait for debounce flush (150ms)
    await new Promise((r) => setTimeout(r, 200));
    expect(useMissionStore.getState().busMessages).toHaveLength(500);
    expect(useMissionStore.getState().busMessages[0].message_id).toBe("msg-519");
  });

  it("selects a mission", () => {
    useMissionStore.getState().selectMission("m1");
    expect(useMissionStore.getState().selectedMission).toBe("m1");
    useMissionStore.getState().selectMission(null);
    expect(useMissionStore.getState().selectedMission).toBeNull();
  });

  it("sets loading and error", () => {
    useMissionStore.getState().setLoading(true);
    expect(useMissionStore.getState().loading).toBe(true);
    useMissionStore.getState().setError("Connection failed");
    expect(useMissionStore.getState().error).toBe("Connection failed");
  });
});
