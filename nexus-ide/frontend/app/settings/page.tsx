"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import {
  Settings as SettingsIcon,
  Save,
  Key,
  Database,
  Server,
  CheckCircle,
  AlertCircle,
  Brain,
} from "lucide-react";
import { getSettings, saveSettings } from "../../lib/api";

interface AppSettings {
  local_llm_device: string;
  backend_host: string;
  default_mode: string;
  default_model: string;
  enable_telemetry: boolean;
  llm_provider: string;
  openai_api_key: string;
  deepseek_api_key: string;
  kimi_api_key: string;
  groq_api_key: string;
  anthropic_api_key: string;
  gemini_api_key: string;
  openrouter_api_key: string;
  kilo_api_key: string;
}

const PROVIDER_OPTIONS = [
  { value: "ollama", label: "🖥️ Ollama (Local)" },
  { value: "openai", label: "🤖 OpenAI" },
  { value: "deepseek", label: "🔍 DeepSeek" },
  { value: "kimi", label: "🌙 Kimi (Moonshot)" },
  { value: "groq", label: "⚡ Groq" },
  { value: "anthropic", label: "🧠 Claude (Anthropic)" },
  { value: "gemini", label: "💎 Gemini (Google)" },
  { value: "openrouter", label: "🔀 OpenRouter" },
  { value: "kilo", label: "🚀 Kilo AI Gateway" },
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>({
    local_llm_device: "auto",
    backend_host: "http://localhost:8000",
    default_mode: "auto",
    default_model: "coder",
    enable_telemetry: true,
    llm_provider: "ollama",
    openai_api_key: "",
    deepseek_api_key: "",
    kimi_api_key: "",
    groq_api_key: "",
    anthropic_api_key: "",
    gemini_api_key: "",
    openrouter_api_key: "",
    kilo_api_key: "",
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load settings from backend on mount
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const data = await getSettings();
        // GET /api/settings deliberately masks secrets.  Never put those
        // masked values in editable password fields: a subsequent Save would
        // otherwise replace the real key with ``****``.
        const {
          openai_api_key: _openaiApiKey,
          deepseek_api_key: _deepseekApiKey,
          kimi_api_key: _kimiApiKey,
          groq_api_key: _groqApiKey,
          anthropic_api_key: _anthropicApiKey,
          gemini_api_key: _geminiApiKey,
          openrouter_api_key: _openrouterApiKey,
          kilo_api_key: _kiloApiKey,
          ...publicSettings
        } = data as Partial<AppSettings>;
        const telemetryValue = (publicSettings as Record<string, unknown>).enable_telemetry;
        setSettings((prev) => ({
          ...prev,
          ...publicSettings,
          enable_telemetry:
            typeof telemetryValue === "string"
              ? telemetryValue.toLowerCase() === "true"
              : typeof telemetryValue === "boolean"
                ? telemetryValue
                : prev.enable_telemetry,
          openai_api_key: "",
          deepseek_api_key: "",
          kimi_api_key: "",
          groq_api_key: "",
          anthropic_api_key: "",
          gemini_api_key: "",
          openrouter_api_key: "",
          kilo_api_key: "",
        }));
      } catch {
        if (process.env.NODE_ENV !== "development") {
          setSettings((prev) => ({
            ...prev,
            llm_provider: "ollama",
            openai_api_key: "",
            deepseek_api_key: "",
            kimi_api_key: "",
            groq_api_key: "",
            anthropic_api_key: "",
            gemini_api_key: "",
            openrouter_api_key: "",
            kilo_api_key: "",
          }));
        } else {
          const stored = localStorage.getItem("nexus_settings");
          if (stored) {
            try {
              const parsed = JSON.parse(stored) as Partial<AppSettings>;
              const { llm_provider, default_mode, default_model, local_llm_device, backend_host, enable_telemetry } = parsed;
              setSettings((prev) => ({
                ...prev,
                ...(llm_provider ? { llm_provider } : {}),
                ...(default_mode ? { default_mode } : {}),
                ...(default_model ? { default_model } : {}),
                ...(local_llm_device ? { local_llm_device } : {}),
                ...(backend_host ? { backend_host } : {}),
                ...(typeof enable_telemetry === 'boolean' ? { enable_telemetry } : {}),
                openai_api_key: "",
                deepseek_api_key: "",
                kimi_api_key: "",
                groq_api_key: "",
                anthropic_api_key: "",
                gemini_api_key: "",
                openrouter_api_key: "",
                kilo_api_key: "",
              }));
            } catch { /* ignore */ }
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
      await saveSettings(settings as unknown as Record<string, unknown>);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      const safeSettings = {
        llm_provider: settings.llm_provider,
        default_mode: settings.default_mode,
        default_model: settings.default_model,
        local_llm_device: settings.local_llm_device,
        backend_host: settings.backend_host,
        enable_telemetry: settings.enable_telemetry,
      };
      localStorage.setItem("nexus_settings", JSON.stringify(safeSettings));
      setError("Não foi possível guardar no backend. As definições não sensíveis foram guardadas apenas neste navegador.");
    }
  };


  if (loading) {
    return (
      <AppShell title="Definições">
        <div className="flex h-full items-center justify-center text-gray-500">
          A carregar definições...
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell title="Definições">
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
              Guardar
            </button>
          </div>
        </div>

        <div className="space-y-6">
          {/* Server Configuration */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
          >
            <div className="mb-4 flex items-center gap-2">
              <Server className="h-4 w-4 text-nexus-accent" />
              <h3 className="text-sm font-semibold">Server Configuration</h3>
            </div>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Local LLM Device</label>
                <input
                  type="text"
                  value={settings.local_llm_device}
                  onChange={(e) =>
                    setSettings({ ...settings, local_llm_device: e.target.value })
                  }
                  className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Backend Host</label>
                <input
                  type="text"
                  value={settings.backend_host}
                  onChange={(e) =>
                    setSettings({ ...settings, backend_host: e.target.value })
                  }
                  className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                />
              </div>
            </div>
          </motion.div>

          {/* AI Provider Config */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 }}
            className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
          >
            <div className="mb-4 flex items-center gap-2">
              <Brain className="h-4 w-4 text-nexus-accent" />
              <h3 className="text-sm font-semibold">AI Provider</h3>
            </div>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Provider</label>
                <select
                  value={settings.llm_provider}
                  onChange={(e) =>
                    setSettings({ ...settings, llm_provider: e.target.value })
                  }
                  className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                >
                  {PROVIDER_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500">
                  O provider Ollama usa modelos locais. Os restantes precisam da respectiva API key configurada abaixo.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {([
                  { key: "openai", label: "OpenAI API Key", placeholder: "sk-..." },
                  { key: "deepseek", label: "DeepSeek API Key", placeholder: "sk-..." },
                  { key: "kimi", label: "Kimi (Moonshot) API Key", placeholder: "sk-..." },
                  { key: "groq", label: "Groq API Key", placeholder: "gsk_..." },
                  { key: "anthropic", label: "Claude (Anthropic) API Key", placeholder: "sk-ant-..." },
                  { key: "gemini", label: "Gemini (Google) API Key", placeholder: "AIza..." },
                  { key: "openrouter", label: "OpenRouter API Key", placeholder: "sk-or-v1-..." },
                  { key: "kilo", label: "Kilo AI Gateway API Key", placeholder: "eyJ..." },
                ] as const).map(({ key, label, placeholder }) => (
                  <div key={key}>
                    <label className="mb-1 block text-xs text-gray-400">{label}</label>
                    <input
                      type="password"
                      value={(settings as any)[`${key}_api_key`] ?? ""}
                      onChange={(e) =>
                        setSettings({
                          ...settings,
                          [`${key}_api_key`]: e.target.value,
                        } as AppSettings)
                      }
                      placeholder={placeholder}
                      className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                    />
                  </div>
                ))}
              </div>
            </div>
          </motion.div>

          {/* AI Configuration */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
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
                  onChange={(e) =>
                    setSettings({ ...settings, default_mode: e.target.value })
                  }
                  className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                >
                  <option value="auto">Auto</option>
                  <option value="coder">Coder</option>
                  <option value="analyst">Analyst</option>
                  <option value="plan">Plano</option>
                  <option value="debug">Debug</option>
                  <option value="ask">Ask</option>
                  <option value="swarm">Swarm</option>
                  <option value="fast">Fast</option>
                  <option value="deep">Deep</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Default Model</label>
                <select
                  value={settings.default_model}
                  onChange={(e) =>
                    setSettings({ ...settings, default_model: e.target.value })
                  }
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

          {/* Data & Privacy */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
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
                onClick={() =>
                  setSettings({ ...settings, enable_telemetry: !settings.enable_telemetry })
                }
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
      </motion.div>
    </AppShell>
  );
}
