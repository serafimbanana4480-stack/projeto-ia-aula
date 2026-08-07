"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Plug,
  Plus,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Trash2,
  Copy,
  Check,
  X,
  ExternalLink,
  Loader2,
} from "lucide-react";
import {
  getMCPTemplates,
  getMCPTemplate,
  getMCPConnectors,
  createMCPConnector,
  deleteMCPConnector,
  testMCPConnector,
  exportMCPConnector,
  exportAllMCPConnectors,
  type MCPTemplateSummary,
  type MCPTemplateDetail,
  type MCPConnector,
  type MCPConnectorsSummary,
} from "../../lib/api";

const CATEGORY_LABELS: Record<string, string> = {
  filesystem: "Ficheiros",
  dev: "Desenvolvimento",
  data: "Dados",
  web: "Web",
  collab: "Colaboração",
  custom: "Personalizado",
};

function StatusBadge({ status }: { status: MCPConnector["last_test_status"] }) {
  const map: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    ok: { label: "Ligado", cls: "text-emerald-400 bg-emerald-500/10", icon: <CheckCircle2 className="h-3 w-3" /> },
    warning: { label: "Aviso", cls: "text-yellow-400 bg-yellow-500/10", icon: <AlertCircle className="h-3 w-3" /> },
    error: { label: "Erro", cls: "text-red-400 bg-red-500/10", icon: <XCircle className="h-3 w-3" /> },
    untested: { label: "Não testado", cls: "text-nexus-muted bg-white/5", icon: <AlertCircle className="h-3 w-3" /> },
  };
  const s = map[status] ?? map.untested;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${s.cls}`}>
      {s.icon}
      {s.label}
    </span>
  );
}

function CreateConnectorModal({
  template,
  onClose,
  onCreated,
}: {
  template: MCPTemplateDetail;
  onClose: () => void;
  onCreated: (c: MCPConnector) => void;
}) {
  const [name, setName] = useState(template.name);
  const [params, setParams] = useState<Record<string, string>>({});
  const [env, setEnv] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const missingRequired = useMemo(() => {
    const missingParams = template.params.filter((p) => p.required && !params[p.key]?.trim());
    const missingEnv = template.env.filter((e) => e.required && !env[e.key]?.trim());
    return [...missingParams, ...missingEnv];
  }, [template, params, env]);

  const handleSubmit = useCallback(async () => {
    if (!name.trim() || missingRequired.length > 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const connector = await createMCPConnector({
        name: name.trim(),
        template_id: template.id,
        params,
        env,
      });
      onCreated(connector);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao criar conector");
    } finally {
      setSubmitting(false);
    }
  }, [name, params, env, template, missingRequired, onCreated]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-xl border border-nexus-border bg-[#0e0e18] p-6 shadow-2xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xl">{template.icon}</span>
            <h3 className="text-sm font-semibold text-white">Ligar {template.name}</h3>
          </div>
          <button onClick={onClose} className="text-nexus-muted hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
          <div>
            <label className="mb-1 block text-[11px] font-medium text-nexus-muted">Nome do conector</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-nexus-border bg-black/30 px-3 py-2 text-sm text-white focus:border-nexus-accent focus:outline-none"
            />
          </div>

          {template.params.map((p) => (
            <div key={p.key}>
              <label className="mb-1 block text-[11px] font-medium text-nexus-muted">
                {p.label}
                {p.required && <span className="text-red-400"> *</span>}
              </label>
              <input
                type={p.secret ? "password" : "text"}
                placeholder={p.placeholder}
                value={params[p.key] ?? ""}
                onChange={(e) => setParams((prev) => ({ ...prev, [p.key]: e.target.value }))}
                className="w-full rounded-lg border border-nexus-border bg-black/30 px-3 py-2 text-sm text-white focus:border-nexus-accent focus:outline-none"
              />
            </div>
          ))}

          {template.env.map((e) => (
            <div key={e.key}>
              <label className="mb-1 block text-[11px] font-medium text-nexus-muted">
                {e.label}
                {e.required && <span className="text-red-400"> *</span>}
              </label>
              <input
                type={e.secret ? "password" : "text"}
                placeholder={e.placeholder ?? e.key}
                value={env[e.key] ?? ""}
                onChange={(ev) => setEnv((prev) => ({ ...prev, [e.key]: ev.target.value }))}
                className="w-full rounded-lg border border-nexus-border bg-black/30 px-3 py-2 text-sm text-white focus:border-nexus-accent focus:outline-none"
              />
            </div>
          ))}

          {template.params.length === 0 && template.env.length === 0 && (
            <p className="text-xs text-nexus-muted italic">Este servidor não precisa de configuração adicional.</p>
          )}
        </div>

        {error && <p className="mt-3 text-xs text-red-400">{error}</p>}

        <div className="mt-5 flex items-center justify-between">
          {template.docs_url && (
            <a
              href={template.docs_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-[11px] text-nexus-muted hover:text-nexus-accent"
            >
              Documentação <ExternalLink className="h-3 w-3" />
            </a>
          )}
          <button
            onClick={handleSubmit}
            disabled={submitting || !name.trim() || missingRequired.length > 0}
            className="ml-auto flex items-center gap-2 rounded-lg bg-nexus-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-40 hover:bg-nexus-accent/90"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Criar conector
          </button>
        </div>
      </motion.div>
    </div>
  );
}

function ExportModal({ data, onClose }: { data: Record<string, unknown>; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const json = JSON.stringify(data, null, 2);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore clipboard errors */
    }
  }, [json]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-xl border border-nexus-border bg-[#0e0e18] p-6 shadow-2xl"
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Configuração MCP (JSON)</h3>
          <button onClick={onClose} className="text-nexus-muted hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-3 text-[11px] text-nexus-muted">
          Cola este bloco no <code className="text-nexus-accent">mcpServers</code> do teu cliente MCP (Claude Desktop, etc.).
        </p>
        <pre className="max-h-80 overflow-auto rounded-lg border border-nexus-border bg-black/40 p-3 text-[11px] text-emerald-300">
          {json}
        </pre>
        <button
          onClick={copy}
          className="mt-3 flex items-center gap-2 rounded-lg border border-nexus-border px-3 py-1.5 text-xs text-nexus-text hover:border-nexus-accent"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copiado!" : "Copiar JSON"}
        </button>
      </motion.div>
    </div>
  );
}

export default function MCPWizard() {
  const [templates, setTemplates] = useState<MCPTemplateSummary[]>([]);
  const [connectors, setConnectors] = useState<MCPConnector[]>([]);
  const [summary, setSummary] = useState<MCPConnectorsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTemplate, setActiveTemplate] = useState<MCPTemplateDetail | null>(null);
  const [exportData, setExportData] = useState<Record<string, unknown> | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>("all");

  const loadAll = useCallback(async () => {
    const [tmpls, connResp] = await Promise.all([getMCPTemplates(), getMCPConnectors()]);
    setTemplates(tmpls);
    setConnectors(connResp.connectors);
    setSummary(connResp.summary);
  }, []);

  useEffect(() => {
    setLoading(true);
    loadAll().finally(() => setLoading(false));
  }, [loadAll]);

  const categories = useMemo(() => {
    const set = new Set(templates.map((t) => t.category));
    return ["all", ...Array.from(set)];
  }, [templates]);

  const filteredTemplates = useMemo(
    () => (categoryFilter === "all" ? templates : templates.filter((t) => t.category === categoryFilter)),
    [templates, categoryFilter],
  );

  const openTemplate = useCallback(async (templateId: string) => {
    const detail = await getMCPTemplate(templateId);
    setActiveTemplate(detail);
  }, []);

  const handleCreated = useCallback(
    (connector: MCPConnector) => {
      setConnectors((prev) => [...prev, connector]);
      setActiveTemplate(null);
      loadAll();
    },
    [loadAll],
  );

  const handleDelete = useCallback(async (id: string) => {
    setConnectors((prev) => prev.filter((c) => c.id !== id));
    await deleteMCPConnector(id);
  }, []);

  const handleTest = useCallback(async (id: string) => {
    setTestingId(id);
    try {
      await testMCPConnector(id);
      const resp = await getMCPConnectors();
      setConnectors(resp.connectors);
      setSummary(resp.summary);
    } finally {
      setTestingId(null);
    }
  }, []);

  const handleExportOne = useCallback(async (id: string) => {
    const data = await exportMCPConnector(id);
    setExportData(data);
  }, []);

  const handleExportAll = useCallback(async () => {
    const data = await exportAllMCPConnectors();
    setExportData(data);
  }, []);

  return (
    <div className="space-y-6">
      {/* Summary bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          { label: "Total", value: summary?.total ?? 0, cls: "text-white" },
          { label: "Ativos", value: summary?.enabled ?? 0, cls: "text-nexus-accent" },
          { label: "Saudáveis", value: summary?.healthy ?? 0, cls: "text-emerald-400" },
          { label: "Avisos", value: summary?.warning ?? 0, cls: "text-yellow-400" },
          { label: "Erros", value: summary?.error ?? 0, cls: "text-red-400" },
        ].map((s) => (
          <div key={s.label} className="rounded-lg border border-nexus-border bg-[#13131f]/40 p-3 text-center">
            <div className={`text-xl font-bold ${s.cls}`}>{s.value}</div>
            <div className="text-[10px] text-nexus-muted">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Existing connectors */}
      <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent">
              <Plug className="h-4 w-4" />
            </div>
            <h3 className="text-sm font-semibold text-white">Conectores MCP configurados</h3>
          </div>
          {connectors.length > 0 && (
            <button
              onClick={handleExportAll}
              className="flex items-center gap-1.5 rounded-lg border border-nexus-border px-3 py-1.5 text-xs text-nexus-text hover:border-nexus-accent"
            >
              <Copy className="h-3.5 w-3.5" /> Exportar tudo
            </button>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <RefreshCw className="h-5 w-5 animate-spin text-nexus-muted" />
          </div>
        ) : connectors.length === 0 ? (
          <p className="text-xs text-nexus-muted italic py-4 text-center">
            Ainda não ligaste nenhum servidor MCP. Escolhe um template abaixo para começar.
          </p>
        ) : (
          <div className="space-y-2">
            {connectors.map((c) => (
              <motion.div
                key={c.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center justify-between rounded-lg border border-nexus-border/50 bg-black/20 px-3 py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-white">{c.name}</span>
                    <StatusBadge status={c.last_test_status} />
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-nexus-muted">
                    {c.transport === "http" ? c.url : `${c.command} ${c.args.join(" ")}`}
                  </p>
                  {c.last_test_detail && (
                    <p className="mt-0.5 truncate text-[10px] text-nexus-muted/70">{c.last_test_detail}</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-1.5 pl-3">
                  <button
                    onClick={() => handleTest(c.id)}
                    disabled={testingId === c.id}
                    title="Testar ligação"
                    className="rounded-md p-1.5 text-nexus-muted hover:bg-white/5 hover:text-nexus-accent disabled:opacity-50"
                  >
                    {testingId === c.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <button
                    onClick={() => handleExportOne(c.id)}
                    title="Exportar JSON"
                    className="rounded-md p-1.5 text-nexus-muted hover:bg-white/5 hover:text-nexus-accent"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => handleDelete(c.id)}
                    title="Remover"
                    className="rounded-md p-1.5 text-nexus-muted hover:bg-red-500/10 hover:text-red-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Template gallery */}
      <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-white">Adicionar novo conector</h3>
          <div className="flex flex-wrap gap-1.5">
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategoryFilter(cat)}
                className={`rounded-full px-3 py-1 text-[11px] transition-colors ${
                  categoryFilter === cat
                    ? "bg-nexus-accent/15 text-nexus-accent"
                    : "text-nexus-muted hover:bg-white/5"
                }`}
              >
                {cat === "all" ? "Todos" : CATEGORY_LABELS[cat] ?? cat}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredTemplates.map((t) => (
            <button
              key={t.id}
              onClick={() => openTemplate(t.id)}
              className="group flex flex-col items-start rounded-lg border border-nexus-border/60 bg-black/20 p-4 text-left transition-all hover:border-nexus-accent/50 hover:bg-black/30"
            >
              <div className="mb-2 flex w-full items-center justify-between">
                <span className="text-xl">{t.icon}</span>
                <Plus className="h-3.5 w-3.5 text-nexus-muted opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <div className="text-sm font-medium text-white">{t.name}</div>
              <p className="mt-1 text-[11px] text-nexus-muted line-clamp-2">{t.description}</p>
              {t.requires_env.length > 0 && (
                <p className="mt-2 text-[10px] text-yellow-400/80">Requer: {t.requires_env.join(", ")}</p>
              )}
            </button>
          ))}
        </div>
      </div>

      <AnimatePresence>
        {activeTemplate && (
          <CreateConnectorModal
            template={activeTemplate}
            onClose={() => setActiveTemplate(null)}
            onCreated={handleCreated}
          />
        )}
        {exportData && <ExportModal data={exportData} onClose={() => setExportData(null)} />}
      </AnimatePresence>
    </div>
  );
}
