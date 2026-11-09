"use client";

/**
 * AgentTranscript — the chronological, chat-first rendering of one run.
 *
 * Built only from the run's real `(run_id, seq)` frames (`message.events`):
 *   - assistant text (streamed Markdown) can appear before, between and after tools
 *   - real reasoning only (visibility "full"); "label" placeholders are never shown
 *   - one compact, expandable row per tool call, paired with its result by `call_id`
 *   - subagents as cards that open their own conversation in a resizable side panel
 *
 * No synthetic progress: if the backend did not emit it, nothing is drawn.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  Bot,
  BookOpen,
  Check,
  ChevronRight,
  FilePen,
  FileText,
  FlaskConical,
  FolderTree,
  Globe,
  ListTodo,
  Loader2,
  Maximize2,
  Minimize2,
  Search,
  Sparkles,
  Terminal,
  Wrench,
  X,
} from "lucide-react";
import type { StreamEvent } from "../../lib/types";
import { confirmTool, getSubagentActivity, type SessionTodo } from "../../lib/api";
import TodoTree from "./TodoTree";

// ─── model ────────────────────────────────────────────────────────────────

type ToolStatus = "running" | "success" | "error" | "approval" | "unknown";
type SubagentStatus = "running" | "success" | "error" | "cancelled" | "blocked" | "unknown";
type RunOutcome = "completed" | "failed" | "cancelled" | "interrupted" | "unknown";

interface DiffFile {
  path: string;
  diff: string;
  truncated?: boolean;
  added?: number;
  removed?: number;
  created?: boolean;
  deleted?: boolean;
}

interface DiffPayload {
  files: DiffFile[];
  added: number;
  removed: number;
}

interface ToolItem {
  kind: "tool";
  key: string;
  callId?: string;
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  error?: string;
  status: ToolStatus;
  startedAt: number;
  durationMs?: number;
  cwd?: string;
  stdout?: string;
  stderr?: string;
  diff?: DiffPayload;
  confirmationId?: string;
  confirmationDecided?: boolean;
}

interface TextItem {
  kind: "text";
  key: string;
  text: string;
}

interface ThinkingItem {
  kind: "thinking";
  key: string;
  text: string;
  startedAt: number;
  endedAt?: number;
}

interface NoteItem {
  kind: "note";
  key: string;
  text: string;
  tone: "info" | "warning";
}

interface SubagentItem {
  kind: "subagent";
  key: string;
  taskId: string;
  name: string;
  objective: string;
  status: SubagentStatus;
  result?: string;
  error?: string;
  startedAt: number;
  endedAt?: number;
  /** Durable child session created by the backend for this delegation. */
  childSessionId?: string;
}

type Item = TextItem | ThinkingItem | ToolItem | NoteItem | SubagentItem;

interface Transcript {
  main: Item[];
  subagents: SubagentItem[];
  children: Map<string, Item[]>;
  done: boolean;
  outcome: RunOutcome;
  runMs?: number;
}

