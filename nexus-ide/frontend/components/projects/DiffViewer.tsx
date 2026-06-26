"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, X, Eye, FileText } from "lucide-react";

interface DiffChange {
  id: string;
  file_path: string;
  operation: "create" | "modify" | "delete";
  diff: string;
  new_content: string;
}

interface DiffViewerProps {
  changes: DiffChange[];
  onApply: (changeId: string) => void;
  onReject: (changeId: string) => void;
}

export default function DiffViewer({ changes, onApply, onReject }: DiffViewerProps) {
  const [selectedChange, setSelectedChange] = useState<DiffChange | null>(null);

  const getOperationColor = (op: string) => {
    switch (op) {
      case "create":
        return "bg-green-500/20 border-green-500/30 text-green-400";
      case "modify":
        return "bg-yellow-500/20 border-yellow-500/30 text-yellow-400";
      case "delete":
        return "bg-red-500/20 border-red-500/30 text-red-400";
    }
  };

  const getOperationIcon = (op: string) => {
    switch (op) {
      case "create":
        return "+";
      case "modify":
        return "~";
      case "delete":
        return "-";
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-nexus-accent" />
          <span className="text-sm font-semibold">Proposed Changes</span>
          <span className="text-xs text-gray-500">({changes.length} files)</span>
        </div>
      </div>

      <div className="space-y-2">
        {changes.map((change) => (
          <motion.div
            key={change.id}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            className="rounded border border-nexus-border/50 bg-nexus-panel p-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`rounded px-2 py-0.5 text-xs font-medium ${getOperationColor(change.operation)}`}>
                  {getOperationIcon(change.operation)} {change.operation}
                </span>
                <span className="text-sm text-gray-300">{change.file_path}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSelectedChange(change)}
                  className="rounded p-1 text-gray-400 hover:bg-nexus-border hover:text-gray-300"
                >
                  <Eye className="h-4 w-4" />
                </button>
                <button
                  onClick={() => onApply(change.id)}
                  className="rounded p-1 text-green-400 hover:bg-green-500/20"
                >
                  <Check className="h-4 w-4" />
                </button>
                <button
                  onClick={() => onReject(change.id)}
                  className="rounded p-1 text-red-400 hover:bg-red-500/20"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          </motion.div>
        ))}
      </div>

      <AnimatePresence>
        {selectedChange && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
            onClick={() => setSelectedChange(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="max-h-[80vh] w-[800px] rounded-lg border border-nexus-border bg-nexus-panel p-4"
            >
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-nexus-accent" />
                  <span className="text-sm font-semibold">{selectedChange.file_path}</span>
                </div>
                <button
                  onClick={() => setSelectedChange(null)}
                  className="rounded p-1 text-gray-400 hover:bg-nexus-border hover:text-gray-300"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              
              <div className="overflow-auto rounded bg-black/30 p-4">
                <pre className="text-xs text-gray-400 whitespace-pre-wrap">
                  {selectedChange.diff || selectedChange.new_content}
                </pre>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
