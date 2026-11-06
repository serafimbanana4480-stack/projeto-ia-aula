import type { ActivityItem, ChatMessage, RunStep, StepStatus } from "./types";
import { workerOf } from "./activityGroups";

/**
 * Turns structured run steps into short Portuguese sentences.
 *
 * The runtime label is kept when it is already something a person can read.
 * Labels that are agent prefixes, snake_case events or mission counters are
 * rewritten from the step's own kind, verb, target and status. Nothing here
 * invents a result: success, failure and counts appear only when the step
 * reports them.
 */

export type WorkPhase =
  | "analyzing"
  | "searching"
  | "planning"
  | "coding"
  | "tooling"
  | "testing"
  | "waiting"
  | "blocked"
  | "authorization"
  | "done"
  | "failed"
  | "cancelled";

export const PHASE_LABEL: Record<WorkPhase, string> = {
  analyzing: "A analisar",
  searching: "A pesquisar",
  planning: "A planear",
  coding: "A programar",
  tooling: "A executar ferramentas",
  testing: "A testar",
  waiting: "À espera de resultados",
  blocked: "Bloqueado",
  authorization: "A aguardar autorização",
  done: "Concluído",
  failed: "Falhou",
  cancelled: "Cancelado",
};

export interface Narration {
  sentence: string;
  phase: WorkPhase;
  phaseLabel: string;
  /** True when the visible sentence was rewritten from structured fields. */
  technical: boolean;
  raw: string;
}

const TECHNICAL_LABEL =
  /continuing mission|mission\s+\d+\s*\/\s*\d+|\biteration\s*[:=]?\s*\d+\b|^(?:status_update|tool_started|tool_completed|tool_failed|runtime_event|heartbeat|subagent_started|subagent_progress)$/i;

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function textField(record: Record<string, unknown> | null, keys: string[]): string {
  if (!record) return "";
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function intField(record: Record<string, unknown> | null, keys: string[]): number | null {
  if (!record) return null;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isInteger(value)) return value;
  }
  return null;
}

function stripRolePrefix(label: string): string {
  const match = label.match(/^([A-Z][A-Z0-9_]{1,32})\s*:\s*([\s\S]+)$/);
  return match ? match[2].trim() : label.trim();
}

export function looksLikeTechnicalLabel(label: string): boolean {
  const text = stripRolePrefix(label);
  if (!text) return true;
  if (TECHNICAL_LABEL.test(text)) return true;
  if (/^[A-Za-z]+(?:_[A-Za-z0-9]+)+$/.test(text)) return true;
  if (!/\s/.test(text) && /[_./\\]/.test(text)) return true;
  if (/^[A-Z0-9_]{3,}$/.test(text)) return true;
  return false;
}

function baseName(target: string): string {
  const trimmed = target.trim();
  if (!trimmed) return "";
  const parts = trimmed.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || trimmed;
}

function shortTarget(target: string, max = 80): string {
  const value = target.trim().replace(/\s+/g, " ");
  if (!value) return "";
  return value.length > max ? `${value.slice(0, max - 1).trimEnd()}…` : value;
}

function workPhase(step: Pick<RunStep, "kind" | "verb" | "target">): WorkPhase {
  const kind = (step.kind || "").toLowerCase();
  const target = (step.target || "").toLowerCase();
  const blob = `${kind} ${target}`;
  if (step.verb === "thinking" || kind.includes("think")) return "analyzing";
  if (step.verb === "test" || kind.startsWith("test") || /pytest|vitest|jest|typecheck/.test(blob)) return "testing";
  if (/web_search|search_web|fetch_url|browser/.test(blob) || kind.startsWith("search") || kind.startsWith("web")) {
    return "searching";
  }
  if (/grep|search_code|glob|codebase/.test(blob)) return "searching";
  if (/plan|todo/.test(blob) || kind.includes("plan")) return "planning";
  if (step.verb === "agent" || kind.startsWith("subagent")) return "planning";
  if (/write|edit|patch|create|scaffold/.test(blob)) return "coding";
  if (step.verb === "file" && /read|list|tree|open/.test(blob)) return "analyzing";
  if (step.verb === "file") return "coding";
  if (step.verb === "command" || step.verb === "tool") return "tooling";
  if (/wait|heartbeat|depend|recover/.test(kind)) return "waiting";
  return "analyzing";
}

