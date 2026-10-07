import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const screenshotRoot = path.join(frontendRoot, "test-results-functional", "screenshots");
const appOrigin = process.env.NEXUS_VISUAL_ORIGIN || "http://127.0.0.1:3222";
const apiOrigins = new Set(["http://127.0.0.1:8000", "http://localhost:8000"]);
function bicycleFixtureSvg(index) {
  const palettes = [
    ["#29265f", "#8b7cff", "#dff7ff"],
    ["#183b4b", "#47b9c3", "#fff1cc"],
    ["#4a2947", "#ec8c9f", "#fff0d8"],
    ["#254132", "#82c77b", "#f4f0d2"],
    ["#3e304e", "#d3a0f2", "#e7f2ff"],
  ];
  const [sky, accent, sun] = palettes[(index - 1) % palettes.length];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
    <defs><linearGradient id="sky" x2="0" y2="1"><stop stop-color="${sky}"/><stop offset="1" stop-color="#11131f"/></linearGradient></defs>
    <rect width="640" height="480" fill="url(#sky)"/>
    <circle cx="500" cy="106" r="54" fill="${sun}" opacity=".9"/>
    <path d="M0 292 155 190l115 97 126-134 244 153v174H0Z" fill="${accent}" opacity=".25"/>
    <path d="M0 352 171 250l140 111 145-132 184 108v143H0Z" fill="#11131f" opacity=".72"/>
    <path d="M0 395 640 337v143H0Z" fill="#0b0c14" opacity=".8"/>
    <g fill="none" stroke="#f7f5ff" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="206" cy="350" r="66" stroke-width="10" opacity=".9"/>
      <circle cx="438" cy="350" r="66" stroke-width="10" opacity=".9"/>
      <path d="m206 350 78-104 69 104H206l41-70h106l48 70m-112-104h-35m105 0h25" stroke-width="13"/>
    </g>
    <circle cx="284" cy="246" r="11" fill="${accent}"/><circle cx="353" cy="350" r="11" fill="${accent}"/>
    <path d="M232 420h178" stroke="${accent}" stroke-width="4" stroke-linecap="round" opacity=".9"/>
  </svg>`;
}

const dashboardMetrics = {
  tokens_per_second: 42.1,
  active_model: "fixture-model-for-browser-check",
  active_sessions: 3,
  queue_depth: 1,
  ram_used_bytes: 6_442_450_944,
  ram_total_bytes: 17_179_869_184,
  ram_percent: 37.5,
  cpu_percent: 21.4,
  disk_used_bytes: 128_849_018_880,
  disk_total_bytes: 512_110_190_592,
  disk_percent: 25.2,
  uptime_seconds: 86_400,
  requests_total: 120,
  requests_successful: 114,
  requests_failed: 6,
  avg_latency_ms: 84,
  timestamp: Date.now(),
  message_stats: {
    total_messages: 2_480,
    sessions_with_messages: 3,
    tokens_out_total: 184_000,
    tokens_in_total: 91_000,
    avg_latency_ms: 84,
  },
  change_stats: { total_changes: 12, files_modified: 7 },
  agent_activity: [
    {
      agent: "QA fixture · CODER",
      status: "active",
      tasks_completed: 11,
      tasks_failed: 1,
      avg_latency_ms: 840,
      last_activity: new Date().toISOString(),
    },
  ],
};

const fixtureTask = (id, title, status) => ({
  id,
  title,
  agent: "QA fixture agent",
  status,
  progress: status === "running" ? 45 : null,
  created_at: "2026-09-28T10:00:00Z",
  kind: "workflow",
  approval_status: null,
  completed_steps: null,
  total_steps: null,
  steps: [],
  error: null,
});

const taskPagination = (offset, hasMore) => Object.fromEntries(
  ["active", "queued", "failed", "completed", "cancelled"].map((group) => [
    group,
    {
      offset,
      limit: 50,
      total: group === "queued" ? 2 : 0,
      has_more: group === "queued" && hasMore,
    },
  ]),
);

function jsonResponse(body, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

function makeTaskPage(offset) {
  const firstPage = offset === 0;
  return {
    active: firstPage ? [fixtureTask("qa-active-1", "QA mock: validar dashboard", "running")] : [],
    queued: [fixtureTask(
      firstPage ? "qa-queued-1" : "qa-queued-2",
      firstPage ? "QA mock: tarefa na fila 1" : "QA mock: tarefa na fila 2",
      "queued",
    )],
    failed: [],
    completed: firstPage ? [fixtureTask("qa-completed-1", "QA mock: revisão concluída", "completed")] : [],
    cancelled: [],
    warnings: [],
    sources: { workflows: { available: true }, plans: { available: true } },
    pagination: taskPagination(firstPage ? 0 : 50, firstPage),
  };
}

function imageHits() {
  return Array.from({ length: 50 }, (_, index) => ({
    title: `Mock bicicleta ${String(index + 1).padStart(2, "0")}`,
    url: `https://example.org/fixture/source-${index + 1}`,
    thumbnail_url: `https://imgs.search.brave.com/fixture-thumb-${index + 1}`,
    source: "example.org · fixture",
    width: 640,
    height: 480,
  }));
}

