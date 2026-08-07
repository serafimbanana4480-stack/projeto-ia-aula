"use client";

/**
 * NEXUS IDE — Advanced Mode Header Indicator
 *
 * A compact indicator shown in the ChatPanel header when advanced modes
 * are active. Click to open the full Advanced Mode panel.
 */
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Infinity, Sparkles, Eye, Shield } from "lucide-react";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";

const MODE_MINI_ICONS: Record<string, React.ElementType> = {
  sentinel: Eye,
  "advisor-infinity": Shield,
  autonomous: Sparkles,
};

export default function AdvancedModeHeaderIndicator() {
  const { activeModeIds, loadModes } = useAdvancedModeStore();
  const [showPanel, setShowPanel] = useState(false);

  useEffect(() => {
    loadModes();
  }, [loadModes]);

  if (activeModeIds.length === 0) return null;

  // Open the AdvancedModePanel by dispatching a click to the floating button
  const handleClick = () => {
    // Find and click the floating Infinity button
    const btn = document.querySelector('[data-advanced-mode-toggle]') as HTMLButtonElement;
    btn?.click();
  };

  return (
    <motion.button
      initial={{ scale: 0 }}
      animate={{ scale: 1 }}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
      onClick={handleClick}
      className="flex items-center gap-1.5 rounded-lg border border-purple-500/30 bg-purple-500/10 px-2.5 py-1.5 text-xs font-medium text-purple-300 transition-all hover:bg-purple-500/20"
    >
      <Infinity className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">
        {activeModeIds.length} active
      </span>
      <div className="flex -space-x-1">
        {activeModeIds.slice(0, 3).map((id) => {
          const MiniIcon = MODE_MINI_ICONS[id] || Sparkles;
          return (
            <div
              key={id}
              className="flex h-4 w-4 items-center justify-center rounded-full bg-purple-500/20"
            >
              <MiniIcon className="h-2.5 w-2.5" />
            </div>
          );
        })}
      </div>
    </motion.button>
  );
}