function phaseOf(step: Pick<RunStep, "kind" | "verb" | "status" | "target">): WorkPhase {
  if (step.status === "awaiting_confirmation") return "authorization";
  if (step.status === "error") return "failed";
  if (step.status === "cancelled") return "cancelled";
  if (step.status === "paused" || step.status === "warning") return "blocked";
  if (step.status === "success") return "done";
  return workPhase(step);
}

function countSuffix(label: string, detail: Record<string, unknown> | null): string {
  const fromLabel = stripRolePrefix(label).match(/(\d+)\s*\/\s*(\d+)/);
  const done = fromLabel ? Number(fromLabel[1]) : intField(detail, ["completed", "done", "tasks_done"]);
  const total = fromLabel ? Number(fromLabel[2]) : intField(detail, ["total", "tasks_total", "task_total"]);
  if (done === null || total === null) return "";
  if (total <= 0 || done < 0 || done > total) return "";
  return ` Progresso registado: ${done} de ${total}.`;
}

function structuredSentence(step: Pick<RunStep, "kind" | "label" | "target" | "verb" | "status" | "detail">): string {
  const detail = asRecord(step.detail);
  const kind = (step.kind || "").toLowerCase();
  const target = step.target || "";
  const file = baseName(target);
  const phase = workPhase(step);
  const counts = countSuffix(step.label, detail);

  if (step.status === "awaiting_confirmation") {
    return file ? `Preciso da sua autorização para continuar em ${file}.` : "Preciso da sua autorização para continuar.";
  }
  if (step.status === "cancelled") return "Esta ação foi cancelada.";
  if (step.status === "paused") return "A execução está em pausa.";

  if (step.status === "error") {
    const reason = textField(detail, ["error", "reason", "message"]);
    const safeReason = reason && !looksLikeTechnicalLabel(reason) && reason.length <= 160 ? ` ${reason}` : "";
    if (file && phase === "testing") return `Os testes falharam em ${file}.${safeReason}`;
    if (file) return `Encontrei um problema em ${file}.${safeReason}`;
    return `Encontrei um problema.${safeReason}`;
  }

  if (step.status === "success") {
    if (phase === "testing") {
      const failed = intField(detail, ["failed", "failures", "failed_tests"]);
      const passed = intField(detail, ["passed", "passed_tests"]);
      if (failed !== null && failed > 0) {
        return passed !== null
          ? `Os testes terminaram: ${passed} aprovados e ${failed} falhados.`
          : `Os testes terminaram com ${failed} falhas.`;
      }
      if (detail?.ok === true && (failed === null || failed === 0)) {
        return passed !== null ? `Os testes passaram: ${passed} aprovados.` : "Os testes passaram.";
      }
      return "A verificação terminou.";
    }
    if (/read|list|tree|open/.test(kind) || step.verb === "file" && /read|list/.test(kind + target)) {
      return file ? `Analisei ${file}.` : "Analisei os ficheiros.";
    }
    if (/write|edit|patch|changed|create/.test(kind)) {
      return file ? `Alterei ${file}.` : "Alterei ficheiros.";
    }
    if (step.verb === "command" || kind.startsWith("command")) {
      return target ? `O comando terminou: ${shortTarget(target)}.` : "O comando terminou.";
    }
    if (step.verb === "agent" || kind.startsWith("subagent")) {
      return file ? `${file} concluiu a sua parte.` : "O agente concluiu a sua parte.";
    }
    return counts ? `Esta etapa terminou.${counts}` : "Esta etapa terminou.";
  }

  if (phase === "testing") return "Estou a executar os testes.";
  if (phase === "searching") {
    return target ? `Estou a pesquisar ${shortTarget(target, 72)}.` : "Estou a pesquisar.";
  }
  if (phase === "planning") {
    return target && step.verb === "agent"
      ? `Estou a coordenar ${baseName(target)}.`
      : `Estou a planear o próximo passo.${counts}`;
  }
  if (phase === "coding") return file ? `Estou a alterar ${file}.` : "Estou a alterar código.";
  if (phase === "waiting") return "Estou à espera de resultados.";
  if (phase === "analyzing" && file && (step.verb === "file" || /read|list/.test(kind))) {
    return `Estou a ler ${file}.`;
  }
  if (phase === "analyzing" && step.verb === "thinking") return "Estou a analisar a tarefa.";
  if (step.verb === "command") {
    return target ? `Estou a executar ${shortTarget(target)}.` : "Estou a executar um comando.";
  }
  if (step.verb === "tool" && file) return `Estou a usar ${file.replace(/_/g, " ")}.`;
  return `Estou a trabalhar nesta tarefa.${counts}`;
}

