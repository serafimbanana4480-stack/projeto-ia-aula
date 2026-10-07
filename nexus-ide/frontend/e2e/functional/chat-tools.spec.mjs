import { expect, test } from "@playwright/test";

const appOrigin = process.env.NEXUS_VISUAL_ORIGIN || "http://127.0.0.1:3222";
const sessionId = "fixture-todo-session";
const runId = "fixture-todo-run";
const fixtureUser = {
  id: "fixture-user",
  email: "fixture@example.invalid",
  full_name: "Fixture",
  is_active: true,
};
const timestamp = "2026-09-28T10:00:00.000Z";
const todos = [
  { id: 1, content: "Rever os eventos do chat", priority: "high", status: "pending" },
  { id: 2, content: "Validar a checklist após reload", priority: "normal", status: "in_progress" },
  { id: 3, content: "Confirmar o resultado final", priority: "low", status: "completed" },
];

function jsonResponse(body, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

function todoEvents() {
  return [
    {
      type: "tool_call",
      tool_name: "todo_write",
      tool_args: { operation: "set_all", items: todos.map(({ content, priority }) => ({ content, priority })) },
      timestamp,
      run_id: runId,
      seq: 1,
      event_id: `${runId}:1`,
    },
    {
      type: "progress",
      content: "plano atualizado",
      data: { kind: "plan_updated", event: "plan_updated", tool: "todo_write", todos },
      timestamp,
      run_id: runId,
      seq: 2,
      event_id: `${runId}:2`,
    },
    {
      type: "tool_result",
      tool_name: "todo_write",
      tool_result: {
        ok: true,
        result: {
          session_id: sessionId,
          todos,
          counts: { pending: 1, in_progress: 1, completed: 1, cancelled: 0, total: 3 },
        },
      },
      timestamp,
      run_id: runId,
      seq: 3,
      event_id: `${runId}:3`,
    },
    {
      type: "token",
      content: "Checklist atualizada.",
      timestamp,
      run_id: runId,
      seq: 4,
      event_id: `${runId}:4`,
    },
    {
      type: "done",
      content: "",
      timestamp,
      run_id: runId,
      seq: 5,
      event_id: `${runId}:5`,
    },
  ];
}

function sseResponse(events, corsHeaders) {
  return {
    status: 200,
    contentType: "text/event-stream",
    headers: { ...corsHeaders, "cache-control": "no-cache", connection: "keep-alive" },
    body: `${events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")}`,
  };
}

async function installFixture(page, state) {
  const expiry = Math.floor(Date.now() / 1_000) + 3_600;
  const tokenPayload = Buffer.from(JSON.stringify({ exp: expiry })).toString("base64url");
  await page.addInitScript(({ token, user, activeSession }) => {
    localStorage.setItem("nexus.access_token", token);
    localStorage.setItem("nexus.user", JSON.stringify(user));
    localStorage.setItem("nexus.chat.currentSession", activeSession);
  }, {
    token: `fixture.${tokenPayload}.local-only`,
    user: fixtureUser,
    activeSession: sessionId,
  });

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;
    if (!pathname.startsWith("/api/")) {
      if (url.origin === appOrigin) return route.continue();
      state.blockedExternal.push(url.origin);
      return route.abort("blockedbyclient");
    }

    const origin = request.headers().origin || appOrigin;
    const cors = {
      "access-control-allow-origin": origin,
      "access-control-allow-credentials": "true",
      "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
      "access-control-allow-headers": "authorization,content-type,accept,x-nexus-request-id",
      "cache-control": "no-store",
    };
    if (request.method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: cors, body: "" });
    }

    state.apiRequests.push(`${request.method()} ${pathname}${url.search}`);
    if (pathname === "/api/auth/me") {
      return route.fulfill({ ...jsonResponse(fixtureUser), headers: cors });
    }
    if (pathname === "/api/sessions" && request.method() === "GET") {
      return route.fulfill({
        ...jsonResponse({
          sessions: [{
            id: sessionId,
            title: "Sessão TODO · fixture",
            mode: "auto",
            project_id: null,
            created_at: timestamp,
            last_active_at: timestamp,
            message_count: state.persistedMessages.length,
          }],
          total: 1,
          offset: 0,
          limit: 100,
        }),
        headers: cors,
      });
    }
    if (pathname === `/api/sessions/${sessionId}/messages` && request.method() === "GET") {
      return route.fulfill({
        ...jsonResponse({
          messages: state.persistedMessages,
          count: state.persistedMessages.length,
          has_more: false,
          next_cursor: null,
        }),
        headers: cors,
      });
    }
    if (pathname === `/api/sessions/${sessionId}/runs` && request.method() === "GET") {
      const runs = state.persistedMessages.some((message) => message.run_id === runId)
        ? [{ id: runId, session_id: sessionId, status: "completed", updated_at: timestamp }]
        : [];
      return route.fulfill({
        ...jsonResponse({ runs, count: runs.length, has_more: false, next_offset: runs.length }),
        headers: cors,
      });
    }
    if (pathname === `/api/sessions/${sessionId}/events` && request.method() === "GET") {
      state.replayRequests.push(url.searchParams.get("run_id"));
      return route.fulfill(sseResponse(todoEvents(), cors));
    }
    if (pathname === "/api/chat" && request.method() === "POST") {
      const body = request.postDataJSON();
      state.chatBodies.push(body);
      state.persistedMessages = [
        { id: "todo-user-message", role: "user", content: body.message, timestamp, session_id: sessionId },
        { id: "todo-assistant-message", role: "assistant", content: "Checklist atualizada.", timestamp, session_id: sessionId, run_id: runId },
      ];
      return route.fulfill(sseResponse(todoEvents(), cors));
    }
    if (pathname === "/api/models/catalog") {
      return route.fulfill({ ...jsonResponse({ models: [], providers: [] }), headers: cors });
    }
    if (pathname === "/api/providers/status") {
      return route.fulfill({ ...jsonResponse({ providers: {}, breakers: {} }), headers: cors });
    }
    if (pathname === "/api/modes") {
      return route.fulfill({
        ...jsonResponse({ modes: { auto: { description: "Fixture", default_agent: "NEXUS", default_model: "auto", router: "fixture", tools_enabled: ["todo_write", "todo_list"] } } }),
        headers: cors,
      });
    }
    if (pathname === "/api/projects") return route.fulfill({ ...jsonResponse([]), headers: cors });
    if (pathname === "/api/tools") return route.fulfill({ ...jsonResponse({ tools: [] }), headers: cors });
    if (pathname === "/api/agents/instances") return route.fulfill({ ...jsonResponse({ agents: [], count: 0 }), headers: cors });

    state.unexpectedApi.push(`${request.method()} ${pathname}${url.search}`);
    return route.fulfill({ ...jsonResponse({}), headers: cors });
  });
}

