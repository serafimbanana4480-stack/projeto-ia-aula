"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Small shared primitives: buttons, badges, status dots, meters, gauges and
 * animated numerals.
 *
 * These existed before as one-off Tailwind strings scattered across forty
 * files, which is why the same "online" pill appeared in four different
 * greens. Centralising them costs one import and buys consistency plus the
 * dimensional treatment (rim light, inset well, contact shadow) everywhere.
 */

/* ========================================================================
   BUTTON
   ==================================================================== */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "xs" | "sm" | "md";

const BTN_VARIANT: Record<ButtonVariant, string> = {
  // A raised key: gradient fill top-lit, coloured contact shadow underneath.
  primary:
    "text-white bg-gradient-to-b from-[var(--nx-accent-bright)] to-[var(--nx-accent)] " +
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.25),var(--nx-shadow-accent)] " +
    "hover:brightness-110 active:brightness-95",
  secondary:
    "text-nexus-text bg-gradient-to-b from-[var(--nx-surface-3)] to-[var(--nx-surface-2)] " +
    "border border-[var(--nx-line)] shadow-[inset_0_1px_0_var(--nx-rim),var(--nx-shadow-1)] " +
    "hover:border-[rgba(124,106,251,0.35)]",
  ghost: "text-nexus-muted hover:text-nexus-text hover:bg-white/[0.05]",
  danger:
    "text-white bg-gradient-to-b from-rose-400 to-rose-600 " +
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.22),0_8px_20px_-8px_rgba(244,63,94,0.55)] " +
    "hover:brightness-110",
};

const BTN_SIZE: Record<ButtonSize, string> = {
  xs: "h-7 px-2.5 text-[11px] gap-1.5 rounded-lg",
  sm: "h-8 px-3 text-xs gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-xl",
};

export function Button({
  children,
  variant = "secondary",
  size = "sm",
  icon,
  loading = false,
  disabled = false,
  className = "",
  onClick,
  type = "button",
  title,
}: {
  children?: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  loading?: boolean;
  disabled?: boolean;
  className?: string;
  onClick?: () => void;
  type?: "button" | "submit";
  title?: string;
}) {
  return (
    <button
      type={type}
      title={title}
      disabled={disabled || loading}
      onClick={onClick}
      className={[
        "inline-flex items-center justify-center font-semibold whitespace-nowrap",
        "transition-all duration-200 ease-nx",
        "active:translate-y-px disabled:opacity-45 disabled:pointer-events-none",
        BTN_VARIANT[variant],
        BTN_SIZE[size],
        className,
      ].join(" ")}
    >
      {loading ? (
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}

/* ========================================================================
   BADGE + STATUS DOT
   ==================================================================== */

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const BADGE_TONE: Record<Tone, string> = {
  neutral: "text-nexus-muted bg-white/[0.05] border-white/[0.08]",
  accent: "text-[var(--nx-accent-bright)] bg-[rgba(124,106,251,0.12)] border-[rgba(124,106,251,0.28)]",
  success: "text-emerald-300 bg-emerald-400/10 border-emerald-400/25",
  warning: "text-amber-300 bg-amber-400/10 border-amber-400/25",
  danger: "text-rose-300 bg-rose-400/10 border-rose-400/25",
  info: "text-cyan-300 bg-cyan-400/10 border-cyan-400/25",
};

export function Badge({
  children,
  tone = "neutral",
  icon,
  className = "",
}: {
  children: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
        "text-[10px] font-semibold uppercase tracking-wide shadow-rim",
        BADGE_TONE[tone],
        className,
      ].join(" ")}
    >
      {icon}
      {children}
    </span>
  );
}

const DOT_TONE: Record<Tone, string> = {
  neutral: "bg-nexus-faint",
  accent: "bg-[var(--nx-accent)]",
  success: "bg-emerald-400",
  warning: "bg-amber-400",
  danger: "bg-rose-400",
  info: "bg-cyan-400",
};

/**
 * A status light. `pulse` emits expanding rings — used only where something
 * genuinely is in flight, so a glance at the page tells you whether the
 * system is idle or working.
 */
export function StatusDot({
  tone = "neutral",
  pulse = false,
  size = 8,
  label,
}: {
  tone?: Tone;
  pulse?: boolean;
  size?: number;
  label?: string;
}) {
  return (
    <span className="relative inline-flex shrink-0 items-center" title={label}>
      <span
        className={`relative rounded-full ${DOT_TONE[tone]}`}
        style={{
          width: size,
          height: size,
          boxShadow: pulse ? `0 0 ${size}px currentColor` : undefined,
        }}
      >
        {pulse ? (
          <span
            className={`absolute inset-0 animate-radar-ping rounded-full ${DOT_TONE[tone]} opacity-70`}
          />
        ) : null}
      </span>
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  );
}

/* ========================================================================
   METER — a sunken track with a lit fill
   ==================================================================== */

/** Thresholds are load-bearing: the same bar turns amber then red as it
 *  fills, so a saturated resource is visible without reading the number. */
export function Meter({
  value,
  max = 100,
  tone,
  height = 6,
  showThresholds = true,
  className = "",
}: {
  value: number | null | undefined;
  max?: number;
  tone?: Tone;
  height?: number;
  showThresholds?: boolean;
  className?: string;
}) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));

  let resolved: Tone = tone ?? "accent";
  if (!tone && showThresholds) {
    if (pct >= 90) resolved = "danger";
    else if (pct >= 75) resolved = "warning";
  }

  const FILL: Record<Tone, string> = {
    neutral: "from-slate-500 to-slate-400",
    accent: "from-[var(--nx-accent-deep)] to-[var(--nx-accent-bright)]",
    success: "from-emerald-600 to-emerald-400",
    warning: "from-amber-600 to-amber-400",
    danger: "from-rose-600 to-rose-400",
    info: "from-cyan-600 to-cyan-400",
  };

  return (
    <div
      className={`nx-inset overflow-hidden rounded-full ${className}`}
      style={{ height }}
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={`h-full rounded-full bg-gradient-to-r ${FILL[resolved]} transition-[width] duration-700 ease-nx`}
        style={{
          width: `${pct}%`,
          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.35), 0 0 12px -2px currentColor",
        }}
      />
    </div>
  );
}

