"use client";
import { useToolsStore } from "../../stores/toolsStore";
import { motion } from "framer-motion";
import { Wrench, Check, AlertTriangle, Ban, ShieldAlert, Loader2 } from "lucide-react";
import { useEffect } from "react";

export default function ToolsPanel() {
  const { tools, toggleTool, loadTools, toolsLoading, toolsError } = useToolsStore();

  useEffect(() => {
    void loadTools();
  }, [loadTools]);

  const statusLabel = (status?: string) => {
    if (status === "missing_dependency") return "dependência em falta";
    if (status === "blocked") return "bloqueada";
    if (status === "requires_confirmation") return "requer confirmação";
    return "disponível";
  };

  const statusIcon = (status?: string) => {
    if (status === "missing_dependency") return <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />;
    if (status === "blocked") return <Ban className="h-3.5 w-3.5 text-slate-400" />;
    if (status === "requires_confirmation") return <ShieldAlert className="h-3.5 w-3.5 text-amber-300" />;
    return <Check className="h-3.5 w-3.5 text-emerald-300" />;
  };

  return (
    <motion.div
      initial={{ x: 20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="rounded border border-nexus-border bg-nexus-panel/50 p-3"
    >
      <div className="mb-3 flex items-center gap-2">
        <Wrench className="h-4 w-4 text-nexus-accent" />
        <span className="text-sm font-semibold">Tools do registry</span>
      </div>
      {toolsLoading && <div className="mb-2 flex items-center gap-2 text-[10px] text-nexus-muted"><Loader2 className="h-3 w-3 animate-spin" /> A carregar estado real…</div>}
      {toolsError && <div className="mb-2 rounded border border-rose-400/20 bg-rose-400/5 p-2 text-[10px] text-rose-200">Não foi possível carregar o registry: {toolsError}</div>}
      <div className="space-y-2">
        {tools.map((tool) => {
          const status = tool.status ?? (tool.enabled ? "available" : "blocked");
          const interactive = status !== "missing_dependency";
          return (
            <motion.button
              key={tool.name}
              type="button"
              disabled={!interactive}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={async () => {
                if (interactive) await toggleTool(tool.name);
              }}
              className={`flex w-full items-center justify-between rounded border p-2 text-left transition-colors ${
                status === "available" || status === "requires_confirmation"
                  ? "border-nexus-border bg-nexus-border/30"
                  : "border-nexus-border/30 bg-transparent opacity-60"
              }`}
            >
              <div>
                <div className="text-xs font-medium">{tool.name}</div>
                <div className="text-xs text-gray-500">{tool.description}</div>
                <div className="mt-1 text-[9px] text-nexus-muted">{statusLabel(status)}{tool.dependency ? ` · ${tool.dependency}` : ""}</div>
              </div>
              {statusIcon(status)}
            </motion.button>
          );
        })}
      </div>
    </motion.div>
  );
}