async function mockBrowserNetwork(page, state) {
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.hostname === "imgs.search.brave.com") {
      const match = url.pathname.match(/(\d+)$/);
      const index = Number(match?.[1] ?? 1);
      await route.fulfill({ status: 200, contentType: "image/svg+xml", body: bicycleFixtureSvg(index) });
      return;
    }

    if (url.origin === appOrigin) {
      await route.continue();
      return;
    }

    if (apiOrigins.has(url.origin)) {
      state.apiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
      const cors = {
        "access-control-allow-origin": appOrigin,
        "access-control-allow-credentials": "true",
        "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "access-control-allow-headers": "authorization,content-type,accept",
        "cache-control": "no-store",
      };

      if (request.method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: cors, body: "" });
        return;
      }

      const pathname = url.pathname;
      if (pathname === "/api/auth/me") {
        await route.fulfill({ ...jsonResponse({ id: "qa-fixture-user", full_name: "QA Fixture" }), headers: cors });
      } else if (pathname === "/api/metrics/current") {
        await route.fulfill({ ...jsonResponse(state.emptyMetrics ? {} : dashboardMetrics), headers: cors });
      } else if (pathname === "/api/ready") {
        await route.fulfill({
          ...jsonResponse(state.criticalDisk ? {
            status: "not_ready",
            dependencies: { database: "ready", disk: "not_ready", agent_pool: "ready", workflow_tracker: "ready" },
            disk_pressure: { status: "critical", pressure: true, write_blocked: true, snapshot: { free_percent: 1.9 } },
          } : {
            status: "ready",
            dependencies: { database: "ready", disk: "ready", agent_pool: "ready", workflow_tracker: "ready" },
            disk_pressure: { status: "normal", pressure: false, write_blocked: false, snapshot: { free_percent: 45 } },
          }),
          headers: cors,
        });
      } else if (pathname === "/api/metrics/history") {
        await route.fulfill({ ...jsonResponse({ history: [] }), headers: cors });
      } else if (pathname === "/api/metrics/usage") {
        await route.fulfill({
          ...jsonResponse({
            total_tokens: 275_000,
            total_tokens_in: 91_000,
            total_tokens_out: 184_000,
            total_cost: 0,
            by_model: {},
            by_agent: {},
            range_seconds: 86_400,
            generated_at: Date.now() / 1000,
            currency: "USD",
          }),
          headers: cors,
        });
      } else if (pathname === "/api/modes") {
        await route.fulfill({
          ...jsonResponse({ modes: Object.fromEntries(["auto", "coder", "swarm", "auto_swarm"].map((id) => [id, {
            description: `Fixture ${id}`,
            default_agent: "CODER",
            default_model: "auto",
            router: "fixture",
            tools_enabled: [],
          }])) }),
          headers: cors,
        });
      } else if (pathname === "/api/projects") {
        await route.fulfill({ ...jsonResponse([]), headers: cors });
      } else if (pathname === "/api/tools") {
        await route.fulfill({ ...jsonResponse({ tools: [] }), headers: cors });
      } else if (pathname === "/api/models/catalog") {
        await route.fulfill({
          ...jsonResponse({ models: [], providers: [] }),
          headers: cors,
        });
      } else if (pathname === "/api/providers/status") {
        await route.fulfill({
          ...jsonResponse({
            providers: {
              "fixture-local": {
                healthy: true,
                latency: 12,
                success_rate: 1,
                request_count: 12,
                failure_count: 0,
                circuit_breaker: { name: "fixture-local", state: "closed", failures: 0, last_failure_time: 0 },
              },
            },
            breakers: {},
            note: "Dados de browser fixture; não refletem providers reais.",
          }),
          headers: cors,
        });
      } else if (pathname === "/api/mcp/connectors") {
        await route.fulfill({
          ...jsonResponse({
            connectors: [],
            summary: { total: 0, enabled: 0, healthy: 0, warning: 0, error: 0, untested: 0 },
          }),
          headers: cors,
        });
      } else if (pathname === "/api/mission/current") {
        await route.fulfill({ ...jsonResponse({ active: false, mission: null }), headers: cors });
      } else if (pathname === "/api/advanced-modes/health") {
        await route.fulfill({
          ...jsonResponse({
            healthy: true,
            active_modes: 1,
            total_modes: 1,
            modes: {
              "qa-fixture": {
                active: true,
                session_count: 1,
                active_session_count: 1,
                total_session_count: 1,
                group: "quality",
                display_name: "QA fixture",
                description: "Modo de dados de teste para a captura local.",
                icon: "CheckCircle2",
                color: "#38bdf8",
                runtime_status: "composed",
                runtime_role: "fixture",
                runtime_summary: "Captura local sem execução de provider.",
                handler: null,
              },
            },
          }),
          headers: cors,
        });
      } else if (pathname === "/api/advanced-modes/commands") {
        await route.fulfill({ ...jsonResponse({ commands: {} }), headers: cors });
      } else if (pathname === "/api/advanced-modes/advisor-infinity") {
        await route.fulfill({
          ...jsonResponse({
            mode_id: "advisor-infinity",
            display_name: "Advisor Infinity · fixture",
            description: "Dados de teste local.",
            color: "#f59e0b",
            active: false,
            session_count: 0,
            sessions: [],
            available: true,
          }),
          headers: cors,
        });
      } else if (pathname === "/api/improvement/status") {
        await route.fulfill({
          ...jsonResponse({ running: true, total_cycles: 4, consecutive_failures: 0, circuit_open: false }),
          headers: cors,
        });
      } else if (pathname === "/api/improvement/subagents") {
        await route.fulfill({
          ...jsonResponse({
            stats: {
              total_subagents: 4,
              successful: 3,
              failed: 1,
              success_rate: 0.75,
              retried: 1,
              context_degraded: 0,
              total_tokens: 5_012,
            },
            recent: [{
              subagent_id: "qa-fixture-subagent",
              phase: "RESEARCH",
              success: true,
              error: null,
              tokens_used: 501,
              duration_seconds: 2.4,
              retries: 0,
              resumed: false,
              context_degraded: false,
              started_at: "2026-09-28T10:00:00Z",
              completed_at: "2026-09-28T10:00:02Z",
            }],
          }),
          headers: cors,
        });
      } else if (pathname === "/api/tasks/list") {
        await route.fulfill({
          ...jsonResponse(makeTaskPage(Number(url.searchParams.get("offset") ?? 0))),
          headers: cors,
        });
      } else if (pathname === "/api/workflows") {
        await route.fulfill({ ...jsonResponse([]), headers: cors });
      } else if (pathname === "/api/agents/instances") {
        await route.fulfill({
          ...jsonResponse({ agents: [{
            instance_id: "qa-agent-1",
            agent_type: "Agente de pesquisa",
            objective: "Validar o contrato real dos agentes",
            status: "running",
            tokens_used: 0,
          }] }),
          headers: cors,
        });
      } else if (pathname === "/api/memory/stats") {
        await route.fulfill({
          ...jsonResponse(state.emptyMetrics ? {} : {
            vector_db_size: 12_345,
            total_retrievals: 7,
            avg_relevance: 0.82,
          }),
          headers: cors,
        });
      } else if (pathname === "/api/system/metrics/stream") {
        const frame = state.emptyMetrics ? {} : {
          cpu_usage: dashboardMetrics.cpu_percent,
          memory_usage: dashboardMetrics.ram_percent,
          disk_usage: dashboardMetrics.disk_percent,
          tokens_per_second: dashboardMetrics.tokens_per_second,
          timestamp: dashboardMetrics.timestamp,
        };
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          headers: { ...cors, "cache-control": "no-cache" },
          body: `data: ${JSON.stringify(frame)}\n\n`,
        });
      } else if (pathname === "/api/autonomous-tasks/stream" || pathname === "/api/agents/topology/stream") {
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          headers: { ...cors, "cache-control": "no-cache" },
          body: "",
        });
      } else if (pathname === "/api/web_search/images") {
        const payload = request.postDataJSON() ?? {};
        await route.fulfill({
          ...jsonResponse({ query: payload.query ?? "fixture", hits: imageHits(), count: 50, configured: true, provider: "fixture" }),
          headers: cors,
        });
      } else if (pathname === "/api/web_search") {
        const payload = request.postDataJSON() ?? {};
        await route.fulfill({
          ...jsonResponse({
            query: payload.query ?? "fixture",
            count: 2,
            hits: [
              { title: "Mock resultado web 01", url: "https://example.org/fixture/one", snippet: "Resultado local de teste.", source_engine: "fixture" },
              { title: "Mock resultado web 02", url: "https://example.org/fixture/two", snippet: "Segundo resultado local de teste.", source_engine: "fixture" },
            ],
          }),
          headers: cors,
        });
      } else if (pathname === "/api/sessions") {
        await route.fulfill({ ...jsonResponse({ sessions: [] }), headers: cors });
      } else if (/^\/api\/sessions\/[^/]+\/messages$/.test(pathname)) {
        await route.fulfill({ ...jsonResponse({ messages: [], count: 0, has_more: false, next_cursor: null }), headers: cors });
      } else if (/^\/api\/sessions\/[^/]+\/runs$/.test(pathname)) {
        await route.fulfill({ ...jsonResponse({ runs: [] }), headers: cors });
      } else {
        state.unexpectedApi.push(`${request.method()} ${pathname}${url.search}`);
        await route.fulfill({ ...jsonResponse({}), headers: cors });
      }
      return;
    }

    state.blockedExternal.push(url.origin);
    await route.abort("blockedbyclient");
  });
}

