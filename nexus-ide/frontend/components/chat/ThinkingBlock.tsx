"use client";
import { useState, memo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Brain } from "lucide-react";

interface ThinkingBlockProps {
  content: string;
  iteration?: number;
}

function ThinkingBlock({
  content,
  iteration,
}: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(true);

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-3 rounded border border-nexus-border/50 bg-nexus-panel/30 p-3"
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-300"
      >
        <Brain className="h-3 w-3 text-nexus-accent" />
        <span className="font-medium">Thinking</span>
        {iteration && (
          <span className="text-gray-500">Iteration {iteration}</span>
        )}
        {expanded ? (
          <ChevronUp className="h-3 w-3" />
        ) : (
          <ChevronDown className="h-3 w-3" />
        )}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="mt-2 overflow-hidden"
          >
            <div className="text-xs text-gray-400 whitespace-pre-wrap">
              {content}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export default memo(ThinkingBlock);
