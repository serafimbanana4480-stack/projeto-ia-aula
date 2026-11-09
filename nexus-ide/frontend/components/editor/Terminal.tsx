"use client";

import { Play, SquareTerminal, TerminalSquare, Bot } from "lucide-react";
import type { TerminalExecutionResult } from "../../lib/types";

interface TerminalProps {
  command: string;
  onCommandChange: (value: string) => void;
  onRun: () => void;
  running: boolean;
  results: TerminalExecutionResult[];
}

/**
 * Terminal output.
 *
 * Each run states who asked for it. A command the agent issued is a different
 * fact from one the user typed, and the previous rendering showed both as a
 * bare `$ …` line, so an autonomous run read as if the user had typed it.
 */
function CommandOrigin({ origin }: { origin?: "user" | "agent" }) {
  if (origin === "agent") {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-nexus-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-nexus-accent">
        <Bot className="h-2.5 w-2.5" aria-hidden="true" />
        IA
      </span>
    );
  }
  if (origin === "user") {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-nexus-accent2/10 px-1.5 py-0.5 text-[10px] font-medium text-nexus-accent2">
        <TerminalSquare className="h-2.5 w-2.5" aria-hidden="true" />
        Tu
      </span>
    );
  }
  return null;
}

export default function Terminal({
  command,
  onCommandChange,
  onRun,
  running,
  results,
}: TerminalProps) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-nexus-void font-mono text-xs text-nexus-text">
      {/* No second header bar here: the parent already labels the panel
          "Terminal local / Execução segura via sandbox", and two stacked bars
          on one panel read as two panes. */}

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
            aria-label="Comando a executar"
            className="flex-1 rounded-md border border-nexus-border bg-nexus-void px-3 py-2 text-nexus-text placeholder:text-nexus-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/70"
          />
          <button
            type="button"
            onClick={onRun}
            disabled={running || !command.trim()}
            aria-busy={running}
            className="inline-flex items-center gap-2 rounded-md bg-nexus-accent px-3 py-2 font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" aria-hidden="true" />
            {running ? "A executar…" : "Executar"}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {results.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 rounded-md border border-dashed border-nexus-border px-3 py-6 text-center text-nexus-faint">
            <SquareTerminal className="h-5 w-5" aria-hidden="true" />
            <p className="font-medium text-nexus-muted">Sem execuções</p>
            <p className="max-w-[38ch] text-[11px] leading-relaxed">
              Escreve um comando acima para ver o resultado aqui. O output, os
              erros e o código de saída aparecem separados.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {results.map((result) => {
              const ok = result.exit_code === 0 && !result.timed_out;
              return (
                <div
                  key={result.execution_id}
                  className="nx-inset rounded-md p-3"
                >
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-nexus-faint">
                    <span className="flex min-w-0 items-center gap-2">
                      <CommandOrigin origin={result.origin} />
                      <span className="truncate font-mono text-nexus-text">
                        $ {result.command}
                      </span>
                    </span>
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        ok
                          ? "bg-nexus-accent2/10 text-nexus-accent2"
                          : "bg-nexus-accent4/10 text-nexus-accent4"
                      }`}
                    >
                      {result.risk_level} · saída {result.exit_code}
                    </span>
                  </div>
                  {result.stdout && (
                    <pre className="whitespace-pre-wrap break-words text-nexus-text">
                      {result.stdout}
                    </pre>
                  )}
                  {result.stderr && (
                    <pre
                      className="mt-2 whitespace-pre-wrap break-words text-nexus-accent4"
                      aria-label="Erros do comando"
                    >
                      {result.stderr}
                    </pre>
                  )}
                  <div className="mt-2 text-[11px] text-nexus-faint">
                    {result.duration_ms}ms
                    {result.timed_out ? " · tempo excedido" : ""}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
