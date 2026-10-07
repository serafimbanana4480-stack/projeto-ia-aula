"use client";

import { useId, useMemo, useState, memo, type CSSProperties, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronDown,
  ChevronUp,
  FileText,
  Save,
  FolderOpen,
  Terminal,
  Search,
  Globe,
  GitBranch,
  Hammer,
  Loader2,
  CheckCircle2,
  XCircle,
  Wrench,
  Code2,
  RotateCcw,
  ShieldAlert,
  Copy,
  BookOpen,
  ListTodo,
  Brain,
  Bot,
  Database,
  Workflow,
} from "lucide-react";
import type { ToolCallItem } from "../../lib/types";
import { confirmTool, executeTool } from "../../lib/api";
import { AGENT_DECLARED_TODO_CAVEAT } from "../../lib/foldRun";
import { log } from "../../lib/log";
import {
  extractWebSources,
  formatRunDuration,
  primaryToolArg,
  toolKindGroup,
} from "../../lib/chatPresentation";

interface ToolCallTimelineProps {
  calls: ToolCallItem[];
  sessionId?: string;
}

const TOOL_LABELS: Record<string, string> = {
  write_file: "Escrever ficheiro",
  write_file_absolute: "Escrever ficheiro",
  read_file: "Ler ficheiro",
  read_file_absolute: "Ler ficheiro",
  list_dir: "Listar diretoria",
  list_dir_absolute: "Listar diretoria",
  execute_code: "Executar código",
  execute_terminal: "Executar terminal",
  search_codebase: "Pesquisar código",
  web_search: "Pesquisa web",
  fetch_url: "Abrir URL",
  search_github: "GitHub",
  git_clone: "Git clone",
  scaffold_project: "Gerar projeto",
  consult_agent: "Consultar agente",
  todo_write: "Atualizar checklist",
  todo_list: "Consultar checklist",
  recall_context: "Memória",
  analyze_data: "Analisar dados",
  generate_report: "Relatório",
  data_analysis: "Analisar dados",
  report_generation: "Gerar relatório",
  list_skills: "Descobrir skills",
  load_skill: "Carregar skill",
  build_skill: "Criar skill",
  update_skill: "Atualizar skill",
  sequential_thinking: "Organizar raciocínio",
  write_memory: "Guardar memória",
  read_memory: "Consultar memória",
  spawn_agent: "Iniciar subagente",
  spawn_task: "Iniciar tarefa em segundo plano",
  store_memory: "Guardar memória",
  check_tasks: "Consultar tarefas em segundo plano",
  spawn_agents: "Distribuir trabalho",
  check_agent: "Consultar subagente",
  check_agents: "Consultar subagentes",
  collect_agent: "Recolher resultado",
  collect_agents: "Recolher resultados",
  message_agent: "Orientar subagente",
  create_plan: "Criar plano",
  get_plan: "Consultar plano",
  update_plan: "Atualizar plano",
};

const TOOL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  write_file: Save,
  write_file_absolute: Save,
  read_file: FileText,
  read_file_absolute: FileText,
  list_dir: FolderOpen,
  list_dir_absolute: FolderOpen,
  execute_code: Terminal,
  execute_terminal: Terminal,
  search_codebase: Search,
  web_search: Globe,
  fetch_url: Globe,
  search_github: GitBranch,
  git_clone: GitBranch,
  scaffold_project: Hammer,
  consult_agent: Wrench,
  recall_context: Wrench,
  analyze_data: Wrench,
  generate_report: Wrench,
  data_analysis: Wrench,
  report_generation: Wrench,
  todo_write: ListTodo,
  todo_list: ListTodo,
  list_skills: BookOpen,
  load_skill: BookOpen,
  build_skill: BookOpen,
  update_skill: BookOpen,
  sequential_thinking: Brain,
  write_memory: Database,
  read_memory: Database,
  spawn_agent: Bot,
  spawn_task: Bot,
  store_memory: Database,
  check_tasks: Bot,
  spawn_agents: Bot,
  check_agent: Bot,
  check_agents: Bot,
  collect_agent: Bot,
  collect_agents: Bot,
  message_agent: Bot,
  create_plan: Workflow,
  get_plan: Workflow,
  update_plan: Workflow,
};

function getToolDisplay(name: string) {
  return {
    label: TOOL_LABELS[name] || name.replace(/_/g, " "),
    Icon: TOOL_ICONS[name] || Wrench,
  };
}

function groupAdjacentToolCalls(calls: ToolCallItem[]) {
  const groups: ToolCallItem[][] = [];
  for (const call of calls) {
    const previous = groups.at(-1);
    const first = previous?.[0];
    if (first && first.name === call.name && first.status === call.status) {
      previous.push(call);
    } else {
      groups.push([call]);
    }
  }
  return groups;
}

const OUTPUT_ROW_HEIGHT = 18;
const OUTPUT_VIEWPORT_HEIGHT = 324;
const OUTPUT_OVERSCAN = 4;
const MAX_RENDERED_LINE_LENGTH = 4_000;
const ANSI_FOREGROUND: Record<number, string> = {
  30: "#111827", 31: "#fb7185", 32: "#4ade80", 33: "#facc15",
  34: "#60a5fa", 35: "#e879f9", 36: "#22d3ee", 37: "#e5e7eb",
  90: "#6b7280", 91: "#fda4af", 92: "#86efac", 93: "#fde047",
  94: "#93c5fd", 95: "#f0abfc", 96: "#67e8f9", 97: "#ffffff",
};
const ANSI_BACKGROUND: Record<number, string> = {
  40: "#111827", 41: "#7f1d1d", 42: "#14532d", 43: "#713f12",
  44: "#1e3a8a", 45: "#701a75", 46: "#164e63", 47: "#374151",
  100: "#4b5563", 101: "#881337", 102: "#166534", 103: "#854d0e",
  104: "#1e40af", 105: "#86198f", 106: "#155e75", 107: "#d1d5db",
};

