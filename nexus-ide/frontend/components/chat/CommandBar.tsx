"use client";
/**
 * NEXUS IDE — Enhanced CommandBar with /command support
 *
 * Features:
 * - /command autocomplete with mode info
 * - Visual feedback for active advanced modes
 * - Command suggestion chips
 * - Mode status indicators
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send,
  Paperclip,
  Mic,
  Command,
  Sparkles,
  Infinity,
  Shield,
  Hammer,
  Layers,
  GitBranch,
  CheckCircle,
  FlaskConical,
  Search,
  Brain,
  Eye,
} from "lucide-react";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";

interface CommandBarProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

const COMMAND_ICONS: Record<string, React.ElementType> = {
  "vibe-infinity": Infinity,
  "advisor-infinity": Shield,
  forge: Hammer,
  "swarm-foundry": Layers,
  multiverse: GitBranch,
  proof: CheckCircle,
  "reality-lab": FlaskConical,
  archaeologist: Search,
  evolve: Brain,
  sentinel: Eye,
  autonomous: Sparkles,
};

const COMMAND_COLORS: Record<string, string> = {
  "vibe-infinity": "#8B5CF6",
  "advisor-infinity": "#F59E0B",
  forge: "#EF4444",
  "swarm-foundry": "#10B981",
  multiverse: "#06B6D4",
  proof: "#22C55E",
  "reality-lab": "#F97316",
  archaeologist: "#6366F1",
  evolve: "#D946EF",
  sentinel: "#DC2626",
  autonomous: "#A855F7",
};

// Quick command suggestions
const SUGGESTED_COMMANDS = [
  { cmd: "/vibe-infinity", label: "Vibe", color: "#8B5CF6" },
  { cmd: "/advisor-infinity", label: "Advisor", color: "#F59E0B" },
  { cmd: "/forge", label: "Forge", color: "#EF4444" },
  { cmd: "/proof", label: "Proof", color: "#22C55E" },
  { cmd: "/archaeologist", label: "Archaeologist", color: "#6366F1" },
  { cmd: "/autonomous", label: "Auto", color: "#A855F7" },
];

export default function CommandBar({ onSend, disabled = false }: CommandBarProps) {
  const [input, setInput] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestions, setSuggestions] = useState<
    Array<{ cmd: string; label: string; description: string }>
  >([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const { commands, loadCommands, activeModeIds } = useAdvancedModeStore();

  useEffect(() => {
    loadCommands();
  }, [loadCommands]);

  const allCommands = Object.entries(commands).map(([name, cmd]) => ({
    cmd: `/${name}`,
    label: name,
    description: cmd.description,
    aliases: cmd.aliases || [],
  }));

  const handleInputChange = useCallback(
    (value: string) => {
      setInput(value);

      if (value.startsWith("/") && value.length > 1) {
        const query = value.toLowerCase();
        const matches = allCommands.filter(
          (c) =>
            c.cmd.toLowerCase().startsWith(query) ||
            c.label.toLowerCase().startsWith(query.slice(1)) ||
            c.aliases.some((a: string) => a.toLowerCase().startsWith(query))
        );
        setSuggestions(matches.slice(0, 6));
        setShowSuggestions(matches.length > 0);
        setSelectedIndex(0);
      } else if (value === "/") {
        setSuggestions(allCommands.slice(0, 6));
        setShowSuggestions(true);
        setSelectedIndex(0);
      } else {
        setShowSuggestions(false);
      }
    },
    [allCommands]
  );

  const handleSend = () => {
    const trimmed = input.trim();
    if (trimmed && !disabled) {
      onSend(trimmed);
      setInput("");
      setShowSuggestions(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showSuggestions) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, suggestions.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === "Tab" || e.key === "Enter") {
        const selected = suggestions[selectedIndex];
        if (selected && showSuggestions) {
          e.preventDefault();
          setInput(selected.cmd + " ");
          setShowSuggestions(false);
          inputRef.current?.focus();
          return;
        }
      }
      if (e.key === "Escape") {
        setShowSuggestions(false);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSuggestionClick = (cmd: string) => {
    setInput(cmd + " ");
    setShowSuggestions(false);
    inputRef.current?.focus();
  };

  // Detect if current input is a /command
  const isCommand = input.startsWith("/");

  return (
    <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="border-t border-nexus-border bg-nexus-panel/50 backdrop-blur-md"
    >
      <div className="px-4 pb-3 pt-3">
        {/* Active mode indicator */}
        <AnimatePresence>
          {activeModeIds.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mb-2 flex flex-wrap items-center gap-1.5 overflow-hidden"
            >
              <span className="text-[10px] font-medium uppercase tracking-wider text-purple-400">
                Modos activos:
              </span>
              {activeModeIds.map((id) => {
                const Icon = COMMAND_ICONS[id] || Sparkles;
                const color = COMMAND_COLORS[id] || "#A855F7";
                return (
                  <span
                    key={id}
                    className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                    style={{
                      backgroundColor: `${color}20`,
                      color: color,
                    }}
                  >
                    <Icon className="h-2.5 w-2.5" />
                    {id}
                  </span>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Input area */}
        <div className="relative flex items-center gap-3">
          {/* Mode indicator */}
          <div
            className={`flex items-center gap-1 rounded-full px-2 py-1 transition-colors ${
              isCommand
                ? "bg-purple-500/20 text-purple-300"
                : "bg-nexus-border/50 text-gray-500"
            }`}
          >
            <Command className="h-3 w-3" />
            <span className="text-xs">{isCommand ? "CMD" : "Chat"}</span>
          </div>

          {/* Input */}
          <div className="relative flex-1">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => {
                if (input === "/") {
                  setSuggestions(allCommands.slice(0, 6));
                  setShowSuggestions(true);
                }
              }}
              onBlur={() => {
                // Delay to allow click on suggestion
                setTimeout(() => setShowSuggestions(false), 200);
              }}
              placeholder={
                activeModeIds.length > 0
                  ? "Ask with advanced mode context..."
                  : 'Ask anything... (use /vibe-infinity, /forge, /proof)'
              }
              disabled={disabled}
              className={`w-full bg-transparent text-sm text-gray-300 placeholder:text-gray-500 focus:outline-none ${
                isCommand ? "font-mono text-purple-300" : ""
              }`}
            />

            {/* Suggestions dropdown */}
            <AnimatePresence>
              {showSuggestions && suggestions.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: -5 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -5 }}
                  className="absolute bottom-full left-0 right-0 z-50 mb-1 overflow-hidden rounded-lg border border-nexus-border bg-nexus-panel shadow-xl backdrop-blur-xl"
                >
                  {suggestions.map((suggestion, index) => {
                    const color =
                      COMMAND_COLORS[suggestion.label] || "#A855F7";
                    const Icon = COMMAND_ICONS[suggestion.label] || Command;
                    return (
                      <button
                        key={suggestion.cmd}
                        className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors ${
                          index === selectedIndex
                            ? "bg-purple-500/20"
                            : "hover:bg-white/5"
                        }`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          handleSuggestionClick(suggestion.cmd);
                        }}
                      >
                        <div
                          className="flex h-6 w-6 items-center justify-center rounded-md text-xs"
                          style={{
                            backgroundColor: `${color}20`,
                            color: color,
                          }}
                        >
                          <Icon className="h-3 w-3" />
                        </div>
                        <div>
                          <div
                            className="text-sm font-medium"
                            style={{ color }}
                          >
                            {suggestion.cmd}
                          </div>
                          <div className="text-[10px] text-gray-500">
                            {suggestion.description}
                          </div>
                        </div>
                        {index === selectedIndex && (
                          <span className="ml-auto text-[9px] text-gray-500">
                            Tab
                          </span>
                        )}
                      </button>
                    );
                  })}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-1.5">
            <button className="rounded-md p-2 text-gray-400 hover:bg-nexus-border hover:text-gray-300">
              <Paperclip className="h-4 w-4" />
            </button>
            <button className="rounded-md p-2 text-gray-400 hover:bg-nexus-border hover:text-gray-300">
              <Mic className="h-4 w-4" />
            </button>
            <button
              onClick={handleSend}
              disabled={disabled || !input.trim()}
              className={`rounded-md p-2 text-black transition-all ${
                isCommand
                  ? "bg-purple-500 hover:bg-purple-400"
                  : "bg-nexus-accent hover:bg-nexus-accent/80"
              } disabled:cursor-not-allowed disabled:opacity-50`}
            >
              <Send className="h-4 w-4 pointer-events-none" />
            </button>
          </div>
        </div>

        {/* Command suggestions */}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] text-gray-600">Suggest:</span>
          {SUGGESTED_COMMANDS.map((cmd) => {
            const isActive = activeModeIds.includes(cmd.cmd.slice(1));
            return (
              <button
                key={cmd.cmd}
                onClick={() => handleSuggestionClick(cmd.cmd)}
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium transition-all ${
                  isActive
                    ? "text-white shadow-sm"
                    : "text-gray-500 hover:text-gray-300"
                }`}
                style={{
                  backgroundColor: isActive
                    ? `${cmd.color}30`
                    : "rgba(255,255,255,0.04)",
                  borderColor: isActive ? cmd.color : "transparent",
                  borderWidth: isActive ? 1 : 0,
                }}
              >
                {cmd.label}
              </button>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}
