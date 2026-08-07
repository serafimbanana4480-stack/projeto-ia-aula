"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Sparkles, Zap, Brain, Shield, Activity, Wrench } from "lucide-react";
import { useModeStore } from "../../stores/modeStore";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, EmptyState } from "../ui/Primitives";

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

  return (
    <Surface elevation={1} padding="sm">
      <SurfaceHeader
        icon={<Sparkles className="h-4 w-4" />}
        title="Modos"
        subtitle="Perfis de comportamento dos agentes"
        action={<Badge tone="accent">{currentMode}</Badge>}
      />

      <div className="mt-3">
        {modesLoading && modeList.length === 0 ? (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="nx-shimmer h-16 rounded-lg" />
            ))}
          </div>
        ) : modesError && modeList.length === 0 ? (
          <EmptyState compact icon={<Sparkles className="h-5 w-5" />} title="Modos indisponíveis" hint={modesError} />
        ) : (
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Lista de modos disponíveis">
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
                    className={`nx-surface group relative w-full rounded-lg border bg-gradient-to-br p-2 text-left transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
                      isActive
                        ? `${gradient} ring-1 ring-nexus-accent/40 shadow-nx-1`
                        : "border-[var(--nx-line)] bg-nexus-panel/60 hover:border-nexus-accent/30"
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <Icon className="h-3.5 w-3.5 text-nexus-accent" aria-hidden />
                      <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-nexus-text">
                        {mode.id}
                      </span>
                      {isActive && <CheckCircle2 className="ml-auto h-3 w-3 text-nexus-accent" aria-hidden />}
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-nexus-muted">
                      {mode.description || `${mode.default_agent} • ${mode.default_model}`}
                    </p>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Surface>
  );
}