const COMMAND_TOOLS = new Set(["run_shell", "execute_code", "run_command", "terminal"]);
const TEST_TOOLS = new Set(["run_tests", "run_lint", "type_check"]);
const READ_TOOLS = new Set(["read_file", "read_multiple_files", "get_file_info", "read_file_absolute"]);
const LIST_TOOLS = new Set(["list_dir", "list_dir_absolute", "list_directory", "tree", "glob"]);
const SEARCH_TOOLS = new Set(["search_codebase", "search_in_files", "search_symbols", "grep", "find_references"]);
const WRITE_TOOLS = new Set([
  "write_file",
  "write_file_absolute",
  "append_file",
  "edit_file",
  "apply_patch",
  "delete_file",
  "scaffold_project",
  "format_code",
]);
const WEB_TOOLS = new Set(["web_search", "search_web_v2", "web_search_v2", "deep_research", "search_docs", "search_github", "fetch_url", "fetch_content_v2", "browse", "browser_navigate", "http_request"]);
const SKILL_TOOLS = new Set(["list_skills", "load_skill", "build_skill", "update_skill"]);
const DELEGATE_TOOLS = new Set(["spawn_task", "delegate", "spawn_subagent"]);
const PLAN_TOOLS = new Set(["todo_write", "todo_list", "sequential_thinking"]);

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function str(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function timeOf(event: StreamEvent, fallback: number): number {
  const parsed = Date.parse(event.timestamp || "");
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** Peel `{"result": …}` envelopes and JSON-encoded strings off a tool result. */
export function unwrapResult(value: unknown): unknown {
  let current = value;
  for (let depth = 0; depth < 4; depth += 1) {
    if (typeof current === "string") {
      const trimmed = current.trim();
      if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
        try {
          current = JSON.parse(trimmed);
          continue;
        } catch {
          return current;
        }
      }
      return current;
    }
    const record = asRecord(current);
    if (record && "result" in record && !("stdout" in record) && Object.keys(record).length <= 3) {
      current = record.result;
      continue;
    }
    return current;
  }
  return current;
}

function resultFailure(value: unknown): string {
  // Inspect each envelope before unwrapping it: an outer failure may contain
  // a result, and results from older transports may themselves be JSON strings.
  let current = value;
  for (let depth = 0; depth < 5; depth += 1) {
    if (typeof current === "string") {
      try { current = JSON.parse(current); } catch { return ""; }
    }
    const record = asRecord(current);
    if (!record) return "";
    if (record.ok === false || record.success === false) return str(record.error) || str(record.message) || "falhou";
    if (["denied", "failed", "error"].includes(str(record.status).toLowerCase())) {
      return str(record.reason) || str(record.error) || "não foi executado";
    }
    if (typeof record.error === "string" && record.error.trim() && !("stdout" in record)) return record.error;
    if (!("result" in record)) return "";
    current = record.result;
  }
  return "";
}

function exitCodeOf(value: unknown): number | null {
  const record = asRecord(unwrapResult(value));
  if (!record) return null;
  const raw = record.exit_code ?? record.exitCode ?? record.returncode ?? record.code;
  return typeof raw === "number" ? raw : null;
}

function isDiffPayload(value: unknown): value is DiffPayload {
  const record = asRecord(value);
  return Boolean(record && Array.isArray(record.files));
}

function isSubagentStart(event: StreamEvent): boolean {
  return event.type === "agent_started" && event.data?.kind === "subagent_started" && Boolean(event.task_id);
}

/** Pure: frames → the main conversation plus one conversation per subagent. */
export function buildTranscript(events: StreamEvent[]): Transcript {
  const subagentIds = new Set(events.filter(isSubagentStart).map((event) => event.task_id as string));
  const main: Item[] = [];
  const children = new Map<string, Item[]>();
  const subagents: SubagentItem[] = [];
  const subagentByTask = new Map<string, SubagentItem>();
  const openTools = new Map<string, ToolItem>();
  let done = false;
  let outcome: RunOutcome = "unknown";
  let runMs: number | undefined;
  let lastStatusNote = "";
  let fallbackClock = 0;

  const listFor = (event: StreamEvent): Item[] => {
    const taskId = event.task_id;
    if (taskId && subagentIds.has(taskId) && !isSubagentStart(event)) {
      let list = children.get(taskId);
      if (!list) {
        list = [];
        children.set(taskId, list);
      }
      return list;
    }
    return main;
  };

  const closeThinking = (list: Item[], at: number) => {
    const last = list[list.length - 1];
    if (last && last.kind === "thinking" && last.endedAt === undefined) last.endedAt = at;
  };

  const findOpenTool = (list: Item[], event: StreamEvent): ToolItem | undefined => {
    const callId = str(event.data?.call_id);
    if (callId) return openTools.get(`${event.task_id || ""}\0${callId}`);
    const name = event.tool_name || "";
    const candidates = list.filter(
      (item): item is ToolItem =>
        item.kind === "tool" && (item.status === "running" || item.status === "approval") && item.name === name && !item.callId,
    );
    // Older events have no identity. Pair only when there is no ambiguity.
    return candidates.length === 1 ? candidates[0] : undefined;
  };

  events.forEach((event, index) => {
    fallbackClock += 1;
    const at = timeOf(event, fallbackClock);
    const list = listFor(event);
    const key = event.event_id || `${event.run_id ?? "run"}:${event.seq ?? index}:${index}`;

    switch (event.type) {
      case "token": {
        const text = event.content ?? "";
        if (!text || text.startsWith("<event>")) return;
        closeThinking(list, at);
        const last = list[list.length - 1];
        if (last && last.kind === "text") last.text += text;
        else list.push({ kind: "text", key, text });
        return;
      }
      case "thinking": {
        if (event.data?.visibility !== "full") return;
        const text = event.content ?? "";
        if (!text) return;
        const last = list[list.length - 1];
        if (last && last.kind === "thinking" && last.endedAt === undefined) last.text += text;
        else list.push({ kind: "thinking", key, text, startedAt: at });
        return;
      }
      case "tool_call": {
        const name = event.tool_name || "tool";
        closeThinking(list, at);
        const callId = str(event.data?.call_id) || undefined;
        const item: ToolItem = {
          kind: "tool",
          key,
          callId,
          name,
          args: event.tool_args || {},
          status: "running",
          startedAt: at,
        };
        if (callId) openTools.set(`${event.task_id || ""}\0${callId}`, item);
        list.push(item);
        return;
      }
      case "tool_confirmation": {
        const open = findOpenTool(list, event);
        if (open) {
          open.status = "approval";
          open.confirmationId = str(event.data?.confirmation_id) || undefined;
        }
        else list.push({ kind: "note", key, text: `Aguarda aprovação: ${event.tool_name || "ferramenta"}`, tone: "warning" });
        return;
      }
      case "tool_result":
      case "tool_error": {
        closeThinking(list, at);
        let item = findOpenTool(list, event);
        const unmatched = !item;
        if (!item) {
          item = {
            kind: "tool",
            key,
            callId: str(event.data?.call_id) || undefined,
            name: event.tool_name || "tool",
            args: event.tool_args || {},
            status: "running",
            startedAt: at,
          };
          list.push(item);
        }
        if (item.callId) openTools.delete(`${event.task_id || ""}\0${item.callId}`);
        const failure = event.type === "tool_error" ? event.tool_error || "falhou" : resultFailure(event.tool_result);
        const exitCode = exitCodeOf(event.tool_result);
        item.result = event.tool_result;
        item.error = failure || (unmatched ? "Resultado sem chamada associada." : undefined);
        item.status = failure || (exitCode !== null && exitCode !== 0) ? "error" : unmatched ? "unknown" : "success";
        const duration = Number(event.data?.duration_ms);
        item.durationMs = Number.isFinite(duration) && duration >= 0 ? duration : Math.max(0, at - item.startedAt);
        if (isDiffPayload(event.data?.diff)) item.diff = event.data?.diff as DiffPayload;
        return;
      }
      case "agent_started": {
        if (!isSubagentStart(event)) return;
        closeThinking(main, at);
        const taskId = event.task_id as string;
        const data = event.data || {};
        const sub: SubagentItem = {
          kind: "subagent",
          key,
          taskId,
          // Scheduler names arrive as "ROLE:objective"; show "ROLE · objective".
          name: (str(data.name) || str(event.agent) || "subagente").replace(/^([A-Z][A-Z0-9_]{1,32})\s*:\s*(?=\S)/, "$1 · "),
          objective: str(data.objective) || event.content || "",
          status: "running",
          startedAt: at,
        };
        subagentByTask.set(taskId, sub);
        subagents.push(sub);
        main.push(sub);
        return;
      }
      case "agent_finished": {
        const sub = event.task_id ? subagentByTask.get(event.task_id) : undefined;
        if (!sub) return;
        const data = event.data || {};
        const state = str(data.status).toLowerCase();
        sub.status = state === "cancelled" || state === "canceled"
          ? "cancelled"
          : state === "blocked"
            ? "blocked"
            : state === "failed" || state === "error" || Boolean(str(data.error))
              ? "error"
              : state === "completed" || state === "success" || state === "succeeded"
                ? "success"
                : "unknown";
        sub.error = str(data.error) || undefined;
        sub.result = str(data.result) || event.content || undefined;
        sub.endedAt = at;
        closeThinking(children.get(sub.taskId) ?? [], at);
        return;
      }
      case "progress": {
        const data = event.data || {};
        const kind = str(data.kind) || str(data.runtime_type);
        if (str(data.phase) === "child_session_created") {
          const owner = subagentByTask.get(event.task_id || str(data.task_id));
          if (owner && str(data.child_session_id)) owner.childSessionId = str(data.child_session_id);
          return;
        }
        if (kind === "command_started" || kind === "command_output") {
          const open = findOpenTool(list, event);
          if (!open) return;
          if (kind === "command_started") open.cwd = str(data.cwd) || undefined;
          else if (data.stream === "stdout" || data.stream === "stderr") {
            const stream = data.stream;
            // The backend also limits the emitted preview; this guard keeps
            // old or malformed replays from growing a rendered item forever.
            open[stream] = ((open[stream] || "") + str(data.text)).slice(0, 128_100);
          }
          return;
        }
        if (kind === "run_cancelled") outcome = "cancelled";
        if (kind === "run_interrupted") outcome = "interrupted";
        if (kind === "status_update") {
          if (str(data.blocked_on) === "waiting_model") return;
          const text = (event.content || str(data.label)).trim();
          if (!text || text === lastStatusNote) return;
          lastStatusNote = text;
          closeThinking(list, at);
          list.push({ kind: "note", key, text, tone: "info" });
          return;
        }
        if (kind === "recovery" || kind === "user_steering") {
          const text = (event.content || str(data.message) || str(data.text)).trim();
          if (!text) return;
          closeThinking(list, at);
          list.push({ kind: "note", key, text: kind === "user_steering" ? `Orientação recebida: ${text}` : text, tone: kind === "recovery" ? "warning" : "info" });
        }
        return;
      }
      case "metric": {
        const kind = str(event.data?.kind) || str(event.data?.runtime_type);
        if (kind === "run_completed") {
          outcome = "completed";
          const rawMs = event.data?.duration_ms ?? event.metrics?.duration_ms;
          const ms = rawMs != null ? Number(rawMs) : Number(event.data?.duration) * 1000;
          if (Number.isFinite(ms)) runMs = ms;
        }
        return;
      }
      case "error": {
        if (list === main) outcome = str(event.data?.kind) === "run_interrupted" ? "interrupted" : "failed";
        const text = (event.content || "").trim();
        if (text) list.push({ kind: "note", key, text, tone: "warning" });
        return;
      }
      case "done": {
        done = true;
        closeThinking(main, at);
        return;
      }
      default:
        return;
    }
  });

  if (done || outcome !== "unknown") {
    const settle = (items: Item[]) =>
      items.forEach((item) => {
        if (item.kind === "tool" && item.status === "running") {
          item.status = "unknown";
          item.error = item.error || "Sem resultado registado (a execução terminou antes).";
        }
        if (item.kind === "thinking" && item.endedAt === undefined) item.endedAt = item.startedAt;
      });
    settle(main);
    // A parent transport ending does not prove that a child has stopped.
    subagents.filter((sub) => sub.status !== "running").forEach((sub) => settle(children.get(sub.taskId) ?? []));
  }
  return { main, subagents, children, done, outcome, runMs };
}

// ─── formatting ───────────────────────────────────────────────────────────

export function formatDuration(ms: number | undefined): string {
  if (ms === undefined || !Number.isFinite(ms)) return "";
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  if (ms < 60_000) return `${(ms / 1000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes} min ${seconds} s`;
}

function shortPath(path: string): string {
  const clean = path.replace(/\\/g, "/");
  const parts = clean.split("/").filter(Boolean);
  return parts.length > 3 ? `…/${parts.slice(-3).join("/")}` : clean;
}

function firstLine(text: string, max = 90): string {
  const line = text.split(/\r?\n/)[0] ?? "";
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

function argPath(args: Record<string, unknown>): string {
  const direct = str(args.path) || str(args.file_path) || str(args.filepath) || str(args.file) || str(args.target);
  if (direct) return direct;
  const many = args.paths ?? args.files;
  if (Array.isArray(many)) return many.map((p) => str(p) || str(asRecord(p)?.path)).filter(Boolean).join(", ");
  return "";
}

interface ToolPresentation {
  icon: typeof Terminal;
  label: string;
  target: string;
  kind: "terminal" | "tests" | "file" | "list" | "search" | "edit" | "web" | "plan" | "generic";
}

function describeTool(item: ToolItem): ToolPresentation {
  const { name, args } = item;
  if (COMMAND_TOOLS.has(name)) {
    return { icon: Terminal, label: "Terminal", target: firstLine(str(args.command) || str(args.cmd) || str(args.code)), kind: "terminal" };
  }
  if (TEST_TOOLS.has(name)) {
    const label = name === "run_lint" ? "Lint" : name === "type_check" ? "Type-check" : "Testes";
    return { icon: FlaskConical, label, target: firstLine(str(args.command) || str(args.path) || str(args.pattern) || str(args.target)), kind: "tests" };
  }
  if (READ_TOOLS.has(name)) return { icon: FileText, label: "Leu", target: shortPath(argPath(args)), kind: "file" };
  if (LIST_TOOLS.has(name)) {
    const raw = argPath(args) || str(args.pattern) || ".";
    const target = raw === "." || raw === "./" || raw === "" ? "raiz do projeto" : shortPath(raw);
    return { icon: FolderTree, label: "Listou", target, kind: "list" };
  }
  if (SEARCH_TOOLS.has(name)) {
    const query = str(args.query) || str(args.pattern) || str(args.symbol) || str(args.text);
    const scope = str(args.file_pattern) || str(args.glob) || str(args.path);
    return { icon: Search, label: "Pesquisou", target: `“${firstLine(query, 60)}”${scope ? ` em ${scope}` : ""}`, kind: "search" };
  }
  if (WRITE_TOOLS.has(name)) {
    const created = item.diff?.files?.some((file) => file.created);
    const deleted = name === "delete_file" || item.diff?.files?.some((file) => file.deleted);
    const label = deleted ? "Apagou" : created ? "Criou" : "Editou";
    const target = item.diff?.files?.length
      ? item.diff.files.map((file) => shortPath(file.path)).join(", ")
      : shortPath(argPath(args));
    return { icon: FilePen, label, target, kind: "edit" };
  }
  if (WEB_TOOLS.has(name)) return { icon: Globe, label: "Web", target: firstLine(str(args.query) || str(args.url)), kind: "web" };
  if (SKILL_TOOLS.has(name)) return { icon: BookOpen, label: name === "list_skills" ? "Skills disponíveis" : name === "load_skill" ? "Carregar skill" : name === "build_skill" ? "Criar skill" : "Atualizar skill", target: firstLine(str(args.name)), kind: "generic" };
  if (DELEGATE_TOOLS.has(name)) return { icon: Bot, label: "Delegação", target: firstLine(str(args.name) || str(args.task) || str(args.objective)), kind: "generic" };
  if (PLAN_TOOLS.has(name)) return { icon: ListTodo, label: "Plano", target: "", kind: "plan" };
  const preview = Object.values(args).map((value) => str(value)).find(Boolean) || "";
  return { icon: Wrench, label: name.replace(/_/g, " "), target: firstLine(preview, 70), kind: "generic" };
}

const STATUS_TEXT: Record<ToolStatus, string> = {
  running: "A executar",
  success: "Concluído",
  error: "Falhou",
  approval: "Aguarda aprovação",
  unknown: "Sem resultado registado",
};

const SUBAGENT_STATUS_TEXT: Record<SubagentStatus, string> = {
  running: "A trabalhar",
  success: "Concluído",
  error: "Falhou",
  cancelled: "Cancelado",
  blocked: "Bloqueado",
  unknown: "Estado desconhecido",
};

const RUN_OUTCOME_TEXT: Record<RunOutcome, string> = {
  completed: "Concluído",
  failed: "Falhou",
  cancelled: "Cancelado",
  interrupted: "Interrompido",
  unknown: "Estado não confirmado",
};

// ─── renderers ────────────────────────────────────────────────────────────

function Pre({ children, tone = "default", maxHeight = 340 }: { children: ReactNode; tone?: "default" | "error"; maxHeight?: number }) {
  return (
    <pre
      className={`nx-transcript-pre overflow-auto whitespace-pre-wrap break-words rounded-lg border px-3 py-2 font-mono text-[12px] leading-[1.55] ${
        tone === "error"
          ? "border-nexus-accent4/25 bg-nexus-accent4/[0.06] text-nexus-accent4"
          : "border-nexus-border/50 bg-black/30 text-nexus-text/90"
      }`}
      style={{ maxHeight }}
    >
      {children}
    </pre>
  );
}

function clip(text: string, max = 20_000): string {
  return text.length > max ? `${text.slice(0, max)}\n… (${text.length - max} caracteres omitidos)` : text;
}

function stringifyValue(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function TerminalBody({ item }: { item: ToolItem }) {
  const result = unwrapResult(item.result);
  const record = asRecord(result);
  const command = str(item.args.command) || str(item.args.cmd) || str(item.args.code);
  const stdout = item.stdout || (record ? str(record.stdout) || str(record.output) : typeof result === "string" ? result : "");
  const stderr = item.stderr || (record ? str(record.stderr) : "");
  const exitCode = exitCodeOf(item.result);
  return (
    <div className="space-y-1.5">
      {item.cwd && <div className="text-[11px] text-nexus-faint">Diretório: {item.cwd}</div>}
      {(item.stdout || item.stderr) && <div className="text-[11px] text-nexus-faint">Saída observada durante a execução</div>}
      <Pre maxHeight={380}>
        <span className="select-none text-nexus-accent">$ </span>
        <span className="text-nexus-text">{command}</span>
        {stdout ? `\n${clip(stdout, 128_100)}` : ""}
        {stderr ? <span className="text-nexus-accent4/90">{`\n${clip(stderr, 128_100)}`}</span> : null}
        {!stdout && !stderr && record && ("stdout" in record || "stderr" in record) ? <span className="text-nexus-faint">{"\n(sem saída)"}</span> : null}
      </Pre>
      {exitCode !== null && (
        <div className={`text-[11px] ${exitCode === 0 ? "text-nexus-faint" : "text-nexus-accent4"}`}>exit code {exitCode}</div>
      )}
    </div>
  );
}

function DiffBody({ item }: { item: ToolItem }) {
  if (item.diff?.files?.length) {
    return (
      <div className="space-y-2">
        {item.diff.files.map((file) => (
          <div key={file.path} className="overflow-hidden rounded-lg border border-nexus-border/50">
            <div className="flex items-center gap-2 border-b border-nexus-border/40 bg-black/25 px-3 py-1.5 text-[11.5px]">
              <span className="truncate font-mono text-nexus-text/90">{file.path}</span>
              {file.created && <span className="rounded bg-emerald-500/10 px-1.5 text-[10px] text-emerald-400">novo</span>}
              {file.deleted && <span className="rounded bg-red-500/10 px-1.5 text-[10px] text-red-400">apagado</span>}
              <span className="ml-auto font-mono text-emerald-400">+{file.added ?? 0}</span>
              <span className="font-mono text-red-400">−{file.removed ?? 0}</span>
            </div>
            <pre className="max-h-[420px] overflow-auto bg-black/30 py-1 font-mono text-[12px] leading-[1.5]">
              {file.diff.split("\n").map((line, index) => {
                const cls = line.startsWith("+++") || line.startsWith("---")
                  ? "text-nexus-faint"
                  : line.startsWith("@@")
                    ? "text-sky-400/80"
                    : line.startsWith("+")
                      ? "bg-emerald-500/[0.08] text-emerald-300"
                      : line.startsWith("-")
                        ? "bg-red-500/[0.08] text-red-300"
                        : "text-nexus-text/75";
                return (
                  <div key={index} className={`px-3 ${cls}`}>
                    {line || " "}
                  </div>
                );
              })}
              {file.truncated && <div className="px-3 text-nexus-faint">… diff truncado</div>}
            </pre>
          </div>
        ))}
      </div>
    );
  }
  const content = str(item.args.content) || str(item.args.new_content) || str(item.args.patch) || str(item.args.diff);
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] text-nexus-faint">Sem diff registado — conteúdo enviado à ferramenta:</div>
      {content ? <Pre>{clip(content)}</Pre> : <Pre>{stringifyValue(item.args)}</Pre>}
      {item.result !== undefined && <Pre maxHeight={160}>{clip(stringifyValue(unwrapResult(item.result)), 4000)}</Pre>}
    </div>
  );
}

function FileBody({ item }: { item: ToolItem }) {
  const result = unwrapResult(item.result);
  const record = asRecord(result);
  const content = typeof result === "string" ? result : record ? str(record.content) || str(record.text) || str(record.data) : "";
  if (content) {
    const lines = clip(content).split("\n");
    return (
      <pre className="max-h-[380px] overflow-auto rounded-lg border border-nexus-border/50 bg-black/30 py-2 font-mono text-[12px] leading-[1.5]">
        {lines.map((line, index) => (
          <div key={index} className="flex">
            <span className="w-11 shrink-0 select-none pr-3 text-right text-nexus-faint/70">{index + 1}</span>
            <span className="whitespace-pre-wrap break-words pr-3 text-nexus-text/85">{line || " "}</span>
          </div>
        ))}
      </pre>
    );
  }
  return <Pre>{clip(stringifyValue(result))}</Pre>;
}

interface SearchMatch {
  file: string;
  line?: number;
  text: string;
}

function searchMatches(result: unknown): SearchMatch[] | null {
  const value = unwrapResult(result);
  const record = asRecord(value);
  const list = Array.isArray(value)
    ? value
    : record
      ? (record.matches ?? record.results ?? record.items ?? record.hits)
      : null;
  if (!Array.isArray(list)) return null;
  return list.slice(0, 200).map((entry) => {
    const match = asRecord(entry);
    if (!match) return { file: "", text: str(entry) };
    const line = Number(match.line ?? match.line_number ?? match.lineno);
    return {
      file: str(match.file) || str(match.path) || str(match.file_path),
      line: Number.isFinite(line) ? line : undefined,
      text: str(match.text) || str(match.content) || str(match.snippet) || str(match.match) || str(match.preview),
    };
  });
}

function SearchBody({ item }: { item: ToolItem }) {
  const matches = searchMatches(item.result);
  if (!matches) return <Pre>{clip(stringifyValue(unwrapResult(item.result)))}</Pre>;
  if (!matches.length) return <div className="text-[12px] text-nexus-faint">Sem resultados.</div>;
  return (
    <div className="max-h-[360px] overflow-auto rounded-lg border border-nexus-border/50 bg-black/25 py-1 font-mono text-[12px]">
      {matches.map((match, index) => (
        <div key={index} className="flex gap-2 px-3 py-0.5">
          <span className="shrink-0 text-sky-400/80">
            {shortPath(match.file)}
            {match.line !== undefined ? `:${match.line}` : ""}
          </span>
          <span className="truncate text-nexus-text/80">{match.text.trim()}</span>
        </div>
      ))}
    </div>
  );
}

function PlanBody({ item }: { item: ToolItem }) {
  // The result is the authoritative, updated list; arguments can contain
  // an older proposed list or only the operation that changed one item.
  const todos = asRecord(unwrapResult(item.result))?.todos ?? item.args.todos ?? item.args.items;
  if (Array.isArray(todos)) {
    if (todos.some((todo) => { const row = asRecord(todo); return row && (row.parent_id != null || row.type === "category" || row.type === "objective"); }) && todos.every((todo) => { const row = asRecord(todo); return row && (typeof row.id === "number" || typeof row.id === "string") && typeof row.content === "string" && typeof row.status === "string"; })) {
      return <TodoTree todos={todos as SessionTodo[]} />;
    }
    return (
      <ul className="space-y-1 text-[13px]">
        {todos.map((todo, index) => {
          const record = asRecord(todo) || {};
          const status = str(record.status);
          const cancelled = status === "cancelled" || status === "canceled";
          return (
            <li key={index} className="flex items-start gap-2">
              <span className={`mt-[3px] h-3.5 w-3.5 shrink-0 rounded-full border ${
                status === "completed" ? "border-emerald-400 bg-emerald-400/20" : status === "in_progress" ? "border-nexus-accent" : "border-nexus-border"
              }`} />
              <span className={status === "completed" || cancelled ? "text-nexus-faint line-through" : "text-nexus-text/90"}>
                {str(record.content) || str(record.title) || str(todo)}
                {cancelled && <span className="ml-1.5 no-underline">(cancelada)</span>}
              </span>
            </li>
          );
        })}
      </ul>
    );
  }
  return <GenericBody item={item} />;
}

function GenericBody({ item }: { item: ToolItem }) {
  const args = Object.keys(item.args).length ? stringifyValue(item.args) : "";
  const result = item.result !== undefined ? stringifyValue(unwrapResult(item.result)) : "";
  return (
    <div className="space-y-1.5">
      {args && <Pre maxHeight={200}>{clip(args, 6000)}</Pre>}
      {result && <Pre>{clip(result)}</Pre>}
    </div>
  );
}

function WebBody({ item }: { item: ToolItem }) {
  const result = unwrapResult(item.result);
  const record = asRecord(result);
  const entries = Array.isArray(result) ? result : record?.hits ?? record?.results ?? record?.sources;
  if (!Array.isArray(entries)) return <GenericBody item={item} />;
  if (!entries.length) return <div className="text-[12px] text-nexus-faint">Sem fontes encontradas.</div>;
  return (
    <div className="space-y-2" data-testid="transcript-web-results">
      {entries.slice(0, 30).map((entry, index) => {
        const source = asRecord(entry);
        if (!source) return <Pre key={index}>{clip(stringifyValue(entry), 2000)}</Pre>;
        const rawUrl = str(source.url);
        let url: URL | undefined;
        try { const parsed = new URL(rawUrl); if (parsed.protocol === "https:" || parsed.protocol === "http:") url = parsed; } catch { /* Render invalid URLs as text. */ }
        const title = str(source.title) || rawUrl || "Fonte";
        const snippet = str(source.snippet) || str(source.description) || str(source.summary);
        return (
          <div key={index} className="rounded-lg border border-nexus-border/50 bg-white/[0.02] px-3 py-2">
            {url ? <a href={url.href} target="_blank" rel="noopener noreferrer" className="break-words text-[13px] font-medium text-nexus-accent hover:underline">{title}</a> : <span className="break-words text-[13px] font-medium text-nexus-text">{title}</span>}
            {url && <div className="mt-0.5 break-all text-[11px] text-nexus-faint">{url.hostname}</div>}
            {snippet && <p className="mt-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-nexus-muted">{clip(snippet, 2000)}</p>}
          </div>
        );
      })}
      {entries.length > 30 && <div className="text-[11px] text-nexus-faint">A mostrar 30 de {entries.length} fontes.</div>}
    </div>
  );
}

function ToolBody({ item, kind }: { item: ToolItem; kind: ToolPresentation["kind"] }) {
  let body: ReactNode;
  if (kind === "terminal" || kind === "tests") body = <TerminalBody item={item} />;
  else if (kind === "edit") body = <DiffBody item={item} />;
  else if (kind === "file") body = <FileBody item={item} />;
  else if (kind === "search" || kind === "list") body = kind === "search" ? <SearchBody item={item} /> : <FileBody item={item} />;
  else if (kind === "plan") body = <PlanBody item={item} />;
  else if (kind === "web") body = <WebBody item={item} />;
  else body = <GenericBody item={item} />;
  return (
    <div className="mt-1.5 space-y-1.5 pl-6">
      {body}
      {item.error && kind !== "terminal" && kind !== "tests" && <Pre tone="error" maxHeight={180}>{item.error}</Pre>}
      {item.error && (kind === "terminal" || kind === "tests") && (
        <Pre tone="error" maxHeight={180}>{item.error}</Pre>
      )}
    </div>
  );
}

const ToolRow = memo(function ToolRow({ item }: { item: ToolItem }) {
  const [open, setOpen] = useState(false);
  const presentation = describeTool(item);
  const Icon = presentation.icon;
  const exitCode = presentation.kind === "terminal" || presentation.kind === "tests" ? exitCodeOf(item.result) : null;
  return (
    <div className="nx-tool-row" data-testid="transcript-tool" data-tool={item.name} data-status={item.status}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="group/tool flex w-full min-w-0 items-center gap-2 rounded-md py-1 text-left text-[13px] text-nexus-muted transition-colors hover:text-nexus-text"
      >
        <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-nexus-faint transition-transform ${open ? "rotate-90" : ""}`} aria-hidden="true" />
        <Icon className="h-3.5 w-3.5 shrink-0 opacity-80" aria-hidden="true" />
        <span className="shrink-0 font-medium text-nexus-text/85">{presentation.label}</span>
        {presentation.target && (
          <>
            <span className="shrink-0 text-nexus-faint">·</span>
            <span className="min-w-0 truncate font-mono text-[12px]">{presentation.target}</span>
          </>
        )}
        {item.diff && (
          <span className="shrink-0 font-mono text-[11.5px]">
            <span className="text-emerald-400">+{item.diff.added}</span> <span className="text-red-400">−{item.diff.removed}</span>
          </span>
        )}
        <span className="shrink-0 text-nexus-faint">·</span>
        <span
          className={`flex shrink-0 items-center gap-1 text-[12px] ${
            item.status === "error" ? "text-nexus-accent4" : item.status === "running" ? "text-nexus-accent" : item.status === "approval" ? "text-amber-400" : "text-nexus-faint"
          }`}
        >
          {item.status === "running" && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
          {STATUS_TEXT[item.status]}
          {exitCode !== null && exitCode !== 0 ? ` (exit ${exitCode})` : ""}
        </span>
        {item.durationMs !== undefined && item.status !== "running" && (
          <>
            <span className="shrink-0 text-nexus-faint">·</span>
            <span className="shrink-0 tabular-nums text-[12px] text-nexus-faint">{formatDuration(item.durationMs)}</span>
          </>
        )}
      </button>
      {item.status === "approval" && <ApprovalBar item={item} />}
      {open && <ToolBody item={item} kind={presentation.kind} />}
    </div>
  );
});

/** Inline decision for a tool held at the confirmation gate. */
function ApprovalBar({ item }: { item: ToolItem }) {
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">("idle");
  const [error, setError] = useState("");
  const decide = async (approved: boolean) => {
    if (!item.confirmationId) return;
    setState("sending");
    try {
      await confirmTool(item.confirmationId, approved);
      setState("done");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setState("error");
    }
  };
  if (state === "done") {
    return <div className="ml-6 py-1 text-[12px] text-nexus-faint">Decisão enviada.</div>;
  }
  return (
    <div className="ml-6 my-1 flex flex-wrap items-center gap-2 rounded-md border border-amber-400/30 bg-amber-400/5 px-2.5 py-1.5 text-[12px]" data-testid="tool-approval">
      <span className="text-amber-300">Esta ação precisa da tua aprovação.</span>
      {!item.confirmationId && <span className="text-nexus-accent4">Falta o identificador da confirmação.</span>}
      <button
        type="button"
        disabled={!item.confirmationId || state === "sending"}
        onClick={() => void decide(true)}
        className="rounded-md border border-emerald-400/40 bg-emerald-400/10 px-2 py-0.5 font-medium text-emerald-300 hover:bg-emerald-400/20 disabled:opacity-50"
      >
        Confirmar
      </button>
      <button
        type="button"
        disabled={!item.confirmationId || state === "sending"}
        onClick={() => void decide(false)}
        className="rounded-md border border-nexus-border/60 px-2 py-0.5 text-nexus-muted hover:text-nexus-text disabled:opacity-50"
      >
        Recusar
      </button>
      {state === "error" && <span className="text-nexus-accent4">Falhou: {error}</span>}
    </div>
  );
}

function ThinkingBlock({ item, live, renderMarkdown }: { item: ThinkingItem; live: boolean; renderMarkdown: (text: string) => ReactNode }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const expanded = open ?? live;
  const seconds = item.endedAt !== undefined ? Math.max(1, Math.round((item.endedAt - item.startedAt) / 1000)) : null;
  return (
    <div className="nx-thinking" data-testid="transcript-thinking">
      <button
        type="button"
        onClick={() => setOpen(!expanded)}
        aria-expanded={expanded}
        className="flex items-center gap-1.5 py-1 text-[13px] text-nexus-muted transition-colors hover:text-nexus-text"
      >
        <Sparkles className={`h-3.5 w-3.5 ${live ? "animate-pulse text-nexus-accent" : "opacity-70"}`} aria-hidden="true" />
        <span className={live ? "nx-shimmer-text" : undefined}>
          {live ? "A pensar…" : seconds !== null ? `Pensou durante ${seconds} s` : "Raciocínio"}
        </span>
        <ChevronRight className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-90" : ""}`} aria-hidden="true" />
      </button>
      {expanded && (
        <div className="mb-1 ml-[7px] max-h-[320px] overflow-auto border-l border-nexus-border/60 pl-4 text-[13px] leading-[1.6] text-nexus-muted [&_.nx-prose]:text-nexus-muted [&_p]:my-1.5">
          {renderMarkdown(item.text)}
        </div>
      )}
    </div>
  );
}

function SubagentCard({ item, toolCount, onOpen, active }: { item: SubagentItem; toolCount: number; onOpen: () => void; active: boolean }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid="transcript-subagent"
      data-task-id={item.taskId}
      className={`flex w-full min-w-0 items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${
        active ? "border-nexus-accent/50 bg-nexus-accent/[0.06]" : "border-nexus-border/60 bg-white/[0.02] hover:border-nexus-border hover:bg-white/[0.04]"
      }`}
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent">
        <Bot className="h-4 w-4" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 text-[13px]">
          <span className="font-medium text-nexus-text">{item.name}</span>
          <span className="text-nexus-faint">·</span>
          <span className={item.status === "error" ? "text-nexus-accent4" : item.status === "running" ? "text-nexus-accent" : "text-nexus-faint"}>
            {SUBAGENT_STATUS_TEXT[item.status]}
          </span>
          {item.endedAt !== undefined && (
            <span className="tabular-nums text-nexus-faint">· {formatDuration(item.endedAt - item.startedAt)}</span>
          )}
          {toolCount > 0 && <span className="text-nexus-faint">· {toolCount} ferramenta{toolCount === 1 ? "" : "s"}</span>}
        </span>
        {item.objective && <span className="mt-0.5 block truncate text-[12px] text-nexus-muted">{item.objective}</span>}
      </span>
      {item.status === "running" ? (
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-nexus-accent" aria-hidden="true" />
      ) : item.status !== "success" ? (
        <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-nexus-accent4" aria-hidden="true" />
      ) : (
        <Check className="h-3.5 w-3.5 shrink-0 text-emerald-400" aria-hidden="true" />
      )}
      <span className="shrink-0 text-[12px] text-nexus-faint">Abrir ›</span>
    </button>
  );
}

