"use client";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
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
  Sparkles,
  X,
  ChevronDown,
  Zap,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { useAdvancedModeStore, AdvancedMode, AdvancedModeGroup } from "../../stores/advancedModeStore";

const MODE_ICONS: Record<string, React.ElementType> = {
  infinity: Infinity,
  shield: Shield,
  hammer: Hammer,
  layers: Layers,
  "git-branch": GitBranch,
  "check-circle": CheckCircle,
  flask: FlaskConical,
  search: Search,
  brain: Brain,
  eye: Eye,
  sparkles: Sparkles,
};

const MODE_EMOJIS: Record<string, string> = {
  "vibe-infinity": "\u{1F52E}",
  "advisor-infinity": "\u{1F6E1}\uFE0F",
  forge: "\u2692\uFE0F",
  "swarm-foundry": "\u{1F9EC}",
  multiverse: "\u{1F30C}",
  proof: "\u2705",
  "reality-lab": "\u{1F9EA}",
  archaeologist: "\u{1F50D}",
  evolve: "\u{1F9E0}",
  sentinel: "\u{1F441}\uFE0F",
  autonomous: "\u26A1",
};

function getModeIcon(mode: AdvancedMode) {
  return MODE_ICONS[mode.icon] || Sparkles;
}

function getRuntimeLabel(mode: AdvancedMode) {
  if (mode.runtime_status === "integrated") return "CONNECTED";
  if (mode.runtime_status === "composed") return "POLICY";
  return "CATALOG";
}

