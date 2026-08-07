export default function Loading() {
  return (
    <div
      className="flex h-screen items-center justify-center bg-nexus-bg text-nexus-muted"
      aria-busy="true"
      aria-live="polite"
    >
      <div className="flex items-center gap-3 text-sm">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
        A carregar secção...
      </div>
    </div>
  );
}