function ItemList({
  items,
  live,
  renderMarkdown,
  transcript,
  openTask,
  onOpenTask,
}: {
  items: Item[];
  live: boolean;
  renderMarkdown: (text: string) => ReactNode;
  transcript: Transcript;
  openTask?: string | null;
  onOpenTask?: (taskId: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        switch (item.kind) {
          case "text":
            return (
              <div key={item.key} className="py-0.5">
                {renderMarkdown(item.text)}
              </div>
            );
          case "thinking":
            return <ThinkingBlock key={item.key} item={item} live={live && isLast && item.endedAt === undefined} renderMarkdown={renderMarkdown} />;
          case "tool":
            return <ToolRow key={item.key} item={item} />;
          case "note":
            return (
              <div key={item.key} className={`flex items-center gap-2 py-0.5 text-[12.5px] ${item.tone === "warning" ? "text-amber-400/90" : "text-nexus-faint"}`}>
                <span className="h-1 w-1 shrink-0 rounded-full bg-current opacity-70" aria-hidden="true" />
                <span className="min-w-0">{item.text}</span>
              </div>
            );
          case "subagent": {
            const toolCount = (transcript.children.get(item.taskId) ?? []).filter((child) => child.kind === "tool").length;
            return (
              <SubagentCard
                key={item.key}
                item={item}
                toolCount={toolCount}
                active={openTask === item.taskId}
                onOpen={() => onOpenTask?.(item.taskId)}
              />
            );
          }
          default:
            return null;
        }
      })}
    </div>
  );
}