function primaryRuntimeSentence(
  step: Pick<RunStep, "status">,
  label: string,
): string | null {
  const match = label.match(/^(NEXUS|ORCHESTRATOR)\b\s*:?\s*(.*)$/);
  if (!match) return null;
  const rest = match[2].trim().toLowerCase();
  if (!rest || /conclu/.test(rest)) {
    if (step.status === "error") return "A execução terminou com erro.";
    if (step.status === "success") return "A resposta ficou pronta.";
    return "Estou a trabalhar.";
  }
  if (/prepar/.test(rest)) {
    return step.status === "success" ? "A resposta ficou pronta." : "Estou a preparar a resposta.";
  }
  return null;
}

const PHASE_LINE: Record<string, string> = {
  planning: "A planear o próximo passo.",
  observe: "A observar o pedido.",
  act: "A executar o próximo passo.",
  executing: "A executar ferramentas.",
  verifying: "A verificar o resultado.",
  routing: "A encaminhar a tarefa.",
  model_request: "A chamar o modelo.",
};

export function narrateStep(step: Pick<RunStep, "kind" | "label" | "target" | "verb" | "status" | "detail" | "agent">): Narration {
  const raw = (step.label || "").trim();
  const stripped = stripRolePrefix(raw);
  const phaseLine = PHASE_LINE[stripped.toLowerCase()];
  if (phaseLine) {
    const phase = phaseOf(step);
    return { sentence: phaseLine, phase, phaseLabel: PHASE_LABEL[phase], technical: true, raw };
  }
  const primary = primaryRuntimeSentence(step, stripped);
  const aside = isOrchestratorAside(stripped);
  const technical = looksLikeTechnicalLabel(raw) || aside || primary !== null;
  const phase = phaseOf(step);
  const sentence = primary ?? (technical ? structuredSentence(step) : stripped || structuredSentence(step));
  return {
    sentence,
    phase,
    phaseLabel: PHASE_LABEL[phase],
    technical,
    raw,
  };
}

export function narrateActivity(activity: Pick<ActivityItem, "title" | "detail" | "status" | "kind">): string {
  const title = (activity.title || "").trim();
  const detail = (activity.detail || "").trim();
  const candidate = !looksLikeTechnicalLabel(detail) && detail ? detail : title;
  if (candidate && !looksLikeTechnicalLabel(candidate)) return candidate;
  if (activity.status === "error") return "Encontrei um problema nesta etapa.";
  if (activity.status === "paused") return "A execução está em pausa.";
  if (activity.status === "success") return "Esta etapa terminou.";
  if (activity.kind === "verification") return "Estou a verificar o resultado.";
  if (activity.kind === "plan") return "Estou a atualizar o plano.";
  if (activity.kind === "agent") return "Um agente está a trabalhar.";
  return "Estou a trabalhar nesta tarefa.";
}

const TODO_DONE = new Set(["done", "complete", "completed", "success"]);

/** Counts only todos the run actually attached to a plan activity. */
export function declaredPlanProgress(activities: ActivityItem[] | undefined): { done: number; total: number } | null {
  if (!activities?.length) return null;
  for (let index = activities.length - 1; index >= 0; index -= 1) {
    const activity = activities[index];
    if (activity.kind !== "plan") continue;
    const todos = activity.data?.todos;
    if (!Array.isArray(todos) || todos.length === 0) continue;
    let done = 0;
    let seen = 0;
    for (const todo of todos) {
      if (!todo || typeof todo !== "object") continue;
      if (["category", "objective"].includes(String((todo as { type?: unknown }).type))) continue;
      seen += 1;
      const status = String((todo as { status?: unknown }).status ?? "").toLowerCase();
      if (TODO_DONE.has(status)) done += 1;
    }
    if (seen === 0) return null;
    return { done, total: seen };
  }
  return null;
}

const AGENT_ROLE: Record<string, string> = {
  ARCHITECT: "Arquitetura",
  ARCHITECT_DESIGN: "Arquitetura",
  ARCHITECT_COMPLEXITY: "Arquitetura",
  CODER: "Implementação",
  RESEARCHER: "Pesquisa",
  RESEARCHER_WEB: "Pesquisa",
  DEBUGGER: "Verificação",
  ANALYZER: "Análise",
  DOCUMENTER: "Documentação",
  OPTIMIZER: "Desempenho",
  REVIEWER: "Revisão",
  PLANNER: "Planeamento",
  TEST_RUNNER_UNIT: "Testes",
  TEST_RUNNER_E2E: "Testes",
  BUG_HUNTER_STATIC: "Verificação",
  BUG_HUNTER_RUNTIME: "Verificação",
};

