"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import {
  Settings as SettingsIcon,
  Save,
  Key,
  Database,
  Server,
  CheckCircle,
  AlertCircle,
} from "lucide-react";
import { apiUrl } from "../../lib/api";

interface AppSettings {
  ollama_host: string;
  backend_host: string;
  default_mode: string;
  default_model: string;
  enable_telemetry: boolean;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>({
    ollama_host: "http://localhost:11434",
    backend_host: "http://localhost:8000",
    default_mode: "auto",
    default_model: "coder",
    enable_telemetry: true,
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load settings from backend on mount
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const response = await fetch(apiUrl("/api/settings"));
        if (response.ok) {
          const data = await response.json();
          setSettings((prev) => ({
            ...prev,
            ...data,
          }));
        } else {
          // Fallback to localStorage if backend not available
          const stored = localStorage.getItem("nexus_settings");
          if (stored) {
            try {
              setSettings((prev) => ({
                ...prev,
                ...JSON.parse(stored),
              }));
            } catch {
              // Ignore parse errors
            }
          }
        }
      } catch {
        // Backend not available, try localStorage
        const stored = localStorage.getItem("nexus_settings");
        if (stored) {
          try {
            setSettings((prev) => ({
              ...prev,
              ...JSON.parse(stored),
            }));
          } catch {
            // Ignore
          }
        }
      } finally {
        setLoading(false);
      }
    };

    loadSettings();
  }, []);

  const handleSave = async () => {
    setError(null);
    try {
      // Try backend first
      const response = await fetch(apiUrl("/api/settings"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });

      if (response.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
        return;
      }

      // Fallback to localStorage
      localStorage.setItem("nexus_settings", JSON.stringify(settings));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // Fallback to localStorage
      localStorage.setItem("nexus_settings", JSON.stringify(settings));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen flex-col bg-nexus-bg">
        <TopBar />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-auto p-6">
            <div className="flex h-full items-center justify-center text-gray-500">
              A carregar definições...
            </div>
          </main>
        </div>
        <BottomHUD />
      </div>
    );
  }

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
              <div className="flex items-center gap-3">
                {saved && (
                  <motion.div
                    initial={{ opacity: 0, x: 10 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="flex items-center gap-1 text-sm text-green-400"
                  >
                    <CheckCircle className="h-4 w-4" />
                    Guardado
                  </motion.div>
                )}
                {error && (
                  <div className="flex items-center gap-1 text-sm text-red-400">
                    <AlertCircle className="h-4 w-4" />
                    {error}
                  </div>
                )}
                <button
                  onClick={handleSave}
                  className="flex items-center gap-2 rounded bg-nexus-accent px-4 py-2 text-sm font-medium text-black hover:bg-nexus-accent/80"
                >
                  <Save className="h-4 w-4" />
                  Save
                </button>
              </div>
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
                  <h3 className="text-sm font-semibold">
                    Server Configuration
                  </h3>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="mb-1 block text-xs text-gray-400">
                      Ollama Host
                    </label>
                    <input
                      type="text"
                      value={settings.ollama_host}
                      onChange={(e) =>
                        setSettings({
                          ...settings,
                          ollama_host: e.target.value,
                        })
                      }
                      className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-400">
                      Backend Host
                    </label>
                    <input
                      type="text"
                      value={settings.backend_host}
                      onChange={(e) =>
                        setSettings({
                          ...settings,
                          backend_host: e.target.value,
                        })
                      }
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
                    <label className="mb-1 block text-xs text-gray-400">
                      Default Mode
                    </label>
                    <select
                      value={settings.default_mode}
                      onChange={(e) =>
                        setSettings({
                          ...settings,
                          default_mode: e.target.value,
                        })
                      }
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
                    <label className="mb-1 block text-xs text-gray-400">
                      Default Model
                    </label>
                    <select
                      value={settings.default_model}
                      onChange={(e) =>
                        setSettings({
                          ...settings,
                          default_model: e.target.value,
                        })
                      }
                      className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                    >
                      <option value="micro">Qwen 0.5B (MICRO)</option>
                      <option value="fast">Qwen 3B (FAST)</option>
                      <option value="coder">Qwen Coder 7B (CODER)</option>
                      <option value="reasoning">
                        DeepSeek R1 14B (REASONING)
                      </option>
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
                    <div className="text-xs text-gray-500">
                      Send anonymous usage data
                    </div>
                  </div>
                  <button
                    onClick={() =>
                      setSettings({
                        ...settings,
                        enable_telemetry: !settings.enable_telemetry,
                      })
                    }
                    className={`h-6 w-11 rounded-full p-1 transition-colors ${
                      settings.enable_telemetry
                        ? "bg-nexus-accent"
                        : "bg-nexus-border"
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
          </motion.div>
        </main>
      </div>

      <BottomHUD />
    </div>
  );
}