// ─── subagent panel ───────────────────────────────────────────────────────

const PANEL_EVENT = "nexus:subagent-panel";
const CHILD_POLL_MS = 2500;

function seqOf(event: StreamEvent): number | undefined {
  const raw = event.seq ?? (event.data?.seq as number | undefined);
  const seq = Number(raw);
  return raw !== undefined && raw !== null && Number.isFinite(seq) ? seq : undefined;
}

/** Restore the top-level envelope a frame carries in ``data`` (journal replays). */
function normalizeFrame(event: StreamEvent): StreamEvent {
  const data = event.data || {};
  return {
    ...event,
    run_id: event.run_id || str(data.run_id) || undefined,
    seq: seqOf(event),
    event_id: event.event_id || str(data.event_id) || undefined,
    task_id: event.task_id || str(data.task_id) || undefined,
  };
}

/** Merge live frames with the durable child journal; one frame set per seq, no duplicates. */
export function mergeChildFrames(local: StreamEvent[], durable: StreamEvent[]): StreamEvent[] {
  const localSeqs = new Set<number>();
  const merged: StreamEvent[] = [];
  for (const event of local) {
    const seq = seqOf(event);
    if (seq !== undefined) localSeqs.add(seq);
    merged.push(event);
  }
  for (const raw of durable) {
    const event = normalizeFrame(raw);
    if (event.seq !== undefined && localSeqs.has(event.seq)) continue;
    merged.push(event);
  }
  return merged
    .map((event, index) => ({ event, index }))
    .sort((a, b) => (seqOf(a.event) ?? Number.MAX_SAFE_INTEGER) - (seqOf(b.event) ?? Number.MAX_SAFE_INTEGER) || a.index - b.index)
    .map(({ event }) => event);
}

