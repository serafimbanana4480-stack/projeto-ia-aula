import AppShell from "../../components/layout/AppShell";

export default function DashboardLoading() {
  return (
    <AppShell title="Dashboard" noPadding mainAs="div">
      <div className="min-h-full" aria-busy="true" aria-label="A carregar o painel">
        <div className="border-b border-nexus-border/60 px-4 py-6 sm:px-6 sm:py-7 lg:px-8">
          <div className="mx-auto flex max-w-7xl flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2.5">
              <div className="nx-shimmer h-3 w-32 rounded" />
              <div className="nx-shimmer h-8 w-64 rounded" />
              <div className="nx-shimmer h-3 w-80 max-w-full rounded" />
            </div>
            <div className="grid grid-cols-2 gap-2.5 min-[380px]:grid-cols-3 sm:flex sm:items-stretch">
              {["model", "uptime", "updated"].map((key) => (
                <div key={key} className="nx-shimmer h-14 min-w-0 rounded-xl" />
              ))}
            </div>
          </div>
        </div>

        <div
          aria-hidden="true"
          className="sticky top-0 z-20 border-b border-nexus-border/70 bg-nexus-bg/95 px-4 py-2 sm:px-6 lg:px-8"
        >
          <div className="mx-auto flex max-w-7xl flex-wrap gap-1.5 sm:flex-nowrap">
            {["w-16", "w-28", "w-20", "w-24", "w-16", "w-14"].map((width, index) => (
              <div key={index} className={`nx-shimmer h-10 shrink-0 rounded-lg ${width}`} />
            ))}
          </div>
        </div>

        <div className="mx-auto max-w-7xl space-y-6 px-4 py-5 sm:px-6 sm:py-6 lg:px-8">
          <div className="nx-shimmer h-44 rounded-2xl" />
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
          <div className="nx-shimmer h-52 rounded-2xl" />
          <div className="nx-shimmer h-44 rounded-2xl" />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {["integration-1", "integration-2", "integration-3"].map((key) => (
              <div key={key} className="nx-shimmer h-52 rounded-2xl" />
            ))}
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="nx-shimmer h-52 rounded-2xl lg:col-span-2" />
            <div className="nx-shimmer h-52 rounded-2xl" />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="nx-shimmer h-64 rounded-2xl lg:col-span-2" />
            <div className="nx-shimmer h-64 rounded-2xl" />
          </div>
        </div>
      </div>
    </AppShell>
  );
}
