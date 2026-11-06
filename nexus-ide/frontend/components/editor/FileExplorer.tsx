"use client";

import { ChevronRight, File, Folder, FolderOpen, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import type { FileTreeEntry } from "../../lib/types";

interface FileExplorerProps {
  tree: FileTreeEntry[];
  activePath: string;
  loading: boolean;
  onSelectFile: (path: string) => void;
}

/** Directories first, then alphabetically — the order every file tree uses. */
function sortNodes(nodes: FileTreeEntry[]): FileTreeEntry[] {
  return [...nodes].sort((a, b) => {
    if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { numeric: true });
  });
}

/**
 * Expand every ancestor of the active file.
 *
 * Only `depth < 1` used to auto-open, so opening a deep file from search left
 * it selected but invisible: the user saw the name in the header with nothing
 * highlighted in the tree.
 */
function ancestorPathsOf(path: string): Set<string> {
  const parts = path.split("/");
  const ancestors = new Set<string>();
  let current = "";
  for (let i = 0; i < parts.length - 1; i += 1) {
    current = current ? `${current}/${parts[i]}` : parts[i];
    ancestors.add(current);
  }
  return ancestors;
}

function TreeNode({
  node,
  depth,
  activePath,
  onSelectFile,
  forceOpen = false,
}: {
  node: FileTreeEntry;
  depth: number;
  activePath: string;
  onSelectFile: (path: string) => void;
  forceOpen?: boolean;
}) {
  const [expanded, setExpanded] = useState(depth < 1 || forceOpen);
  const isActive = activePath === node.path;
  const hasChildren = (node.children?.length ?? 0) > 0;
  const children = useMemo(() => (node.children ? sortNodes(node.children) : []), [node.children]);
  const paddingLeft = useMemo(() => `${depth * 0.85}rem`, [depth]);

  if (node.type === "file") {
    return (
      <button
        type="button"
        onClick={() => onSelectFile(node.path)}
        // `title` reveals the full name; the label itself is truncated so a
        // deep path does not push the tree sideways.
        title={node.path}
        aria-current={isActive ? "true" : undefined}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/70 ${
          isActive
            ? "bg-nexus-accent/20 font-medium text-nexus-text ring-1 ring-inset ring-nexus-accent/40"
            : "text-nexus-muted hover:bg-nexus-elevated hover:text-nexus-text"
        }`}
        style={{ paddingLeft }}
      >
        <File className="h-3.5 w-3.5 shrink-0 text-nexus-faint" aria-hidden="true" />
        <span className="truncate">{node.name}</span>
      </button>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/70 ${
          isActive
            ? "bg-nexus-elevated text-nexus-text"
            : "text-nexus-muted hover:bg-nexus-elevated hover:text-nexus-text"
        }`}
        style={{ paddingLeft }}
      >
        {hasChildren ? (
          <ChevronRight
            className={`h-3.5 w-3.5 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}
            aria-hidden="true"
          />
        ) : (
          <span className="w-3.5" aria-hidden="true" />
        )}
        {expanded ? (
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-nexus-accent" aria-hidden="true" />
        ) : (
          <Folder className="h-3.5 w-3.5 shrink-0 text-nexus-accent" aria-hidden="true" />
        )}
        <span className="truncate" title={node.name}>
          {node.name}
        </span>
      </button>
      {expanded && hasChildren && (
        <div className="mt-0.5 space-y-0.5">
          {children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              activePath={activePath}
              onSelectFile={onSelectFile}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function FileExplorer({
  tree,
  activePath,
  loading,
  onSelectFile,
}: FileExplorerProps) {
  const sortedTree = useMemo(() => sortNodes(tree), [tree]);
  // The active file's ancestors stay open, so the selection is always visible.
  const openAncestors = useMemo(
    () => (activePath ? ancestorPathsOf(activePath) : new Set<string>()),
    [activePath],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-nexus-border/60 bg-nexus-elevated px-3 py-2 text-sm text-nexus-muted">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        A carregar ficheiros…
      </div>
    );
  }

  if (tree.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-nexus-border px-3 py-4 text-sm text-nexus-muted">
        Nenhum ficheiro encontrado nesta pasta.
      </div>
    );
  }

  return (
    <div className="space-y-0.5" role="tree" aria-label="Ficheiros do projeto">
      {sortedTree.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          activePath={activePath}
          onSelectFile={onSelectFile}
          forceOpen={openAncestors.has(node.path)}
        />
      ))}
    </div>
  );
}
