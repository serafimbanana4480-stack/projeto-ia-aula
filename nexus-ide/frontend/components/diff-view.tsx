"use client";

import React, { useMemo } from "react";

export type DiffLineType = "add" | "remove" | "context" | "hunk";

export interface DiffLine {
  type: DiffLineType;
  oldLine: number | null;
  newLine: number | null;
  content: string;
}

export interface DiffHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: DiffLine[];
}

interface CodeDiffViewProps {
  hunks: DiffHunk[];
  filename?: string;
  oldFilename?: string;
  showLineNumbers?: boolean;
  className?: string;
}

const typeToBg: Record<DiffLineType, string> = {
  add: "bg-emerald-950/40",
  remove: "bg-red-950/40",
  context: "bg-transparent",
  hunk: "bg-blue-950/30",
};

const typeToBorder: Record<DiffLineType, string> = {
  add: "border-l-2 border-l-emerald-500",
  remove: "border-l-2 border-l-red-500",
  context: "border-l-2 border-l-transparent",
  hunk: "border-l-2 border-l-blue-400",
};

const typeToSymbol: Record<DiffLineType, string> = {
  add: "+",
  remove: "−",
  context: " ",
  hunk: "@",
};

/**
 * Parse unified diff text into structured hunks.
 * Supports unified diff format:
 * @@ -oldStart,oldLines +newStart,newLines @@
 */
export function parseUnifiedDiff(diffText: string): DiffHunk[] {
  const lines = diffText.split("\n");
  const hunks: DiffHunk[] = [];
  let currentHunk: DiffHunk | null = null;
  let oldLine = 0;
  let newLine = 0;

  for (const rawLine of lines) {
    if (rawLine.startsWith("@@")) {
      const m = rawLine.match(
        /@@\s*-([0-9]+)(?:,([0-9]+))?\s*\+([0-9]+)(?:,([0-9]+))?\s*@@/
      );
      if (m) {
        currentHunk = {
          oldStart: parseInt(m[1], 10),
          oldLines: m[2] ? parseInt(m[2], 10) : 1,
          newStart: parseInt(m[3], 10),
          newLines: m[4] ? parseInt(m[4], 10) : 1,
          lines: [],
        };
        hunks.push(currentHunk);
        oldLine = currentHunk.oldStart;
        newLine = currentHunk.newStart;
      }
      continue;
    }

    if (!currentHunk) continue;

    let type: DiffLineType = "context";
    if (rawLine.startsWith("+")) type = "add";
    else if (rawLine.startsWith("-")) type = "remove";
    else if (rawLine.startsWith("@")) type = "hunk";

    const content = rawLine.slice(1);

    const line: DiffLine = {
      type,
      oldLine: type === "add" ? null : oldLine,
      newLine: type === "remove" ? null : newLine,
      content,
    };

    if (type === "context") {
      oldLine++;
      newLine++;
    } else if (type === "add") {
      newLine++;
    } else if (type === "remove") {
      oldLine++;
    }

    currentHunk.lines.push(line);
  }

  return hunks;
}

export default function CodeDiffView({
  hunks,
  filename,
  oldFilename,
  showLineNumbers = true,
  className = "",
}: CodeDiffViewProps) {
  const stats = useMemo(() => {
    let added = 0;
    let removed = 0;
    for (const h of hunks) {
      for (const l of h.lines) {
        if (l.type === "add") added++;
        if (l.type === "remove") removed++;
      }
    }
    return { added, removed };
  }, [hunks]);

  return (
    <div
      className={`rounded-lg border border-slate-700 bg-slate-900 text-sm font-mono overflow-hidden ${className}`}
      data-testid="code-diff-view"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          {oldFilename && oldFilename !== filename ? (
            <span className="text-slate-300">
              {oldFilename} → <span className="text-white font-semibold">{filename}</span>
            </span>
          ) : (
            <span className="text-white font-semibold">{filename}</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs">
          {stats.added > 0 && (
            <span className="text-emerald-400">+{stats.added}</span>
          )}
          {stats.removed > 0 && (
            <span className="text-red-400">−{stats.removed}</span>
          )}
        </div>
      </div>

      {/* Diff body */}
      <div className="overflow-x-auto">
        {hunks.map((hunk, hi) => (
          <div key={hi}>
            {/* Hunk header */}
            <div className="px-4 py-1 bg-slate-800/60 text-blue-300 text-xs border-y border-slate-700/50">
              @@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@
            </div>

            <table className="w-full border-collapse">
              <tbody>
                {hunk.lines.map((line, li) => (
                  <tr
                    key={li}
                    className={`${typeToBg[line.type]} ${typeToBorder[line.type]} hover:bg-slate-800/50 transition-colors`}
                  >
                    {showLineNumbers && (
                      <>
                        <td className="text-right pr-2 w-12 text-slate-500 select-none text-xs py-0.5">
                          {line.oldLine ?? ""}
                        </td>
                        <td className="text-right pr-2 w-12 text-slate-500 select-none text-xs py-0.5 border-r border-slate-700/50">
                          {line.newLine ?? ""}
                        </td>
                      </>
                    )}
                    <td className="pl-3 pr-4 whitespace-pre py-0.5">
                      <span className="select-none text-slate-500 mr-1">
                        {typeToSymbol[line.type]}
                      </span>
                      <span className="text-slate-200">{line.content}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}

/*
Usage example:

import CodeDiffView, { parseUnifiedDiff } from "@/components/diff-view";

const diff = parseUnifiedDiff(`\
@@ -1,5 +1,6 @@
 function hello() {
-  console.log("old");
+  console.log("new");
+  return 42;
 }
`);

<CodeDiffView hunks={diff} filename="hello.js" />
*/