async function installSyntheticAuth(page) {
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3_600 })).toString("base64url");
  const token = `fixture.${payload}.local-only`;
  const user = {
    id: "qa-fixture-user",
    email: "qa-fixture@example.invalid",
    full_name: "QA Fixture",
    is_active: true,
    created_at: "2026-09-28T00:00:00Z",
  };

  await page.addInitScript(({ accessToken, fixtureUser }) => {
    localStorage.setItem("nexus.access_token", accessToken);
    localStorage.setItem("nexus.user", JSON.stringify(fixtureUser));
  }, { accessToken: token, fixtureUser: user });
}

async function saveScreenshot(page, name) {
  await fs.mkdir(screenshotRoot, { recursive: true });
  await page.screenshot({ path: path.join(screenshotRoot, name), animations: "disabled" });
}

async function assertNoHorizontalOverflow(page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(dimensions.document, JSON.stringify(dimensions)).toBeLessThanOrEqual(dimensions.viewport + 1);
  expect(dimensions.body, JSON.stringify(dimensions)).toBeLessThanOrEqual(dimensions.viewport + 1);
}

test.beforeEach(async ({ page }) => {
  const state = { apiRequests: [], blockedExternal: [], unexpectedApi: [] };
  page.__nexusFunctionalState = state;
  page.on("pageerror", (error) => state.pageErrors?.push(error.message));
  state.consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") state.consoleErrors.push(message.text());
  });
  state.pageErrors = [];
  await installSyntheticAuth(page);
  await mockBrowserNetwork(page, state);
});