export interface AgentRosterEntry {
  name: string;
  taskId?: string;
  role: string;
  status: StepStatus;
  sentence: string;
  objective?: string;
  task?: string;
  tool?: string;
  files: string[];
  errors: string[];
  dependsOn: string[];
  durationMs?: number;
}

function statusRank(status: StepStatus): number {
  switch (status) {
    case "running":
      return 7;
    case "awaiting_confirmation":
      return 6;
    case "paused":
      return 5;
    case "error":
      return 4;
    case "warning":
      return 3;
    case "pending":
      return 2;
    case "success":
      return 1;
    default:
      return 0;
  }
}

function coerceStatus(value: string | undefined): StepStatus {
  if (
    value === "running" ||
    value === "success" ||
    value === "error" ||
    value === "warning" ||
    value === "cancelled" ||
    value === "paused" ||
    value === "awaiting_confirmation" ||
    value === "pending"
  ) {
    return value;
  }
  return "pending";
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).map((item) => item.trim());
}

interface RosterDraft {
  name: string;
  taskId?: string;
  status: StepStatus;
  statusAt?: number;
  sentence: string;
  objective?: string;
  task?: string;
  tool?: string;
  files: string[];
  errors: string[];
  dependsOn: string[];
  durationMs?: number;
  startedAt?: number;
  endedAt?: number;
}

function ensure(map: Map<string, RosterDraft>, name: string, taskId?: string): RosterDraft {
  const key = `${name.trim()}\u0000${taskId ?? ""}`;
  const existing = map.get(key);
  if (existing) return existing;
  const created: RosterDraft = {
    name: name.trim(),
    taskId,
    status: "pending",
    sentence: "",
    files: [],
    errors: [],
    dependsOn: [],
  };
  map.set(key, created);
  return created;
}

function preferStatus(current: StepStatus, next: StepStatus): StepStatus {
  const terminal = new Set<StepStatus>(["success", "error", "cancelled"]);
  if (terminal.has(next)) return next;
  if (terminal.has(current)) return current;
  return statusRank(next) > statusRank(current) ? next : current;
}

function updateAgentStatus(draft: RosterDraft, next: StepStatus, timestamp?: number): void {
  if (timestamp !== undefined && Number.isFinite(timestamp)) {
    if (draft.statusAt === undefined || timestamp > draft.statusAt) {
      draft.status = next;
      draft.statusAt = timestamp;
    } else if (timestamp === draft.statusAt) {
      draft.status = preferStatus(draft.status, next);
    }
  } else if (draft.statusAt === undefined) {
    draft.status = preferStatus(draft.status, next);
  }
}