function applyAnsiCodes(style: CSSProperties, rawCodes: string): CSSProperties {
  const codes = rawCodes ? rawCodes.split(";").map((code) => Number(code || 0)) : [0];
  const next = { ...style };
  for (let index = 0; index < codes.length; index += 1) {
    const code = codes[index];
    if (code === 0) {
      Object.keys(next).forEach((key) => delete next[key as keyof CSSProperties]);
    } else if (code === 1) next.fontWeight = 700;
    else if (code === 2) next.opacity = 0.7;
    else if (code === 3) next.fontStyle = "italic";
    else if (code === 4) next.textDecoration = "underline";
    else if (code === 22) { delete next.fontWeight; delete next.opacity; }
    else if (code === 23) delete next.fontStyle;
    else if (code === 24) delete next.textDecoration;
    else if (code === 39) delete next.color;
    else if (code === 49) delete next.backgroundColor;
    else if (ANSI_FOREGROUND[code]) next.color = ANSI_FOREGROUND[code];
    else if (ANSI_BACKGROUND[code]) next.backgroundColor = ANSI_BACKGROUND[code];
    else if ((code === 38 || code === 48) && codes[index + 1] === 5) {
      const colorIndex = codes[index + 2];
      if (Number.isInteger(colorIndex) && colorIndex >= 0 && colorIndex <= 255) {
        const color = colorIndex < 16
          ? (ANSI_FOREGROUND[30 + (colorIndex % 8)] ?? "#e5e7eb")
          : `hsl(${(colorIndex * 47) % 360} 72% ${colorIndex < 232 ? 55 : 80}%)`;
        if (code === 38) next.color = color;
        else next.backgroundColor = color;
      }
      index += 2;
    } else if ((code === 38 || code === 48) && codes[index + 1] === 2) {
      const [red, green, blue] = codes.slice(index + 2, index + 5).map((part) =>
        Math.min(255, Math.max(0, part)),
      );
      if ([red, green, blue].every(Number.isFinite)) {
        const color = `rgb(${red} ${green} ${blue})`;
        if (code === 38) next.color = color;
        else next.backgroundColor = color;
      }
      index += 4;
    }
  }
  return next;
}

function renderAnsiLine(rawLine: string): ReactNode {
  const line = rawLine.replace(/\u001b\][^\u0007]*(?:\u0007|\u001b\\)/g, "");
  const tokens: ReactNode[] = [];
  const csi = /\u001b\[([0-?]*[ -/]*)([@-~])/g;
  let cursor = 0;
  let style: CSSProperties = {};
  for (let match = csi.exec(line); match; match = csi.exec(line)) {
    if (match.index > cursor) {
      const text = line.slice(cursor, match.index);
      tokens.push(Object.keys(style).length ? <span key={tokens.length} style={style}>{text}</span> : text);
    }
    // SGR carries visual styling. Other CSI control sequences are stripped so
    // cursor movement and terminal controls never become browser markup.
    if (match[2] === "m" && /^[0-9;]*$/.test(match[1])) {
      style = applyAnsiCodes(style, match[1]);
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < line.length) {
    const text = line.slice(cursor);
    tokens.push(Object.keys(style).length ? <span key={tokens.length} style={style}>{text}</span> : text);
  }
  return tokens.length ? tokens : " ";
}

function OutputViewer({ content, label, showLabel = true }: { content: string; label: string; showLabel?: boolean }) {
  const [scrollTop, setScrollTop] = useState(0);
  const [query, setQuery] = useState("");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const lines = useMemo(() => content.replace(/\r\n/g, "\n").split("\n"), [content]);
  const visibleLines = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return lines.flatMap((text, index) =>
      !normalizedQuery || text.toLocaleLowerCase().includes(normalizedQuery)
        ? [{ text, lineNumber: index + 1 }]
        : [],
    );
  }, [lines, query]);
  const firstRow = Math.max(0, Math.floor(scrollTop / OUTPUT_ROW_HEIGHT) - OUTPUT_OVERSCAN);
  const lastRow = Math.min(
    visibleLines.length,
    Math.ceil((scrollTop + OUTPUT_VIEWPORT_HEIGHT) / OUTPUT_ROW_HEIGHT) + OUTPUT_OVERSCAN,
  );
  const rows = visibleLines.slice(firstRow, lastRow);

  const copyOutput = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard indisponível");
      await navigator.clipboard.writeText(content);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  return (
    <section className="overflow-hidden rounded-lg border border-nexus-border/60 bg-nexus-bg/70" aria-label={label}>
      <div className="flex flex-wrap items-center gap-2 border-b border-nexus-border/40 bg-nexus-panel/50 px-2.5 py-2">
        {showLabel && <span className="mr-auto text-[9px] font-semibold uppercase tracking-wide text-nexus-muted">{label}</span>}
        {!showLabel && <span className="mr-auto" />}
        <span className="text-[9px] text-nexus-muted">
          {new Intl.NumberFormat("pt-PT").format(lines.length)} linhas
          {query ? ` · ${new Intl.NumberFormat("pt-PT").format(visibleLines.length)} resultados` : ""}
        </span>
        <label className="flex items-center gap-1 rounded border border-nexus-border/40 px-1.5">
          <Search className="h-3 w-3 text-nexus-muted" />
          <input
            aria-label={`Pesquisar em ${label}`}
            value={query}
            onChange={(event) => { setQuery(event.currentTarget.value); setScrollTop(0); }}
            placeholder="Pesquisar"
            className="w-24 bg-transparent py-0.5 text-[9px] text-nexus-text outline-none placeholder:text-nexus-muted/60"
          />
        </label>
        <button
          type="button"
          onClick={() => void copyOutput()}
          className="inline-flex items-center gap-1 rounded border border-nexus-border/40 px-1.5 py-1 text-[9px] text-nexus-muted hover:text-nexus-text"
          aria-label={`Copiar ${label}`}
        >
          <Copy className="h-3 w-3" />
          {copyState === "copied" ? "Copiado" : copyState === "failed" ? "Falhou" : "Copiar"}
        </button>
      </div>
      <div
        role="log"
        aria-label={label}
        aria-live="off"
        tabIndex={0}
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        className="overflow-auto font-mono text-[10px] leading-[18px] text-slate-200/90"
        style={{ height: OUTPUT_VIEWPORT_HEIGHT }}
      >
        <div aria-hidden="true" style={{ height: firstRow * OUTPUT_ROW_HEIGHT }} />
        {rows.map(({ text, lineNumber }, rowIndex) => {
          const isLong = text.length > MAX_RENDERED_LINE_LENGTH;
          const rendered = isLong ? `${text.slice(0, MAX_RENDERED_LINE_LENGTH)}…` : text;
          return (
            <div
              key={`${lineNumber}-${rowIndex}`}
              data-output-line={lineNumber}
              title={isLong ? `${text.length} caracteres; copiar inclui a linha completa.` : undefined}
              className="flex h-[18px] min-w-max whitespace-pre"
            >
              <span className="sticky left-0 mr-2 inline-block w-10 shrink-0 select-none bg-nexus-bg px-1 text-right text-nexus-muted/60">
                {lineNumber}
              </span>
              <span>{renderAnsiLine(rendered)}</span>
              {isLong && <span className="ml-2 text-amber-300/80">linha truncada na pré-visualização</span>}
            </div>
          );
        })}
        <div aria-hidden="true" style={{ height: Math.max(0, visibleLines.length - lastRow) * OUTPUT_ROW_HEIGHT }} />
        {visibleLines.length === 0 && <div className="px-2 py-2 text-nexus-muted">Sem linhas que correspondam.</div>}
      </div>
    </section>
  );
}