interface ChildActivity {
  frames: StreamEvent[];
  status: string;
  durable: boolean;
  error: string;
  loaded: boolean;
}

/** Read the child's own session (durable journal) and follow it while it runs. */
function useChildActivity(childSessionId: string | undefined, follow: boolean): ChildActivity {
  const [state, setState] = useState<ChildActivity>({ frames: [], status: "", durable: false, error: "", loaded: false });
  useEffect(() => {
    if (!childSessionId) return;
    let cancelled = false;
    let after = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const frames: StreamEvent[] = [];
    const tick = async () => {
      try {
        for (let page = 0; page < 20; page += 1) {
          const data = await getSubagentActivity(childSessionId, after, controller.signal);
          if (cancelled) return;
          frames.push(...(data.events || []));
          after = Math.max(after, Number(data.next_after_seq) || after);
          setState({ frames: [...frames], status: data.status || "", durable: Boolean(data.durable), error: "", loaded: true });
          if (!data.has_more) {
            const running = data.status === "running" || data.live;
            if (follow || running) timer = setTimeout(() => void tick(), CHILD_POLL_MS);
            return;
          }
        }
      } catch (reason) {
        if (cancelled || controller.signal.aborted) return;
        setState((prev) => ({ ...prev, loaded: true, error: reason instanceof Error ? reason.message : String(reason) }));
      }
    };
    void tick();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [childSessionId, follow]);
  return state;
}
const MIN_WIDTH = 340;

function SubagentPanel({
  transcript,
  events,
  taskId,
  onSelect,
  onClose,
  live,
  renderMarkdown,
}: {
  transcript: Transcript;
  events: StreamEvent[];
  taskId: string;
  onSelect: (taskId: string) => void;
  onClose: () => void;
  live: boolean;
  renderMarkdown: (text: string) => ReactNode;
}) {
  const [width, setWidth] = useState(520);
  const [centered, setCentered] = useState(false);
  const dragging = useRef(false);
  const observed = transcript.subagents.find((item) => item.taskId === taskId);
  const child = useChildActivity(observed?.childSessionId, live && observed?.status === "running");
  const durableView = useMemo(() => {
    if (!child.frames.length) return null;
    const local = events.filter((event) => (event.task_id || str(event.data?.task_id)) === taskId);
    return buildTranscript(mergeChildFrames(local, child.frames));
  }, [child.frames, events, taskId]);
  const durableSub = durableView?.subagents.find((item) => item.taskId === taskId);
  const observedItems = transcript.children.get(taskId) ?? [];
  const durableItems = durableView?.children.get(taskId) ?? [];
  const items = durableItems.length > observedItems.length ? durableItems : observedItems;
  const sub = observed && durableSub && observed.status === "running" && durableSub.status !== "running"
    ? { ...observed, status: durableSub.status, result: durableSub.result, error: durableSub.error, endedAt: durableSub.endedAt }
    : observed;
  const changedFiles = Array.from(new Set(items.flatMap((item) => (item.kind === "tool" && item.diff ? item.diff.files.map((file) => file.path) : []))));
  const hasText = items.some((item) => item.kind === "text");
  const subLive = live && sub?.status === "running";
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const el = bodyRef.current;
    if (el && subLive && el.scrollHeight - el.scrollTop - el.clientHeight < 160) el.scrollTop = el.scrollHeight;
  }, [items.length, subLive]);

  const onPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
  }, []);
  const onPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    const next = Math.min(window.innerWidth * 0.95, Math.max(MIN_WIDTH, window.innerWidth - event.clientX));
    setCentered(false);
    setWidth(next);
  }, []);
  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  if (typeof document === "undefined" || !sub) return null;
  const panelWidth = centered ? "min(1100px, 92vw)" : `${width}px`;

  return createPortal(
    <div
      className="fixed inset-y-0 right-0 z-[60] flex border-l border-nexus-border/70 bg-nexus-bg/95 shadow-2xl backdrop-blur-xl"
      style={{ width: panelWidth, maxWidth: "100vw" }}
      role="dialog"
      aria-label={`Conversa do subagente ${sub.name}`}
      data-testid="subagent-panel"
    >
      <div
        className="w-1.5 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-nexus-accent/30"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-1 border-b border-nexus-border/60 px-2 py-2">
          <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
            {transcript.subagents.map((tab) => (
              <button
                key={tab.taskId}
                type="button"
                onClick={() => onSelect(tab.taskId)}
                className={`flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12.5px] transition-colors ${
                  tab.taskId === taskId ? "bg-white/[0.07] text-nexus-text" : "text-nexus-muted hover:bg-white/[0.04] hover:text-nexus-text"
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    tab.status === "running" ? "animate-pulse bg-nexus-accent" : tab.status === "success" ? "bg-emerald-400" : "bg-nexus-accent4"
                  }`}
                />
                {tab.name}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setCentered((value) => !value)}
            className="rounded-md p-1.5 text-nexus-muted hover:bg-white/[0.05] hover:text-nexus-text"
            title={centered ? "Reduzir painel" : "Expandir ao centro"}
          >
            {centered ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-nexus-muted hover:bg-white/[0.05] hover:text-nexus-text"
            title="Fechar (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div ref={bodyRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="mb-4 rounded-xl border border-nexus-border/50 bg-white/[0.02] px-3 py-2.5">
            <div className="text-[11px] uppercase tracking-wider text-nexus-faint">Objetivo</div>
            <div className="mt-1 whitespace-pre-wrap text-[13px] text-nexus-text/90">{sub.objective || "—"}</div>
          </div>
          {items.length === 0 && sub.status === "running" && (
            <div className="flex items-center gap-2 text-[13px] text-nexus-faint">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> A iniciar…
            </div>
          )}
          <ItemList items={items} live={Boolean(subLive)} renderMarkdown={renderMarkdown} transcript={transcript} />
          {changedFiles.length > 0 && (
            <div className="mt-3 rounded-xl border border-nexus-border/50 bg-white/[0.02] px-3 py-2.5" data-testid="subagent-changed-files">
              <div className="text-[11px] uppercase tracking-wider text-nexus-faint">Ficheiros alterados</div>
              <ul className="mt-1 space-y-0.5 font-mono text-[12px] text-nexus-text/85">
                {changedFiles.map((path) => <li key={path} className="truncate">{path}</li>)}
              </ul>
            </div>
          )}
          {sub.status !== "running" && !hasText && sub.result && (
            <div className="mt-3 border-t border-nexus-border/40 pt-3">
              <div className="mb-1 text-[11px] uppercase tracking-wider text-nexus-faint">Resultado</div>
              {renderMarkdown(sub.result)}
            </div>
          )}
          {sub.error && <div className="mt-3"><Pre tone="error">{sub.error}</Pre></div>}
        </div>
        <div className="border-t border-nexus-border/60 px-4 py-2.5 text-[11.5px] text-nexus-faint">
          {sub.childSessionId ? (
            <span data-testid="subagent-child-session">
              Conversa-filha própria · sessão <span className="font-mono">{sub.childSessionId.slice(0, 18)}</span>
              {child.durable ? " · histórico gravado" : child.loaded ? " · ainda sem histórico gravado" : " · a carregar histórico…"}
              {child.error ? ` · não foi possível ler o histórico (${child.error})` : ""}
              . Mensagens ou interrupções dirigidas a este subagente ainda não são suportadas pelo backend.
            </span>
          ) : (
            "Atividade observada na execução principal (execução sem sessão-filha registada). Mensagens diretas ao subagente não são suportadas."
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ─── public component ─────────────────────────────────────────────────────

export interface AgentTranscriptProps {
  events: StreamEvent[];
  isStreaming?: boolean;
  /** Final text when the frames carried no token text (legacy runs). */
  fallbackContent?: string;
  renderMarkdown: (text: string) => ReactNode;
}

function AgentTranscript({ events, isStreaming = false, fallbackContent = "", renderMarkdown }: AgentTranscriptProps) {
  const transcript = useMemo(() => buildTranscript(events), [events]);
  const [openTask, setOpenTask] = useState<string | null>(null);
  const instanceId = useRef(`t${Math.random().toString(36).slice(2)}`);
  const live = isStreaming && !transcript.done;

  useEffect(() => {
    const onOther = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (detail !== instanceId.current) setOpenTask(null);
    };
    window.addEventListener(PANEL_EVENT, onOther);
    return () => window.removeEventListener(PANEL_EVENT, onOther);
  }, []);

  const openSubagent = useCallback((taskId: string) => {
    window.dispatchEvent(new CustomEvent(PANEL_EVENT, { detail: instanceId.current }));
    setOpenTask(taskId);
  }, []);

  const hasMainText = transcript.main.some((item) => item.kind === "text");
  const recordedText = transcript.main.filter((item): item is TextItem => item.kind === "text").map((item) => item.text).join("").trim();
  // p44: deltas are joined without the separators the stored answer keeps; compare ignoring whitespace.
  const squash = (value: string) => value.replace(/\s+/g, "");
  const savedTextDiffers = !live && hasMainText && fallbackContent.trim() && squash(fallbackContent) !== squash(recordedText);
  const last = transcript.main[transcript.main.length - 1];
  const working = live && (!last || (last.kind !== "text" && last.kind !== "thinking" && !(last.kind === "tool" && last.status === "running")));
  const toolCount = transcript.main.filter((item) => item.kind === "tool").length
    + Array.from(transcript.children.values()).reduce((sum, list) => sum + list.filter((item) => item.kind === "tool").length, 0);

  return (
    <div className="nx-agent-transcript" data-testid="agent-transcript">
      <ItemList
        items={transcript.main}
        live={live}
        renderMarkdown={renderMarkdown}
        transcript={transcript}
        openTask={openTask}
        onOpenTask={openSubagent}
      />
      {!hasMainText && fallbackContent.trim() && !live && <div className="py-0.5">{renderMarkdown(fallbackContent)}</div>}
      {savedTextDiffers && (
        <details className="my-2 rounded-lg border border-amber-400/30 px-3 py-2 text-[13px]" data-testid="saved-answer-mismatch">
          <summary className="cursor-pointer text-amber-300">A resposta guardada difere dos eventos recuperados. Ver resposta guardada</summary>
          <div className="mt-2">{renderMarkdown(fallbackContent)}</div>
        </details>
      )}
      {live && last?.kind === "text" && <span aria-hidden="true" className="nx-caret" />}
      {working && (
        <div className="flex items-center gap-2 py-1 text-[13px] text-nexus-faint">
          <span className="nx-shimmer-text">A trabalhar…</span>
        </div>
      )}
      {!live && transcript.done && (toolCount > 0 || transcript.runMs !== undefined) && (
        <div className="mt-2 text-[11.5px] text-nexus-faint">
          {RUN_OUTCOME_TEXT[transcript.outcome]}
          {transcript.runMs !== undefined ? ` · ${formatDuration(transcript.runMs)}` : ""}
          {toolCount > 0 ? ` · ${toolCount} ferramenta${toolCount === 1 ? "" : "s"}` : ""}
          {transcript.subagents.length > 0 ? ` · ${transcript.subagents.length} subagente${transcript.subagents.length === 1 ? "" : "s"}` : ""}
        </div>
      )}
      {openTask && (
        <SubagentPanel
          transcript={transcript}
          events={events}
          taskId={openTask}
          onSelect={setOpenTask}
          onClose={() => setOpenTask(null)}
          live={isStreaming}
          renderMarkdown={renderMarkdown}
        />
      )}
    </div>
  );
}

export default memo(AgentTranscript);