/** Subagents the run actually started. Available-but-unused catalog entries are absent. */
export function buildAgentRoster(message: Pick<ChatMessage, "steps" | "activities"> | null): AgentRosterEntry[] {
  if (!message) return [];
  const map = new Map<string, RosterDraft>();
  // A role name is not an identity. Precompute task IDs so unscoped legacy
  // events are only attributed by name when that name has a single task.
  const tasksByName = new Map<string, Set<string>>();
  const rememberTask = (name: string, taskId: unknown) => {
    if (!name || typeof taskId !== "string" || !taskId) return;
    const ids = tasksByName.get(name) ?? new Set<string>();
    ids.add(taskId);
    tasksByName.set(name, ids);
  };
  for (const activity of message.activities ?? []) {
    if (activity.kind === "agent") rememberTask((activity.agent || "").trim(), asRecord(activity.data)?.task_id);
  }
  for (const step of message.steps ?? []) {
    if (step.verb === "agent") rememberTask(workerOf(step).trim(), step.taskId);
  }
  const resolveTask = (name: string, taskId?: string): string | undefined => {
    if (taskId) return taskId;
    const ids = tasksByName.get(name);
    return ids?.size === 1 ? [...ids][0] : undefined;
  };

  for (const activity of message.activities ?? []) {
    if (activity.kind !== "agent") continue;
    const name = (activity.agent || "").trim();
    if (!name || name === "NEXUS" || name === "ORCHESTRATOR") continue;
    const data = asRecord(activity.data);
    const taskId = resolveTask(name, typeof data?.task_id === "string" ? data.task_id : undefined);
    const draft = ensure(map, name, taskId);
    const activityTime = Date.parse(activity.timestamp);
    updateAgentStatus(draft, coerceStatus(activity.status), Number.isFinite(activityTime) ? activityTime : undefined);
    const objective = textField(data, ["objective", "goal", "brief"]);
    const task = textField(data, ["task", "assignment"]);
    if (objective) draft.objective = objective;
    if (task) draft.task = task;
    for (const dep of stringList(data?.depends_on ?? data?.dependsOn)) {
      if (!draft.dependsOn.includes(dep)) draft.dependsOn.push(dep);
    }
    if (!draft.sentence && activity.detail && !looksLikeTechnicalLabel(activity.detail)) {
      draft.sentence = activity.detail;
    }
  }

  for (const step of message.steps ?? []) {
    const spawned = step.verb === "agent";
    const name = (workerOf(step) || (spawned ? step.target : "") || "").trim();
    if (!name || name === "NEXUS" || name === "ORCHESTRATOR") continue;
    const taskId = resolveTask(name, step.taskId);
    const key = `${name}\u0000${taskId ?? ""}`;
    if (!spawned && !map.has(key)) continue;
    const draft = ensure(map, name, taskId);
    if (spawned) {
      const eventTime = Date.parse(step.event?.timestamp ?? "");
      updateAgentStatus(draft, step.status, Number.isFinite(eventTime) ? eventTime : step.startedAt);
    }
    if (typeof step.startedAt === "number" && Number.isFinite(step.startedAt)) {
      draft.startedAt = draft.startedAt === undefined ? step.startedAt : Math.min(draft.startedAt, step.startedAt);
      if (typeof step.durationMs === "number" && Number.isFinite(step.durationMs)) {
        const end = step.startedAt + step.durationMs;
        draft.endedAt = draft.endedAt === undefined ? end : Math.max(draft.endedAt, end);
      }
    }
    if (step.verb === "tool" && step.target) draft.tool = step.target;
    if (step.verb === "file" && step.target) {
      for (const file of step.target.split(",").map((part) => baseName(part.trim())).filter(Boolean)) {
        if (!draft.files.includes(file)) draft.files.push(file);
      }
    }
    if (step.status === "error") {
      const narration = narrateStep(step);
      if (!draft.errors.includes(narration.sentence)) draft.errors.push(narration.sentence);
    }
    if (spawned && step.status === "running") {
      const narration = narrateStep(step);
      draft.sentence = narration.technical ? "A trabalhar na tarefa atribuída." : narration.sentence;
    }
  }

  const entries: AgentRosterEntry[] = [];
  for (const draft of map.values()) {
    if (!draft.sentence) {
      if (draft.status === "running" || draft.status === "pending") {
        draft.sentence = "A trabalhar na tarefa atribuída.";
      } else if (draft.status === "error") {
        draft.sentence = draft.errors[0] || "Encontrou um erro.";
      } else if (draft.status === "paused" || draft.status === "awaiting_confirmation") {
        draft.sentence = draft.status === "awaiting_confirmation"
          ? "À espera de autorização."
          : "Em pausa.";
      } else if (draft.status === "cancelled") {
        draft.sentence = "Foi cancelado.";
      } else if (draft.status === "success") {
        draft.sentence = "Concluiu a sua parte.";
      } else {
        draft.sentence = "Sem atualização nova.";
      }
    }
    const durationMs =
      draft.startedAt !== undefined && draft.endedAt !== undefined
        ? Math.max(0, draft.endedAt - draft.startedAt)
        : undefined;
    entries.push({
      name: draft.name,
      taskId: draft.taskId,
      role: AGENT_ROLE[draft.name] || "Agente",
      status: draft.status,
      sentence: draft.sentence,
      objective: draft.objective,
      task: draft.task,
      tool: draft.tool,
      files: draft.files.slice(0, 8),
      errors: draft.errors.slice(0, 4),
      dependsOn: draft.dependsOn,
      durationMs,
    });
  }

  entries.sort((a, b) => statusRank(b.status) - statusRank(a.status) || a.name.localeCompare(b.name));
  return entries;
}

