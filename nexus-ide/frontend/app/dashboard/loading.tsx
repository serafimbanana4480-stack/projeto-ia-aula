export default function DashboardLoading() {
  return (
    <div className="min-h-full" aria-busy="true" aria-label="A carregar o painel">
      <div className="border-b border-nexus-border/60 px-4 py-6 sm:px-6 sm:py-7 lg:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2.5">
            <div className="nx-shimmer h-3 w-32 rounded" />
            <div className="nx-shimmer h-8 w-64 rounded" />
            <div className="nx-shimmer h-3 w-80 max-w-full rounded" />
          </div>
        </div>
      </div>
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-5 sm:px-6 sm:py-6 lg:px-8">
        <div className="nx-shimmer h-44 rounded-2xl" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {["kpi-1", "kpi-2", "kpi-3", "kpi-4"].map((key) => (
            <div key={key} className="nx-shimmer h-28 rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  );
}
