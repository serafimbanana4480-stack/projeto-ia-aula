"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Play, CheckCircle, XCircle, Loader2 } from "lucide-react";

interface ToolCallCardProps {
  toolName: string;
  args: any;
  status: "running" | "success" | "error";
  result?: any;
  error?: string;
  durationMs?: number;
}

export default function ToolCallCard({ toolName, args, status, result, error, durationMs }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  const getStatusIcon = () => {
    switch (status) {
      case "running":
        return <Loader2 className="h-3 w-3 animate-spin text-nexus-accent" />;
      case "success":
        return <CheckCircle className="h-3 w-3 text-green-500" />;
      case "error":
        return <XCircle className="h-3 w-3 text-red-500" />;
    }
  };

  const getStatusColor = () => {
    switch (status) {
      case "running":
        return "border-nexus-accent/50 bg-nexus-accent/10";
      case "success":
        return "border-green-500/50 bg-green-500/10";
      case "error":
        return "border-red-500/50 bg-red-500/10";
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      className={`mb-2 rounded border ${getStatusColor()} p-2`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between"
      >
        <div className="flex items-center gap-2">
          {getStatusIcon()}
          <span className="text-xs font-medium">{toolName}</span>
          {durationMs && <span className="text-xs text-gray-500">{durationMs}ms</span>}
        </div>
        {expanded ? <ChevronUp className="h-3 w-3 text-gray-400" /> : <ChevronDown className="h-3 w-3 text-gray-400" />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="mt-2 overflow-hidden"
          >
            <div className="mb-2">
              <div className="text-xs text-gray-500">Arguments:</div>
              <pre className="mt-1 rounded bg-black/20 p-2 text-xs text-gray-400 overflow-x-auto">
                {JSON.stringify(args, null, 2)}
              </pre>
            </div>
            
            {status === "success" && result && (
              <div>
                <div className="text-xs text-gray-500">Result:</div>
                <pre className="mt-1 rounded bg-black/20 p-2 text-xs text-gray-400 overflow-x-auto">
                  {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
                </pre>
              </div>
            )}
            
            {status === "error" && error && (
              <div className="text-xs text-red-400">{error}</div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
