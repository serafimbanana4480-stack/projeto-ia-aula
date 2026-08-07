"use client";

import type { ReactNode } from "react";

/**
 * The single card primitive.
 *
 * Every widget previously repeated its own `rounded-xl border border-nexus-border
 * bg-[#13131f]/40 p-5 …` string, with padding drifting between p-3 and p-8 and
 * radii between lg and 2xl. Variants here keep density and elevation
 * consistent, and use the `nexus-*` tokens so theming actually works.
 *
 * DEPTH: variants map onto the same `.nx-elev-*` recipes that `Surface` uses,
 * rather than a flat `bg-*` fill. That matters because the KPI row is built on
 * `Card` — with a flat fill the page's most important numbers were also its
 * flattest elements, so nothing in the visual hierarchy agreed with the
 * information hierarchy. Delegating to the elevation scale gives every existing
 * `Card` call site a rim light and a layered shadow with no API change.
 */

type Padding = "none" | "sm" | "md" | "lg";
type Variant = "default" | "subtle" | "raised" | "accent";

const PADDING: Record<Padding, string> = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-6",
};

/** Each variant is a full depth recipe: fill + rim highlight + drop shadow. */
const VARIANT: Record<Variant, string> = {
  default: "nx-elev-1",
  subtle: "nx-elev-0",
  raised: "nx-elev-2",
  accent: "nx-elev-2 !border-[rgba(124,106,251,0.28)] shadow-nx-accent",
};

export interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: Padding;
  variant?: Variant;
  /** Adds a hover affordance. Use only when the whole card is clickable. */
  interactive?: boolean;
  onClick?: () => void;
}

export function Card({
  children,
  className = "",
  padding = "md",
  variant = "default",
  interactive = false,
  onClick,
}: CardProps) {
  const Element = onClick ? "button" : "div";
  return (
    <Element
      onClick={onClick}
      type={onClick ? "button" : undefined}
      className={[
        "rounded-xl",
        VARIANT[variant],
        // Specular sheen. Without it a dark fill reads as a hole, not an object.
        "nx-surface",
        PADDING[padding],
        interactive || onClick ? "nx-lift text-left" : "",
        onClick ? "w-full" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Element>
  );
}

export interface CardHeaderProps {
  title: string;
  /** One short line explaining what the card shows. Optional. */
  subtitle?: string;
  icon?: ReactNode;
  /** Tint for the icon chip, e.g. "text-nexus-accent bg-nexus-accent/10". */
  iconClassName?: string;
  action?: ReactNode;
  className?: string;
}

export function CardHeader({
  title,
  subtitle,
  icon,
  iconClassName = "text-nexus-accent bg-nexus-accent/10",
  action,
  className = "",
}: CardHeaderProps) {
  return (
    <div className={`flex items-start justify-between gap-3 ${className}`}>
      <div className="flex min-w-0 items-center gap-2.5">
        {icon ? (
          <span
            className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${iconClassName}`}
          >
            {icon}
          </span>
        ) : null}
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-nexus-text">{title}</h3>
          {subtitle ? (
            <p className="truncate text-[11px] text-nexus-muted">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/**
 * Small label/value pair used inside cards.
 *
 * Rendered as a sunken well (`.nx-inset`) rather than another raised box: a
 * stat nested inside a card is subordinate to it, and recessing it says so.
 * Stacking two raised surfaces would flatten both.
 */
export function CardStat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="nx-inset rounded-lg px-2.5 py-2" title={hint}>
      <div className="text-[10px] uppercase tracking-wider text-nexus-faint">{label}</div>
      <div className="mt-0.5 truncate text-[13px] font-semibold tabular-nums text-nexus-text">
        {value}
      </div>
    </div>
  );
}

/** Consistent empty state — replaces the ad-hoc "—" / "sem dados" strings. */
export function CardEmpty({
  children,
  icon,
}: {
  children: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-dashed border-nexus-border/70 bg-nexus-bg/30 px-3 py-3 text-[11px] text-nexus-muted">
      {icon}
      <span className="min-w-0">{children}</span>
    </div>
  );
}