test.afterEach(async ({ page }) => {
  const state = page.__nexusFunctionalState;
  expect(state.pageErrors).toEqual([]);
  expect(state.consoleErrors).toEqual([]);
  expect(state.blockedExternal).toEqual([]);
  expect(state.unexpectedApi).toEqual([]);
});

test("dashboard, subagentes, navegação e hierarquia visual", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Painel de Operações" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Lançar objetivo" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Novo objetivo", exact: true })).toHaveAttribute("aria-current", "location");
  await expect(page.getByRole("main").getByText("fixture-model-for-browser-check")).toBeVisible();
  await expect(page.locator("main")).toHaveCount(1);
  await assertNoHorizontalOverflow(page);
  await saveScreenshot(page, "01-dashboard-desktop.png");
  const darkBackground = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.getByRole("button", { name: "Mudar para tema claro" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).not.toBe(darkBackground);
  await saveScreenshot(page, "12-dashboard-light.png");
  await page.getByRole("button", { name: "Mudar para tema escuro" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Painel de Operações" })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  const mobileSidebar = page.locator("#nexus-primary-navigation");
  await expect(page.getByRole("button", { name: "Abrir menu" })).toHaveAttribute("aria-expanded", "false");
  await expect(mobileSidebar).toHaveAttribute("aria-hidden", "true");
  await expect(mobileSidebar).toHaveAttribute("inert", "");
  await page.getByRole("button", { name: "Abrir menu" }).click();
  await expect(page.getByRole("button", { name: "Fechar menu" })).toHaveAttribute("aria-expanded", "true");
  await expect(mobileSidebar).not.toHaveAttribute("inert");
  await expect(mobileSidebar).not.toHaveAttribute("aria-hidden");
  await page.getByRole("button", { name: "Fechar menu" }).click();
  await saveScreenshot(page, "06-dashboard-mobile.png");
  await page.setViewportSize({ width: 1440, height: 1000 });

  await page.getByRole("link", { name: "Agentes", exact: true }).click();
  await expect(page.getByRole("link", { name: "Agentes", exact: true })).toHaveAttribute("aria-current", "location");
  await expect(page.getByRole("link", { name: "Novo objetivo", exact: true })).not.toHaveAttribute("aria-current", "location");
  await page.locator("main").evaluate((main) => { main.scrollTop = 0; });
  await expect(page.getByRole("link", { name: "Novo objetivo", exact: true })).toHaveAttribute("aria-current", "location");
  await page.getByRole("link", { name: "Agentes", exact: true }).click();
  await expect(page.getByRole("link", { name: "Agentes", exact: true })).toHaveAttribute("aria-current", "location");
  await expect(page.getByRole("heading", { name: "Subagentes do ciclo autónomo" })).toBeVisible();
  await expect(page.getByText("4 ciclos")).toBeVisible();
  await expect(page.getByText("RESEARCH", { exact: true })).toBeVisible();
  await expect(page.getByText("501 tok")).toBeVisible();
  await saveScreenshot(page, "02-dashboard-agents-desktop.png");

  await page.getByRole("button", { name: "Atualizar telemetria de subagentes" }).click();
  await expect.poll(() => page.__nexusFunctionalState.apiRequests.filter((item) => item.endsWith("/api/improvement/subagents")).length)
    .toBeGreaterThanOrEqual(2);

  await page.getByRole("button", { name: "Análise profunda do repositório" }).click();
  const objective = page.getByRole("textbox", { name: "O que queres fazer?" });
  await expect(objective).toHaveValue("Análise profunda do repositório");
  await page.getByRole("button", { name: "Preparar no chat" }).click();
  const chatComposer = page.getByPlaceholder(/Escreve o que queres fazer/);
  await expect(chatComposer).toHaveValue("Análise profunda do repositório");
  await expect(page).not.toHaveURL(/prompt=/);

  const failures = await page.evaluate(() => ({
    unnamedButtons: [...document.querySelectorAll("button")].filter((button) => {
      const rect = button.getBoundingClientRect();
      const visible = rect.width > 0 && rect.height > 0;
      const name = button.getAttribute("aria-label")
        || button.getAttribute("aria-labelledby")
        || button.getAttribute("title")
        || button.textContent?.trim();
      return visible && !name;
    }).length,
  }));
  expect(failures.unnamedButtons).toBe(0);
  expect(page.__nexusFunctionalState.blockedExternal).toEqual([]);
});

test("dashboard avisa quando a API responde, mas o runtime não está pronto", async ({ page }) => {
  page.__nexusFunctionalState.criticalDisk = true;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Painel de Operações" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Armazenamento crítico");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("1,9% livre");
  await expect(page.getByRole("button", { name: "Preparar no chat" })).toBeEnabled();
  await assertNoHorizontalOverflow(page);
});

test("Mission Control distingue telemetria recebida e respostas vazias", async ({ page }) => {
  const state = page.__nexusFunctionalState;
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/nexus", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Visão geral" })).toBeVisible();
  await expect(page.getByText("API ligada · telemetria disponível")).toBeVisible();
  await expect(page.getByText("Agente de pesquisa", { exact: true })).toBeVisible();
  await expect(page.getByText("agentes ativos", { exact: true }).locator("..")).toContainText("1");
  await expect(page.getByText("Ainda não há fluxos registados")).toBeVisible();
  await expect(page.getByRole("region", { name: "Memória e conhecimento" })).toContainText(/12[,\.\u00a0\u202f]345/);
  await expect(page.locator('[aria-label="CPU: 21%"]')).toBeVisible();
  expect(state.apiRequests.some((item) => item.endsWith("/api/memory/stats"))).toBe(true);
  expect(state.blockedExternal).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await saveScreenshot(page, "08-mission-control-desktop.png");

  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoHorizontalOverflow(page);
  await saveScreenshot(page, "09-mission-control-mobile.png");

  state.emptyMetrics = true;
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("API ligada · sem dados")).toBeVisible();
  await expect(page.getByText("API ligada · sem telemetria")).toBeVisible();
  await expect(page.locator('[aria-label="CPU: sem dados"]')).toBeVisible();
  await expect(page.getByText("— vetores")).toBeVisible();
  await expect(page.getByText("Ainda não há fluxos registados")).toBeVisible();
  expect(state.unexpectedApi).toEqual([]);
  expect(state.blockedExternal).toEqual([]);
});

