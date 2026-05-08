"use client";
import { useEffect } from "react";
import { useModeStore } from "../../stores/modeStore";
import { motion } from "framer-motion";
import { Bot, Compass, Bug, MessageCircle } from "lucide-react";

const MODES = [
  { id: "agent", label: "Agent", desc: "Autonomous tool-using workflow", icon: Bot },
  { id: "plan", label: "Plan", desc: "Planning-only mode", icon: Compass },
  { id: "debug", label: "Debug", desc: "Root-cause investigation", icon: Bug },
  { id: "ask", label: "Ask", desc: "Direct answer mode", icon: MessageCircle },
];

export default function ModeSelector() {
  const { currentMode, setMode } = useModeStore();

  useEffect(() => {
    const storedMode = window.localStorage.getItem("nexus.currentMode");
    if (storedMode) setMode(storedMode);
  }, [setMode]);

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-1 rounded-full border border-nexus-border bg-nexus-panel/70 px-2 py-1 backdrop-blur"
    >
      <span className="text-[10px] uppercase tracking-wide text-gray-500">Mode</span>
      {MODES.map((mode) => {
        const Icon = mode.icon;
        return (
          <motion.button
            key={mode.id}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => setMode(mode.id)}
            className={`rounded-full px-2 py-1 text-[10px] font-medium transition-colors flex items-center gap-1 ${
              currentMode === mode.id
                ? "bg-nexus-accent text-black shadow-sm"
                : "bg-black/20 text-gray-400 hover:text-gray-200"
            }`}
            title={mode.desc}
          >
            <Icon className="h-2.5 w-2.5" />
            {mode.label}
          </motion.button>
        );
      })}
    </motion.div>
  );
}
