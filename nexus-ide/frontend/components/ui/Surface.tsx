"use client";

import { useCallback, useRef, type CSSProperties, type ReactNode } from "react";

/**
 * The dimensional panel primitive that every widget sits on.
 *
 * Previously each widget hand-rolled `rounded-xl border border-nexus-border
 * bg-[#13131f]/40`, which produced a flat sheet of near-identical rectangles —
 * nothing told the eye what was important. `Surface` replaces that with an
 * explicit elevation scale: pick how far off the page something sits, and the
 * background, rim light and shadow are chosen together so the result reads as
 * a lit object rather than a coloured box.
 *
 * `tilt` adds pointer-tracked parallax. It is deliberately opt-in and only
 * worth using on a handful of hero surfaces — applied everywhere it turns
 * from "dimensional" into "seasick".
 */

type Elevation = 0 | 1 | 2 | 3;
type Padding = "none" | "xs" | "sm" | "md" | "lg";
type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const ELEVATION: Record<Elevation, string> = {
  0: "nx-elev-0",
  1: "nx-elev-1",
  2: "nx-elev-2",
  3: "nx-elev-3",
};

const PADDING: Record<Padding, string> = {
  none: "",
  xs: "p-2.5",
  sm: "p-3",
  md: "p-4",
  lg: "p-6",
};

/** Tones tint the border and add a coloured bloom, never the whole fill —
 *  a fully tinted panel stops reading as a surface and starts reading as an
 *  alert, which is a signal we want to reserve for real alerts.
 *
 *  The tints are `color-mix` against the live token rather than hardcoded
 *  rgba: the dark accent is #7c6afb but the light one is #6d56dd, and a
 *  literal kept the dark purple border in the light theme. */
const TONE: Record<Tone, string> = {
  neutral: "",
  accent:
    "!border-[color-mix(in_srgb,var(--nx-accent)_30%,transparent)] shadow-nx-accent",
  success: "!border-[color-mix(in_srgb,var(--nx-emerald)_28%,transparent)]",
  warning: "!border-[color-mix(in_srgb,var(--nx-amber)_28%,transparent)]",
  danger: "!border-[color-mix(in_srgb,var(--nx-rose)_30%,transparent)]",
  info: "!border-[color-mix(in_srgb,var(--nx-cyan)_28%,transparent)]",
};

export interface SurfaceProps {
  children: ReactNode;
  className?: string;
  elevation?: Elevation;
  padding?: Padding;
  tone?: Tone;
  /** Frosted translucent material. Use for overlays and sticky bars. */
  glass?: boolean;
  /** Hover lift + shadow bloom. Implies the whole surface is actionable. */
  interactive?: boolean;
  /** Pointer-tracked 3D tilt. Reserve for hero cards. */
  tilt?: boolean;
  /** Cursor-following specular highlight. */
  spotlight?: boolean;
  /** Animated hairline sweeping the top edge — means "streaming right now". */
  live?: boolean;
  rounded?: "md" | "lg" | "xl";
  onClick?: () => void;
  style?: CSSProperties;
  as?: "div" | "section" | "article" | "aside";
}

const ROUNDED = {
  md: "rounded-xl",
  lg: "rounded-2xl",
  xl: "rounded-3xl",
} as const;

/** Maximum rotation in degrees. Past ~8° the text edges start to alias. */
const MAX_TILT = 5;

export function Surface({
  children,
  className = "",
  elevation = 1,
  padding = "md",
  tone = "neutral",
  glass = false,
  interactive = false,
  tilt = false,
  spotlight = false,
  live = false,
  rounded = "lg",
  onClick,
  style,
  as = "div",
}: SurfaceProps) {
  const ref = useRef<HTMLDivElement>(null);
  const frame = useRef<number | null>(null);

  // Pointer maths runs on every mousemove, so it is throttled to one write
  // per animation frame and touches only custom properties — no React state,
  // no re-render, no layout thrash.
  const handleMove = useCallback(
    (event: React.MouseEvent<HTMLElement>) => {
      if (!tilt && !spotlight) return;
      const node = ref.current;
      if (!node) return;

      const { clientX, clientY } = event;
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => {
        const rect = node.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const px = (clientX - rect.left) / rect.width;
        const py = (clientY - rect.top) / rect.height;

        if (spotlight) {
          node.style.setProperty("--mx", `${px * 100}%`);
          node.style.setProperty("--my", `${py * 100}%`);
        }
        if (tilt) {
          // Invert X: pushing the pointer up should tip the top edge away.
          node.style.setProperty("--ry", `${(px - 0.5) * 2 * MAX_TILT}deg`);
          node.style.setProperty("--rx", `${-(py - 0.5) * 2 * MAX_TILT}deg`);
        }
      });
    },
    [tilt, spotlight]
  );

  const handleLeave = useCallback(() => {
    const node = ref.current;
    if (!node) return;
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    node.style.setProperty("--rx", "0deg");
    node.style.setProperty("--ry", "0deg");
  }, []);

  const Element = as as "div";

  return (
    <Element
      ref={ref}
      onClick={onClick}
      onMouseMove={tilt || spotlight ? handleMove : undefined}
      onMouseLeave={tilt ? handleLeave : undefined}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e: React.KeyboardEvent) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      style={style}
      className={[
        ROUNDED[rounded],
        glass ? "nx-glass" : ELEVATION[elevation],
        "nx-surface min-w-0",
        PADDING[padding],
        TONE[tone],
        interactive || onClick ? "nx-lift cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/70 focus-visible:ring-offset-2 focus-visible:ring-offset-nexus-bg" : "",
        tilt ? "nx-tilt" : "",
        spotlight ? "nx-spotlight" : "",
        live ? "nx-live-rim" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Element>
  );
}

/**
 * Header row for a Surface: icon chip, title, one line of context, and an
 * optional action. The subtitle is not decoration — a metric with no
 * explanation of what it measures is a number nobody can act on.
 */
export function SurfaceHeader({
  title,
  subtitle,
  icon,
  tone = "accent",
  action,
  className = "",
}: {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  tone?: Tone;
  action?: ReactNode;
  className?: string;
}) {
  // Token-derived tints so the icon chips follow the active theme.
  const ICON_TONE: Record<Tone, string> = {
    neutral: "text-nexus-muted bg-white/[0.05]",
    accent: "text-nexus-accent-bright bg-nexus-accent/15",
    success: "text-nexus-accent2 bg-nexus-accent2/12",
    warning: "text-nexus-accent3 bg-nexus-accent3/12",
    danger: "text-nexus-accent4 bg-nexus-accent4/12",
    info: "text-nexus-cyan bg-nexus-cyan/12",
  };

  return (
    <div className={`flex items-start justify-between gap-3 ${className}`}>
      <div className="flex min-w-0 items-center gap-2.5">
        {icon ? (
          <span
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${ICON_TONE[tone]}`}
          >
            {icon}
          </span>
        ) : null}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold leading-snug tracking-tight text-nexus-text">
            {title}
          </h3>
          {subtitle ? (
            <p className="mt-0.5 text-[11px] leading-relaxed text-nexus-muted">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export default Surface;
