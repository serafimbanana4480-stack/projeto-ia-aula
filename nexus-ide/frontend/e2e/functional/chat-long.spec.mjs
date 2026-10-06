import { expect, test } from "@playwright/test";

const appOrigin = process.env.NEXUS_VISUAL_ORIGIN || "http://127.0.0.1:3222";
const apiOrigins = new Set(["http://127.0.0.1:8000", "http://localhost:8000"]);
const longSessionId = "fixture-long-session";
const otherSessionId = "fixture-other-session";
const runId = "fixture-restored-run";
const modelId = "fixture-provider/exact-model-id";
const historyTotal = Math.max(520, Number(process.env.NEXUS_CHAT_LONG_MESSAGES || 520));
const historyPageCount = Math.ceil(historyTotal / 100);

const timestamp = (index) => new Date(Date.UTC(2026, 0, 1, 0, index)).toISOString();
const messages = Array.from({ length: historyTotal }, (_, index) => ({
  id: `long-message-${String(index + 1).padStart(3, "0")}`,
  role: index % 2 === 0 ? "user" : "assistant",
  content: index === historyTotal - 1
    ? "Resposta persistida ligada à execução restaurada."
    : index === 3
      ? "Mensagem histórica 004 com marcador de pesquisa única."
      : `Mensagem histórica ${String(index + 1).padStart(3, "0")}`,
  timestamp: timestamp(index),
  ...(index === historyTotal - 1 ? { run_id: runId } : {}),
}));

const sessions = [
  { id: longSessionId, title: "Sessão longa · fixture", mode: "auto", project_id: null, created_at: timestamp(0), last_active_at: timestamp(historyTotal - 1), message_count: historyTotal },
  { id: otherSessionId, title: "Sessão alternativa · fixture", mode: "auto", project_id: null, created_at: timestamp(0), last_active_at: timestamp(30), message_count: 2 },
];

function jsonResponse(body, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

function sseResponse(events) {
  return {
    status: 200,
    contentType: "text/event-stream",
    headers: { "cache-control": "no-cache", connection: "keep-alive" },
    body: `${events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")}`,
  };
}

function historyPage(sessionId, url) {
  const rows = sessionId === longSessionId
    ? messages
    : [
        { id: "other-message-1", role: "user", content: "Conversa alternativa", timestamp: timestamp(1) },
        { id: "other-message-2", role: "assistant", content: "Resposta alternativa", timestamp: timestamp(2) },
      ];
  const limit = Math.min(Number(url.searchParams.get("limit") || 100), 100);
  const beforeId = url.searchParams.get("before_id");
  const beforeIndex = beforeId ? rows.findIndex((message) => message.id === beforeId) : rows.length;
  const end = beforeIndex < 0 ? rows.length : beforeIndex;
  const start = Math.max(0, end - limit);
  const page = rows.slice(start, end);
  return {
    messages: page,
    count: page.length,
    has_more: start > 0,
    next_cursor: start > 0 ? page[0]?.id ?? null : null,
  };
}

function eventFrames() {
  // Deliberately deliver seq 2 before seq 1 to check that the timeline is
  // rendered in run_id/seq order rather than network arrival order.
  return [
    { type: "token", content: "segundo", run_id: runId, seq: 2, event_id: `${runId}:2` },
    { type: "token", content: "primeiro ", run_id: runId, seq: 1, event_id: `${runId}:1` },
    { type: "done", content: "", run_id: runId, seq: 3, event_id: `${runId}:3` },
  ];
}

async function installSyntheticAuth(page) {
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3_600 })).toString("base64url");
  await page.addInitScript(({ token, user }) => {
    localStorage.setItem("nexus.access_token", token);
    localStorage.setItem("nexus.user", JSON.stringify(user));
    localStorage.setItem("nexus.chat.currentSession", "fixture-long-session");
  }, {
    token: `fixture.${payload}.local-only`,
    user: { id: "fixture-user", email: "fixture@example.invalid", full_name: "Fixture", is_active: true },
  });
}

