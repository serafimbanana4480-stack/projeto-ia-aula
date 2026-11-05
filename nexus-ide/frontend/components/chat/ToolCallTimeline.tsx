"use client";

import { useEffect, useMemo, useRef, useState, memo } from "react";
import {
  ChevronDown,
  ChevronUp,
  Copy,
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
  RotateCcw,
  ShieldAlert,
  Square,
} from "lucide-react";
import type { ToolCallItem } from "../../lib/types";
import { confirmTool, executeTool } from "../../lib/api";
import { looksLikeDiff, terminalFields, toolAction, toolKind } from "../../lib/runLifecycle";

interface ToolCallTimelineProps {
  calls: ToolCallItem[];
  sessionId?: string;
  onCancel?: () => void;
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
  recall_context: "Memória",
  analyze_data: "Analisar dados",
  generate_report: "Relatório",
  data_analysis: "Analisar dados",
  report_generation: "Gerar relatório",
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
};

function getToolDisplay(name: string) {
  return {
    label: TOOL_LABELS[name] || name.replace(/_/g, " "),
    Icon: TOOL_ICONS[name] || Wrench,
  };
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
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />;
  }
  if (status === "cancelled") {
    return <Square className="h-3.5 w-3.5 text-nexus-muted" />;
  }
  return <XCircle className="h-3.5 w-3.5 text-rose-400" />;
}

function StatusConfig(status: ToolCallItem["status"]) {
  if (status === "running") {
    return {
      border: "border-l-2 border-l-nexus-accent/60",
      badge: "bg-gradient-to-br from-nexus-accent/20 to-indigo-500/10 text-nexus-accent border border-nexus-accent/30 shadow-[0_2px_8px_rgba(99,102,241,0.2)]",
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
      badge: "bg-gradient-to-br from-emerald-500/20 to-green-500/10 text-emerald-400 border border-emerald-400/30 shadow-[0_2px_8px_rgba(52,211,153,0.2)]",
      icon: "text-emerald-400",
      resultBg: "bg-emerald-500/5 border border-emerald-400/10",
      resultText: "text-emerald-400/80",
    };
  }
  return {
    border: "border-l-2 border-l-rose-400/60",
    badge: "bg-gradient-to-br from-rose-500/20 to-red-500/10 text-rose-400 border border-rose-400/30 shadow-[0_2px_8px_rgba(251,113,133,0.2)]",
    icon: "text-rose-400",
    resultBg: "bg-rose-500/5 border border-rose-400/10",
    resultText: "text-rose-400/80",
  };
}

