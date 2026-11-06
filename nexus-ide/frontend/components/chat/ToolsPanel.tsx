"use client";
import { useMemo, useState, useEffect } from "react";
import { Wrench, Check, AlertTriangle, Ban, ShieldAlert, Loader2, Search } from "lucide-react";
import { useToolsStore } from "../../stores/toolsStore";

export default function ToolsPanel() {
  const { tools, toggleTool, loadTools, toolsLoading, toolsError } = useToolsStore();
  const [query, setQuery] = useState("");

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
    if (status === "missing_dependency") return <AlertTriangle className="h-3.5 w-3.5 text-nexus-accent3" />;
    if (status === "blocked") return <Ban className="h-3.5 w-3.5 text-nexus-muted" />;
    if (status === "requires_confirmation") return <ShieldAlert className="h-3.5 w-3.5 text-nexus-accent3" />;
    return <Check className="h-3.5 w-3.5 text-nexus-accent2" />;
  };

  const needle = query.trim().toLowerCase();
  const visible = useMemo(
    () => tools.filter((tool) => {
      if (!needle) return true;
      return tool.name.toLowerCase().includes(needle) || (tool.description ?? "").toLowerCase().includes(needle);
    }),
    [needle, tools],
  );
  const ready = tools.filter((tool) => {
    const status = tool.status ?? (tool.enabled ? "available" : "blocked");
    return status === "available" || status === "requires_confirmation";
  }).length;

  return (
    <section aria-label="Ferramentas do registry" className="nx-work-surface rounded-2xl border border-nexus-border p-3">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-nexus-accent/12 text-nexus-accent">
          <Wrench className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold tracking-tight text-nexus-text">Ferramentas</h2>
          <p className="text-[10px] text-nexus-faint">{ready} prontas · {tools.length} no registry</p>
        </div>
      </div>
      <label className="mb-3 flex items-center gap-2 rounded-xl border border-nexus-border/70 bg-nexus-bg/40 px-2.5 py-1.5 focus-within:ring-2 focus-within:ring-nexus-accent">
        <Search className="h-3.5 w-3.5 shrink-0 text-nexus-faint" aria-hidden="true" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filtrar por nome"
          aria-label="Filtrar ferramentas"
          className="w-full bg-transparent text-xs text-nexus-text outline-none placeholder:text-nexus-faint"
        />
      </label>
      {toolsLoading && <div className="mb-2 flex items-center gap-2 text-[11px] text-nexus-muted"><Loader2 className="h-3 w-3 animate-spin" /> A carregar estado real…</div>}
      {toolsError && <div className="mb-2 rounded-lg border border-rose-400/20 bg-rose-400/5 p-2 text-[11px] text-nexus-accent4">Não foi possível carregar o registry: {toolsError}</div>}
      {visible.length === 0 && !toolsLoading && !toolsError ? (
        <p className="rounded-lg border border-dashed border-nexus-border/50 px-2.5 py-3 text-[11px] text-nexus-faint">
          {tools.length === 0 ? "O registry não devolveu ferramentas." : `Nenhuma ferramenta corresponde a “${query.trim()}”.`}
        </p>
      ) : null}
      <div className="space-y-1.5">
        {visible.map((tool) => {
          const status = tool.status ?? (tool.enabled ? "available" : "blocked");
          const interactive = status !== "missing_dependency";
          const readyStatus = status === "available" || status === "requires_confirmation";
          return (
            <button
              key={tool.name}
              type="button"
              disabled={!interactive}
              onClick={() => {
                if (interactive) void toggleTool(tool.name);
              }}
              className={`flex w-full items-center gap-2.5 rounded-xl border px-2.5 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:cursor-not-allowed ${
                readyStatus
                  ? "border-nexus-border/70 bg-nexus-bg/35 hover:border-nexus-accent/35 hover:bg-nexus-accent/5"
                  : "border-nexus-border/30 bg-transparent opacity-70"
              }`}
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-nexus-bg/70">
                {statusIcon(status)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-[12px] font-medium text-nexus-text">{tool.name}</span>
                <span className="block truncate text-[11px] text-nexus-muted">{tool.description}</span>
                <span className="mt-0.5 block text-[10px] text-nexus-faint">{statusLabel(status)}{tool.dependency ? ` · ${tool.dependency}` : ""}</span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