async function expectChecklist(page) {
  const timeline = page.getByTestId("run-timeline-toggle").last();
  if (await timeline.getAttribute("aria-expanded") === "false") await timeline.click();
  await page.getByRole("button", { name: /Atualizar checklist/ }).click();
  const checklist = page.getByRole("region", { name: "Lista de tarefas" });
  await expect(checklist).toBeVisible();
  await expect(checklist.getByRole("list", { name: "Tarefas" }).getByText("Rever os eventos do chat")).toBeVisible();
  await expect(checklist.getByText("Validar a checklist após reload")).toBeVisible();
  await expect(checklist.getByText("Confirmar o resultado final")).toBeVisible();
  await expect(checklist.getByText("3 tarefas", { exact: true })).toBeVisible();
  await expect(checklist.getByText("1 por fazer", { exact: true })).toBeVisible();
  await expect(checklist.getByText("1 em curso", { exact: true })).toBeVisible();
  await expect(checklist.getByText("1 concluída", { exact: true })).toBeVisible();
  await expect(checklist.getByText("0 canceladas", { exact: true })).toBeVisible();
  await expect(page.getByText(/"todos"\s*:/)).toHaveCount(0);
}

test("renderiza TODOs do SSE como checklist e recupera a timeline após reload", async ({ page }) => {
  const state = { apiRequests: [], chatBodies: [], persistedMessages: [], replayRequests: [], unexpectedApi: [], blockedExternal: [] };
  await page.setViewportSize({ width: 1365, height: 900 });
  await installFixture(page, state);
  await page.goto("/", { waitUntil: "domcontentloaded" });

  const composer = page.getByTestId("messages").locator("..").locator("textarea").last();
  await expect(composer).toBeVisible();
  await composer.fill("Atualiza a checklist e mostra os estados das tarefas");
  await page.getByRole("button", { name: "Enviar mensagem" }).click();

  await expect.poll(() => state.chatBodies.length).toBe(1);
  expect(state.chatBodies[0]).toMatchObject({ session_id: sessionId, message: "Atualiza a checklist e mostra os estados das tarefas" });
  await expect(page.getByText("Checklist atualizada.", { exact: true })).toBeVisible();
  await expectChecklist(page);

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("Checklist atualizada.", { exact: true })).toBeVisible();
  await expect.poll(() => state.replayRequests).toContain(runId);
  await expectChecklist(page);
  expect(state.blockedExternal).toEqual([]);
  await page.screenshot({ path: "test-results-functional/screenshots/10-chat-tools-desktop.png", animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results-functional/screenshots/11-chat-tools-mobile.png", animations: "disabled" });
});
