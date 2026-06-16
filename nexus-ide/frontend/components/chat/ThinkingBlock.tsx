"use client";
import { useState, memo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Brain, Sparkles } from "lucide-react";

interface ThinkingBlockProps {
  content: string;
  iteration?: number;
}

function ThinkingBlock({ content, iteration }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(true);

  return (
    <motion.div
      initial={{ opacity: 0, y: -8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="my-3"
    >
      <div className="rounded-xl bg-gradient-to-br from-indigo-500/10 via-purple-500/10 to-pink-500/10 p-[1px]">
        <div className="rounded-[11px] bg-nexus-panel/80 p-3.5 backdrop-blur-sm">
          <motion.button
            onClick={() => setExpanded(!expanded)}
            className="flex w-full items-center gap-2.5 text-left transition-colors duration-200"
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.99 }}
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 shadow-lg shadow-indigo-500/25">
              <Brain className="h-3.5 w-3.5 text-white" />
            </div>
            <span className="text-xs font-semibold tracking-wide text-nexus-text">
              Pensamento da IA
            </span>
            {iteration !== undefined && (
              <motion.span
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-indigo-500/20 to-purple-500/20 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-indigo-300 ring-1 ring-indigo-400/30"
              >
                <Sparkles className="h-2.5 w-2.5" />
                Iteração {iteration}
              </motion.span>
            )}
            <motion.div
              className="ml-auto flex items-center gap-1 rounded-full bg-nexus-bg/60 px-2 py-1 text-[10px] text-nexus-muted transition-colors duration-200 hover:bg-nexus-bg/80 hover:text-nexus-text"
              whileHover={{ scale: 1.05 }}
            >
              {expanded ? (
                <>
                  <span>Recolher</span>
                  <ChevronUp className="h-3 w-3" />
                </>
              ) : (
                <>
                  <span>Expandir</span>
                  <ChevronDown className="h-3 w-3" />
                </>
              )}
            </motion.div>
          </motion.button>

          <AnimatePresence initial={false}>
            {expanded && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.25, ease: "easeInOut" }}
                className="mt-3 overflow-hidden"
              >
                <div className="rounded-lg border border-indigo-500/15 bg-gradient-to-br from-indigo-500/5 to-purple-500/5 p-3 text-xs leading-relaxed text-nexus-muted shadow-inner">
                  <div className="whitespace-pre-wrap font-light">{content}</div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}

export default memo(ThinkingBlock);
