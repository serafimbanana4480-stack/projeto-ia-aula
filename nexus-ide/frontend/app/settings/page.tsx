"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import {
  Settings as SettingsIcon,
  Save,
  CheckCircle,
  AlertCircle,
  Globe2,
} from "lucide-react";
import { getSettings, saveSettings, getProviderCatalog, validateProviderKey, type ProviderSpec } from "../../lib/api";

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
  brave_api_key: string;
}


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
    brave_api_key: "",
  });
  const [providers, setProviders] = useState<ProviderSpec[]>([]);
  const [catalogError, setCatalogError] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { valid: boolean; message: string }>>({});
  const [loaded, setLoaded] = useState(false);
  const [initialProvider, setInitialProvider] = useState("");
  const [saving, setSaving] = useState(false);
  const [braveKeyConfigured, setBraveKeyConfigured] = useState<boolean | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load settings from backend on mount
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const data = await getSettings();
        try { setProviders(await getProviderCatalog()); } catch { setCatalogError(true); }
        // Read only public fields used here. No masked credential is ever
        // copied back into an editable field, including new catalog entries.
        const active = typeof data.llm_provider === "string" ? data.llm_provider : "ollama";
        setSettings((prev) => ({ ...prev, llm_provider: active }));
        setInitialProvider(active);
        setBraveKeyConfigured(typeof data.brave_api_key === "string" && data.brave_api_key.length > 0);
        setLoaded(true);
      } catch {
        setError("Não foi possível carregar as definições do servidor. Verifica a ligação e volta a carregar a página.");
        setBraveKeyConfigured(null);
      } finally {
        setLoading(false);
      }
    };

    loadSettings();
  }, []);

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      // Only send fields that this screen can substantiate; GET includes
      // operator-controlled values and unrelated runtime settings.
      const update: Record<string, string> = {};
      if (settings.llm_provider !== initialProvider) update.llm_provider = settings.llm_provider;
      for (const item of providers) {
        const value = (settings as unknown as Record<string, unknown>)[item.key_setting];
        if (item.key_setting && typeof value === "string" && value.trim()) update[item.key_setting] = value;
      }
      if (settings.brave_api_key.trim()) update.brave_api_key = settings.brave_api_key;
      if (Object.keys(update).length === 0) return;
      await saveSettings(update);
      setInitialProvider(settings.llm_provider);
      setSettings((current) => {
        const next = { ...current } as unknown as Record<string, unknown>;
        for (const item of providers) if (item.key_setting) next[item.key_setting] = "";
        return next as unknown as AppSettings;
      });
      setTestResults({});
      try { setProviders(await getProviderCatalog()); setCatalogError(false); }
      catch { setCatalogError(true); }
      setSaved(true);
      if (settings.brave_api_key.trim()) {
        setBraveKeyConfigured(true);
        setSettings((current) => ({ ...current, brave_api_key: "" }));
      }
      setTimeout(() => setSaved(false), 2000);
    } catch (saveError) {
      if (
        saveError instanceof Error &&
        "responseText" in saveError &&
        typeof saveError.responseText === "string" &&
        saveError.responseText.includes("invalid format")
      ) {
        setError("A chave Brave tem um formato inválido. Revê o valor e tenta novamente.");
        return;
      }
      setError("Não foi possível guardar no servidor. Confirma a ligação, os valores e as permissões de administrador. As alterações continuam nesta página.");
    } finally {
      setSaving(false);
    }
  };


  const testProvider = async (item: ProviderSpec) => {
    setTesting(item.id);
    setTestResults((current) => { const next = { ...current }; delete next[item.id]; return next; });
    try {
      const key = (settings as unknown as Record<string, unknown>)[item.key_setting];
      const typedKey = typeof key === "string" ? key.trim() : "";
      const result = await validateProviderKey(item.id, typedKey || undefined);
      setTestResults((current) => ({ ...current, [item.id]: {
        valid: result.valid,
        message: result.valid ? `Ligação confirmada · ${result.models_count} modelos${typedKey ? " · chave ainda por guardar" : ""}` : (result.error || "Não foi possível validar a ligação."),
      } }));
    } catch {
      setTestResults((current) => ({ ...current, [item.id]: { valid: false, message: "Não foi possível concluir o teste. Verifica a ligação e tenta novamente." } }));
    } finally { setTesting(null); }
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
            <div><h1 className="text-2xl font-bold">Definições e integrações</h1><p className="mt-1 text-sm text-gray-400">Configura as APIs e confirma as tuas ligações ao NEXUS.</p></div>
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
              disabled={!loaded || catalogError || saving || !!testing}
              className="flex items-center gap-2 rounded bg-nexus-accent px-4 py-2 text-sm font-medium text-black hover:bg-nexus-accent/80"
            >
              <Save className="h-4 w-4" />
              {saving ? "A guardar…" : "Guardar alterações"}
            </button>
          </div>
        </div>

        <div className="space-y-6">
          {/* AI Provider Config */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.025 }}
            className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
          >
            <div className="mb-3 flex items-center gap-2">
              <Globe2 className="h-4 w-4 text-nexus-accent" />
              <h3 className="text-sm font-semibold">Pesquisa Web e Imagens</h3>
            </div>
            <div>
              <label htmlFor="brave-api-key" className="mb-1 block text-xs text-gray-400">
                Brave Search API Key
              </label>
              <input
                disabled={!loaded || saving}
                id="brave-api-key"
                type="password"
                autoComplete="new-password"
                spellCheck={false}
                value={settings.brave_api_key}
                onChange={(event) => setSettings({ ...settings, brave_api_key: event.target.value })}
                placeholder={braveKeyConfigured ? "Chave guardada; deixa vazio para manter" : "Introduz a chave Brave"}
                aria-describedby="brave-api-key-help"
                className="w-full rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-nexus-accent"
              />
              <p id="brave-api-key-help" className="mt-1 text-xs text-gray-500">
                {braveKeyConfigured === true
                  ? "A chave existente fica oculta. Um valor novo substitui-a; deixa o campo vazio para a manter."
                  : braveKeyConfigured === false
                    ? "A chave é guardada cifrada no backend. O campo vazio não apaga uma chave definida no ambiente."
                    : "Não foi possível confirmar a configuração atual. O campo vazio preserva qualquer chave existente."}
              </p>
            </div>
          </motion.div>

          <section className="rounded-2xl border border-nexus-border bg-nexus-panel/70 p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div><h2 className="text-lg font-semibold">Ligações de IA</h2><p className="mt-1 text-sm text-gray-400">Escolhe o fornecedor e testa as ligações diretamente. Uma chave configurada ainda precisa de ser validada.</p></div>
              <a href="/models" className="text-sm text-nexus-accent hover:underline">Ver modelos →</a>
            </div>
            {catalogError && <p role="alert" className="mt-4 text-sm text-amber-300">Não foi possível carregar o estado dos fornecedores. Recarrega a página para tentar novamente.</p>}
            <label htmlFor="provider-select" className="mb-2 mt-5 block text-xs text-gray-400">Fornecedor predefinido</label>
            <select id="provider-select" disabled={!loaded || saving} value={settings.llm_provider} onChange={(event) => setSettings({ ...settings, llm_provider: event.target.value })} className="w-full max-w-md rounded-xl border border-nexus-border bg-nexus-bg px-3 py-2.5 text-sm">
              {!providers.some((item) => item.id === settings.llm_provider) && <option value={settings.llm_provider}>{settings.llm_provider}</option>}
              {providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
            <div className="mt-6 grid gap-4 lg:grid-cols-2">
              {providers.map((item) => {
                const value = (settings as unknown as Record<string, unknown>)[item.key_setting];
                const key = typeof value === "string" ? value : "";
                const result = testResults[item.id];
                return <article key={item.id} className="rounded-xl border border-nexus-border bg-black/10 p-4">
                  <div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold">{item.label}</h3><p className="mt-1 text-xs text-gray-500">{item.requires_key ? "Fornecedor remoto" : "Ligação local"}</p></div><span className={`rounded-full px-2.5 py-1 text-xs ${item.api_key_set ? "bg-green-500/10 text-green-400" : "bg-white/5 text-gray-400"}`}>{item.api_key_set ? "Chave configurada" : item.requires_key ? "Sem chave" : "Chave opcional"}</span></div>
                  {item.key_setting && <div className="mt-4"><label htmlFor={`key-${item.id}`} className="mb-1 block text-xs text-gray-400">Chave API{!item.requires_key && " (opcional)"}</label><input id={`key-${item.id}`} type="password" autoComplete="new-password" spellCheck={false} disabled={testing === item.id || saving} value={key} onChange={(event) => { setSettings((current) => ({ ...current, [item.key_setting]: event.target.value })); setTestResults((current) => { const next = { ...current }; delete next[item.id]; return next; }); }} placeholder={item.api_key_set ? "Deixa vazio para manter a chave" : "Introduz uma chave"} className="w-full rounded-lg border border-nexus-border bg-nexus-bg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-nexus-accent" /></div>}
                  <div className="mt-4 flex items-center gap-4"><button type="button" disabled={!!testing || saving || (item.requires_key && !item.api_key_set && !key.trim())} onClick={() => void testProvider(item)} className="rounded-lg border border-nexus-border px-3 py-2 text-xs hover:bg-white/5 disabled:opacity-40">{testing === item.id ? "A testar…" : "Testar ligação"}</button>{item.docs && <a href={item.docs} target="_blank" rel="noreferrer" className="text-xs text-gray-400 hover:underline">Documentação ↗</a>}</div>
                  {result && <p role="status" className={`mt-3 break-words text-xs ${result.valid ? "text-green-400" : "text-red-400"}`}>{result.message}</p>}
                </article>;
              })}
            </div>
            <p className="mt-5 text-xs leading-5 text-gray-500">As chaves existentes ficam ocultas. Deixa o campo vazio para manter a chave atual; um valor novo substitui-a ao guardar. Guardar requer permissões de administrador.</p>
          </section>
        </div>
      </motion.div>
    </AppShell>
  );
}
