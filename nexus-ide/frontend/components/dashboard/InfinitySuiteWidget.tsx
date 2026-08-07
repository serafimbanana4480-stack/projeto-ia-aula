"use client";

/**
 * InfinitySuiteWidget — the eleven advanced modes, on the page.
 *
 * Before this component the Infinity Suite was invisible from the dashboard.
 * `config/modes-advanced.yaml` defines eleven modes, `advanced_modes.py`
 * implements them and fifteen REST endpoints serve them — and the dashboard
 * rendered four unrelated base modes (`auto`, `coder`, `swarm`, `auto_swarm`)
 * from a hardcoded `MAIN_MODE_IDS`. The only way in was a floating button in
 * the bottom-left corner. The most substantial subsystem in the product had
 * the least surface area.
 *
 * Three decisions:
 *
 * 1. THE YAML ALREADY KNOWS HOW IT SHOULD LOOK. Every mode ships an `icon`
 *    and a `color`. The old `ModesWidget` ignored both and kept its own map
 *    keyed on IDs (`agent`, `code`, `analysis`) that no mode actually has, so
 *    every tile fell through to the same grey sparkle. Here the colour comes
 *    off the wire and the icon name is mapped to a real lucide glyph.
 *
 * 2. RUNTIME HONESTY IS PART OF THE DESIGN. Seven of the eleven are `composed`
 *    — a prompt contract and a state model, not a standalone worker. The API
 *    has said so in `runtime_status` from the start and no UI showed it.
 *    Presenting all eleven as equally "live" would be the more attractive lie.
 *    Each tile carries its runtime badge.
 *
 * 3. GROUPED, NOT LISTED. Eleven equal tiles is a wall. The YAML's five groups
 *    (infinity, productivity, quality, analysis, security) give the eye a
 *    structure to land on.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  Brain,
  CheckCircle2,
  Eye,
  FlaskConical,
  GitBranch,
  Hammer,
  Infinity as InfinityIcon,
  Layers,
  Loader2,
  Search,
  Shield,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { apiUrl, authHeaders } from "../../lib/api";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { CardEmpty } from "../ui/Card";

// ── Types ──────────────────────────────────────────────────────────────────

interface ModeSummary {
  active: boolean;
  session_count: number;
  active_session_count: number;
  total_session_count: number;
  group: string;
  display_name: string;
  description: string;
  icon: string;
  color: string;
  runtime_status: string;
  runtime_role: string;
  runtime_summary: string;
  handler: string | null;
}

interface HealthResponse {
  healthy: boolean;
  active_modes: number;
  total_modes: number;
  modes: Record<string, ModeSummary>;
  groups: Record<string, { display_name?: string; description?: string; modes?: string[] }>;
}

const POLL_MS = 20_000;

/** Icon names come from the YAML, so this map is keyed on those exact strings. */
const ICONS: Record<string, LucideIcon> = {
  infinity: InfinityIcon,
  shield: Shield,
  hammer: Hammer,
  layers: Layers,
  "git-branch": GitBranch,
  "check-circle": CheckCircle2,
  flask: FlaskConical,
  search: Search,
  brain: Brain,
  eye: Eye,
  sparkles: Sparkles,
  bot: Bot,
};

/**
 * `integrated` means a real endpoint or agent executes it. `composed` means a
 * prompt and state contract that rides on another executor. The distinction is
 * the difference between a feature and a description of a feature.
 */
const RUNTIME_TONE: Record<string, { label: string; className: string }> = {
  integrated: {
    label: "integrado",
    className: "bg-[rgba(52,211,153,0.14)] text-emerald-300",
  },
  composed: {
    label: "composto",
    className: "bg-[rgba(148,163,184,0.14)] text-nexus-muted",
  },
  unknown: {
    label: "desconhecido",
    className: "bg-[rgba(251,191,36,0.14)] text-amber-300",
  },
};

const GROUP_LABEL: Record<string, string> = {
  infinity: "Infinity",
  productivity: "Produtividade",
  quality: "Qualidade",
  analysis: "Análise",
  security: "Segurança",
};

const GROUP_ORDER = ["infinity", "quality", "analysis", "security", "productivity"];

// ── Component ──────────────────────────────────────────────────────────────

