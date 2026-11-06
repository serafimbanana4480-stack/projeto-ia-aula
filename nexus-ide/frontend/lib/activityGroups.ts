import type { RunStep } from "./types";
import { verificationWasSkipped } from "./activityLine";

/**
 * Activity grouping — the synthesis layer between raw run steps and the
 * human question "what did the agent actually do?".
 *
 * WHY THIS EXISTS
 * ---------------
 * A faithful timeline renders one row per runtime step. When the agent reads
 * 24 files, that is 24 identical rows — technically complete, useless to read.
 * The fold below groups CONTIGUOUS steps into families of work so the timeline
 * can show one honest line ("Explorou 24 ficheiros · 18s") that expands into
 * the real rows.
 *
 * RULES (kept deliberately strict so the summary can never lie):
 * - Grouping is a presentation fold only: every step keeps its `seq`, `kind`
 *   and runtime identity, so the expanded view is the exact same data.
 * - A group of 1 or 2 steps is NOT collapsed (see `COLLAPSE_THRESHOLD`): two
 *   actions are already readable as two rows, and hiding them saves nothing.
 * - `agent` steps are never grouped: each subagent start/finish is its own
 *   fact in the run. Same for `status`/`thinking`/`message` steps, which are
 *   the run's narration, not repeated work.
 * - Counts in a group label are real counts of real steps. No estimates.
 */

export type ActivityFamily =
  | "explore"
  | "edit"
  | "command"
  | "search"
  | "verify"
  | "web"
  | "agent"
  | "memory"
  | "skill"
  | "plan"
  | "think"
  | "status";

/** Families that describe repeated mechanical work and therefore group. */
const GROUPABLE: ReadonlySet<ActivityFamily> = new Set<ActivityFamily>([
  "explore",
  "edit",
  "command",
  "search",
  "verify",
  "web",
  "memory",
  "skill",
  "plan",
]);

/** Fewer than this many contiguous steps of one family → keep them as rows. */
export const COLLAPSE_THRESHOLD = 3;

export interface ActivityGroup {
  family: ActivityFamily;
  /** The steps of this group, in runtime (`seq`) order. */
  steps: RunStep[];
  /** Editorial one-liner: "Explorou 24 ficheiros". */
  label: string;
  /** Past-tense label used when every step finished: "Explorou 24 ficheiros". */
  doneLabel: string;
  /** Present-tense label used while at least one step is running. */
  runningLabel: string;
  /** Unique targets (paths, commands, queries) — powers the group subtitle. */
  targets: string[];
  running: boolean;
  errors: number;
  /** Span between the first step's start and the last step's end, when known. */
  durationMs?: number;
  /** Aggregate status for the group as a whole. */
  status: RunStep["status"];
}

/** What the renderer emits: either ungrouped steps or one collapsible group. */
export type ActivityBlock =
  | { type: "steps"; steps: RunStep[] }
  | { type: "task"; taskId: string; steps: RunStep[] }
  | { type: "group"; group: ActivityGroup };

const PARENT_AGENTS = new Set(["NEXUS", "ORCHESTRATOR", "IA", "Agente", ""]);

/** The subagent this step belongs to. The parent runtime is not a worker. */
export function workerOf(step: RunStep): string {
  const detail =
    step.detail && typeof step.detail === "object" && !Array.isArray(step.detail)
      ? (step.detail as Record<string, unknown>)
      : null;
  const named = typeof detail?.name === "string" ? detail.name.trim() : "";
  const agent = (step.agent || "").trim();
  // The scheduler name can include a task suffix ("CODER:edit"). Its role
  // is the event's actor; taskId is the unique worker identity.
  if (agent && named.startsWith(`${agent}:`)) return agent;
  if (named && !PARENT_AGENTS.has(named)) return named;
  if (agent && !PARENT_AGENTS.has(agent)) return agent;
  const target = (step.target || "").trim();
  if (/^[A-Z][A-Z0-9_]{1,40}$/.test(target) && !PARENT_AGENTS.has(target)) return target;
  const prefix = (step.label || "").match(/^([A-Z][A-Z0-9_]{1,40})\b/);
  if (prefix && !PARENT_AGENTS.has(prefix[1])) return prefix[1];
  return "";
}

