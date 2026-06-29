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

function TreeNode({
  node,
  depth,
  activePath,
  onSelectFile,
}: {
  node: FileTreeEntry;
  depth: number;
  activePath: string;
  onSelectFile: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const isActive = activePath === node.path;
  const hasChildren = (node.children?.length ?? 0) > 0;
  const paddingLeft = useMemo(() => `${depth * 0.85}rem`, [depth]);

  if (node.type === "file") {
    return (
      <button
        type="button"
        onClick={() => onSelectFile(node.path)}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
          isActive
            ? "bg-nexus-accent text-black"
            : "text-gray-300 hover:bg-nexus-border/60"
        }`}
        style={{ paddingLeft }}
      >
        <File className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{node.name}</span>
      </button>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
          isActive
            ? "bg-nexus-border/70 text-gray-100"
            : "text-gray-300 hover:bg-nexus-border/60"
        }`}
        style={{ paddingLeft }}
      >
        {hasChildren ? (
          <ChevronRight
            className={`h-3.5 w-3.5 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}
          />
        ) : (
          <span className="w-3.5" />
        )}
        {expanded ? (
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-nexus-accent" />
        ) : (
          <Folder className="h-3.5 w-3.5 shrink-0 text-nexus-accent" />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {expanded && hasChildren && (
        <div className="mt-0.5 space-y-0.5">
          {node.children!.map((child) => (
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
  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-nexus-border/60 bg-black/20 px-3 py-2 text-sm text-gray-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading files...
      </div>
    );
  }

  if (tree.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-nexus-border/70 px-3 py-4 text-sm text-gray-500">
        No files found.
      </div>
    );
  }

  return (
    <div className="space-y-0.5">
      {tree.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          activePath={activePath}
          onSelectFile={onSelectFile}
        />
      ))}
    </div>
  );
}