export function toolCallSentence(name: string, args: Record<string, unknown> | undefined, status: string): string {
  const path = typeof args?.path === "string" ? baseName(args.path) : "";
  const command = typeof args?.command === "string" ? shortTarget(args.command, 72) : "";
  const query = typeof args?.query === "string" ? shortTarget(args.query, 72) : "";
  if (status === "unknown") return "O resultado desta ferramenta não foi confirmado.";
  if (status === "error") {
    if (path) return `A ferramenta falhou em ${path}.`;
    return "A ferramenta falhou.";
  }
  if (status === "awaiting_confirmation") return "Esta ferramenta precisa da sua autorização.";
  if (/recall_context|read_memory|search_memory/.test(name)) {
    return status === "running" ? "Estou a consultar o contexto do projeto." : "Consultei o contexto do projeto.";
  }
  if (/write_memory|store_memory/.test(name)) {
    return status === "success" ? "A memória foi guardada." : "Estou a guardar memória.";
  }
  if (status === "running") {
    if (/^read_file|^list_dir|^get_file/.test(name) && path) return `Estou a ler ${path}.`;
    if (/write|edit|patch|create/.test(name) && path) return `Estou a alterar ${path}.`;
    if (/terminal|shell|command|execute/.test(name)) return command ? `Estou a executar ${command}.` : "Estou a executar um comando.";
    if (/web_search|search_web/.test(name)) return query ? `Estou a pesquisar ${query}.` : "Estou a pesquisar na web.";
    if (/test|pytest|vitest/.test(name)) return "Estou a executar os testes.";
    return "Estou a usar uma ferramenta.";
  }
  if (/^read_file|^list_dir/.test(name) && path) return `Analisei ${path}.`;
  if (/write|edit|patch|create/.test(name) && path) return `Alterei ${path}.`;
  if (/terminal|shell|command|execute/.test(name)) return command ? `O comando terminou: ${command}.` : "O comando terminou.";
  if (/web_search|search_web/.test(name)) return query ? `Pesquisei ${query}.` : "A pesquisa terminou.";
  if (/run_tests|pytest|vitest|jest|^test$/.test(name)) return "A ferramenta de testes terminou.";
  return "A ferramenta terminou.";
}

export type DetailLevel = "simple" | "detailed" | "technical";

const PRIMARY_RUNTIME_AGENTS = new Set(["NEXUS", "ORCHESTRATOR"]);

const PRIMARY_ACTIVITY_TITLE: Record<string, string> = {
  "concluiu a sua parte": "A resposta ficou pronta.",
  "começou a trabalhar": "Estou a trabalhar.",
  "recebeu trabalho delegado": "Recebi a tarefa.",
  "terminou com erro": "A execução terminou com erro.",
  "foi cancelado": "A execução foi cancelada.",
  "ficou bloqueado ou em pausa": "A execução está em pausa.",
  "terminou com aviso": "A execução terminou com um aviso.",
  "está pendente": "Ainda à espera.",
};

/** Routing notes the runtime attaches to status events. Not a result. */
export function isOrchestratorAside(text: string): boolean {
  const value = text.trim();
  if (!value) return false;
  if (/^[a-z]+(?:_[a-z0-9]+)+$/.test(value)) return true;
  return /agente primário|sinais de planeamento|pedido curto|orchestrat|runtime_type/i.test(value);
}

/**
 * Same activity, three depths. Simple hides routing asides and the primary
 * runtime name. Detailed keeps the aside. Technical also keeps the agent id.
 */
export function presentActivity(
  item: Pick<ActivityItem, "title" | "detail" | "agent" | "kind">,
  level: DetailLevel,
): { title: string; detail?: string; showAgent: boolean } {
  const agent = (item.agent ?? "").trim();
  const primary = PRIMARY_RUNTIME_AGENTS.has(agent);
  let title = item.title;
  if (level !== "technical" && primary && title.startsWith(`${agent} `)) {
    const rest = title.slice(agent.length).trim();
    title = PRIMARY_ACTIVITY_TITLE[rest] ?? `${rest.charAt(0).toUpperCase()}${rest.slice(1)}`;
  }
  const detail = item.detail && item.detail !== title ? item.detail : undefined;
  const hideDetail = level === "simple" && Boolean(detail && isOrchestratorAside(detail));
  return {
    title,
    detail: hideDetail ? undefined : detail,
    showAgent: Boolean(agent) && (level === "technical" || !primary),
  };
}

export type ToolPresentationKind =
  | "file-read"
  | "code-change"
  | "terminal"
  | "web-search"
  | "tests"
  | "browser"
  | "memory"
  | "generic";

