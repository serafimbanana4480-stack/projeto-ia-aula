export default function DashboardLoading() {
  return (
    <main className="flex-1 overflow-auto">
      <div className="sticky top-0 z-10 border-b border-nexus-border bg-nexus-panel/90 px-4 py-2 backdrop-blur">
        <div className="flex items-center gap-4 text-xs">
          <div className="h-2 w-2 animate-pulse rounded-full bg-yellow-500" />
          <span className="text-gray-500">A carregar dashboard…</span>
        </div>
      </div>
      <div className="p-4 space-y-4">
        <div className="h-32 animate-pulse rounded bg-nexus-border/20" />
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="space-y-4">
            <div className="h-64 animate-pulse rounded bg-nexus-border/20" />
            <div className="h-64 animate-pulse rounded bg-nexus-border/20" />
            <div className="h-64 animate-pulse rounded bg-nexus-border/20" />
          </div>
          <div className="space-y-4">
            <div className="h-64 animate-pulse rounded bg-nexus-border/20" />
            <div className="h-64 animate-pulse rounded bg-nexus-border/20" />
          </div>
        </div>
        <div className="h-48 animate-pulse rounded bg-nexus-border/20" />
        <div className="h-48 animate-pulse rounded bg-nexus-border/20" />
      </div>
    </main>
  );
}
