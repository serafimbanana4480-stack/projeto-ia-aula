"use client";

import type { ReactNode } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { Card } from "./Card";
import { Sparkline } from "./Sparkline";
import { EMPTY } from "../../lib/format";

/**
 * A headline metric: value, trend line, and change versus the previous period.
 *
 * `goodDirection` matters because "up" is not universally good — rising spend
 * or latency should read red while rising throughput reads green.
 */

export interface KpiCardProps {
  label: string;
  /** Pre-formatted for display; use the helpers in lib/format. */
  value: string;
  icon?: ReactNode;
  color?: string;
  /** Oldest value first. Omit to hide the sparkline. */
  history?: number[];
  /** Fractional change vs. the previous period (0.12 = +12%). */
  delta?: number | null;
  goodDirection?: "up" | "down" | "neutral";
  /** Short qualifier under the value, e.g. "vs. ontem". */
  hint?: string;
  loading?: boolean;
  /**
   * Hero KPIs sit one elevation step above the rest of the grid. Reserve for
   * the three or four numbers the page actually exists to communicate — if
   * everything is emphasised, nothing is.
   */
  emphasis?: boolean;
}

function DeltaBadge({
  delta,
  goodDirection,
}: {
  delta: number;
  goodDirection: "up" | "down" | "neutral";
}) {
  // Treat sub-0.5% moves as flat; otherwise noise looks like a signal.
  const flat = Math.abs(delta) < 0.005;
  const rising = delta > 0;

  let tone = "text-nexus-muted";
  if (!flat && goodDirection !== "neutral") {
    const good = goodDirection === "up" ? rising : !rising;
    tone = good ? "text-emerald-400" : "text-red-400";
  }

  const Icon = flat ? ArrowRight : rising ? ArrowUpRight : ArrowDownRight;

  return (
    <span className={`flex items-center gap-0.5 text-[11px] font-medium ${tone}`}>
      <Icon className="h-3 w-3" />
      {flat ? "estável" : `${rising ? "+" : ""}${(delta * 100).toFixed(1)}%`}
    </span>
  );
}

export function KpiCard({
  label,
  value,
  icon,
  // A token, not a literal — a hardcoded hex is invisible to the theme
  // switcher, so a light-theme KPI would keep its dark-theme accent.
  color = "var(--nx-accent)",
  history,
  delta = null,
  goodDirection = "neutral",
  hint,
  loading = false,
  emphasis = false,
}: KpiCardProps) {
  return (
    <Card
      padding="md"
      variant={emphasis ? "raised" : "default"}
      className="group relative flex flex-col justify-between overflow-hidden"
    >
      {/* Top hairline tinted with the metric's own colour. Identifies the card
          at a glance in a dense grid without adding another label. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px opacity-70"
        style={{ background: `linear-gradient(90deg, transparent, ${color}, transparent)` }}
      />

      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-nexus-muted">
          {label}
        </span>
        {icon ? (
          <span
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg shadow-rim transition-transform duration-200 group-hover:scale-105"
            style={{ color, backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)` }}
          >
            {icon}
          </span>
        ) : null}
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="min-w-0">
          {loading ? (
            <div className="nx-shimmer h-8 w-24 rounded" />
          ) : (
            <div
              className={`truncate font-bold leading-none tabular-nums text-nexus-text ${
                emphasis ? "text-3xl" : "text-2xl"
              }`}
            >
              {value || EMPTY}
            </div>
          )}
          <div className="mt-2 flex items-center gap-1.5">
            {delta != null && !loading ? (
              <DeltaBadge delta={delta} goodDirection={goodDirection} />
            ) : null}
            {hint ? <span className="text-[10px] text-nexus-faint">{hint}</span> : null}
          </div>
        </div>

        {history && history.length > 1 ? (
          <Sparkline
            data={history}
            color={color}
            width={emphasis ? 104 : 88}
            height={emphasis ? 36 : 30}
            className="shrink-0"
          />
        ) : null}
      </div>
    </Card>
  );
}

/**
 * Secondary metric with a progress bar — CPU, RAM, disk, context usage.
 *
 * Deliberately one elevation step *below* KpiCard. Host telemetry is context,
 * not headline: it should be legible when you look for it and quiet when you
 * do not. The track is a sunken well so the fill reads as sitting inside it.
 */
export function GaugeCard({
  label,
  percent,
  icon,
  color = "var(--nx-cyan)",
  detail,
}: {
  label: string;
  percent: number | null | undefined;
  icon?: ReactNode;
  color?: string;
  detail?: string;
}) {
  const known = percent != null && !Number.isNaN(percent);
  const clamped = known ? Math.max(0, Math.min(100, percent)) : 0;
  // Saturation is earned: a gauge only turns warm once it is worth reacting to.
  const barColor = !known
    ? "var(--nx-surface-4)"
    : clamped >= 90
      ? "var(--nx-rose)"
      : clamped >= 75
        ? "var(--nx-amber)"
        : color;

  return (
    <Card padding="sm" variant="subtle">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-medium uppercase tracking-wider text-nexus-faint">
          {label}
        </span>
        {icon ? (
          <span className="shrink-0" style={{ color: barColor }}>
            {icon}
          </span>
        ) : null}
      </div>
      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span className="text-lg font-semibold tabular-nums text-nexus-text">
          {known ? `${clamped.toFixed(0)}%` : EMPTY}
        </span>
        {detail ? <span className="text-[10px] text-nexus-faint">{detail}</span> : null}
      </div>
      <div
        className="nx-inset mt-2 h-1.5 overflow-hidden rounded-full"
        role="progressbar"
        aria-label={label}
        aria-valuenow={known ? Math.round(clamped) : undefined}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full transition-[width,background-color] duration-500"
          style={{
            width: `${clamped}%`,
            backgroundColor: barColor,
            boxShadow: known ? `0 0 8px -1px ${barColor}` : undefined,
          }}
        />
      </div>
    </Card>
  );
}