/** Which renderer a tool name belongs to. Order is most specific first. */
export function toolPresentationKind(name: string): ToolPresentationKind {
  const n = (name ?? "").toLowerCase();
  if (/playwright|browser_|browse_page|^browser$/.test(n)) return "browser";
  if (/web_search|search_web|fetch_url|search_github|open_url/.test(n)) return "web-search";
  if (/run_tests|run_test|pytest|vitest|jest|typecheck|^test$/.test(n)) return "tests";
  if (/execute_terminal|execute_code|run_command|powershell|^bash$|^shell$/.test(n)) return "terminal";
  if (/write_file|edit_file|apply_patch|create_file|patch_file|str_replace|insert_code|replace_in_file/.test(n)) {
    return "code-change";
  }
  if (/read_file|list_dir|get_file_tree|open_file|view_file/.test(n)) return "file-read";
  if (/memory|recall_context|remember/.test(n)) return "memory";
  return "generic";
}

export function dedupeNarration(lines: Narration[]): Narration[] {
  const out: Narration[] = [];
  for (const line of lines) {
    const previous = out[out.length - 1];
    if (previous && previous.phase === line.phase && previous.sentence === line.sentence) continue;
    out.push(line);
  }
  return out;
}

/** Drop consecutive status rows that say the same thing. Other steps stay intact. */
export function collapseRepeatedStatus(steps: RunStep[]): RunStep[] {
  const out: RunStep[] = [];
  for (const step of steps) {
    const previous = out[out.length - 1];
    if (
      previous &&
      step.verb === "status" &&
      previous.verb === "status" &&
      narrateStep(step).sentence === narrateStep(previous).sentence
    ) {
      out[out.length - 1] = {
        ...previous,
        status: step.status,
        repeatCount: (previous.repeatCount ?? 1) + (step.repeatCount ?? 1),
      };
      continue;
    }
    out.push(step);
  }
  return out;
}

export function isComplexWork(message: Pick<ChatMessage, "steps" | "toolCalls" | "activities"> | null | undefined): boolean {
  if (!message) return false;
  if ((message.toolCalls ?? []).length > 0) return true;
  if ((message.steps ?? []).some((step) =>
    step.verb === "tool" || step.verb === "file" || step.verb === "command" || step.verb === "test",
  )) return true;
  if (buildAgentRoster(message).length > 0) return true;
  return (message.activities ?? []).some((activity) =>
    activity.kind === "plan" || activity.kind === "verification" || activity.kind === "task",
  );
}

const SUCCESS_CLAIM = /passaram|validada|foi guardada|conclu[ií]da com sucesso/i;

/**
 * One sentence for the live region. A success claim is returned only when a
 * step or tool already reported that outcome.
 */
export function narrateLive(
  message: Pick<ChatMessage, "steps" | "toolCalls" | "activities"> | null | undefined,
  streaming = false,
): Narration {
  const steps = message?.steps ?? [];
  const calls = message?.toolCalls ?? [];
  const idle = (sentence: string, phase: WorkPhase): Narration => ({
    sentence,
    phase,
    phaseLabel: PHASE_LABEL[phase],
    technical: false,
    raw: "",
  });

  const running = [...steps].reverse().find((step) =>
    step.status === "running" || step.status === "paused" || step.status === "awaiting_confirmation",
  );
  if (running) {
    const narration = narrateStep(running);
    const corrected = steps.some((step) =>
      step.status === "success" && /write|edit|patch|changed|create/.test(`${step.kind} ${step.verb}`),
    );
    if (narration.phase === "testing" && running.status === "running" && corrected) {
      return { ...narration, sentence: "Terminei a correção e vou executar os testes.", technical: true };
    }
    if (SUCCESS_CLAIM.test(narration.sentence) && running.status !== "success") {
      return { ...narration, sentence: "Estou a trabalhar nesta tarefa." };
    }
    return narration;
  }

  const runningCall = [...calls].reverse().find((call) =>
    call.status === "running" || call.status === "awaiting_confirmation",
  );
  if (runningCall) {
    return idle(toolCallSentence(runningCall.name, runningCall.args, runningCall.status), "tooling");
  }

  if (!streaming) {
    const failedTest = steps.some((step) => workPhase(step) === "testing" && step.status === "error")
      || calls.some((call) => toolPresentationKind(call.name) === "tests" && call.status === "error");
    if (failedTest) return idle("Os testes falharam.", "failed");
    const passedTest = steps.some((step) => {
      if (workPhase(step) !== "testing" || step.status !== "success") return false;
      const detail = asRecord(step.detail);
      return detail?.ok === true;
    });
    if (passedTest) return idle("Os testes passaram.", "done");
  }

  const latest = [...steps].reverse().find((step) => step.verb !== "thinking");
  if (latest) return narrateStep(latest);
  if (streaming) return idle("A iniciar execução…", "analyzing");
  return idle("Analisei o pedido.", "analyzing");
}