function JsonBlock({ data }: { data: unknown }) {
  const json = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <pre className="max-h-56 overflow-auto whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-nexus-text">
      {json}
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

function statusLabel(status: ToolCallItem["status"]): string {
  switch (status) {
    case "running":
      return "a correr";
    case "awaiting_confirmation":
      return "à espera";
    case "success":
      return "feito";
    case "cancelled":
      return "cancelado";
    default:
      return "falhou";
  }
}

function resultText(result: unknown): string {
  if (typeof result === "string") return result;
  if (result == null) return "";
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

function DiffBlock({ text }: { text: string }) {
  return (
    <pre className="max-h-64 overflow-auto font-mono text-[10px] leading-relaxed">
      {text.split("\n").map((line, index) => {
        const tone = line.startsWith("+") && !line.startsWith("+++")
          ? "text-emerald-300"
          : line.startsWith("-") && !line.startsWith("---")
            ? "text-rose-300"
            : "text-nexus-muted";
        return (
          <div key={`${index}-${line.slice(0, 12)}`} className={tone}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

function ToolRow({
  call,
  sessionId,
  onCancel,
}: {
  call: ToolCallItem;
  sessionId: string;
  onCancel?: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(call.status === "awaiting_confirmation" || call.status === "error");
  useEffect(() => {
    if (!open) return;
    rootRef.current?.scrollIntoView({ block: "nearest" });
  }, [open]);
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [retryResult, setRetryResult] = useState<unknown>();
  const { label } = getToolDisplay(call.name);
  const kind = toolKind(call.name);
  const action = toolAction(call.name, call.args);
  const terminal = useMemo(() => terminalFields(call.result), [call.result]);
  const plain = resultText(retryResult ?? call.result);
  const diff = !terminal && looksLikeDiff(plain) ? plain : "";
  const status = StatusConfig(call.status);
  const output = terminal
    ? [terminal.stdout, terminal.stderr].filter(Boolean).join("\n")
    : plain;
  const filtered = query
    ? output.split("\n").filter((line) => line.toLowerCase().includes(query.toLowerCase())).join("\n")
    : output;

  async function copyOutput() {
    try {
      await navigator.clipboard.writeText(output);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div ref={rootRef} data-testid="tool-row" className={`rounded-lg border border-white/10 bg-black/20 ${status.border}`}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
        aria-expanded={open}
      >
        <span className="w-16 shrink-0 font-mono text-[10px] uppercase tracking-wide text-nexus-faint">{kind}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-nexus-text">
          <span className="text-nexus-muted">{label}</span>
          <span className="px-1 text-nexus-faint">·</span>
          {action}
        </span>
        <span className={`shrink-0 font-mono text-[10px] ${status.icon}`}>{statusLabel(call.status)}</span>
        <span className="w-14 shrink-0 text-right font-mono text-[10px] text-nexus-faint">
          {call.durationMs != null ? `${call.durationMs} ms` : "—"}
        </span>
        {open ? <ChevronUp className="h-3 w-3 text-nexus-faint" /> : <ChevronDown className="h-3 w-3 text-nexus-faint" />}
      </button>
      {open && (
        <div className="space-y-2 border-t border-white/8 px-2.5 py-2">
          {Object.keys(call.args || {}).length > 0 && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide text-nexus-faint">Argumentos</div>
              <JsonBlock data={call.args} />
            </div>
          )}
          {terminal && (
            <div data-testid="terminal-output" className="flex flex-wrap items-center gap-2 text-[10px] text-nexus-muted">
              <span>cwd {terminal.cwd || "—"}</span>
              <span>exit {terminal.exitCode ?? "—"}</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Procurar na saída"
                aria-label="Procurar na saída do terminal"
                className="min-w-0 flex-1 rounded border border-white/10 bg-transparent px-2 py-1 text-[11px] text-nexus-text outline-none"
              />
              <button type="button" onClick={() => void copyOutput()} className="inline-flex items-center gap-1 rounded px-1.5 py-1 hover:bg-white/5">
                <Copy className="h-3 w-3" />
                {copied ? "Copiado" : "Copiar"}
              </button>
              {call.status === "running" && onCancel && (
                <button type="button" onClick={onCancel} className="rounded px-1.5 py-1 text-rose-300 hover:bg-rose-400/10">
                  Parar
                </button>
              )}
            </div>
          )}
          {diff ? <DiffBlock text={diff} /> : filtered ? <JsonBlock data={filtered} /> : null}
          {call.error && <p className="text-[11px] text-rose-300">{call.error}</p>}
          {call.status === "error" && call.error && getToolErrorSuggestion(call.name, call.error) && (
            <p className="text-[11px] text-amber-200">Sugestão: {getToolErrorSuggestion(call.name, call.error)}</p>
          )}
          {call.status === "error" && (
            <button
              type="button"
              disabled={retrying}
              onClick={() => {
                setRetrying(true);
                void executeTool(call.name, call.args, sessionId)
                  .then((result) => setRetryResult(result))
                  .finally(() => setRetrying(false));
              }}
              className="inline-flex items-center gap-1 rounded border border-rose-300/30 px-2 py-1 text-[10px] text-rose-200"
            >
              <RotateCcw className={`h-3 w-3 ${retrying ? "animate-spin" : ""}`} />
              Repetir
            </button>
          )}
          {call.status === "awaiting_confirmation" && (
            <div className="flex gap-2">
              <button
                type="button"
                disabled={confirming || !call.confirmationId}
                onClick={() => {
                  if (!call.confirmationId) return;
                  setConfirming(true);
                  void confirmTool(call.confirmationId, true).finally(() => setConfirming(false));
                }}
                className="rounded bg-emerald-400/15 px-2 py-1 text-[10px] font-semibold text-emerald-200"
              >
                Permitir uma vez
              </button>
              <button
                type="button"
                disabled={confirming || !call.confirmationId}
                onClick={() => {
                  if (!call.confirmationId) return;
                  setConfirming(true);
                  void confirmTool(call.confirmationId, false).finally(() => setConfirming(false));
                }}
                className="rounded bg-rose-400/10 px-2 py-1 text-[10px] font-semibold text-rose-200"
              >
                Recusar
              </button>
            </div>
          )}
          {getMemoryOrigins(call.result).length > 0 && (
            <div className="flex flex-wrap gap-1 text-[10px] text-cyan-200/80">
              {getMemoryOrigins(call.result).map((origin) => (
                <span key={origin} className="rounded-full bg-cyan-400/10 px-2 py-0.5">Memória: {origin}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolCallTimeline({ calls, sessionId = "default", onCancel }: ToolCallTimelineProps) {
  if (!calls || calls.length === 0) return null;
  return (
    <div className="mt-3 space-y-1.5" data-testid="tool-timeline">
      {calls.map((call) => (
        <ToolRow key={call.id} call={call} sessionId={sessionId} onCancel={onCancel} />
      ))}
    </div>
  );
}

export default memo(ToolCallTimeline);
