import { Suspense } from "react";
import EvolutionClient from "./EvolutionClient";
import AppShell from "../../../components/layout/AppShell";

export const metadata = {
  title: "Evolution Engine | NEXUS IDE",
  description: "Self-improving agent evolution engine — champions, challengers, failure analysis, and rollback history",
};

function EvolutionSkeleton() {
  return (
    <div className="min-h-full" aria-busy="true" aria-label="Loading evolution dashboard">
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
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {[1, 2, 3, 4].map((key) => (
            <div key={key} className="nx-shimmer h-64 rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function EvolutionPage() {
  return (
    <AppShell title="Evolution Engine" noPadding>
      <Suspense fallback={<EvolutionSkeleton />}>
        <EvolutionClient />
      </Suspense>
    </AppShell>
  );
}