test("tarefas com filtros, contagens e paginação sem duplicados", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/tasks", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: "Tarefas" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("QA mock: validar dashboard")).toBeVisible();
  await expect(page.getByText("QA mock: tarefa na fila 1")).toBeVisible();
  await expect(page.getByText("QA mock: revisão concluída")).toBeVisible();
  await expect(page.getByRole("button", { name: "Carregar mais tarefas" })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await saveScreenshot(page, "03-tasks-desktop.png");

  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoHorizontalOverflow(page);
  await saveScreenshot(page, "07-tasks-mobile.png");
  await page.setViewportSize({ width: 1440, height: 1000 });

  await page.getByRole("button", { name: "Carregar mais tarefas" }).click();
  await expect(page.getByText("QA mock: tarefa na fila 2")).toBeVisible();
  await expect(page.getByText("QA mock: tarefa na fila 1")).toBeVisible();
  await expect(page.getByRole("button", { name: "Carregar mais tarefas" })).toHaveCount(0);

  await page.getByRole("button", { name: /Concluídas/ }).click();
  await expect(page.getByText("QA mock: revisão concluída")).toBeVisible();
  await expect(page.getByText("QA mock: validar dashboard")).toHaveCount(0);
  expect(page.__nexusFunctionalState.apiRequests.some((item) => item.includes("/api/tasks/list?limit=50&offset=50"))).toBe(true);
  expect(page.__nexusFunctionalState.blockedExternal).toEqual([]);
});

