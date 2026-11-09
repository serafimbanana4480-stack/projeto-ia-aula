"use client";

import React from "react";

// ─── Base Skeleton ───────────────────────────────────────────────────────────

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string;
}

/**
 * Base skeleton block.
 *
 * Uses the design-system `.nx-shimmer` sweep instead of a second overlapping
 * `animate-pulse`: two simultaneous pulses read as flicker, and `slate-*` is
 * off-token so the placeholder stays dark in the light theme.
 * Use className to control dimensions (w-xx, h-xx, rounded-xx).
 */
export function Skeleton({ className = "", ...props }: SkeletonProps) {
  return (
    <div
      className={`nx-shimmer rounded-lg ${className}`}
      {...props}
    />
  );
}

// ─── Dashboard Widget Skeleton ──────────────────────────────────────────────

/**
 * Skeleton that fills its parent container (intended to be placed inside a
 * .nexus-widget div).  Matches the internal layout of a typical dashboard
 * widget: a header bar + body placeholder rows.
 */
export function WidgetSkeleton() {
  return (
    <div className="h-full flex flex-col">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-nexus-border/60">
        <div className="flex items-center gap-2">
          <Skeleton className="w-4 h-4 rounded" />
          <Skeleton className="h-3 w-36 rounded" />
        </div>
        <Skeleton className="h-3 w-16 rounded" />
      </div>

      {/* Body placeholder rows */}
      <div className="flex-1 p-4 space-y-3">
        <Skeleton className="h-3 w-3/4 rounded" />
        <Skeleton className="h-3 w-1/2 rounded" />
        <Skeleton className="h-3 w-5/6 rounded" />
        <div className="pt-2 space-y-2">
          <Skeleton className="h-8 w-full rounded-lg" />
          <Skeleton className="h-8 w-full rounded-lg" />
          <Skeleton className="h-8 w-2/3 rounded-lg" />
        </div>
      </div>
    </div>
  );
}

/** Compact skeleton for smaller stat cards (e.g. inside a stats grid). */
export function CardSkeleton() {
  return (
    <div className="nx-card p-4 space-y-3">
      <Skeleton className="h-3 w-24 rounded" />
      <Skeleton className="h-8 w-16 rounded" />
      <Skeleton className="h-2 w-full rounded" />
    </div>
  );
}

/** Tall skeleton for charts / graphs. */
export function ChartSkeleton() {
  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-nexus-border/60">
        <Skeleton className="h-3 w-32 rounded" />
        <Skeleton className="h-3 w-12 rounded" />
      </div>
      <div className="flex-1 p-4 flex items-end gap-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton
            key={i}
            className="flex-1 rounded-t"
            // Deterministic heights: `Math.random()` here produces a
            // server/client hydration mismatch and reshuffles on re-render.
            style={{ height: `${30 + ((i * 29) % 45)}%` }}
          />
        ))}
      </div>
    </div>
  );
}

/** Wide skeleton for table‑like layouts. */
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="flex gap-4 px-4 py-2">
        <Skeleton className="h-3 w-1/4 rounded" />
        <Skeleton className="h-3 w-1/4 rounded" />
        <Skeleton className="h-3 w-1/4 rounded" />
        <Skeleton className="h-3 w-1/4 rounded" />
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 px-4 py-3 border-b border-nexus-border/40">
          <Skeleton className="h-3 w-1/4 rounded" />
          <Skeleton className="h-3 w-1/4 rounded" />
          <Skeleton className="h-3 w-1/4 rounded" />
          <Skeleton className="h-3 w-1/6 rounded" />
        </div>
      ))}
    </div>
  );
}

// ─── Full dashboard skeleton (used as Suspense fallback in dashboard/page.tsx) ──

export function DashboardSkeleton() {
  return (
    <div className="p-4 space-y-4">
      {/* Top row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="nx-elev-1 overflow-hidden rounded-nx-lg lg:col-span-2">
          <WidgetSkeleton />
        </div>
        <div className="nx-elev-1 overflow-hidden rounded-nx-lg">
          <WidgetSkeleton />
        </div>
      </div>

      {/* Middle row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="nx-elev-1 overflow-hidden rounded-nx-lg">
          <WidgetSkeleton />
        </div>
        <div className="nx-elev-1 overflow-hidden rounded-nx-lg">
          <WidgetSkeleton />
        </div>
        <div className="nx-elev-1 overflow-hidden rounded-nx-lg">
          <WidgetSkeleton />
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="nx-elev-1 overflow-hidden rounded-nx-lg">
          <WidgetSkeleton />
        </div>
        <div className="nx-elev-1 overflow-hidden rounded-nx-lg">
          <WidgetSkeleton />
        </div>
      </div>
    </div>
  );
}
