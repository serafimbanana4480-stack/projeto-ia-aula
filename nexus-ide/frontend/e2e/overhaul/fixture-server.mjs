/**
 * Local fixture API for the UI overhaul.
 * It never calls a paid model provider. Host CPU/RAM figures, when present,
 * come from the machine running this process.
 */
import http from "node:http";
import os from "node:os";

const port = Number(process.env.OVERHAUL_API_PORT || 8765);
const kilo = "O Kilo está bloqueado pela política só gratuita. Revê essa política e a configuração do fornecedor em Definições.";

function b64url(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

const exp = Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 14;
const accessToken = `${b64url({ alg: "none", typ: "JWT" })}.${b64url({ sub: "user-1", email: "dev@nexus.local", exp })}.fixture`;
const user = {
  id: "user-1",
  email: "dev@nexus.local",
  username: "dev",
  full_name: "Dev Fixture",
  role: "admin",
  is_active: true,
  created_at: "2026-11-01T00:00:00Z",
};

const bots = [
  { id: "forge", session_id: "sess-forge", name: "FORGE", description: "Programação", instructions: "Implementa com evidência.", provider: "kilo", model: "kilo-free", archived: false, last_message: "Encontrei o ramo em parse().", last_active_at: "2026-11-09T10:05:00Z" },
  { id: "debug", session_id: "sess-debug", name: "Debugger", description: "Diagnóstico", instructions: "Separa hipótese de evidência.", provider: "kilo", model: "kilo-free", archived: false, last_message: null, last_active_at: "2026-11-09T09:00:00Z" },
  { id: "pulse", session_id: "sess-pulse", name: "PULSE", description: "Síntese", instructions: "Sintetiza só o que está verificado.", provider: "ollama", model: "fixture/model-1", archived: false, last_message: null, last_active_at: "2026-11-08T18:00:00Z" },
];

const groups = [
  { id: "g-fail", name: "123", bot_ids: ["forge", "debug"], last_message: "O Kilo está bloqueado pela política só gratuita." },
  { id: "g-run", name: "Revisão em curso", bot_ids: ["forge", "debug"], last_message: "A analisar o diff" },
  { id: "g-done", name: "Revisão concluída", bot_ids: ["forge", "debug", "pulse"], last_message: "Falta cobertura para string vazia." },
  { id: "g-idle", name: "Planeamento", bot_ids: ["forge", "debug"], last_message: null },
];

function errorMessage(id, bot) {
  return { id, role: "error", content: kilo, bot_id: bot.id, bot_name: bot.name, created_at: "2026-11-09T10:00:00Z" };
}

const histories = {
  "g-fail": [
    { id: "u0", role: "user", content: "Contexto longo para o scroll.\n\n" + "linha de histórico\n".repeat(40), bot_id: null, bot_name: null, created_at: "2026-11-09T09:50:00Z" },
    { id: "u1", role: "user", content: "bom dia", bot_id: null, bot_name: null, created_at: "2026-11-09T09:59:00Z" },
    errorMessage("e1", bots[0]),
    errorMessage("e2", bots[1]),
    errorMessage("e3", bots[0]),
    errorMessage("e4", bots[1]),
  ],
  "g-run": [
    { id: "u2", role: "user", content: "Revê o diff do parser.", bot_id: null, bot_name: null, created_at: "2026-11-09T11:00:00Z" },
    { id: "a2", role: "assistant", content: "A ler `parser.ts` e a comparar com o teste.", bot_id: "forge", bot_name: "FORGE", created_at: "2026-11-09T11:00:02Z" },
  ],
  "g-done": [
    { id: "u3", role: "user", content: "O que garante o contrato de `parse`?", bot_id: null, bot_name: null, created_at: "2026-11-09T12:00:00Z" },
    { id: "a3", role: "assistant", content: "O ramo relevante está em `parse()`.\n\n```ts\nexport function parse(input: string) {\n  return input.trim();\n}\n```\n\nO trim é o que o ficheiro faz. Não vi testes.", bot_id: "forge", bot_name: "FORGE", created_at: "2026-11-09T12:00:04Z" },
    { id: "a4", role: "assistant", content: "Concordo com o trim, mas falta o caso de entrada vazia. Sem um teste, a conclusão fica por verificar.", bot_id: "debug", bot_name: "Debugger", created_at: "2026-11-09T12:00:09Z" },
  ],
  "g-idle": [],
};

const runs = {
  "g-fail": [{
    id: "run-failed",
    status: "failed",
    request: "Ler o ficheiro e explicar a falha",
    project_root: "/workspace/nexus",
    file_path: "src/parser.ts",
    tasks: [
      { id: "t1", bot_name: "FORGE", provider: "kilo", model: "kilo-free", status: "failed", result: null, error: kilo },
      { id: "t2", bot_name: "Debugger", provider: "kilo", model: "kilo-free", status: "skipped", result: null, error: null },
    ],
    records: [
      { id: "fail-call", task_id: "t1", kind: "tool_call", payload: { tool: "read_file", path: "src/parser.ts" } },
      { id: "fail-result", task_id: "t1", kind: "tool_result", payload: { call_id: "fail-call", error: kilo } },
    ],
  }],
  "g-run": [{
    id: "run-live",
    status: "running",
    request: "Rever o diff do parser",
    project_root: "/workspace/nexus",
    file_path: "src/parser.ts",
    tasks: [
      { id: "t3", bot_name: "FORGE", provider: "kilo", model: "kilo-free", status: "running", result: null, error: null },
      { id: "t4", bot_name: "Debugger", provider: "kilo", model: "kilo-free", status: "pending", result: null, error: null },
    ],
    records: [
      { id: "live-call", task_id: "t3", kind: "tool_call", payload: { tool: "read_file", path: "src/parser.ts" } },
    ],
  }],
  "g-done": [{
    id: "run-done",
    status: "completed",
    request: "Confirmar o contrato de parse",
    project_root: "/workspace/nexus",
    file_path: "src/parser.ts",
    tasks: [
      { id: "t5", bot_id: "forge", bot_name: "FORGE", provider: "kilo", model: "kilo-free", status: "completed", result: "O trim é o contrato observável no ficheiro.", error: null },
      { id: "t6", bot_id: "debug", bot_name: "Debugger", provider: "kilo", model: "kilo-free", status: "completed", result: "Falta cobertura para string vazia.", error: null },
      { id: "t7", bot_id: "pulse", bot_name: "PULSE", provider: "ollama", model: "fixture/model-1", status: "completed", result: "Verificado: trim. Por verificar: string vazia.", error: null },
    ],
    records: [
      { id: "done-call", task_id: "t5", kind: "tool_call", payload: { tool: "read_file", path: "src/parser.ts" } },
      { id: "done-result", task_id: "t5", kind: "tool_result", payload: { call_id: "done-call", path: "src/parser.ts" } },
      { id: "done-hand", task_id: "t6", kind: "handoff", payload: { source_bot_id: "forge", trust: "analysis_unverified", previous_analyses: [{ bot_name: "FORGE", analysis: "O trim é o contrato observável no ficheiro." }] } },
      { id: "done-hand-2", task_id: "t7", kind: "handoff", payload: { source_bot_id: "debug", trust: "analysis_unverified", previous_analyses: [{ bot_name: "Debugger", analysis: "Falta cobertura para string vazia." }] } },
    ],
  }],
  "g-idle": [],
};

const totalMem = os.totalmem();
const freeMem = os.freemem();
const cpu = os.loadavg()[0];

const metrics = {
  tokens_per_second: null,
  active_model: "",
  active_sessions: 1,
  queue_depth: 0,
  ram_used_bytes: totalMem - freeMem,
  ram_total_bytes: totalMem,
  ram_percent: ((totalMem - freeMem) / totalMem) * 100,
  cpu_percent: Math.min(100, cpu * 10),
  disk_used_bytes: null,
  disk_total_bytes: null,
  disk_percent: null,
  uptime_seconds: os.uptime(),
  requests_total: null,
  requests_successful: null,
  requests_failed: null,
  avg_latency_ms: null,
  timestamp: Date.now() / 1000,
};

const catalogModels = Array.from({ length: 120 }, (_, index) => ({
  id: `fixture/model-${index + 1}`,
  name: `Modelo fixture ${index + 1}`,
  provider: index % 2 === 0 ? "ollama" : "lmstudio",
  context_window: index % 5 === 0 ? 128000 : null,
  free: index % 3 === 0,
  input_price_per_1m: null,
  output_price_per_1m: null,
  capabilities: index % 4 === 0 ? ["code"] : [],
  description: "Entrada de catálogo local. A inferência não foi executada.",
}));

function send(res, status, body, headers = {}) {
  const payload = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json", "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*", ...headers });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", "http://127.0.0.1");
  const path = url.pathname;
  if (req.method === "OPTIONS") {
    send(res, 204, "");
    return;
  }
  if (path === "/api/auth/login" || path === "/api/auth/refresh") {
    send(res, 200, { access_token: accessToken, refresh_token: accessToken, user });
    return;
  }
  if (path === "/api/auth/me") {
    send(res, 200, user);
    return;
  }
  if (path === "/api/projects") {
    send(res, 200, { projects: [{ id: "p1", name: "nexus-ide-phase3-browser", path: "/workspace/nexus-ide", description: "Validação browser do chat", mode: "auto", preferred_model: "", trust: false, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z" }] });
    return;
  }
  if (path === "/api/bots") {
    send(res, 200, { bots });
    return;
  }
  if (path === "/api/bot-groups" && req.method === "GET") {
    send(res, 200, { groups });
    return;
  }
  const groupMessages = path.match(/^\/api\/bot-groups\/([^/]+)\/messages$/);
  if (groupMessages && req.method === "GET") {
    send(res, 200, { messages: histories[groupMessages[1]] ?? [], has_more: false, next_before: null });
    return;
  }
  if (groupMessages && req.method === "POST") {
    await readBody(req);
    const frame = `data: ${JSON.stringify({ type: "error", content: "Fixture: nenhum provider foi contactado." })}\n\n`;
    res.writeHead(200, { "content-type": "text/event-stream", "access-control-allow-origin": "*" });
    res.end(frame);
    return;
  }
  const groupRuns = path.match(/^\/api\/bot-groups\/([^/]+)\/runs$/);
  if (groupRuns && req.method === "GET") {
    send(res, 200, { runs: runs[groupRuns[1]] ?? [] });
    return;
  }
  if (path === "/api/sessions" && req.method === "GET") {
    send(res, 200, { sessions: [{ id: "sess-chat", title: "Refactor do parser", mode: "agent", project_id: "p1", created_at: "2026-11-09T08:00:00Z", last_active_at: "2026-11-09T08:30:00Z", message_count: 2 }], has_more: false });
    return;
  }
  if (path === "/api/sessions" && req.method === "POST") {
    send(res, 200, { id: "sess-new", title: "Nova sessão", mode: "auto" });
    return;
  }
  const sessionMessages = path.match(/^\/api\/sessions\/([^/]+)\/messages$/);
  if (sessionMessages) {
    const id = decodeURIComponent(sessionMessages[1]);
    if (id === "sess-forge") {
      send(res, 200, {
        messages: [
          { id: "m-user", role: "user", content: "Onde é que o parser corta a entrada?", timestamp: "2026-11-09T10:04:00Z" },
          {
            id: "m-tool",
            role: "assistant",
            content: "Encontrei o ramo em `parse()`.\n\n```ts\nexport function parse(input: string) {\n  return input.trim();\n}\n```",
            timestamp: "2026-11-09T10:05:00Z",
            toolCalls: [{ id: "tool-1", name: "read_file", status: "success", args: { path: "src/parser.ts" } }],
          },
        ],
        has_more: false,
        next_cursor: null,
        count: 2,
      });
      return;
    }
    if (id === "sess-chat") {
      send(res, 200, {
        messages: [
          { id: "c1", role: "user", content: "Explica o parser em markdown.", timestamp: "2026-11-09T08:10:00Z" },
          { id: "c2", role: "assistant", content: "## Parser\n\n- valida a entrada\n- devolve texto limpo\n\n```ts\nparse(text)\n```", timestamp: "2026-11-09T08:10:05Z", agent: "NEXUS" },
        ],
        has_more: false,
        next_cursor: null,
        count: 2,
      });
      return;
    }
    send(res, 200, { messages: [], has_more: false, next_cursor: null, count: 0 });
    return;
  }
  if (path.startsWith("/api/sessions/") && path.endsWith("/runs")) {
    send(res, 200, { runs: [], has_more: false, next_offset: 0 });
    return;
  }
  if (path === "/api/models/catalog" || path === "/api/models/available") {
    send(res, 200, {
      models: catalogModels,
      providers: [
        { provider: "ollama", label: "Ollama (local)", count: 60, cached: false, fetched_at: Date.now() / 1000, error: null, configured: true },
        { provider: "lmstudio", label: "LM Studio (local)", count: 60, cached: false, fetched_at: Date.now() / 1000, error: null, configured: true },
        { provider: "kilo", label: "Kilo", count: 0, cached: false, fetched_at: 0, error: "Política só gratuita bloqueou o catálogo remoto.", configured: true },
      ],
    });
    return;
  }
  if (path === "/api/providers/catalog") {
    send(res, 200, [
      { id: "kilo", label: "Kilo", key_setting: "kilo_api_key", requires_key: true, api_key_set: false, base_url: "", docs: "" },
      { id: "ollama", label: "Ollama", key_setting: "", requires_key: false, api_key_set: false, base_url: "http://127.0.0.1:11434", docs: "" },
    ]);
    return;
  }
  if (path === "/api/providers/status") {
    send(res, 200, {
      note: "Fixture local: nenhum provider remoto foi consultado.",
      providers: {
        kilo: { healthy: null, status: "unknown", health_basis: "eligibility", runtime_observed: false },
        ollama: { healthy: null, status: "unknown", runtime_observed: false },
      },
    });
    return;
  }
  if (path === "/api/settings" && req.method === "GET") {
    send(res, 200, { local_llm_device: "auto", backend_host: "http://127.0.0.1:8765", default_mode: "auto", default_model: "", enable_telemetry: false, llm_provider: "ollama" });
    return;
  }
  if (path === "/api/modes") {
    send(res, 200, { modes: { auto: { description: "O router escolhe", default_agent: "NEXUS", default_model: "auto", router: "auto", tools_enabled: [] } } });
    return;
  }
  if (path === "/api/tools") {
    send(res, 200, { tools: [{ name: "read_file", description: "Lê um ficheiro do projeto", enabled: true, schema: {}, status: "available", category: "ficheiros" }] });
    return;
  }
  if (path.startsWith("/api/tasks/list")) {
    const empty = { offset: 0, limit: 50, total: 0, has_more: false };
    send(res, 200, {
      active: [],
      queued: [],
      failed: [{ id: "task-1", title: "Rever parser", agent: "FORGE", status: "failed", progress: null, created_at: "2026-11-09T10:00:00Z", kind: "plan", approval_status: null, completed_steps: 0, total_steps: 2, steps: [], error: kilo }],
      completed: [],
      cancelled: [],
      warnings: [],
      sources: { workflows: { available: true }, plans: { available: true } },
      pagination: { active: empty, queued: empty, failed: { offset: 0, limit: 50, total: 1, has_more: false }, completed: empty, cancelled: empty },
    });
    return;
  }
  if (path === "/api/metrics/current") {
    send(res, 200, metrics);
    return;
  }
  if (path.startsWith("/api/metrics/history")) {
    send(res, 200, { series: {} });
    return;
  }
  send(res, 404, { detail: `Fixture sem esta rota: ${req.method} ${path}` });
});

server.listen(port, "127.0.0.1", () => {
  console.log(`overhaul fixture listening on ${port}`);
});