function GroupSection({
  group,
  modes,
  onToggle,
  onUseCommand,
}: {
  group: AdvancedModeGroup;
  modes: AdvancedMode[];
  onToggle: (modeId: string, shouldBeActive: boolean) => void;
  onUseCommand: (command: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);

  if (modes.length === 0) return null;

  return (
    <div className="mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400 hover:text-gray-200"
      >
        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: group.color }} />
        {group.label}
        <span className="text-[10px] text-gray-500">({modes.length})</span>
        <ChevronDown className="ml-auto h-3 w-3 transition-transform" />
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            {modes.map((mode) => (
              <ModeCard
                key={mode.mode_id}
                mode={mode}
                command={`/${mode.mode_id}`}
                onToggle={onToggle}
                onUseCommand={onUseCommand}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ModeCard({
  mode,
  onToggle,
  command,
  onUseCommand,
}: {
  mode: AdvancedMode;
  onToggle: (modeId: string, shouldBeActive: boolean) => void;
  command: string;
  onUseCommand: (command: string) => void;
}) {
  const [toggling, setToggling] = useState(false);
  const emoji = MODE_EMOJIS[mode.mode_id] || "\u25C6";

  const handleToggle = async () => {
    setToggling(true);
    await onToggle(mode.mode_id, !mode.active);
    setToggling(false);
  };

  const activeSessions = mode.active_session_count ?? mode.session_count ?? 0;
  const totalSessions = mode.total_session_count ?? activeSessions;
  const runtimeLabel = getRuntimeLabel(mode);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      className="group relative mx-2 mb-1.5 cursor-pointer rounded-lg border px-3 py-2.5 transition-all"
      style={mode.active ? { borderLeftColor: mode.color } : {}}
      onClick={handleToggle}
    >
      <div className="flex items-start gap-2.5">
        <div
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[11px]"
          style={{
            backgroundColor: mode.active ? `${mode.color}20` : "rgba(255,255,255,0.05)",
            color: mode.active ? mode.color : "#666",
          }}
        >
          {emoji}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium">
              /{mode.mode_id}
            </span>
            {mode.active && (
              <span className="rounded-full bg-green-500/20 px-1.5 py-0.5 text-[9px] font-medium text-green-400">
                ARMED
              </span>
            )}
            <span
              className={`rounded-full px-1.5 py-0.5 text-[9px] font-medium ${
                mode.runtime_status === "integrated"
                  ? "bg-cyan-500/15 text-cyan-300"
                  : mode.runtime_status === "composed"
                    ? "bg-white/5 text-gray-400"
                    : "bg-yellow-500/10 text-yellow-300"
              }`}
              title={mode.runtime_summary || "Runtime contract unavailable"}
            >
              {runtimeLabel}
            </span>
          </div>
          <p className="mt-0.5 line-clamp-2 text-[11px] leading-tight text-gray-500">
            {mode.description}
          </p>
          {activeSessions > 0 && (
            <div className="mt-1 flex items-center gap-2 text-[9px] text-gray-600">
              <span>&bull; {activeSessions} active session{activeSessions !== 1 ? "s" : ""}</span>
              {totalSessions > activeSessions && <span>· {totalSessions} total</span>}
            </div>
          )}
          <div className="mt-1.5 flex items-center gap-2">
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onUseCommand(command);
              }}
              className="rounded border border-purple-500/20 px-1.5 py-0.5 font-mono text-[9px] text-purple-300 hover:bg-purple-500/10"
              title="Inserir este comando no chat"
            >
              Usar {command}
            </button>
            <span className="truncate text-[9px] text-gray-600" title={mode.runtime_summary || undefined}>
              {mode.runtime_summary || "Contrato de execução não disponível"}
            </span>
          </div>
        </div>
        <div className="shrink-0 self-center">
          {toggling ? (
            <Loader2 className="h-4 w-4 animate-spin text-gray-500" />
          ) : (
            <div
              className="h-3.5 w-3.5 rounded-full border-2 transition-all"
            >
              {mode.active && (
                <div className="flex h-full items-center justify-center">
                  <div className="h-1.5 w-1.5 rounded-full bg-white" />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

export default function AdvancedModePanel() {
  const {
    modes,
    groups,
    activeModeIds,
    executionProfile,
    loading,
    error,
    loadModes,
    activateMode,
    deactivateMode,
  } = useAdvancedModeStore();

  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    loadModes();
  }, [loadModes]);

  useEffect(() => {
    if (!isOpen) return;
    const interval = setInterval(() => loadModes(), 30000);
    return () => clearInterval(interval);
  }, [isOpen, loadModes]);

  const handleToggle = async (modeId: string, shouldBeActive: boolean) => {
    if (shouldBeActive) {
      await activateMode(modeId);
    } else {
      await deactivateMode(modeId);
    }
    await loadModes();
  };

  const handleUseCommand = (command: string) => {
    window.dispatchEvent(new CustomEvent("nexus:insert-command", { detail: { command: `${command} ` } }));
    setIsOpen(false);
  };

  const modesByGroup = Object.entries(groups)
    .sort(([, a], [, b]) => (a.order || 99) - (b.order || 99))
    .map(([groupId, group]) => ({
      groupId,
      group,
      modes: Object.values(modes).filter((m) => m.group === groupId && m.available),
    }))
    .filter(({ modes: ms }) => ms.length > 0);

  const ungroupedModes = Object.values(modes).filter(
    (m) => !groups[m.group] && m.available
  );

  const activeCount = activeModeIds.length;

  return (
    <>
      <motion.button
        data-advanced-mode-toggle
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setIsOpen(!isOpen)}
        className="relative flex items-center gap-1.5 rounded-full border border-nexus-border bg-nexus-panel/80 px-3 py-1.5 text-xs font-medium text-gray-300 backdrop-blur-md hover:bg-nexus-panel hover:text-white"
        title="Advanced Modes (Infinity Suite)"
      >
        <Sparkles className="h-3.5 w-3.5 text-purple-400" />
        <span>Infinity</span>
        {activeCount > 0 && (
          <span className="ml-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-purple-500 px-1 text-[9px] font-bold text-white">
            {activeCount}
          </span>
        )}
      </motion.button>

      <AnimatePresence>
        {isOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
              onClick={() => setIsOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, x: 320 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 320 }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="fixed right-0 top-0 z-50 h-full w-[380px] overflow-y-auto border-l border-nexus-border bg-nexus-panel/95 shadow-2xl backdrop-blur-xl"
            >
              <div className="sticky top-0 z-10 border-b border-nexus-border bg-nexus-panel/90 px-4 py-3 backdrop-blur-md">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-5 w-5 text-purple-400" />
                    <div>
                      <h2 className="text-sm font-semibold text-white">Infinity Suite</h2>
                         <p className="text-[10px] text-gray-500">
                         {activeCount} of {Object.keys(modes).length} armed
                       </p>
                    </div>
                  </div>
                  <button
                    onClick={() => setIsOpen(false)}
                    className="rounded-md p-1.5 text-gray-400 hover:bg-white/10 hover:text-white"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <div className="mt-2 flex gap-1">
                  <button
                    onClick={async () => {
                      await activateMode("autonomous");
                      await loadModes();
                    }}
                    className="flex items-center gap-1 rounded-md bg-purple-500/20 px-2 py-1 text-[10px] font-medium text-purple-300 hover:bg-purple-500/30"
                     title="Arma o perfil composto: planeamento, execução, verificação e políticas Infinity"
                  >
                    <Zap className="h-3 w-3" />
                     Full Orchestration
                  </button>
                  <button
                    onClick={async () => {
                      for (const id of activeModeIds) {
                        await deactivateMode(id);
                      }
                      await loadModes();
                    }}
                    className="flex items-center gap-1 rounded-md bg-red-500/10 px-2 py-1 text-[10px] font-medium text-red-300 hover:bg-red-500/20"
                    disabled={activeCount === 0}
                  >
                    <X className="h-3 w-3" />
                    Deactivate All
                  </button>
                </div>
              </div>

              <div className="p-2">
                {error && (
                  <div className="mx-3 mb-3 flex items-start gap-2 rounded-md border border-yellow-500/20 bg-yellow-500/10 px-3 py-2">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-yellow-400" />
                    <p className="text-[11px] text-yellow-300">{error}</p>
                  </div>
                )}

                {activeCount > 0 && (
                  <div className="mx-3 mb-3 rounded-md border border-purple-500/20 bg-purple-500/5 px-3 py-2">
                    <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-purple-300">
                      <Zap className="h-3 w-3" />
                      Execution profile armed
                    </div>
                    <p className="mt-1 text-[10px] leading-relaxed text-gray-500">
                      Os modos armados entram nos próximos pedidos como um perfil composto.
                      Um badge não significa que um agente esteja a correr neste instante.
                    </p>
                    {executionProfile?.primary_mode && (
                      <div className="mt-2 rounded border border-purple-500/15 bg-black/10 px-2 py-1.5 text-[10px] text-gray-400">
                        <div>
                          Estratégia principal: <span className="font-mono text-purple-300">/{executionProfile.primary_mode}</span>
                        </div>
                        <div className="mt-0.5">
                          Aplicada: {executionProfile.applied_mode_ids.map((id) => `/${id}`).join(", ")}
                        </div>
                        {executionProfile.policy_mode_ids.length > 0 && (
                          <div className="mt-0.5 text-gray-500">
                            Políticas: {executionProfile.policy_mode_ids.map((id) => `/${id}`).join(", ")}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {loading && Object.keys(modes).length === 0 ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-6 w-6 animate-spin text-purple-400" />
                  </div>
                ) : (
                  <>
                    {modesByGroup.map(({ groupId, group, modes: groupModes }) => (
                      <GroupSection
                        key={groupId}
                        group={group}
                        modes={groupModes}
                        onUseCommand={handleUseCommand}
                        onToggle={handleToggle}
                      />
                    ))}
                    {ungroupedModes.length > 0 && (
                      <GroupSection
                        group={{
                          label: "Other",
                          description: "",
                          icon: "sparkles",
                          color: "#888",
                          order: 99,
                        }}
                        modes={ungroupedModes}
                        onUseCommand={handleUseCommand}
                        onToggle={handleToggle}
                      />
                    )}
                  </>
                )}
              </div>

              <div className="border-t border-nexus-border px-4 py-2">
                <p className="text-[9px] text-gray-600">
                  Use <span className="font-mono text-gray-500">/command</span> in chat to toggle
                  modes on-the-fly. See docs for details.
                </p>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