export default function InfinitySuiteWidget() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/api/advanced-modes/health"), {
        headers: authHeaders(),
      });
      if (res.status === 401) {
        setError("Autenticação necessária");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setHealth((await res.json()) as HealthResponse);
      setError(null);
    } catch {
      setError("Sem ligação ao backend");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  /** Optimism here would be a lie: the toggle is only reflected after the
   *  server confirms, because a mode that failed to activate but looks active
   *  is worse than a 200 ms delay. */
  const toggle = useCallback(
    async (id: string, active: boolean) => {
      setBusy(id);
      try {
        await fetch(
          apiUrl(`/api/advanced-modes/${id}/${active ? "deactivate" : "activate"}`),
          { method: "POST", headers: authHeaders() },
        );
        await load();
      } catch {
        setError("A alteração de modo falhou");
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  const grouped = useMemo(() => {
    if (!health) return [];
    const buckets = new Map<string, Array<[string, ModeSummary]>>();
    for (const [id, mode] of Object.entries(health.modes)) {
      const key = mode.group || "outros";
      const list = buckets.get(key) ?? [];
      list.push([id, mode]);
      buckets.set(key, list);
    }
    return [...buckets.entries()].sort((a, b) => {
      const ia = GROUP_ORDER.indexOf(a[0]);
      const ib = GROUP_ORDER.indexOf(b[0]);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  }, [health]);

  const integratedCount = useMemo(
    () =>
      health
        ? Object.values(health.modes).filter((m) => m.runtime_status === "integrated").length
        : 0,
    [health],
  );

  return (
    <Surface elevation={1} padding="lg" className="flex flex-col">
      <SurfaceHeader
        icon={<InfinityIcon className="h-4 w-4" />}
        tone={health && health.active_modes > 0 ? "accent" : "neutral"}
        title="Infinity Suite"
        subtitle="Onze estratégias cognitivas avançadas — ativa por modo ou por /comando no chat"
        action={
          health ? (
            <div className="flex items-center gap-1.5">
              <span className="rounded-full bg-[rgba(124,106,251,0.12)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-accent-bright shadow-rim">
                {health.active_modes}/{health.total_modes} ativos
              </span>
              <span
                className="rounded-full bg-[rgba(52,211,153,0.12)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-300 shadow-rim"
                title="Modos com execução própria (endpoint ou agente dedicado). Os restantes são contratos de prompt aplicados sobre outro executor."
              >
                {integratedCount} integrados
              </span>
            </div>
          ) : undefined
        }
      />

      {error && !health ? (
        <div className="mt-4">
          <CardEmpty icon={<Activity className="h-3.5 w-3.5" />}>{error}</CardEmpty>
        </div>
      ) : !health ? (
        <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="nx-shimmer h-[92px] rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="mt-4 space-y-5">
          {grouped.map(([group, modes]) => (
            <div key={group}>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-nexus-faint">
                  {GROUP_LABEL[group] ?? group}
                </span>
                <span className="h-px flex-1 bg-nexus-border/60" />
                <span className="text-[10px] tabular-nums text-nexus-faint">{modes.length}</span>
              </div>

              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
                {modes.map(([id, mode]) => {
                  const Icon = ICONS[mode.icon] ?? Bot;
                  const runtime = RUNTIME_TONE[mode.runtime_status] ?? RUNTIME_TONE.unknown;
                  const isBusy = busy === id;
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => void toggle(id, mode.active)}
                      disabled={isBusy}
                      aria-pressed={mode.active}
                      title={mode.runtime_summary}
                      className={`nx-surface group relative w-full rounded-xl p-3 text-left transition-all duration-200 disabled:opacity-60 ${
                        mode.active ? "nx-elev-2" : "nx-elev-0 nx-lift"
                      }`}
                      style={
                        mode.active
                          ? {
                              // The colour is the mode's own, straight from the
                              // YAML — not a local palette that drifts from it.
                              borderColor: `color-mix(in srgb, ${mode.color} 50%, transparent)`,
                              boxShadow: `inset 0 1px 0 0 var(--nx-rim-strong), 0 6px 18px -8px ${mode.color}`,
                            }
                          : undefined
                      }
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span
                          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
                          style={{
                            background: `color-mix(in srgb, ${mode.color} 16%, transparent)`,
                            color: mode.color,
                          }}
                        >
                          {isBusy ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Icon className="h-3.5 w-3.5" />
                          )}
                        </span>
                        {mode.active ? (
                          <span
                            className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full animate-pulse-subtle"
                            style={{ background: mode.color }}
                          />
                        ) : null}
                      </div>

                      <div className="mt-2 truncate text-[12px] font-semibold text-nexus-text">
                        {mode.display_name}
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-nexus-muted">
                        {mode.description}
                      </p>

                      <div className="mt-2 flex items-center gap-1.5">
                        <span
                          className={`rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${runtime.className}`}
                        >
                          {runtime.label}
                        </span>
                        {mode.active_session_count > 0 ? (
                          <span className="text-[9px] tabular-nums text-nexus-faint">
                            {mode.active_session_count} sessões
                          </span>
                        ) : null}
                      </div>

                      <code className="pointer-events-none absolute right-2 top-2 font-mono text-[9px] text-nexus-faint opacity-0 transition-opacity group-hover:opacity-100">
                        /{id}
                      </code>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}

          <p className="border-t border-nexus-border/60 pt-3 text-[11px] leading-relaxed text-nexus-faint">
            <strong className="text-nexus-muted">Integrado</strong> = tem execução própria
            (endpoint ou agente dedicado). <strong className="text-nexus-muted">Composto</strong>{" "}
            = contrato de prompt e estado aplicado sobre outro executor. Ambos são reais; só o
            primeiro corre sozinho.
          </p>
        </div>
      )}
    </Surface>
  );
}
