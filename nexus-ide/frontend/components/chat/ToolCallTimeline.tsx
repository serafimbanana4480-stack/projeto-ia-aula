"use client";

import { useState, memo } from "react";
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
} from "lucide-react";
import type { ToolCallItem } from "../../lib/types";

interface ToolCallTimelineProps {
  calls: ToolCallItem[];
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
      badge: "bg-gradient-to-br from-nexus-accent/20 to-indigo-500/10 text-nexus-accent border border-nexus-accent/30 shadow-[0_2px_8px_rgba(99,102,241,0.2)]",
      icon: "text-nexus-accent",
      resultBg: "bg-nexus-accent/5 border border-nexus-accent/10",
      resultText: "text-nexus-accent/80",
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

function JsonSyntaxHighlight({ data }: { data: unknown }) {
  const json = JSON.stringify(data, null, 2);

  const highlighted = json
    .replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (match: string) => {
        let cls = "text-amber-300/90";
        if (/^"/.test(match)) {
          if (/:$/.test(match)) {
            cls = "text-indigo-300 font-semibold";
          } else {
            cls = "text-emerald-300/90";
          }
        } else if (/true|false/.test(match)) {
          cls = "text-purple-300/90";
        } else if (/null/.test(match)) {
          cls = "text-slate-400";
        } else if (!isNaN(Number(match))) {
          cls = "text-orange-300/90";
        }
        return `<span class="${cls}">${match}</span>`;
      },
    )
    .replace(/\n/g, "<br/>")
    .replace(/\s/g, "&nbsp;");

  return (
    <pre
      className="font-mono text-[10px] leading-relaxed"
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  );
}

function ToolCallTimeline({ calls }: ToolCallTimelineProps) {
  const [expanded, setExpanded] = useState(false);
  if (!calls || calls.length === 0) return null;

  const runningCount = calls.filter((c) => c.status === "running").length;
  const successCount = calls.filter((c) => c.status === "success").length;
  const errorCount = calls.filter((c) => c.status === "error").length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="mt-3 overflow-hidden rounded-xl border border-nexus-border/50 bg-nexus-panel/50 shadow-lg backdrop-blur-sm"
    >
      <motion.button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between gap-3 p-3 text-left transition-colors duration-200 hover:bg-nexus-bg/40"
        whileHover={{ scale: 1.005 }}
        whileTap={{ scale: 0.995 }}
      >
        <div className="flex flex-wrap items-center gap-2">
          {calls.slice(0, 4).map((call) => {
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
                {label}
                <StatusIcon status={call.status} />
              </motion.span>
            );
          })}
          {calls.length > 4 && (
            <span className="rounded-full bg-nexus-bg/60 px-2 py-0.5 text-[10px] font-medium text-nexus-muted ring-1 ring-nexus-border/50">
              +{calls.length - 4}
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
            <span className="text-rose-400">{errorCount} erro</span>
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

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="space-y-2.5 border-t border-nexus-border/30 bg-nexus-bg/20 p-3">
              {calls.map((call, idx) => {
                const { label, Icon } = getToolDisplay(call.name);
                const statusConfig = StatusConfig(call.status);
                return (
                  <motion.div
                    key={call.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.05 }}
                    className={`rounded-lg border border-nexus-border/40 bg-nexus-card/80 p-3 shadow-md ${statusConfig.border}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2.5">
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
                        <div
                          className={`text-[10px] leading-relaxed ${statusConfig.resultText} whitespace-pre-wrap font-light`}
                        >
                          {typeof call.result === "string"
                            ? call.result
                            : JSON.stringify(call.result, null, 2)}
                        </div>
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
                      </motion.div>
                    )}
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