/* ========================================================================
   GAUGE — radial dial for headline resource metrics
   ==================================================================== */

/**
 * A 3D-ish radial gauge: recessed track, glowing arc, value in the well.
 * Chosen over a bar for the three system vitals because a dial communicates
 * "how close to the limit" at a glance, which is the actual question.
 */
export function Gauge({
  value,
  label,
  unit = "%",
  size = 116,
  tone,
  sublabel,
}: {
  value: number | null | undefined;
  label: string;
  unit?: string;
  size?: number;
  tone?: Tone;
  sublabel?: string;
}) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value));

  let resolved: Tone = tone ?? "accent";
  if (!tone) {
    if (pct >= 90) resolved = "danger";
    else if (pct >= 75) resolved = "warning";
  }

  const STROKE: Record<Tone, [string, string]> = {
    neutral: ["#64748b", "#94a3b8"],
    accent: ["#5b46e0", "#9b8cff"],
    success: ["#059669", "#34d399"],
    warning: ["#d97706", "#fbbf24"],
    danger: ["#e11d48", "#fb7185"],
    info: ["#0891b2", "#22d3ee"],
  };

  const stroke = 9;
  const radius = (size - stroke) / 2;
  // 270° dial: leaves a gap at the bottom so the ends read as a scale, not
  // a ring, which makes the empty portion legible.
  const sweep = 0.75;
  const circumference = 2 * Math.PI * radius;
  const arc = circumference * sweep;
  const offset = arc * (1 - pct / 100);
  const [from, to] = STROKE[resolved];
  const gradId = `gauge-${label.replace(/\W/g, "")}-${resolved}`;

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-[225deg]">
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor={from} />
              <stop offset="100%" stopColor={to} />
            </linearGradient>
            <filter id={`${gradId}-glow`} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="3.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${arc} ${circumference}`}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={`url(#${gradId})`}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${arc} ${circumference}`}
            strokeDashoffset={offset}
            filter={`url(#${gradId}-glow)`}
            style={{ transition: "stroke-dashoffset 900ms cubic-bezier(0.22,1,0.36,1)" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono text-[22px] font-bold leading-none tracking-tight text-nexus-text">
            {value == null ? "—" : <AnimatedNumber value={pct} decimals={0} />}
            {value != null ? <span className="text-sm text-nexus-faint">{unit}</span> : null}
          </span>
          {sublabel ? (
            <span className="mt-0.5 text-[9px] text-nexus-faint">{sublabel}</span>
          ) : null}
        </div>
      </div>
      <span className="text-[11px] font-medium text-nexus-muted">{label}</span>
    </div>
  );
}

/* ========================================================================
   ANIMATED NUMBER
   ==================================================================== */

/**
 * Eases a numeral to its new value instead of snapping.
 *
 * On a live dashboard a snapped number is easy to miss entirely; a 600 ms
 * ease draws the eye to exactly the figure that changed. Large jumps skip the
 * animation — watching a counter crawl from 0 to 40,000 is noise, not signal.
 */
export function AnimatedNumber({
  value,
  decimals = 0,
  duration = 600,
}: {
  value: number;
  decimals?: number;
  duration?: number;
}) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const from = fromRef.current;
    const delta = value - from;

    if (Math.abs(delta) < 0.01) {
      setDisplay(value);
      fromRef.current = value;
      return;
    }
    // Order-of-magnitude jumps (first load, reset) should just appear.
    if (from !== 0 && Math.abs(delta / (from || 1)) > 5) {
      setDisplay(value);
      fromRef.current = value;
      return;
    }

    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      setDisplay(from + delta * eased);
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
      else fromRef.current = value;
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      fromRef.current = value;
    };
  }, [value, duration]);

  return <>{display.toFixed(decimals)}</>;
}

/* ========================================================================
   EMPTY STATE
   ==================================================================== */

/**
 * An empty state should say what will appear here and, when possible, offer
 * the action that makes it appear. A bare "—" leaves the user unsure whether
 * the system is broken or simply idle.
 */
export function EmptyState({
  icon,
  title,
  hint,
  action,
  compact = false,
}: {
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--nx-line-strong)] bg-black/20 text-center ${
        compact ? "px-3 py-4" : "px-4 py-8"
      }`}
    >
      {icon ? <div className="text-nexus-faint opacity-60">{icon}</div> : null}
      <div className="text-xs font-medium text-nexus-muted">{title}</div>
      {hint ? <div className="max-w-[36ch] text-[11px] text-nexus-faint">{hint}</div> : null}
      {action}
    </div>
  );
}