test("pesquisa Web/Imagens e cartões responsivos com miniaturas mockadas", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/search", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Pesquisa" })).toBeVisible();

  await page.getByRole("button", { name: "Imagens" }).click();
  const input = page.getByRole("searchbox", { name: "Termos de pesquisa" });
  await input.fill("bicicleta urbana");
  await page.getByRole("button", { name: "Pesquisar", exact: true }).click();
  await expect(page.getByRole("link", { name: /Mock bicicleta 01/ })).toBeVisible();
  await expect.poll(() => page.getByRole("img", { name: "Mock bicicleta 01" }).evaluate((image) => image.naturalWidth))
    .toBe(640);
  await expect(page.getByText("Mock bicicleta 26")).toHaveCount(0);
  await saveScreenshot(page, "04-search-images-desktop.png");

  await page.getByRole("button", { name: "Seguinte" }).click();
  await expect(page.getByRole("link", { name: /Mock bicicleta 26/ })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoHorizontalOverflow(page);
  await saveScreenshot(page, "05-search-images-mobile.png");
  await expect(page.getByRole("button", { name: "Anterior" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Seguinte" })).toBeDisabled();

  await input.fill("capacete urbano");
  await page.getByRole("button", { name: "Web" }).click();
  await expect(page.getByRole("link", { name: /Mock resultado web 01/ })).toBeVisible();
  expect(page.__nexusFunctionalState.apiRequests.some((item) => item.includes("/api/web_search/images"))).toBe(true);
  expect(page.__nexusFunctionalState.apiRequests.some((item) => item.includes("/api/web_search"))).toBe(true);
  expect(page.__nexusFunctionalState.blockedExternal).toEqual([]);
  expect(page.__nexusFunctionalState.unexpectedApi).toEqual([]);
});
