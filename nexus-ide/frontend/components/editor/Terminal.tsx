"use client";

import { Play, SquareTerminal } from "lucide-react";
import type { TerminalExecutionResult } from "../../lib/types";

interface TerminalProps {
  command: string;
  onCommandChange: (value: string) => void;
  onRun: () => void;
  running: boolean;
  results: TerminalExecutionResult[];
}

export default function Terminal({
  command,
  onCommandChange,
  onRun,
  running,
  results,
}: TerminalProps) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-black/40 font-mono text-xs text-gray-200">
      <div className="flex items-center gap-2 border-b border-nexus-border px-3 py-2 text-gray-400">
        <SquareTerminal className="h-3.5 w-3.5 text-nexus-accent" />
        <span>Shell local</span>
      </div>

      <div className="border-b border-nexus-border p-3">
        <div className="flex gap-2">
          <input
            value={command}
            onChange={(e) => onCommandChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onRun();
              }
            }}
            placeholder="npm test"
            className="flex-1 rounded-md border border-nexus-border bg-black/50 px-3 py-2 outline-none placeholder:text-gray-600 focus:border-nexus-accent"
          />
          <button
            type="button"
            onClick={onRun}
            disabled={running || !command.trim()}
            className="inline-flex items-center gap-2 rounded-md bg-nexus-accent px-3 py-2 font-semibold text-black disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" />
            {running ? "A executar..." : "Run"}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {results.length === 0 ? (
          <div className="rounded-md border border-dashed border-nexus-border/70 px-3 py-4 text-gray-500">
            Nenhuma execução ainda. Introduz um comando para ver o output aqui.
          </div>
        ) : (
          <div className="space-y-3">
            {results.map((result) => (
              <div
                key={result.execution_id}
                className="rounded-md border border-nexus-border bg-black/30 p-3"
              >
                <div className="mb-2 flex items-center justify-between text-[11px] text-gray-500">
                  <span className="truncate">$ {result.command}</span>
                  <span
                    className={
                      result.exit_code === 0 && !result.timed_out
                        ? "text-emerald-400"
                        : "text-rose-400"
                    }
                  >
                    {result.risk_level} • exit {result.exit_code}
                  </span>
                </div>
                {result.stdout && (
                  <pre className="whitespace-pre-wrap break-words text-gray-200">
                    {result.stdout}
                  </pre>
                )}
                {result.stderr && (
                  <pre className="mt-2 whitespace-pre-wrap break-words text-rose-300">
                    {result.stderr}
                  </pre>
                )}
                <div className="mt-2 text-[11px] text-gray-600">
                  {result.duration_ms}ms{result.timed_out ? " • timed out" : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
