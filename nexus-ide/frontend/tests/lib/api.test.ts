import { vi, describe, it, expect, beforeEach } from "vitest";
import * as api from "../../lib/api";

// Mock the auth module to provide deterministic test headers
vi.mock("../../lib/auth", () => ({
  authHeaders: () => ({ Authorization: "Bearer mock-token" }),
  authenticatedFetch: (input: RequestInfo | URL, init: RequestInit = {}) =>
    fetch(input, {
      ...init,
      headers: { Authorization: "Bearer mock-token", ...(init.headers as Record<string, string> | undefined) },
    }),
  clearAuth: vi.fn(),
  getAccessToken: () => "mock-token",
}));

describe("lib/api.ts Client Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  const mockResponse = (status: number, data: any, ok: boolean = true) => {
    (global.fetch as any).mockResolvedValue({
      ok,
      status,
      statusText: ok ? "OK" : "Error",
      headers: {
        get: (name: string) => {
          if (name.toLowerCase() === "content-length") {
            return data == null ? "0" : String(JSON.stringify(data).length);
          }
          return null;
        },
      },
      json: async () => data,
      text: async () => JSON.stringify(data),
    });
  };

  describe("Thin client basic utilities", () => {
    it("apiUrl constructs correct base url", () => {
      const url = api.apiUrl("/api/test");
      expect(url).toBe("http://localhost:8000/api/test");
    });
  });

  describe("Chat API", () => {
    it("postChat makes correct POST request", async () => {
      mockResponse(200, {});
      const resp = await api.postChat(
        "hello",
        "session123",
        "agent",
        undefined,
        "modelX",
        "/proj",
        "strong",
        undefined,
        "chat_request_1",
      );
      // Verify the fetch was called with the right URL, method, and headers,
      // and that the body contains all expected fields. The exact key order in
      // the body is an implementation detail of ``postChat`` and changes
      // whenever a field is added — assert on parsed content instead.
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/chat",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            Authorization: "Bearer mock-token",
            Accept: "text/event-stream",
            "X-Nexus-Request-Id": "chat_request_1",
          }),
        })
      );
      const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
      const callBody = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(callBody).toMatchObject({
        message: "hello",
        session_id: "session123",
        mode: "agent",
        model: "modelX",
        project_path: "/proj",
        thinking_strength: "strong",
      });
      expect(resp).toBeDefined();
    });

    it("saveSettings uses the backend envelope and does not erase blank secrets", async () => {
      mockResponse(200, { status: "saved" });

      await api.saveSettings({
        llm_provider: "openai",
        enable_telemetry: false,
        openai_api_key: "",
        gemini_api_key: "masked****key",
      });

      const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
      const callBody = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(callBody).toEqual({
        settings: {
          llm_provider: "openai",
          enable_telemetry: "false",
        },
      });
    });

    it("getSessionHistory retrieves and resolves session messages", async () => {
      mockResponse(200, { messages: [{ message: "ok" }] });
      const messages = await api.getSessionHistory("sess1");
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/sessions/sess1/history",
        expect.any(Object)
      );
      expect(messages).toHaveLength(1);
    });
  });

  describe("File operations API", () => {
    it("readFile reads a file", async () => {
      mockResponse(200, { content: "file-content" });
      const res = await api.readFile("test.txt", "/root");
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/files/read",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ path: "test.txt", project_path: "/root" }),
        })
      );
      expect(res.content).toBe("file-content");
    });

    it("writeFile writes to a file", async () => {
      mockResponse(200, {});
      await api.writeFile("test.txt", "new-content", "/root");
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/files/write",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ path: "test.txt", content: "new-content", project_path: "/root" }),
        })
      );
    });

    it("listFiles lists files", async () => {
      mockResponse(200, { tree: [{ path: "file1" }] });
      const list = await api.listFiles("/root", true, "src");
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/files/list",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ path: "src", recursive: true, project_path: "/root" }),
        })
      );
      expect(list).toHaveLength(1);
    });
  });

  describe("Terminal execution API", () => {
    it("executeTerminalCommand runs commands", async () => {
      mockResponse(200, { exit_code: 0, stdout: "done" });
      const res = await api.executeTerminalCommand("ls", "/root", 45, "sess");
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/terminal/execute",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            command: "ls",
            project_path: "/root",
            timeout_seconds: 45,
            session_id: "sess",
          }),
        })
      );
      expect(res.stdout).toBe("done");
    });
  });

  describe("Tools and Settings API", () => {
    it("getTools returns list of tools", async () => {
      mockResponse(200, { tools: [{ name: "t1" }] });
      const tools = await api.getTools();
      expect(tools).toHaveLength(1);
    });

    it("toggleTool sends correct toggle configuration", async () => {
      mockResponse(200, { success: true });
      await api.toggleTool("toolA", true);
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/tools/toolA/toggle?enabled=true",
        expect.objectContaining({ method: "POST" })
      );
    });

    it("getProjects, createProject, and getCurrentMetrics", async () => {
      mockResponse(200, { projects: [] });
      await api.getProjects();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/projects", expect.any(Object));

      mockResponse(200, {});
      await api.createProject({ name: "P1", path: "/p1" });
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/projects",
        expect.objectContaining({ method: "POST" })
      );

      mockResponse(200, {});
      await api.getCurrentMetrics();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/metrics/current", expect.any(Object));
    });
  });

  describe("Bus messages path parameters (Fix validation)", () => {
    it("getBusMessages parses topic as path parameter", async () => {
      mockResponse(200, { messages: [] });
      await api.getBusMessages("my-topic", 20);
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/bus/history/my-topic?limit=20",
        expect.objectContaining({ headers: expect.any(Object) })
      );
    });

    it("getBusMessages defaults to all topic if empty", async () => {
      mockResponse(200, { messages: [] });
      await api.getBusMessages(undefined, 15);
      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/bus/history/all?limit=15",
        expect.any(Object)
      );
    });
  });

  describe("New Core API Endpoints", () => {
    it("Agents Instances endpoints", async () => {
      mockResponse(200, { id: "a1" });
      await api.getAgentInstance("a1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/agents/instances/a1", expect.any(Object));

      mockResponse(200, {});
      await api.pauseAgentInstance("a1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/agents/instances/a1/pause", expect.objectContaining({ method: "POST" }));

      mockResponse(200, {});
      await api.resumeAgentInstance("a1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/agents/instances/a1/resume", expect.objectContaining({ method: "POST" }));

      mockResponse(200, {});
      await api.abortAgentInstance("a1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/agents/instances/a1/abort", expect.objectContaining({ method: "POST" }));
    });

    it("Dashboard endpoints", async () => {
      mockResponse(200, {});
      await api.getDashboardStatus();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/dashboard/status", expect.any(Object));

      await api.getDashboardAlerts();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/dashboard/alerts", expect.any(Object));

      await api.getDashboardMetrics();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/dashboard/metrics", expect.any(Object));

      await api.askDashboard("status request");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/dashboard/ask", expect.objectContaining({ method: "POST" }));

      await api.diagnoseDashboard();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/dashboard/diagnose", expect.objectContaining({ method: "POST" }));
    });

    it("Orchestrator endpoints", async () => {
      mockResponse(200, {});
      await api.createOrchestratorTask({ type: "dummy" });
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/orchestrator/tasks", expect.objectContaining({ method: "POST" }));

      await api.createOrchestratorTasksParallel([{ type: "d1" }]);
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/orchestrator/tasks/parallel", expect.objectContaining({ method: "POST" }));

      await api.getOrchestratorTask("t1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/orchestrator/tasks/t1", expect.any(Object));

      mockResponse(200, { tasks: [] });
      await api.getOrchestratorTasks();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/orchestrator/tasks", expect.any(Object));

      mockResponse(200, {});
      await api.abortOrchestratorTask("t1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/orchestrator/tasks/t1/abort", expect.objectContaining({ method: "POST" }));

      await api.getOrchestratorBriefing();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/orchestrator/briefing", expect.any(Object));
    });

    it("Workers endpoints", async () => {
      mockResponse(200, { workers: [] });
      await api.getWorkers();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workers", expect.any(Object));

      mockResponse(200, {});
      await api.startWorker("w1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workers/w1/start", expect.objectContaining({ method: "POST" }));

      await api.stopWorker("w1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workers/w1/stop", expect.objectContaining({ method: "POST" }));

      await api.pauseWorker("w1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workers/w1/pause", expect.objectContaining({ method: "POST" }));

      await api.resumeWorker("w1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workers/w1/resume", expect.objectContaining({ method: "POST" }));
    });

    it("Skills endpoints", async () => {
      mockResponse(200, { skills: [] });
      await api.getSkills();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/skills", expect.any(Object));

      mockResponse(200, {});
      await api.getSkill("sk1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/skills/sk1", expect.any(Object));

      await api.createSkill({ id: "sk1" });
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/skills", expect.objectContaining({ method: "POST" }));

      await api.updateSkill("sk1", { id: "sk1" });
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/skills/sk1", expect.objectContaining({ method: "PUT" }));

      await api.deleteSkill("sk1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/skills/sk1", expect.objectContaining({ method: "DELETE" }));
    });

    it("Wizard endpoints", async () => {
      mockResponse(200, []);
      await api.getWizardTemplates();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/wizard/templates", expect.any(Object));

      mockResponse(200, {});
      await api.getWizardTemplate("t1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/wizard/templates/t1", expect.any(Object));

      await api.startWizard({});
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/wizard/start", expect.objectContaining({ method: "POST" }));

      await api.answerWizard({});
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/wizard/answer", expect.objectContaining({ method: "POST" }));

      await api.generateWizard({});
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/wizard/generate", expect.objectContaining({ method: "POST" }));

      await api.getWizardStatus("sess1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/wizard/status/sess1", expect.any(Object));
    });

    it("Email endpoints", async () => {
      mockResponse(200, []);
      await api.getEmailAccounts();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/email/accounts", expect.any(Object));

      mockResponse(200, {});
      await api.addEmailAccount({});
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/email/accounts", expect.objectContaining({ method: "POST" }));

      await api.deleteEmailAccount("acc1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/email/accounts/acc1", expect.objectContaining({ method: "DELETE" }));

      mockResponse(200, []);
      await api.getEmailInbox("acc1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/email/inbox?account_id=acc1", expect.any(Object));

      await api.searchEmails("alert");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/email/search?query=alert", expect.any(Object));

      mockResponse(200, {});
      await api.markEmailAsRead("e1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/email/e1/read", expect.objectContaining({ method: "POST" }));

      await api.triageEmails({});
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/email/triage", expect.objectContaining({ method: "POST" }));
    });

    it("Browser endpoints", async () => {
      mockResponse(200, {});
      await api.navigateBrowser("http://google.com");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/browser/navigate", expect.objectContaining({ method: "POST" }));

      await api.clickBrowser(".btn");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/browser/click", expect.objectContaining({ method: "POST" }));

      await api.fillBrowser("#input", "value");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/browser/fill", expect.objectContaining({ method: "POST" }));

      await api.extractBrowser("div");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/browser/extract", expect.objectContaining({ method: "POST" }));

      await api.screenshotBrowser();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/browser/screenshot", expect.objectContaining({ method: "POST" }));

      await api.getBrowserLinks();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/browser/get_links", expect.objectContaining({ method: "POST" }));

      await api.closeBrowser();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/browser/close", expect.objectContaining({ method: "POST" }));
    });

    it("Workspace endpoints", async () => {
      mockResponse(200, { content: "ok" });
      await api.readWorkspaceFile("f.txt");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/read", expect.objectContaining({ method: "POST" }));

      mockResponse(200, {});
      await api.writeWorkspaceFile("f.txt", "data");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/write", expect.objectContaining({ method: "POST" }));

      await api.listWorkspaceFiles();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/list", expect.objectContaining({ method: "POST" }));

      await api.createWorkspaceDir("dir");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/create-dir", expect.objectContaining({ method: "POST" }));

      await api.deleteWorkspaceFile("f.txt");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/delete", expect.objectContaining({ method: "POST" }));

      await api.deleteWorkspaceDir("dir");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/delete-dir", expect.objectContaining({ method: "POST" }));

      await api.moveWorkspaceFile("f.txt", "f2.txt");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/move", expect.objectContaining({ method: "POST" }));

      await api.copyWorkspaceFile("f.txt", "f2.txt");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/copy", expect.objectContaining({ method: "POST" }));

      await api.getWorkspaceFileInfo("f.txt");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/info", expect.objectContaining({ method: "POST" }));

      await api.searchWorkspaceFiles("query");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/files/search", expect.objectContaining({ method: "POST" }));

      await api.executeWorkspaceShell("ls");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/terminal/shell", expect.objectContaining({ method: "POST" }));

      await api.executeWorkspacePython("print(1)");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/terminal/python", expect.objectContaining({ method: "POST" }));

      await api.executeWorkspaceScript("s.sh");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/terminal/script", expect.objectContaining({ method: "POST" }));

      await api.gitInit();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/git/init", expect.objectContaining({ method: "POST" }));

      await api.gitClone("url", "path");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/git/clone", expect.objectContaining({ method: "POST" }));

      await api.gitCommitAll("msg");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/git/commit-all", expect.objectContaining({ method: "POST" }));

      await api.gitPush();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/git/push", expect.objectContaining({ method: "POST" }));

      await api.gitStatus();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/git/status", expect.objectContaining({ method: "POST" }));

      mockResponse(200, []);
      await api.listWorkspaceBackups();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/backups/list", expect.objectContaining({ method: "POST" }));

      mockResponse(200, {});
      await api.restoreWorkspaceBackup("b1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/backups/restore", expect.objectContaining({ method: "POST" }));

      mockResponse(200, []);
      await api.discoverWorkspaceProjects();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/projects/discover", expect.objectContaining({ method: "POST" }));

      mockResponse(200, {});
      await api.getWorkspaceProjectInfo();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/workspace/projects/info", expect.objectContaining({ method: "POST" }));
    });

    it("Memory endpoints", async () => {
      mockResponse(200, []);
      await api.searchMemories("query");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/memories/search", expect.objectContaining({ method: "POST" }));

      mockResponse(200, {});
      await api.storeMemory("content");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/memories", expect.objectContaining({ method: "POST" }));

      mockResponse(200, []);
      await api.getMemories();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/memories?limit=50", expect.any(Object));

      mockResponse(200, {});
      await api.deleteMemory("m1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/memories/m1", expect.objectContaining({ method: "DELETE" }));

      await api.getMemoryStats();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/memories/stats", expect.any(Object));
    });

    it("Meta (Missions) endpoints", async () => {
      mockResponse(200, []);
      await api.getMissions();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/missions", expect.any(Object));

      mockResponse(200, {});
      await api.createMission("objective");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/missions", expect.objectContaining({ method: "POST" }));

      await api.getMission("m1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/missions/m1", expect.any(Object));

      await api.pauseMission("m1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/missions/m1/pause", expect.objectContaining({ method: "POST" }));

      await api.resumeMission("m1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/missions/m1/resume", expect.objectContaining({ method: "POST" }));

      await api.abortMission("m1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/missions/m1/abort", expect.objectContaining({ method: "POST" }));

      mockResponse(200, { agents: [] });
      await api.getMissionAgents("m1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/missions/m1/agents", expect.any(Object));
    });

    it("Embedding endpoints", async () => {
      mockResponse(200, {});
      await api.indexEmbedding("text");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/embeddings/index", expect.objectContaining({ method: "POST" }));

      mockResponse(200, []);
      await api.searchEmbedding("query");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/embeddings/search", expect.objectContaining({ method: "POST" }));

      mockResponse(200, {});
      await api.getEmbeddingStats();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/embeddings/stats", expect.any(Object));
    });

    it("Second Brain endpoints", async () => {
      mockResponse(200, {});
      await api.ingestSecondBrain("content");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/brain/ingest", expect.objectContaining({ method: "POST" }));

      mockResponse(200, []);
      await api.searchSecondBrain("query");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/brain/search?query=query&limit=5", expect.any(Object));

      await api.getSecondBrainMemories();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/brain/memories?limit=50", expect.any(Object));

      mockResponse(200, {});
      await api.deleteSecondBrainMemory("m1");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/brain/memories/m1", expect.objectContaining({ method: "DELETE" }));
    });

    it("Profile endpoints", async () => {
      mockResponse(200, {});
      await api.getProfile();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/me", expect.any(Object));

      await api.updatePreferences({});
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/profile/preferences", expect.objectContaining({ method: "PUT" }));

      mockResponse(200, []);
      await api.getRoutines();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/profile/routines", expect.any(Object));

      mockResponse(200, {});
      await api.createRoutine({});
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/profile/routines", expect.objectContaining({ method: "POST" }));

      mockResponse(200, []);
      await api.getProfileMemories();
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/profile/memories", expect.any(Object));

      mockResponse(200, {});
      await api.createProfileMemory({});
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/profile/memories", expect.objectContaining({ method: "POST" }));
    });
  });
});
