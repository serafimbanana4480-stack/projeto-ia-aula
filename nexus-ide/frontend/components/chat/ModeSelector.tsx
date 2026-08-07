"use client";
/**
 * NEXUS IDE — Enhanced Mode Selector
 *
 * Shows both standard cognitive modes and the advanced Infinity Suite modes.
 * Standard modes handle agent behaviour, advanced modes handle orchestration.
 */
import { useEffect } from "react";
import { useModeStore } from "../../stores/modeStore";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";
import { motion } from "framer-motion";
import {
  Bot,
  Compass,
  Bug,
  MessageCircle,
  Code2,
  Sparkles,
  Search,
  Zap,
  Brain,
  Users,
  Gauge,
  LucideIcon,
  Infinity,
} from "lucide-react";

const MODE_ICONS: Record<string, LucideIcon> = {
  auto: Sparkles,
  auto_swarm: Users,
  swarm: Users,
  coder: Code2,
  reviewer: Search,
  analyst: Gauge,
  fast: Zap,
  deep: Brain,
  plan: Compass,
  debug: Bug,
  ask: MessageCircle,
  dashboard: Gauge,
};

const FEATURED_MODES = ["auto", "auto_swarm", "swarm", "plan", "debug", "ask"];

export default function ModeSelector() {
  const { currentMode, setMode, modes, loadModes, modesError } = useModeStore();
  const { activeModeIds } = useAdvancedModeStore();

  useEffect(() => {
    loadModes();
  }, [loadModes]);

  useEffect(() => {
    const storedMode = window.localStorage.getItem("nexus.currentMode");
    if (storedMode) setMode(storedMode);
  }, [setMode]);

  const available =
    modes.length > 0
      ? FEATURED_MODES.map((id) => modes.find((m) => m.id === id)).filter(
          (m): m is NonNullable<typeof m> => Boolean(m)
        )
      : [
          { id: "auto", description: "Autonomous tool-using workflow" },
          { id: "plan", description: "Planning-only mode" },
          { id: "debug", description: "Root-cause investigation" },
          { id: "ask", description: "Direct answer mode" },
        ];

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-1 rounded-full border border-nexus-border bg-nexus-panel/70 px-2 py-1 backdrop-blur"
    >
      <span className="text-[10px] uppercase tracking-wide text-gray-500">Mode</span>

      {/* Standard modes */}
      {available.map((mode) => {
        const Icon = MODE_ICONS[mode.id] ?? Bot;
        const label =
          mode.id === "auto_swarm"
            ? "Auto Swarm"
            : mode.id.charAt(0).toUpperCase() + mode.id.slice(1);
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
            title={modesError && modes.length === 0 ? modesError : mode.description}
          >
            <Icon className="h-2.5 w-2.5" />
            {label}
          </motion.button>
        );
      })}

      {/* Separator when advanced modes are active */}
      {activeModeIds.length > 0 && (
        <div className="mx-1 h-4 w-px bg-purple-500/30" />
      )}

      {/* Active advanced mode badges */}
      {activeModeIds.length > 0 && (
        <div className="flex items-center gap-0.5">
          {activeModeIds.slice(0, 3).map((id) => (
            <span
              key={id}
              className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[8px] font-medium text-purple-300"
              style={{
                backgroundColor: "rgba(139, 92, 246, 0.15)",
              }}
            >
              <Infinity className="h-2 w-2" />
              {id === "autonomous" ? "∞" : id.split("-")[0]}
            </span>
          ))}
          {activeModeIds.length > 3 && (
            <span className="text-[8px] text-gray-500">
              +{activeModeIds.length - 3}
            </span>
          )}
        </div>
      )}
    </motion.div>
  );
}