async function installLocalApi(page, state) {
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === appOrigin) return route.continue();
    if (!apiOrigins.has(url.origin)) {
      state.blockedExternal.push(url.origin);
      return route.abort("blockedbyclient");
    }

    state.apiRequests.push({ method: request.method(), path: url.pathname, search: url.search });
    const cors = {
      "access-control-allow-origin": appOrigin,
      "access-control-allow-credentials": "true",
      "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
      "access-control-allow-headers": "authorization,content-type,accept,x-nexus-request-id",
      "cache-control": "no-store",
    };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors, body: "" });

    const { pathname } = url;
    if (pathname === "/api/auth/me") {
      return route.fulfill({ ...jsonResponse({ id: "fixture-user", full_name: "Fixture" }), headers: cors });
    }
    if (pathname === "/api/sessions" && request.method() === "GET") {
      return route.fulfill({ ...jsonResponse({ sessions, total: sessions.length, offset: 0, limit: 100 }), headers: cors });
    }
    if (/^\/api\/sessions\/[^/]+\/messages$/.test(pathname)) {
      const sessionId = pathname.split("/")[3];
      state.historyRequests.push({ sessionId, cursor: url.searchParams.get("before_id") });
      if (state.deferFirstLongPage && sessionId === longSessionId && !state.releasedLongPage) {
        await new Promise((resolve) => { state.releaseLongPage = resolve; });
      }
      return route.fulfill({ ...jsonResponse(historyPage(sessionId, url)), headers: cors });
    }
    if (/^\/api\/sessions\/[^/]+\/runs$/.test(pathname)) {
      return route.fulfill({ ...jsonResponse({
        runs: [{ id: runId, session_id: longSessionId, status: "completed", updated_at: timestamp(historyTotal - 1) }],
        count: 1,
        has_more: false,
        next_offset: 1,
      }), headers: cors });
    }
    if (/^\/api\/sessions\/[^/]+\/events$/.test(pathname)) {
      state.replayRequests.push(url.searchParams.get("run_id"));
      return route.fulfill(sseResponse([
        { type: "step_start", content: "Etapa restaurada", run_id: runId, seq: 1, event_id: `${runId}:1` },
        { type: "done", content: "", run_id: runId, seq: 2, event_id: `${runId}:2` },
      ]));
    }
    if (pathname === "/api/models/catalog") {
      return route.fulfill({ ...jsonResponse({
        models: [{ id: modelId, name: "Modelo fixture exato", tier: "CODER", provider: "openrouter", pricing: "fixture", size_gb: 0, status: "available", free: true }],
        providers: [],
      }), headers: cors });
    }
    if (pathname === "/api/providers/status") {
      return route.fulfill({ ...jsonResponse({ providers: {}, breakers: {} }), headers: cors });
    }
    if (pathname === "/api/modes") {
      return route.fulfill({ ...jsonResponse({ modes: { auto: { description: "Fixture", default_agent: "CODER", default_model: "auto", router: "fixture", tools_enabled: [] } } }), headers: cors });
    }
    if (pathname === "/api/projects" || pathname === "/api/tools") {
      return route.fulfill({ ...jsonResponse(pathname.endsWith("tools") ? { tools: [] } : []), headers: cors });
    }
    if (pathname === "/api/chat" && request.method() === "POST") {
      state.chatBodies.push(request.postDataJSON());
      return route.fulfill(sseResponse(eventFrames()));
    }
    if (pathname === "/api/metrics/current") return route.fulfill({ ...jsonResponse({}), headers: cors });
    if (pathname === "/api/metrics/history") return route.fulfill({ ...jsonResponse({ history: [] }), headers: cors });

    state.unexpectedApi.push(`${request.method()} ${pathname}${url.search}`);
    return route.fulfill({ ...jsonResponse({}), headers: cors });
  });
}

test.beforeEach(async ({ page }) => {
  page.__fixtureState = {
    apiRequests: [], historyRequests: [], replayRequests: [], chatBodies: [],
    unexpectedApi: [], blockedExternal: [], deferFirstLongPage: false, releasedLongPage: false,
  };
  await page.setViewportSize({ width: 1440, height: 1000 });
  await installSyntheticAuth(page);
  await installLocalApi(page, page.__fixtureState);
});