/**
 * A delegated task often arrives as "ARCHITECT começou" and then a task_id
 * group whose steps still carry the parent agent. Fold the start line into
 * that group's card so one subagent is one row.
 */
export function foldSubagentCards(blocks: ActivityBlock[]): ActivityBlock[] {
  const out: ActivityBlock[] = [];
  for (const block of blocks) {
    if (block.type !== "task") {
      out.push(block);
      continue;
    }
    const worker = block.steps.map(workerOf).find(Boolean) || "";
    const previous = out[out.length - 1];
    if (!worker || previous?.type !== "steps") {
      out.push(block);
      continue;
    }
    const keep: RunStep[] = [];
    const absorbed: RunStep[] = [];
    for (const step of previous.steps) {
      if (step.verb === "agent" && workerOf(step) === worker) absorbed.push(step);
      else keep.push(step);
    }
    if (absorbed.length === 0) {
      out.push(block);
      continue;
    }
    if (keep.length > 0) out[out.length - 1] = { type: "steps", steps: keep };
    else out.pop();
    out.push({ type: "task", taskId: block.taskId, steps: [...absorbed, ...block.steps] });
  }
  return out;
}

const EXPLORE_TOOLS =
  /^(read_file|read_file_absolute|list_dir|list_dir_absolute|get_file_tree|file_tree|read_directory|open_file|cat|view_file)/;
const SEARCH_TOOLS = /^(search_codebase|grep|glob|search_files|search_project|codebase_search|ripgrep|find|search_repo)/;
const EDIT_TOOLS =
  /^(write_file|write_file_absolute|edit_file|apply_patch|create_file|patch_file|update_file|delete_file|move_file|rename_file|scaffold_project|insert_code|replace_in_file|str_replace)/;
const COMMAND_TOOLS = /^(execute_terminal|execute_code|run_command|shell|terminal|bash|exec|run_script|powershell|run)/;
const VERIFY_TOOLS = /^(run_tests|run_test|pytest|vitest|jest|test|lint|build|typecheck|check|verify|verify_build|audit)/;
const WEB_TOOLS = /^(web_search|search_web|fetch_url|search_github|browser|open_url|http_get|download)/;
const AGENT_TOOLS =
  /^(spawn_agent|spawn_agents|spawn_task|consult_agent|check_agent|check_agents|collect_agent|collect_agents|message_agent|check_tasks|delegate)/;
const MEMORY_TOOLS = /^(recall_context|write_memory|read_memory|store_memory|memory|remember|search_memory)/;
const SKILL_TOOLS = /^(list_skills|load_skill|build_skill|update_skill|skill)/;
const PLAN_TOOLS = /^(todo_write|todo_list|create_plan|get_plan|update_plan|task_write|task_update)/;

function firstMatch(name: string, patterns: RegExp[]): boolean {
  return patterns.some((pattern) => pattern.test(name));
}

/**
 * The family a step belongs to.
 *
 * Precedence matters: a step whose `kind` is explicit (`file_read`,
 * `command_completed`, `subagent_started`…) is the runtime's own word about
 * what happened, so it wins over a guess from the tool name. The tool-name
 * patterns only classify what the runtime left unlabelled.
 */
export function familyOfStep(step: RunStep): ActivityFamily {
  const verb = step.verb;
  if (verb === "agent") return "agent";
  if (verb === "thinking") return "think";
  if (verb === "message") return "think";
  if (verb === "test") return "verify";
  if (verb === "command") return "command";

  const kind = (step.kind ?? "").toLowerCase();
  if (kind.startsWith("subagent") || kind.startsWith("agent")) return "agent";
  if (kind.startsWith("file_read") || kind.startsWith("file_list") || kind.startsWith("file_inspect")) return "explore";
  if (kind.startsWith("file_write") || kind.startsWith("file_changed") || kind.startsWith("file_edit") || kind.startsWith("file_create") || kind.startsWith("file_patch")) return "edit";
  if (kind.startsWith("command")) return "command";
  if (kind.startsWith("test")) return "verify";
  if (kind.startsWith("search")) return "search";
  if (kind.startsWith("web")) return "web";

  const name = (step.target ?? "").toLowerCase();
  if (!name) return "status";
  if (firstMatch(name, [EXPLORE_TOOLS])) return "explore";
  if (firstMatch(name, [SEARCH_TOOLS])) return "search";
  if (firstMatch(name, [EDIT_TOOLS])) return "edit";
  if (firstMatch(name, [VERIFY_TOOLS])) return "verify";
  if (firstMatch(name, [COMMAND_TOOLS])) return "command";
  if (firstMatch(name, [WEB_TOOLS])) return "web";
  if (firstMatch(name, [AGENT_TOOLS])) return "agent";
  if (firstMatch(name, [MEMORY_TOOLS])) return "memory";
  if (firstMatch(name, [SKILL_TOOLS])) return "skill";
  if (firstMatch(name, [PLAN_TOOLS])) return "plan";
  if (verb === "file") return "explore";
  return "status";
}