export interface RunDelivery {
  files: string[];
  /** Null when the run never reported a verification. */
  verification: "passed" | "failed" | "not_run" | null;
  /** Agents the run actually started, excluding the coordinator. */
  agents: string[];
}

/** What a finished turn can honestly say about files, tests and agents. */
export function summarizeRunDelivery(
  message: Pick<ChatMessage, "activities" | "metadata"> | null | undefined,
): RunDelivery | null {
  if (!message) return null;
  const rawFiles = message.metadata?.changedFiles;
  const files = Array.isArray(rawFiles)
    ? rawFiles.filter((path): path is string => typeof path === "string" && path.trim().length > 0)
    : [];
  const verifications = (message.activities ?? []).filter((item) => item.kind === "verification");
  const last = verifications[verifications.length - 1];
  const verification = !last
    ? null
    : last.status === "success"
      ? "passed"
      : last.status === "error"
        ? "failed"
        : last.status === "pending"
          ? "not_run"
          : null;
  const agents = [...new Set(
    (message.activities ?? [])
      .filter((item) => item.kind === "agent" && item.agent && item.agent !== "NEXUS" && item.agent !== "ORCHESTRATOR")
      .map((item) => item.agent as string),
  )];
  if (files.length === 0 && verification === null && agents.length === 0) return null;
  return { files, verification, agents };
}

export function deliverySentence(delivery: RunDelivery): string {
  const parts: string[] = [];
  if (delivery.files.length === 1) parts.push(`Alterei ${delivery.files[0].split(/[/\\]/).pop()}.`);
  else if (delivery.files.length > 1) parts.push(`Alterei ${delivery.files.length} ficheiros.`);
  if (delivery.verification === "passed") parts.push("A verificação foi aprovada.");
  else if (delivery.verification === "failed") parts.push("A verificação falhou.");
  else if (delivery.verification === "not_run") parts.push("A verificação não chegou a correr.");
  if (delivery.agents.length === 1) parts.push(`${delivery.agents[0]} trabalhou nesta missão.`);
  else if (delivery.agents.length > 1) parts.push(`${delivery.agents.join(", ")} trabalharam nesta missão.`);
  return parts.join(" ");
}

export function memoryNotice(
  message: Pick<ChatMessage, "toolCalls"> | null | undefined,
): { sentence: string; sources: string[] } | null {
  const calls = (message?.toolCalls ?? []).filter((call) => toolPresentationKind(call.name) === "memory");
  if (calls.length === 0) return null;
  const sources = [...new Set(calls.map((call) =>
    /recall_context/.test(call.name) ? "contexto da conversa" : "memória persistente",
  ))];
  const saved = calls.some((call) => /write_memory|store_memory|remember/.test(call.name) && call.status === "success");
  const writing = calls.some((call) => /write_memory|store_memory|remember/.test(call.name) && call.status === "running");
  const failed = calls.every((call) => call.status === "error");
  if (failed) return { sentence: "Não consegui consultar o contexto do projeto.", sources };
  if (saved) return { sentence: "A memória foi guardada.", sources };
  if (writing) return { sentence: "Estou a guardar memória.", sources };
  if (calls.some((call) => call.status === "running")) {
    return { sentence: "Estou a consultar o contexto do projeto.", sources };
  }
  if (calls.some((call) => call.status === "success")) {
    return { sentence: "Consultei o contexto do projeto.", sources };
  }
  return null;
}

const SECRET_KEY = /token|secret|password|api[_-]?key|authorization|credential/i;

export function redactPayload(value: unknown, depth = 0): unknown {
  if (depth > 6) return "…";
  if (Array.isArray(value)) return value.slice(0, 40).map((item) => redactPayload(item, depth + 1));
  const record = asRecord(value);
  if (!record) return value;
  const out: Record<string, unknown> = {};
  for (const [key, nested] of Object.entries(record)) {
    out[key] = SECRET_KEY.test(key) ? "«redigido»" : redactPayload(nested, depth + 1);
  }
  return out;
}
