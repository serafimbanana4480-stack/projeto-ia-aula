import { Suspense } from "react";
import DashboardClient from "./DashboardClient";
import AppShell from "../../components/layout/AppShell";

export const metadata = {
  title: "Dashboard | NEXUS IDE",
  description: "Métricas e saúde do sistema em tempo real",
};

/**
 * The fallback mirrors the real layout's geometry — hero band, four KPI cards,
 * four gauges, composer, three widgets. A skeleton whose shape differs from
 * what replaces it produces a visible reflow on hydration, which reads as the
 * page breaking rather than loading.
 */
function DashboardSkeleton() {
  return (
    <div className="min-h-full" aria-busy="true" aria-label="A carregar o painel">
      <div className="border-b border-nexus-border/60 px-6 py-7 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2.5">
            <div className="nx-shimmer h-3 w-32 rounded" />
            <div className="nx-shimmer h-8 w-64 rounded" />
            <div className="nx-shimmer h-3 w-80 rounded" />
          </div>
          <div className="flex gap-2.5">
            {[150, 130, 130].map((width) => (
              <div key={width} className="nx-shimmer h-14 rounded-xl" style={{ width }} />
            ))}
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl space-y-6 px-6 py-6 sm:px-8">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {["kpi-1", "kpi-2", "kpi-3", "kpi-4"].map((key) => (
            <div key={key} className="nx-shimmer h-28 rounded-xl" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {["gauge-1", "gauge-2", "gauge-3", "gauge-4"].map((key) => (
            <div key={key} className="nx-shimmer h-20 rounded-xl" />
          ))}
        </div>
        <div className="nx-shimmer h-44 rounded-2xl" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {["widget-1", "widget-2", "widget-3"].map((key) => (
            <div key={key} className="nx-shimmer h-52 rounded-2xl" />
          ))}
        </div>
      </div>
    </div>
  );
}

// `AppShell` is a client component but a Server Component (this file) is
// allowed to render one directly and pass Server/Client children into its
// `children` slot — that's the standard App Router composition pattern, so
// this page does not need "use client" itself and keeps its `metadata`
// export valid.
//
// `DashboardClient` renders a plain `<div>` root, so `AppShell` supplies the
// single `<main>` landmark for the route. (It previously rendered its own
// `<main>`, which is why this used to pass `mainAs="div"`.)
export default function DashboardPage() {
  return (
    <AppShell title="Dashboard" noPadding>
      <Suspense fallback={<DashboardSkeleton />}>
        <DashboardClient />
      </Suspense>
    </AppShell>
  );
}
