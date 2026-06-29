"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import {
  Wrench,
  ToggleLeft,
  ToggleRight,
  RefreshCw,
  Loader2,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { getTools, toggleTool } from "../../lib/api";
import { log } from "../../lib/log";

interface ToolInfo {
  name: string;
  description: string;
  enabled: boolean;
  schema: Record<string, unknown>;
}

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toggling, setToggling] = useState<string | null>(null);

  const fetchTools = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getTools();
      setTools(data);
    } catch (err) {
      setError("Failed to load tools. Make sure backend is running.");
      log.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTools();
  }, []);

  const handleToggle = async (toolName: string, currentlyEnabled: boolean) => {
    setToggling(toolName);
    try {
      await toggleTool(toolName, !currentlyEnabled);
      setTools((prev) =>
        prev.map((t) =>
          t.name === toolName ? { ...t, enabled: !currentlyEnabled } : t,
        ),
      );
    } catch (err) {
      log.error("Failed to toggle tool:", err);
    } finally {
      setToggling(null);
    }
  };

  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        <main className="flex-1 overflow-auto p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="max-w-4xl mx-auto"
          >
            <div className="mb-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Wrench className="h-6 w-6 text-nexus-accent" />
                <h1 className="text-2xl font-bold">Ferramentas</h1>
              </div>
              <button
                onClick={fetchTools}
                className="flex items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card px-3 py-2 text-xs text-nexus-muted hover:text-nexus-text transition-colors"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Atualizar
              </button>
            </div>

            {loading && (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-nexus-accent" />
              </div>
            )}

            {error && (
              <div className="flex items-center gap-2 text-sm text-red-400">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}

            {!loading && !error && (
              <div className="space-y-3">
                <div className="text-sm text-nexus-muted">
                  {tools.length} ferramentas disponíveis
                </div>
                {tools.map((tool, index) => (
                  <motion.div
                    key={tool.name}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.03 }}
                    className="rounded-lg border border-nexus-border bg-nexus-panel/50 p-4"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-mono text-sm font-medium">
                            {tool.name}
                          </span>
                          {tool.enabled ? (
                            <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />
                          ) : (
                            <AlertCircle className="h-3.5 w-3.5 text-yellow-500" />
                          )}
                        </div>
                        <p className="text-xs text-nexus-muted">
                          {tool.description}
                        </p>
                      </div>
                      <button
                        onClick={() => handleToggle(tool.name, tool.enabled)}
                        disabled={toggling === tool.name}
                        className="ml-4 flex items-center gap-1.5 rounded-lg border border-nexus-border px-3 py-1.5 text-xs transition-colors hover:bg-nexus-card"
                      >
                        {toggling === tool.name ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : tool.enabled ? (
                          <ToggleRight className="h-4 w-4 text-green-400" />
                        ) : (
                          <ToggleLeft className="h-4 w-4 text-nexus-muted" />
                        )}
                        {tool.enabled ? "Ativo" : "Inativo"}
                      </button>
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </motion.div>
        </main>
      </div>

      <BottomHUD />
    </div>
  );
}
