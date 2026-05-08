"use client";

// Minimal file tree. Phase 5 will add real file ops via /api/files.
export default function FileExplorer() {
  return (
    <div className="text-sm text-gray-300">
      <div className="mb-2 font-semibold uppercase tracking-wide text-xs text-gray-500">
        Explorer
      </div>
      <ul className="space-y-1">
        <li>📁 src/</li>
        <li className="pl-4">📄 main.ts</li>
        <li>📁 tests/</li>
      </ul>
    </div>
  );
}
