"use client";
import { useState } from "react";
import { motion } from "framer-motion";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import { Settings as SettingsIcon, Save, Key, Database, Server } from "lucide-react";

export default function SettingsPage() {
  const [settings, setSettings] = useState({
    ollama_host: "http://localhost:11434",
    backend_host: "http://localhost:8000",
    default_mode: "auto",
    default_model: "coder",
    enable_telemetry: true,
  });

  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    try {
      // TODO: Implement real backend API for settings persistence
      // For now, save to localStorage
      localStorage.setItem("nexus_settings", JSON.stringify(settings));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (error) {
      console.error("Failed to save settings:", error);
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
          >
            <div className="mb-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <SettingsIcon className="h-6 w-6 text-nexus-accent" />
                <h1 className="text-2xl font-bold">Settings</h1>
              </div>
              <button
                onClick={handleSave}
                className="flex items-center gap-2 rounded bg-nexus-accent px-4 py-2 text-sm font-medium text-black hover:bg-nexus-accent/80"
              >
                <Save className="h-4 w-4" />
                Save
              </button>
            </div>

            <div className="space-y-6">
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
                className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
              >
                <div className="mb-4 flex items-center gap-2">
                  <Server className="h-4 w-4 text-nexus-accent" />
                  <h3 className="text-sm font-semibold">Server Configuration</h3>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="mb-1 block text-xs text-gray-400">Ollama Host</label>
                    <input
                      type="text"
                      value={settings.ollama_host}
                      onChange={(e) => setSettings({ ...settings, ollama_host: e.target.value })}
                      className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-400">Backend Host</label>
                    <input
                      type="text"
                      value={settings.backend_host}
                      onChange={(e) => setSettings({ ...settings, backend_host: e.target.value })}
                      className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                    />
                  </div>
                </div>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
              >
                <div className="mb-4 flex items-center gap-2">
                  <Key className="h-4 w-4 text-nexus-accent" />
                  <h3 className="text-sm font-semibold">AI Configuration</h3>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="mb-1 block text-xs text-gray-400">Default Mode</label>
                    <select
                      value={settings.default_mode}
                      onChange={(e) => setSettings({ ...settings, default_mode: e.target.value })}
                      className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                    >
                      <option value="auto">Auto</option>
                      <option value="coder">Coder</option>
                      <option value="analyst">Analyst</option>
                      <option value="planner">Planner</option>
                      <option value="fast">Fast</option>
                      <option value="deep">Deep</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-400">Default Model</label>
                    <select
                      value={settings.default_model}
                      onChange={(e) => setSettings({ ...settings, default_model: e.target.value })}
                      className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                    >
                      <option value="micro">Qwen 0.5B (MICRO)</option>
                      <option value="fast">Qwen 3B (FAST)</option>
                      <option value="coder">Qwen Coder 7B (CODER)</option>
                      <option value="reasoning">DeepSeek R1 14B (REASONING)</option>
                      <option value="deep">Qwen 32B (DEEP)</option>
                    </select>
                  </div>
                </div>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3 }}
                className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
              >
                <div className="mb-4 flex items-center gap-2">
                  <Database className="h-4 w-4 text-nexus-accent" />
                  <h3 className="text-sm font-semibold">Data & Privacy</h3>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm">Enable Telemetry</div>
                    <div className="text-xs text-gray-500">Send anonymous usage data</div>
                  </div>
                  <button
                    onClick={() => setSettings({ ...settings, enable_telemetry: !settings.enable_telemetry })}
                    className={`h-6 w-11 rounded-full p-1 transition-colors ${
                      settings.enable_telemetry ? "bg-nexus-accent" : "bg-nexus-border"
                    }`}
                  >
                    <motion.div
                      className="h-4 w-4 rounded-full bg-white"
                      animate={{ x: settings.enable_telemetry ? 20 : 0 }}
                    />
                  </button>
                </div>
              </motion.div>
            </div>

            {saved && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="rounded bg-green-500/20 border border-green-500/30 px-4 py-2 text-center text-sm text-green-400"
              >
                Settings saved successfully
              </motion.div>
            )}
          </motion.div>
        </main>
      </div>
      
      <BottomHUD />
    </div>
  );
}
