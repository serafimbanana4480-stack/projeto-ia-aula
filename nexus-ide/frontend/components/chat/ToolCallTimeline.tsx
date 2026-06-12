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
    return <Loader2 className="h-3 w-3 animate-spin text-nexus-accent" />;
  }
  if (status === "success") {
    return <CheckCircle2 className="h-3 w-3 text-green-500" />;
  }
  return <XCircle className="h-3 w-3 text-red-500" />;
}

function StatusClass(status: ToolCallItem["status"]) {
  if (status === "running") {
    return "border-nexus-accent/40 bg-nexus-accent/10 text-nexus-accent";
  }
  if (status === "success") {
    return "border-green-500/40 bg-green-500/10 text-green-500";
  }
  return "border-red-500/40 bg-red-500/10 text-red-500";
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
      className="mt-3 rounded-lg border border-nexus-border/60 bg-nexus-panel/40 p-2"
    >
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          {calls.slice(0, 4).map((call) => {
            const { label, Icon } = getToolDisplay(call.name);
            return (
              <span
                key={call.id}
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${StatusClass(
                  call.status,
                )}`}
              >
                <Icon className="h-3 w-3" />
                {label}
                <StatusIcon status={call.status} />
              </span>
            );
          })}
          {calls.length > 4 && (
            <span className="text-[10px] text-nexus-muted">
              +{calls.length - 4}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-nexus-muted">
          {runningCount > 0 && (
            <span className="text-nexus-accent">{runningCount} a correr</span>
          )}
          {successCount > 0 && (
            <span className="text-green-500">{successCount} ok</span>
          )}
          {errorCount > 0 && (
            <span className="text-red-500">{errorCount} erro</span>
          )}
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </div>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="mt-2 overflow-hidden"
          >
            <div className="space-y-2">
              {calls.map((call, idx) => {
                const { label, Icon } = getToolDisplay(call.name);
                return (
                  <div
                    key={call.id}
                    className="rounded border border-nexus-border/50 bg-nexus-card/60 p-2 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-nexus-muted">
                          {idx + 1}.
                        </span>
                        <Icon className="h-3.5 w-3.5 text-nexus-muted" />
                        <span className="font-medium">{label}</span>
                        <span className="font-mono text-[10px] text-nexus-muted">
                          {call.name}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <StatusIcon status={call.status} />
                        {call.durationMs !== undefined && (
                          <span className="text-[10px] text-nexus-muted">
                            {call.durationMs}ms
                          </span>
                        )}
                      </div>
                    </div>
                    <pre className="mt-1.5 max-h-24 overflow-auto rounded bg-nexus-bg p-1.5 text-[10px] text-nexus-muted">
                      {JSON.stringify(call.args, null, 2)}
                    </pre>
                    {call.status === "success" && call.result !== undefined && (
                      <pre className="mt-1.5 max-h-32 overflow-auto rounded bg-green-500/5 p-1.5 text-[10px] text-green-600 dark:text-green-400">
                        {typeof call.result === "string"
                          ? call.result
                          : JSON.stringify(call.result, null, 2)}
                      </pre>
                    )}
                    {call.status === "error" && call.error && (
                      <div className="mt-1.5 rounded bg-red-500/5 p-1.5 text-[10px] text-red-500">
                        {call.error}
                      </div>
                    )}
                  </div>
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
