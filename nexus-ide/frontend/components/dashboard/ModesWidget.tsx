"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, Sparkles, Zap, Brain, Shield, Activity, Wrench } from "lucide-react";
import { useModeStore } from "../../stores/modeStore";

const MODE_ICONS: Record<string, typeof Zap> = {
  auto: Sparkles,
  agent: Zap,
  swarm: Brain,
  code: Wrench,
  analysis: Activity,
  security: Shield,
};

const MODE_COLORS: Record<string, string> = {
  auto: "from-violet-500/15 to-fuchsia-500/15 border-violet-500/30",
  agent: "from-blue-500/15 to-cyan-500/15 border-blue-500/30",
  swarm: "from-fuchsia-500/15 to-pink-500/15 border-fuchsia-500/30",
  code: "from-emerald-500/15 to-teal-500/15 border-emerald-500/30",
  analysis: "from-amber-500/15 to-orange-500/15 border-amber-500/30",
  security: "from-red-500/15 to-rose-500/15 border-red-500/30",
};

export default function ModesWidget() {
  const modes = useModeStore((s) => s.modes);
  const currentMode = useModeStore((s) => s.currentMode);
  const modesLoading = useModeStore((s) => s.modesLoading);
  const modesError = useModeStore((s) => s.modesError);
  const modesLoaded = useModeStore((s) => s.modesLoaded);
  const loadModes = useModeStore((s) => s.loadModes);
  const setMode = useModeStore((s) => s.setMode);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (hydrated) return;
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("nexus.currentMode");
      if (stored && stored !== currentMode) {
        setMode(stored);
      }
      setHydrated(true);
    }
  }, [hydrated, currentMode, setMode]);

  useEffect(() => {
    if (!modesLoaded && !modesLoading) {
      void loadModes();
    }
  }, [modesLoaded, modesLoading, loadModes]);

  const modeList = useMemo(() => Object.values(modes), [modes]);

  if (modesLoading && modeList.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded border border-nexus-border bg-nexus-panel">
        <Loader2 className="h-4 w-4 animate-spin text-nexus-muted" aria-hidden />
      </div>
    );
  }

  if (modesError && modeList.length === 0) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-2 rounded border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-xs text-yellow-400"
      >
        <Loader2 className="h-3.5 w-3.5" aria-hidden />
        <span>Modos indisponíveis — {modesError}</span>
      </div>
    );
  }

  return (
    <section
      className="min-w-0 rounded border border-nexus-border bg-nexus-panel p-3"
      aria-labelledby="modes-widget-title"
    >
      <header className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-nexus-accent" aria-hidden />
          <h3 id="modes-widget-title" className="text-sm font-semibold">
            Modos
          </h3>
        </div>
        <span className="rounded-full bg-nexus-accent/15 px-2 py-0.5 text-[10px] font-medium text-nexus-accent">
          {currentMode}
        </span>
      </header>

      <ul
        className="grid grid-cols-2 gap-2 sm:grid-cols-3"
        aria-label="Lista de modos disponíveis"
      >
        {modeList.map((mode) => {
          const Icon = MODE_ICONS[mode.id] ?? Sparkles;
          const gradient = MODE_COLORS[mode.id] ?? "from-nexus-accent/10 to-nexus-accent/5 border-nexus-border";
          const isActive = mode.id === currentMode;
          return (
            <li key={mode.id}>
              <button
                type="button"
                onClick={() => setMode(mode.id)}
                aria-pressed={isActive}
                className={`group relative w-full rounded-lg border bg-gradient-to-br p-2 text-left transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
                  isActive
                    ? `${gradient} ring-1 ring-nexus-accent/40`
                    : "border-nexus-border/40 bg-nexus-bg/30 hover:border-nexus-accent/30"
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <Icon className="h-3.5 w-3.5 text-nexus-accent" aria-hidden />
                  <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-nexus-text">
                    {mode.id}
                  </span>
                  {isActive && (
                    <CheckCircle2 className="ml-auto h-3 w-3 text-nexus-accent" aria-hidden />
                  )}
                </div>
                <p className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-nexus-muted">
                  {mode.description || `${mode.default_agent} • ${mode.default_model}`}
                </p>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