function serializeOutput(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? "null";
  } catch {
    return '"(resultado não serializável)"';
  }
}

type TodoStatus = "pending" | "in_progress" | "completed" | "cancelled";

interface TodoEntry {
  id: string | number;
  content: string;
  status: TodoStatus;
  priority?: string;
}

const TODO_STATUS_LABELS: Record<TodoStatus, string> = {
  pending: "Por fazer",
  in_progress: "Em curso",
  completed: "Marcada como concluída",
  cancelled: "Cancelada",
};

const TODO_COUNT_LABELS: Record<TodoStatus, { one: string; many: string }> = {
  pending: { one: "por fazer", many: "por fazer" },
  in_progress: { one: "em curso", many: "em curso" },
  completed: { one: "marcada como concluída", many: "marcadas como concluídas" },
  cancelled: { one: "cancelada", many: "canceladas" },
};

const TODO_STATUS_STYLES: Record<TodoStatus, string> = {
  pending: "text-amber-200",
  in_progress: "text-sky-300",
  completed: "text-emerald-300",
  cancelled: "text-nexus-muted",
};

const TODO_PRIORITY_LABELS: Record<string, string> = {
  low: "baixa",
  normal: "normal",
  high: "alta",
};

const TODO_STATUSES: TodoStatus[] = ["pending", "in_progress", "completed", "cancelled"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isTodoEntry(value: unknown): value is TodoEntry {
  if (!isRecord(value)) return false;
  const hasValidId = typeof value.id === "string" ||
    (typeof value.id === "number" && Number.isFinite(value.id));
  return hasValidId && typeof value.content === "string" &&
    TODO_STATUSES.includes(value.status as TodoStatus);
}

function isTodoCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isTodoResult(
  result: Record<string, unknown>,
): result is Record<string, unknown> & { todos: TodoEntry[] } {
  return result.ok !== false && Array.isArray(result.todos) && result.todos.every(isTodoEntry);
}

function TodoResultContents({ result }: { result: Record<string, unknown> & { todos: TodoEntry[] } }) {
  const entries = result.todos;
  const rawCounts = isRecord(result.counts) ? result.counts : {};
  const counts = Object.fromEntries(
    TODO_STATUSES.map((status) => [
      status,
      isTodoCount(rawCounts[status])
        ? rawCounts[status]
        : entries.filter((todo) => todo.status === status).length,
    ]),
  ) as Record<TodoStatus, number>;
  const total = isTodoCount(rawCounts.total) ? rawCounts.total : entries.length;

  return (
    <section aria-label="Lista de tarefas" className="space-y-2">
      <h4 className="text-[11px] font-semibold text-nexus-text">Checklist</h4>
      <p role="note" className="text-[10px] leading-relaxed text-nexus-muted">
        {AGENT_DECLARED_TODO_CAVEAT}
      </p>
      <div role="group" aria-label="Resumo das tarefas" className="flex flex-wrap gap-1.5 text-[10px]">
        <span className="rounded-full border border-nexus-border/40 bg-nexus-bg/50 px-2 py-1 text-nexus-text">
          {total} {total === 1 ? "tarefa" : "tarefas"}
        </span>
        {TODO_STATUSES.map((status) => (
          <span key={status} className="rounded-full border border-nexus-border/30 px-2 py-1 text-nexus-muted">
            {counts[status]} {counts[status] === 1 ? TODO_COUNT_LABELS[status].one : TODO_COUNT_LABELS[status].many}
          </span>
        ))}
      </div>
      {entries.length > 0 ? (
        <ul aria-label="Tarefas" className="space-y-1.5">
          {entries.map((todo) => (
            <li key={String(todo.id)} className="flex items-start gap-2 rounded-md border border-nexus-border/30 bg-nexus-bg/45 px-2.5 py-2">
              <span className="shrink-0 pt-0.5 font-mono text-[9px] text-nexus-muted">#{todo.id}</span>
              <div className="min-w-0 flex-1">
                <p className="break-words text-[11px] leading-relaxed text-nexus-text">{todo.content}</p>
                <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[9px] text-nexus-muted">
                  <span className={TODO_STATUS_STYLES[todo.status]}>{TODO_STATUS_LABELS[todo.status]}</span>
                  {typeof todo.priority === "string" && todo.priority && (
                    <span>Prioridade {TODO_PRIORITY_LABELS[todo.priority] ?? todo.priority}</span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-md border border-dashed border-nexus-border/40 px-2.5 py-3 text-[10px] text-nexus-muted">
          Sem tarefas nesta lista.
        </p>
      )}
    </section>
  );
}

function ToolResultContents({ result, toolName }: { result: unknown; toolName?: string }) {
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    return <OutputViewer content={serializeOutput(result)} label="Resultado" showLabel={false} />;
  }
  const record = result as Record<string, unknown>;
  if (toolName === "todo_write" || toolName === "todo_list") {
    // execute_tool returns a typed envelope: { ok, result: <handler payload> }.
    // Older events and some adapters already expose the handler payload at the
    // root, so support both without treating a failed outer call as a success.
    const todoPayload = record.ok === true && isRecord(record.result)
      ? record.result
      : record;
    if (isTodoResult(todoPayload)) return <TodoResultContents result={todoPayload} />;
  }
  const stdoutKey = typeof record.stdout === "string" ? "stdout" : typeof record.stdout_tail === "string" ? "stdout_tail" : null;
  const stderrKey = typeof record.stderr === "string" ? "stderr" : typeof record.stderr_tail === "string" ? "stderr_tail" : null;
  if (!stdoutKey && !stderrKey) {
    return <OutputViewer content={serializeOutput(result)} label="Resultado" showLabel={false} />;
  }
  const streamKeys = new Set([stdoutKey, stderrKey].filter((key): key is string => Boolean(key)));
  const metadata = Object.fromEntries(Object.entries(record).filter(([key]) => !streamKeys.has(key)));
  return (
    <div className="space-y-2">
      {stdoutKey && <OutputViewer content={record[stdoutKey] as string} label={stdoutKey === "stdout_tail" ? "stdout · excerto recebido" : "stdout"} />}
      {stderrKey && <OutputViewer content={record[stderrKey] as string} label={stderrKey === "stderr_tail" ? "stderr · excerto recebido" : "stderr"} />}
      {Object.keys(metadata).length > 0 && (
        <details className="rounded border border-nexus-border/30 px-2 py-1">
          <summary className="cursor-pointer text-[9px] text-nexus-muted">Metadados do resultado</summary>
          <div className="mt-2"><OutputViewer content={serializeOutput(metadata)} label="Metadados" /></div>
        </details>
      )}
    </div>
  );
}

function formatCallTimestamp(timestamp: string): string | null {
  const parsed = Date.parse(timestamp);
  if (!Number.isFinite(parsed)) return null;
  return new Intl.DateTimeFormat("pt-PT", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function StatusIcon({ status }: { status: ToolCallItem["status"] }) {
  if (status === "running") {
    return (
      <div className="relative">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-nexus-accent drop-shadow-[0_0_4px_rgba(99,102,241,0.6)]" />
      </div>
    );
  }
  if (status === "awaiting_confirmation") {
    return <ShieldAlert className="h-3.5 w-3.5 text-amber-300" />;
  }
  if (status === "success") {
    return (
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 drop-shadow-[0_0_3px_rgba(52,211,153,0.5)]" />
    );
  }
  return (
    <XCircle className="h-3.5 w-3.5 text-rose-400 drop-shadow-[0_0_3px_rgba(251,113,133,0.5)]" />
  );
}

function StatusConfig(status: ToolCallItem["status"]) {
  if (status === "running") {
    return {
      border: "border-l-2 border-l-nexus-accent/60",
      badge: "bg-nexus-accent/10 text-nexus-accent border border-nexus-accent/20",
      icon: "text-nexus-accent",
      resultBg: "bg-nexus-accent/5 border border-nexus-accent/10",
      resultText: "text-nexus-accent/80",
    };
  }
  if (status === "awaiting_confirmation") {
    return {
      border: "border-l-2 border-l-amber-300/70",
      badge: "bg-amber-400/10 text-amber-200 border border-amber-300/30",
      icon: "text-amber-300",
      resultBg: "bg-amber-400/5 border border-amber-300/10",
      resultText: "text-amber-200/90",
    };
  }
  if (status === "success") {
    return {
      border: "border-l-2 border-l-emerald-400/60",
      badge: "bg-emerald-400/5 text-emerald-400 border border-emerald-400/15",
      icon: "text-emerald-400",
      resultBg: "bg-emerald-500/5 border border-emerald-400/10",
      resultText: "text-emerald-400/80",
    };
  }
  return {
    border: "border-l-2 border-l-rose-400/60",
    badge: "bg-rose-400/10 text-rose-400 border border-rose-400/20",
    icon: "text-rose-400",
    resultBg: "bg-rose-500/5 border border-rose-400/10",
    resultText: "text-rose-400/80",
  };
}

/**
 * One pass over pretty-printed JSON, yielding the same four token classes the
 * old regex used — but as *data*.
 *
 * This used to build an HTML string and hand it to `dangerouslySetInnerHTML`.
 * Tool arguments come from the model, i.e. from a prompt the model was told to
 * obey, so any `<img src=x onerror=…>` in an argument was live HTML in the
 * operator's browser: a prompt-injected model could run script in the IDE.
 * Rendering tokens as React nodes removes the sink entirely — there is no
 * longer a string that can carry markup.
 */
const JSON_TOKEN =
  /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")(\s*:)?|\b(true|false)\b|\b(null)\b|(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g;

interface JsonToken {
  text: string;
  className: string;
}

function tokenizeJson(json: string): JsonToken[] {
  const tokens: JsonToken[] = [];
  let cursor = 0;
  JSON_TOKEN.lastIndex = 0;
  for (let match = JSON_TOKEN.exec(json); match; match = JSON_TOKEN.exec(json)) {
    if (match.index > cursor) {
      tokens.push({ text: json.slice(cursor, match.index), className: "" });
    }
    const [whole, str, colon, bool, nul, num] = match;
    if (str !== undefined) {
      tokens.push({
        text: str,
        className: colon ? "text-indigo-300 font-semibold" : "text-emerald-300/90",
      });
      if (colon) tokens.push({ text: colon, className: "text-nexus-muted" });
    } else if (bool !== undefined) {
      tokens.push({ text: bool, className: "text-purple-300/90" });
    } else if (nul !== undefined) {
      tokens.push({ text: nul, className: "text-slate-400" });
    } else if (num !== undefined) {
      tokens.push({ text: num, className: "text-orange-300/90" });
    } else {
      tokens.push({ text: whole, className: "text-amber-300/90" });
    }
    cursor = match.index + whole.length;
  }
  if (cursor < json.length) {
    tokens.push({ text: json.slice(cursor), className: "text-amber-300/90" });
  }
  return tokens;
}

function JsonSyntaxHighlight({ data }: { data: unknown }) {
  let json: string;
  try {
    json = JSON.stringify(data, null, 2) ?? "null";
  } catch {
    // Circular structures and BigInt reach here from tool results. The old
    // implementation let `JSON.stringify` throw, which took the whole
    // timeline down with it.
    json = '"(unserializável)"';
  }
  const tokens = tokenizeJson(json);

  return (
    <pre className="overflow-x-auto whitespace-pre font-mono text-[10px] leading-relaxed">
      {/* A static, non-reordering token list: the index is the identity. */}
      {tokens.map((token, index) => (
        <span key={index} className={token.className}>
          {token.text}
        </span>
      ))}
    </pre>
  );
}

function getToolErrorSuggestion(name: string, error: string): string | null {
  if (/not found|não existe|nao existe/i.test(error)) {
    if (name === "execute_terminal") return "Usa execute_shell ou run_shell; execute_terminal não está registada.";
    if (name === "search_web") return "Usa web_search ou search_web_v2; search_web é um alias antigo.";
  }
  if (/playwright|dependency|module not found/i.test(error)) {
    return "Instala a dependência opcional indicada antes de repetir a operação.";
  }
  if (/timeout|timed out/i.test(error)) return "Repete com um timeout maior ou reduz o âmbito da operação.";
  return null;
}

function getMemoryOrigins(result: unknown): string[] {
  if (!result || typeof result !== "object") return [];
  const memories = (result as { memories?: unknown }).memories;
  if (!Array.isArray(memories)) return [];
  return Array.from(
    new Set(
      memories
        .map((memory) => {
          if (!memory || typeof memory !== "object") return "";
          const type = String((memory as { type?: unknown }).type ?? "");
          if (type === "session" || type === "conversation") return "sessão";
          if (type === "project" || (memory as { project_id?: unknown }).project_id) return "projeto";
          if (type === "global") return "histórico global";
          return type;
        })
        .filter(Boolean),
    ),
  );
}

function phaseForTool(name: string): number {
  if (/^(read|list|recall|memory)/i.test(name)) return 0;
  if (/search|fetch|browser|consult/i.test(name)) return 1;
  if (/write|delete|move|copy|execute|run|git|install|scaffold/i.test(name)) return 2;
  return 3;
}

function ExecutionStages({ calls }: { calls: ToolCallItem[] }) {
  const labels = ["A ler", "A pesquisar", "A executar", "A validar"];
  const highest = Math.max(...calls.map((call) => phaseForTool(call.name)), 0);
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-nexus-border/30 bg-nexus-bg/20 px-3 py-2">
      {labels.map((label, index) => {
        const completed = highest > index || calls.some((call) => phaseForTool(call.name) === index && call.status === "success");
        const active = highest === index && calls.some((call) => phaseForTool(call.name) === index && call.status === "running");
        return (
          <span
            key={label}
            className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${
              completed ? "bg-emerald-400/10 text-emerald-300" : active ? "bg-nexus-accent/15 text-nexus-accent" : "bg-nexus-bg/60 text-nexus-muted/60"
            }`}
          >
            {label}
          </span>
        );
      })}
    </div>
  );
}

function WebSearchGroup({ calls }: { calls: ToolCallItem[] }) {
  const webCalls = calls.filter((call) => toolKindGroup(call.name) === "web");
  const [open, setOpen] = useState(false);
  const [openQueries, setOpenQueries] = useState<Record<string, boolean>>({});
  if (webCalls.length === 0) return null;
  return (
    <details
      data-testid="web-search-group"
      open={open}
      className="overflow-hidden rounded-lg border border-nexus-border/30 bg-nexus-bg/40"
    >
      <summary
        onClick={(event) => {
          event.preventDefault();
          setOpen((value) => !value);
        }}
        className="flex cursor-pointer list-none items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-medium text-nexus-text/90 transition-colors duration-150 hover:bg-nexus-bg/60"
      >
        <span aria-hidden="true">🔎</span>
        <span>Pesquisou na web</span>
        <span className="tabular-nums text-[10px] font-normal text-nexus-muted">
          {webCalls.length} consulta{webCalls.length === 1 ? "" : "s"}
        </span>
        <ChevronDown className={`ml-auto h-3 w-3 text-nexus-muted transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </summary>
      {open && (
        <div className="space-y-1 border-t border-nexus-border/20 px-2.5 py-2 [content-visibility:auto]">
          {webCalls.map((call) => {
            const query = primaryToolArg(call.args) || call.name;
            const short = query.length > 80 ? `${query.slice(0, 79).trimEnd()}…` : query;
            const sources = extractWebSources(call.result);
            const queryOpen = Boolean(openQueries[call.id]);
            return (
              <details key={call.id} open={queryOpen} className="rounded-md bg-nexus-card/40 px-2 py-1">
                <summary
                  onClick={(event) => {
                    event.preventDefault();
                    setOpenQueries((current) => ({ ...current, [call.id]: !current[call.id] }));
                  }}
                  className="flex cursor-pointer list-none items-center gap-1.5 text-[10px] text-nexus-muted transition-colors duration-150 hover:text-nexus-text"
                  title={query}
                >
                  <StatusIcon status={call.status} />
                  <span className="min-w-0 flex-1 truncate text-nexus-text/85">{short}</span>
                  {sources.length > 0 && (
                    <span className="shrink-0 tabular-nums text-[9px]">{sources.length} fontes</span>
                  )}
                </summary>
                {queryOpen && (
                  <div className="mt-1.5 space-y-1 border-t border-nexus-border/20 pt-1.5">
                    {sources.length > 0 ? (
                      <ul className="space-y-0.5">
                        {sources.map((source, index) => (
                          <li key={`${call.id}-src-${index}`} className="truncate font-mono text-[9px] text-sky-200/70" title={source}>
                            {isHttpSource(source) ? (
                              <a href={source} target="_blank" rel="noopener noreferrer" className="hover:underline">
                                {source}
                              </a>
                            ) : source}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-[9px] text-nexus-muted/70">sem fontes extraídas — ver detalhe na timeline</p>
                    )}
                  </div>
                )}
              </details>
            );
          })}
        </div>
      )}
    </details>
  );
}

function isHttpSource(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

function TerminalOutputLazy({ content, label }: { content: string; label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details open={open} className="mt-1.5 overflow-hidden rounded-md border border-nexus-border/20 bg-nexus-bg/60">
      <summary
        onClick={(event) => {
          event.preventDefault();
          setOpen((value) => !value);
        }}
        className="cursor-pointer list-none px-2 py-1 text-[9px] text-nexus-muted transition-colors duration-150 hover:text-nexus-text"
      >
        {open ? "ocultar saída" : "ver saída"}
      </summary>
      {open && (
        <div className="border-t border-nexus-border/20 p-1.5 [content-visibility:auto]">
          <OutputViewer content={content} label={label} />
        </div>
      )}
    </details>
  );
}

function TerminalGroup({ calls }: { calls: ToolCallItem[] }) {
  const terminalCalls = calls.filter((call) => toolKindGroup(call.name) === "terminal");
  const [open, setOpen] = useState(false);
  if (terminalCalls.length === 0) return null;
  const errors = terminalCalls.filter((call) => call.status === "error").length;
  return (
    <details
      data-testid="terminal-group"
      open={open}
      className="overflow-hidden rounded-lg border border-nexus-border/30 bg-nexus-bg/40"
    >
      <summary
        onClick={(event) => {
          event.preventDefault();
          setOpen((value) => !value);
        }}
        className="flex cursor-pointer list-none items-center gap-1.5 px-2.5 py-1.5 font-mono text-[11px] font-medium text-nexus-text/90 transition-colors duration-150 hover:bg-nexus-bg/60"
      >
        <span aria-hidden="true" className="text-nexus-muted">&gt;</span>
        <span className="font-sans">Terminal</span>
        <span className="tabular-nums font-sans text-[10px] font-normal text-nexus-muted">
          {terminalCalls.length} {terminalCalls.length === 1 ? "ação" : "ações"}
        </span>
        {errors > 0 && (
          <span className="rounded-full bg-rose-500/10 px-1.5 py-px font-sans text-[9px] text-rose-300">
            {errors} erro{errors === 1 ? "" : "s"}
          </span>
        )}
        <ChevronDown className={`ml-auto h-3 w-3 text-nexus-muted transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </summary>
      {open && (
        <div className="space-y-1 border-t border-nexus-border/20 px-2.5 py-2 [content-visibility:auto]">
          {terminalCalls.map((call) => {
            const command = primaryToolArg(call.args) || call.name;
            const short = command.length > 72 ? `${command.slice(0, 71).trimEnd()}…` : command;
            const duration = typeof call.durationMs === "number" ? formatRunDuration(call.durationMs) : "";
            const output = typeof call.result === "string"
              ? call.result
              : call.result !== undefined
                ? serializeOutput(call.result)
                : call.error ?? "";
            return (
              <div
                key={call.id}
                className={`rounded-md px-2 py-1 font-mono text-[10px] leading-relaxed ${
                  call.status === "error" ? "border border-rose-400/30 bg-rose-500/5 text-rose-200" : "bg-nexus-card/40 text-nexus-text/85"
                }`}
              >
                <div className="flex min-w-0 items-center gap-1.5">
                  <span aria-hidden="true" className={call.status === "error" ? "text-rose-400" : call.status === "running" ? "animate-pulse text-nexus-accent" : "text-emerald-400"}>
                    {call.status === "error" ? "✕" : call.status === "running" ? "◉" : "✓"}
                  </span>
                  <span className="min-w-0 flex-1 truncate" title={command}>
                    {short}{duration ? ` · ${duration}` : ""}
                  </span>
                </div>
                {call.status === "error" && call.error && (
                  <p className="mt-0.5 break-words font-sans text-[9px] text-rose-300/90">{call.error}</p>
                )}
                {output.trim() && <TerminalOutputLazy content={output} label={`Saída de ${call.name}`} />}
              </div>
            );
          })}
        </div>
      )}
    </details>
  );
}

function ToolCallTimeline({ calls, sessionId }: ToolCallTimelineProps) {
  const reactId = useId();
  const timelineBodyId = `tool-call-timeline-${reactId.replace(/:/g, "")}`;
  const [expanded, setExpanded] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [retryResults, setRetryResults] = useState<Record<string, unknown>>({});
  const [retryErrors, setRetryErrors] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState<string | null>(null);
  if (!calls || calls.length === 0) return null;

  const runningCount = calls.filter((c) => c.status === "running").length;
  const successCount = calls.filter((c) => c.status === "success").length;
  const errorCount = calls.filter((c) => c.status === "error").length;
  const confirmationCount = calls.filter((c) => c.status === "awaiting_confirmation").length;
  const callGroups = groupAdjacentToolCalls(calls);
  const headerGroups = callGroups.slice(0, 4);
  const headerCallCount = headerGroups.reduce((count, group) => count + group.length, 0);

  const retryTool = async (call: ToolCallItem, confirmationId?: string) => {
    if (!sessionId || sessionId === "default") {
      setRetryErrors((current) => ({
        ...current,
        [call.id]: "Esta conversa não tem uma sessão válida para repetir a ferramenta.",
      }));
      return;
    }
    setRetrying(call.id);
    setRetryErrors((current) => {
      if (!(call.id in current)) return current;
      const next = { ...current };
      delete next[call.id];
      return next;
    });
    try {
      const result = await executeTool(call.name, call.args, sessionId, confirmationId);
      setRetryResults((current) => ({ ...current, [call.id]: result }));
    } catch (reason) {
      // Used to escape as an unhandled rejection: `void retryTool(call)`
      // discarded it, so a failing retry looked like a button that did nothing.
      const message = reason instanceof Error ? reason.message : String(reason);
      setRetryErrors((current) => ({ ...current, [call.id]: message }));
      log.warn(`Retry of tool ${call.name} failed:`, reason);
    } finally {
      setRetrying(null);
    }
  };

  const resolveConfirmation = async (call: ToolCallItem, approved: boolean) => {
    if (!call.confirmationId) return;
    setConfirming(call.id);
    try {
      await confirmTool(call.confirmationId, approved);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setRetryErrors((current) => ({ ...current, [call.id]: message }));
      log.warn(`Confirmation ${call.confirmationId} failed:`, reason);
    } finally {
      setConfirming(null);
    }
  };

  const approveAndRetry = async (call: ToolCallItem) => {
    const result = retryResults[call.id] as { confirmation_required?: boolean; confirmation_id?: string } | undefined;
    if (!result?.confirmation_required || !result.confirmation_id) return;
    setConfirming(call.id);
    setRetryResults((current) => {
      const next = { ...current };
      delete next[call.id];
      return next;
    });
    try {
      await confirmTool(result.confirmation_id, true);
      await retryTool(call, result.confirmation_id);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setRetryErrors((current) => ({ ...current, [call.id]: message }));
      log.warn(`Approved retry of tool ${call.name} failed:`, reason);
    } finally {
      setConfirming(null);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.16, ease: "easeOut" }}
      className="mt-3 overflow-hidden rounded-xl border border-nexus-border/60 bg-nexus-panel/50"
    >
      <motion.button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-controls={timelineBodyId}
        className="flex w-full flex-wrap items-center justify-between gap-2.5 p-3 text-left transition-colors duration-150 hover:bg-nexus-card/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-accent/50"
        whileHover={{ scale: 1.005 }}
        whileTap={{ scale: 0.995 }}
      >
        <div className="flex flex-wrap items-center gap-2">
          {headerGroups.map((group) => {
            const call = group[0];
            const { label, Icon } = getToolDisplay(call.name);
            const statusConfig = StatusConfig(call.status);
            return (
              <motion.span
                key={call.id}
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold ${statusConfig.badge}`}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.05 }}
              >
                <Icon className="h-3 w-3" />
                {label}{group.length > 1 ? ` × ${group.length}` : ""}
                <StatusIcon status={call.status} />
              </motion.span>
            );
          })}
          {calls.length > headerCallCount && (
            <span className="rounded-full bg-nexus-bg/60 px-2 py-0.5 text-[10px] font-medium text-nexus-muted ring-1 ring-nexus-border/50">
              +{calls.length - headerCallCount}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px] font-medium text-nexus-muted">
          {runningCount > 0 && (
            <span className="flex items-center gap-1 text-nexus-accent">
              <motion.span
                className="inline-block h-1.5 w-1.5 rounded-full bg-nexus-accent"
                animate={{ scale: [1, 1.4, 1], opacity: [0.5, 1, 0.5] }}
                transition={{ duration: 1.5, repeat: Infinity }}
              />
              {runningCount} a correr
            </span>
          )}
          {successCount > 0 && (
            <span className="text-emerald-400">{successCount} ok</span>
          )}
          {errorCount > 0 && (
            <span className="text-rose-400">
              {errorCount} erro{errorCount === 1 ? "" : "s"}
            </span>
          )}
          {confirmationCount > 0 && (
            <span className="text-amber-300">
              {confirmationCount} aprovaç{confirmationCount === 1 ? "ão" : "ões"}
            </span>
          )}
          <motion.div
            className="flex items-center gap-1 rounded-full bg-nexus-bg/60 p-1 ring-1 ring-nexus-border/50"
            whileHover={{ scale: 1.1 }}
          >
            {expanded ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
          </motion.div>
        </div>
      </motion.button>

      <ExecutionStages calls={calls} />

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            id={timelineBodyId}
            data-testid="tool-call-timeline-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.16, ease: "easeInOut" }}
            className="overflow-hidden [content-visibility:auto]"
          >
            <div className="space-y-2.5 border-t border-nexus-border/30 bg-nexus-bg/20 p-3">
              <div className="space-y-2">
                <WebSearchGroup calls={calls} />
                <TerminalGroup calls={calls} />
              </div>
              {calls.map((call, idx) => {
                const { label, Icon } = getToolDisplay(call.name);
                const statusConfig = StatusConfig(call.status);
                return (
                  <motion.div
                    key={call.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.05 }}
                    className={`rounded-xl border border-nexus-border/60 bg-nexus-card/45 p-3 ${statusConfig.border}`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-nexus-bg/80 text-[9px] font-bold text-nexus-muted ring-1 ring-nexus-border/50">
                          {idx + 1}
                        </span>
                        <Icon className={`h-4 w-4 ${statusConfig.icon}`} />
                        <span className="text-xs font-semibold text-nexus-text">
                          {label}
                        </span>
                        <span className="rounded bg-nexus-bg/60 px-1.5 py-0.5 font-mono text-[9px] text-nexus-muted ring-1 ring-nexus-border/40">
                          {call.name}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusIcon status={call.status} />
                        {call.durationMs !== undefined && (
                          <span className="rounded-full bg-nexus-bg/60 px-2 py-0.5 font-mono text-[10px] text-nexus-muted ring-1 ring-nexus-border/40">
                            {call.durationMs}ms
                          </span>
                        )}
                        {formatCallTimestamp(call.timestamp) && (
                          <time
                            dateTime={call.timestamp}
                            className="font-mono text-[9px] text-nexus-muted/75"
                            aria-label="Hora da chamada"
                          >
                            {formatCallTimestamp(call.timestamp)}
                          </time>
                        )}
                      </div>
                    </div>
                    {call.args && Object.keys(call.args).length > 0 && (
                      <div className="mt-2.5 overflow-hidden rounded-lg border border-nexus-border/30 bg-nexus-bg/80 p-2.5 shadow-inner">
                        <div className="mb-1.5 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-wider text-nexus-muted">
                          <Code2 className="h-3 w-3" />
                          Argumentos
                        </div>
                        <JsonSyntaxHighlight data={call.args} />
                      </div>
                    )}
                    {call.status === "success" && call.result !== undefined && (
                      <motion.div
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        className={`mt-2.5 overflow-hidden rounded-lg ${statusConfig.resultBg} p-2.5 shadow-inner`}
                      >
                        <div className="mb-1.5 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-wider text-emerald-400/80">
                          <CheckCircle2 className="h-3 w-3" />
                          Resultado
                        </div>
                        <ToolResultContents result={call.result} toolName={call.name} />
                      </motion.div>
                    )}
                    {call.status === "error" && call.error && (
                      <motion.div
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="mt-2.5 overflow-hidden rounded-lg border border-rose-400/20 bg-rose-500/5 p-2.5 shadow-inner"
                      >
                        <div className="mb-1.5 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-wider text-rose-400/80">
                          <XCircle className="h-3 w-3" />
                          Erro
                        </div>
                        <div className="text-[10px] leading-relaxed text-rose-400/80">
                          {call.error}
                        </div>
                        {(() => {
                          const suggestion = getToolErrorSuggestion(call.name, call.error);
                          return suggestion ? (
                            <div className="mt-2 rounded border border-amber-300/20 bg-amber-300/5 p-2 text-[10px] text-amber-200/90">
                              Sugestão: {suggestion}
                            </div>
                          ) : null;
                        })()}
                        <button
                          type="button"
                          disabled={retrying === call.id}
                          onClick={() => void retryTool(call)}
                          className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-rose-300/25 px-2 py-1 text-[10px] font-semibold text-rose-200 hover:bg-rose-400/10 disabled:opacity-50"
                        >
                          <RotateCcw className={`h-3 w-3 ${retrying === call.id ? "animate-spin" : ""}`} />
                          {retrying === call.id ? "A repetir…" : "Repetir ferramenta"}
                        </button>
                        {retryErrors[call.id] !== undefined && (
                          <div className="mt-2 rounded border border-rose-400/30 bg-rose-500/10 p-2 text-[10px] text-rose-200">
                            A repetição falhou: {retryErrors[call.id]}
                          </div>
                        )}
                      </motion.div>
                    )}
                    {call.status === "awaiting_confirmation" && (
                      <motion.div className="mt-2.5 rounded-lg border border-amber-300/20 bg-amber-300/5 p-2.5">
                        <div className="text-[10px] leading-relaxed text-amber-100/90">
                          Esta operação pode alterar ficheiros, executar código ou aceder a um serviço externo.
                          {call.suggestion && <span className="block mt-1 text-amber-200/70">{call.suggestion}</span>}
                        </div>
                        <div className="mt-2 flex gap-2">
                          <button
                            type="button"
                            disabled={confirming === call.id}
                            onClick={() => void resolveConfirmation(call, true)}
                            className="rounded-md bg-emerald-400/15 px-2 py-1 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-400/25 disabled:opacity-50"
                          >
                            Confirmar
                          </button>
                          <button
                            type="button"
                            disabled={confirming === call.id}
                            onClick={() => void resolveConfirmation(call, false)}
                            className="rounded-md bg-rose-400/10 px-2 py-1 text-[10px] font-semibold text-rose-200 hover:bg-rose-400/20 disabled:opacity-50"
                          >
                            Recusar
                          </button>
                        </div>
                        {retryErrors[call.id] !== undefined && (
                          <div className="mt-2 rounded border border-rose-400/30 bg-rose-500/10 p-2 text-[10px] text-rose-200">
                            A confirmação falhou: {retryErrors[call.id]}
                          </div>
                        )}
                      </motion.div>
                    )}
                    {retryResults[call.id] !== undefined && (
                      <div className="mt-2.5 rounded-lg border border-cyan-300/20 bg-cyan-300/5 p-2.5 text-[10px] text-cyan-100/90">
                        <div className="font-semibold">Resultado da repetição</div>
                        <div className="mt-1">
                          <ToolResultContents result={retryResults[call.id]} toolName={call.name} />
                        </div>
                        {typeof retryResults[call.id] === "object" && retryResults[call.id] !== null &&
                          (retryResults[call.id] as { confirmation_required?: boolean }).confirmation_required && (
                            <button
                              type="button"
                              onClick={() => void approveAndRetry(call)}
                              className="mt-2 rounded-md bg-amber-400/15 px-2 py-1 font-semibold text-amber-200 hover:bg-amber-400/25"
                            >
                              Autorizar e executar
                            </button>
                          )}
                      </div>
                    )}
                    {(() => {
                      // Computed once: this used to re-walk the whole result
                      // object twice per render, per tool call.
                      const memoryOrigins = getMemoryOrigins(call.result);
                      if (memoryOrigins.length === 0) return null;
                      return (
                        <div className="mt-2 flex flex-wrap gap-1 text-[9px] text-cyan-200/80">
                          {memoryOrigins.map((origin) => (
                            <span key={origin} className="rounded-full bg-cyan-400/10 px-2 py-0.5">
                              Memória: {origin}
                            </span>
                          ))}
                        </div>
                      );
                    })()}
                  </motion.div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export default memo(ToolCallTimeline);