test("histórico longo pagina, troca e restaura sem chamadas externas", async ({ page }) => {
  test.setTimeout(120_000);
  const startedAt = Date.now();
  const state = page.__fixtureState;
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("messages")).toBeVisible();
  await expect(page.getByText(`Mensagem histórica ${String(historyTotal).padStart(3, "0")}`, { exact: true })).toHaveCount(0);
  await expect(page.getByText("Resposta persistida ligada à execução restaurada.", { exact: true })).toBeVisible();
  await expect.poll(() => state.replayRequests).toContain(runId);
  await expect(page.locator('[data-testid="messages"] .nx-msg-enter')).toHaveCount(50);

  const scroller = page.getByTestId("messages");
  await scroller.evaluate((element) => { element.scrollTop = 0; });
  const firstVisibleMessage = historyTotal - 49;
  const anchorMessage = page.getByText(`Mensagem histórica ${String(firstVisibleMessage).padStart(3, "0")}`, { exact: true });
  const anchorTopBefore = await anchorMessage.evaluate((element) => element.getBoundingClientRect().top);
  for (let pageIndex = 0; pageIndex < historyPageCount - 1; pageIndex += 1) {
    await page.getByRole("button", { name: "Carregar mensagens anteriores" }).click();
    await expect.poll(() => new Set(
      state.historyRequests
        .filter((item) => item.sessionId === longSessionId && item.cursor)
        .map((item) => item.cursor),
  ).size).toBe(pageIndex + 1);
    if (pageIndex === 0) {
      await expect.poll(async () => Math.abs(
        await anchorMessage.evaluate((element) => element.getBoundingClientRect().top) - anchorTopBefore,
      )).toBeLessThan(1);
    }
  }
  const longPages = state.historyRequests.filter((item) => item.sessionId === longSessionId);
  const cursorPages = [...new Set(longPages.map((item) => item.cursor).filter(Boolean))];
  expect(cursorPages).toHaveLength(historyPageCount - 1);
  expect(new Set(cursorPages).size).toBe(historyPageCount - 1);
  const loaded = await page.locator('[data-testid="messages"] .nx-msg-enter').count();
  expect(loaded).toBeLessThanOrEqual(historyPageCount * 50);
  const localPageExpanders = page.getByRole("button", { name: /Carregar mais \d+ mensagens/ });
  while (await localPageExpanders.count()) await localPageExpanders.first().click();
  const allRendered = await page.locator('[data-testid="messages"] .nx-msg-enter').count();
  expect(allRendered).toBe(historyTotal);
  await expect(page.getByText("Mensagem histórica 001", { exact: true })).toBeVisible();
  await expect(page.getByText("Resposta persistida ligada à execução restaurada.", { exact: true })).toBeVisible();
  console.info(`[chat-long] history=${historyTotal}, cursor_pages=${historyPageCount}, initial_rendered<=${historyPageCount * 50}, expanded_rendered=${allRendered}, pagination_and_expand_ms=${Date.now() - startedAt}`);

  await page.getByRole("button", { name: "Abrir sessões" }).click();
  await page.getByRole("button", { name: "Sessão alternativa · fixture" }).click();
  await expect(page.getByText("Conversa alternativa", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Fechar sessões" }).click();
  await page.getByRole("button", { name: "Abrir sessões" }).click();
  await page.getByRole("button", { name: "Sessão longa · fixture" }).click();
  await expect(page.getByText("Resposta persistida ligada à execução restaurada.", { exact: true })).toBeVisible();

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("Resposta persistida ligada à execução restaurada.", { exact: true })).toBeVisible();
  await expect(page.getByTestId("messages").locator(".nx-msg-enter")).toHaveCount(50);
  await expect.poll(() => state.replayRequests.filter((id) => id === runId).length).toBeGreaterThanOrEqual(2);
  expect(state.blockedExternal).toEqual([]);
});

test("resposta atrasada da sessão anterior não contamina a sessão selecionada", async ({ page }) => {
  const state = page.__fixtureState;
  state.deferFirstLongPage = true;
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(() => Boolean(state.releaseLongPage)).toBe(true);

  await page.getByRole("button", { name: "Abrir sessões" }).click();
  await page.getByRole("button", { name: "Sessão alternativa · fixture" }).click();
  await expect(page.getByText("Conversa alternativa", { exact: true })).toBeVisible();
  state.releasedLongPage = true;
  state.releaseLongPage();
  await page.waitForTimeout(100);
  await expect(page.getByText("Mensagem histórica 520", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Conversa alternativa", { exact: true })).toBeVisible();
});

test("pesquisa atravessa páginas antigas e salta para a mensagem original", async ({ page }) => {
  const state = page.__fixtureState;
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Resposta persistida ligada à execução restaurada.", { exact: true })).toBeVisible();
  // Development hydration can repeat the head request; cursor coverage below
  // verifies that search still traverses the complete history.
  await expect.poll(() => state.historyRequests.filter((item) => item.sessionId === longSessionId).length).toBeGreaterThanOrEqual(1);

  await page.keyboard.press("Control+f");
  const searchBox = page.getByRole("textbox", { name: "Procurar nas mensagens desta conversa" });
  await searchBox.fill("marcador de pesquisa única");
  const result = page.getByRole("button", { name: /NEXUS: .*marcador de pesquisa única/ });
  await expect(result).toBeVisible();

  const searchedPages = state.historyRequests.filter((item) => item.sessionId === longSessionId && item.cursor);
  expect(new Set(searchedPages.map((item) => item.cursor)).size).toBe(historyPageCount - 1);
  await result.click();
  await expect(page.getByText("Mensagem histórica 004 com marcador de pesquisa única.", { exact: true })).toBeVisible();
  expect(state.blockedExternal).toEqual([]);
});

test("modelo concreto segue intacto no pedido e eventos chegam ordenados", async ({ page }) => {
  const state = page.__fixtureState;
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const composer = page.locator('[data-testid="messages"]').locator("..")
    .locator("textarea").last();
  await expect(composer).toHaveAttribute("placeholder", /Escreve o que queres fazer/);
  const submit = page.getByRole("button", { name: "Enviar mensagem" });
  await expect(submit).toBeDisabled();
  await composer.fill("Testar seleção concreta do modelo");
  await expect(submit).toBeEnabled();

  await page.getByTestId("chat-header").getByRole("button", { name: "Automático" }).click();
  await page.getByRole("button", { name: "Modelo fixture exato" }).click();
  await expect(page.getByTestId("chat-header").getByRole("button", { name: "Modelo fixture exato" })).toBeVisible();
  await submit.click();

  await expect.poll(() => state.chatBodies.length).toBe(1);
  expect(state.chatBodies[0]).toMatchObject({ model: modelId, provider: "openrouter", message: "Testar seleção concreta do modelo" });
  await expect(page.getByText("primeiro segundo", { exact: true })).toBeVisible();
});