const NOUN: Record<ActivityFamily, [string, string]> = {
  // [singular, plural]
  explore: ["ação de exploração", "ações de exploração"],
  edit: ["ação de alteração", "ações de alteração"],
  command: ["comando", "comandos"],
  search: ["pesquisa", "pesquisas"],
  verify: ["verificação", "verificações"],
  web: ["pesquisa web", "pesquisas web"],
  agent: ["agente", "agentes"],
  memory: ["consulta à memória", "consultas à memória"],
  skill: ["skill", "skills"],
  plan: ["atualização do plano", "atualizações do plano"],
  think: ["bloco de raciocínio", "blocos de raciocínio"],
  status: ["atualização", "atualizações"],
};

const VERB: Record<ActivityFamily, [string, string]> = {
  // [running, done]
  explore: ["A explorar", "Explorou"],
  edit: ["A alterar", "Alterou"],
  command: ["A executar", "Executou"],
  search: ["A pesquisar", "Pesquisou"],
  verify: ["A verificar", "Verificou"],
  web: ["A pesquisar na web", "Pesquisou na web"],
  agent: ["A coordenar agentes", "Coordenou agentes"],
  memory: ["A consultar memória", "Consultou memória"],
  skill: ["A usar skills", "Usou skills"],
  plan: ["A atualizar o plano", "Atualizou o plano"],
  think: ["A raciocinar", "Raciocinou"],
  status: ["A avançar", "Avançou"],
};

function groupLabel(family: ActivityFamily, count: number, running: boolean): string {
  const [runningVerb, doneVerb] = VERB[family];
  const [singular, plural] = NOUN[family];
  if (family === "explore" || family === "edit") {
    const title = family === "explore" ? (running ? "A explorar" : "Exploração") : (running ? "A alterar" : "Alterações");
    return `${title} · ${count} ${count === 1 ? singular : plural}`;
  }
  const verb = running ? runningVerb : doneVerb;
  return count === 1 ? `${verb} 1 ${singular}` : `${verb} ${count} ${plural}`;
}

function stepStatusOf(steps: RunStep[]): RunStep["status"] {
  if (steps.some((step) => step.status === "error")) return "error";
  if (steps.some((step) => step.status === "awaiting_confirmation")) return "awaiting_confirmation";
  if (steps.some((step) => step.status === "running")) return "running";
  if (steps.some((step) => step.status === "paused")) return "paused";
  if (steps.some((step) => step.status === "warning")) return "warning";
  if (steps.every((step) => step.status === "cancelled")) return "cancelled";
  if (steps.every((step) => step.status === "success")) return "success";
  return "pending";
}

/** Span between the earliest step start and the latest step end, when known. */
function spanDurationMs(steps: RunStep[]): number | undefined {
  let start: number | undefined;
  let end: number | undefined;
  for (const step of steps) {
    if (typeof step.startedAt === "number" && Number.isFinite(step.startedAt)) {
      if (start === undefined || step.startedAt < start) start = step.startedAt;
      const stepEnd =
        typeof step.durationMs === "number" && Number.isFinite(step.durationMs)
          ? step.startedAt + step.durationMs
          : step.startedAt;
      if (end === undefined || stepEnd > end) end = stepEnd;
    }
  }
  if (start === undefined || end === undefined) return undefined;
  const span = end - start;
  return Number.isFinite(span) && span >= 0 ? span : undefined;
}

/**
 * Build a group from consecutive steps of one family.
 * Exported for tests and for the renderer's summary chips.
 */
