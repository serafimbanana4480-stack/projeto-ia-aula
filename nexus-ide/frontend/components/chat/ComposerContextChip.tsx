"use client";

import { useMemo, useState } from "react";
import { Gauge, Layers } from "lucide-react";

import { deriveContextUsage } from "../../lib/contextTelemetry";
import { formatCompact, formatContext } from "../../lib/format";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import { useModelStore } from "../../stores/modelStore";

/**
 * Context chip for the composer.
 *
 * The user decides what to send; the least they need first is how much
 * context the model is already carrying. One compact chip ("42K · 8 ficheiros
 * · 33%") opens the real breakdown derived from the last usage snapshot —
 * the same `deriveContextUsage` the Context Rail uses, so the two can never
 * disagree. Nothing here is estimated on the client beyond the segmentation
 * the backend already reports.
 */

export default function ComposerContextChip({ className = "" }: { className?: string }) {
  const usage = useChatTelemetryStore((state) => state.usage);
  const contextWindow = useModelStore((state) =>
    state.models.find((model) => model.id === state.activeModel)?.contextWindow ?? 0,
  );
  const [open, setOpen] = useState(false);

  const derived = useMemo(() => deriveContextUsage(usage, contextWindow), [usage, contextWindow]);
  const filesSegment = derived.segments.find((segment) => segment.key === "files");

  // Nothing measured yet: stay silent rather than invent a number.
  if (derived.used === null) return null;

  const segments = derived.segments.filter((segment) => segment.value > 0);
  const percent = derived.percent;

  return (
    <div className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        data-testid="composer-context-chip"
        title="Contexto carregado pelo modelo — clique para ver a composição"
        className="inline-flex items-center gap-1.5 rounded-lg border border-nexus-border/60 bg-nexus-bg/50 px-2 py-1 text-[10px] text-nexus-muted transition-[transform,opacity,background-color,color] duration-100 hover:border-nexus-accent/40 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
      >
        <Gauge className="h-3 w-3 shrink-0" aria-hidden="true" />
        <span className="nx-nums">{formatContext(derived.used)}</span>
        {derived.window ? (
          <span className="nx-nums text-nexus-faint">/ {formatContext(derived.window)}</span>
        ) : null}
        {filesSegment ? (
          <span className="hidden items-center gap-1 sm:inline-flex">
            <Layers className="h-3 w-3" aria-hidden="true" />
            <span className="nx-nums">{formatCompact(filesSegment.value)}</span>
          </span>
        ) : null}
        {percent !== null && percent >= 75 ? (
          <span className="rounded-full bg-amber-400/15 px-1.5 text-[9px] text-nexus-accent3">
            {Math.round(percent)}%
          </span>
        ) : null}
      </button>

      {open ? (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="dialog"
            aria-label="Composição do contexto"
            className="nx-elev-2 absolute bottom-full left-0 z-40 mb-2 w-64 rounded-xl p-3"
          >
            <div className="mb-2 flex items-center gap-2">
              <Gauge className="h-3.5 w-3.5 text-nexus-accent-bright" aria-hidden="true" />
              <h3 className="text-xs font-semibold text-nexus-text">Contexto ativo</h3>
              <span className="nx-nums ml-auto text-[10px] text-nexus-muted">
                {formatContext(derived.used)}
                {derived.window ? ` / ${formatContext(derived.window)}` : ""}
              </span>
            </div>
            <ul className="space-y-1">
              {segments.map((segment) => (
                <li key={segment.key} className="flex items-center gap-2 text-[11px]">
                  <span
                    aria-hidden="true"
                    className="h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ background: segment.color }}
                  />
                  <span className="min-w-0 flex-1 truncate text-nexus-muted">{segment.label}</span>
                  <span className="nx-nums shrink-0 font-mono text-nexus-text">
                    {formatCompact(segment.value)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[9px] leading-relaxed text-nexus-faint">
              {derived.source === "provider"
                ? "Valores reportados pelo provider."
                : "Estimativa NEXUS a partir da última execução."}
            </p>
          </div>
        </>
      ) : null}
    </div>
  );
}