export function makeActivityGroup(family: ActivityFamily, steps: RunStep[]): ActivityGroup {
  const running = steps.some((step) => step.status === "running");
  const status = stepStatusOf(steps);
  const targets = Array.from(
    new Set(
      steps
        .map((step) => (step.target ?? "").trim())
        .filter((value) => value.length > 0),
    ),
  ).slice(0, 8);
  return {
    family,
    steps,
    label: status === "running" || status === "success"
      ? groupLabel(family, steps.length, running)
      : `${steps.length} ${steps.length === 1 ? NOUN[family][0] : NOUN[family][1]}`,
    doneLabel: groupLabel(family, steps.length, false),
    runningLabel: groupLabel(family, steps.length, true),
    targets,
    running,
    errors: steps.filter((step) => step.status === "error").length,
    durationMs: spanDurationMs(steps),
    status,
  };
}

/**
 * Group CONTIGUOUS runs of steps of the same family.
 *
 * Contiguity is the point: read → edit → read becomes two groups, because the
 * agent really did explore, then edit, then explore again. Merging them into
 * one "24 files" group would destroy the shape of the work.
 */
export function groupByFamily(steps: RunStep[]): Array<{ family: ActivityFamily; steps: RunStep[] }> {
  const out: Array<{ family: ActivityFamily; steps: RunStep[] }> = [];
  for (const step of steps) {
    const family = familyOfStep(step);
    const last = out[out.length - 1];
    if (last && last.family === family) last.steps.push(step);
    else out.push({ family, steps: [step] });
  }
  return out;
}

/** Aggregate counts for the whole run — powers the timeline header chips. */
export interface ActivityTally {
  filesExplored: number;
  filesEdited: number;
  commands: number;
  searches: number;
  verifications: number;
  webRequests: number;
  errors: number;
}

export function tallyActivity(steps: RunStep[]): ActivityTally {
  const tally: ActivityTally = {
    filesExplored: 0,
    filesEdited: 0,
    commands: 0,
    searches: 0,
    verifications: 0,
    webRequests: 0,
    errors: 0,
  };
  for (const step of steps) {
    if (step.status === "error") tally.errors += 1;
    switch (familyOfStep(step)) {
      case "explore":
        tally.filesExplored += 1;
        break;
      case "edit":
        tally.filesEdited += 1;
        break;
      case "command":
        tally.commands += 1;
        break;
      case "search":
        tally.searches += 1;
        break;
      case "verify":
        if (!verificationWasSkipped(step)) tally.verifications += 1;
        break;
      case "web":
        tally.webRequests += 1;
        break;
      default:
        break;
    }
  }
  return tally;
}

/**
 * Full fold: steps (already `seq`-ordered) → renderable blocks.
 *
 * Two grouping passes, in order:
 *  1. contiguous `taskId` runs (the runtime's own grouping of one delegated
 *     task) — preserved exactly as before;
 *  2. within the ungrouped remainder, contiguous family runs.
 *
 * A family run below `COLLAPSE_THRESHOLD` stays as individual steps.
 */
export function toActivityBlocks(steps: RunStep[]): ActivityBlock[] {
  const ordered = [...steps].sort((a, b) => a.seq - b.seq);
  const blocks: ActivityBlock[] = [];
  let buffer: RunStep[] = [];

  const flush = () => {
    if (buffer.length === 0) return;
    for (const run of groupByFamily(buffer)) {
      if (run.steps.length >= COLLAPSE_THRESHOLD && GROUPABLE.has(run.family)) {
        blocks.push({ type: "group", group: makeActivityGroup(run.family, run.steps) });
      } else {
        blocks.push({ type: "steps", steps: run.steps });
      }
    }
    buffer = [];
  };

  let index = 0;
  while (index < ordered.length) {
    const taskId = ordered[index].taskId?.trim();
    if (!taskId) {
      buffer.push(ordered[index]);
      index += 1;
      continue;
    }
    // A task run: collect the contiguous steps carrying the same id.
    flush();
    const taskSteps: RunStep[] = [];
    while (index < ordered.length && ordered[index].taskId?.trim() === taskId) {
      taskSteps.push(ordered[index]);
      index += 1;
    }
    blocks.push({ type: "task", taskId, steps: taskSteps });
  }
  flush();
  return blocks;
}
