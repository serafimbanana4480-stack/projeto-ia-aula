"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Code2,
  Copy,
  Database,
  ExternalLink,
  FileCode2,
  Globe2,
  Layers3,
  Loader2,
  MoreHorizontal,
  Network,
  Plus,
  RefreshCw,
  Search,
  Server,
  Sparkles,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import {
  createMCPConnector,
  deleteMCPConnector,
  exportAllMCPConnectors,
  exportMCPConnector,
  getMCPOverview,
  getMCPTemplate,
  getMCPTemplates,
  testMCPConnector,
  type MCPActivityItem,
  type MCPConnector,
  type MCPOverview,
  type MCPTemplateDetail,
  type MCPTemplateSummary,
} from "../../lib/api";

const CATEGORY_LABELS: Record<string, string> = {
  all: "Todos",
  filesystem: "Ficheiros",
  dev: "Desenvolvimento",
  data: "Dados",
  web: "Web",
  collab: "Colaboração",
  custom: "Personalizado",
};

type View = "installed" | "marketplace" | "activity" | "graph";
type Sort = "recent" | "latency" | "tools" | "name";

function formatNumber(value: number | null | undefined) {
  return value == null ? "—" : new Intl.NumberFormat("pt-PT").format(value);
}

function formatTime(timestamp: number | null | undefined) {
  if (!timestamp) return "Nunca";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - timestamp));
  if (seconds < 60) return `há ${seconds}s`;
  if (seconds < 3600) return `há ${Math.round(seconds / 60)} min`;
  return `há ${Math.round(seconds / 3600)} h`;
}

function categoryIcon(category: string) {
  if (category === "data") return <Database className="h-4 w-4" />;
  if (category === "web") return <Globe2 className="h-4 w-4" />;
  if (category === "filesystem") return <FileCode2 className="h-4 w-4" />;
  return <Code2 className="h-4 w-4" />;
}

function statusMeta(status: MCPConnector["last_test_status"]) {
  if (status === "ok") return { label: "Saudável", color: "text-emerald-300", dot: "bg-emerald-400", soft: "bg-emerald-400/10" };
  if (status === "warning") return { label: "Degradado", color: "text-amber-300", dot: "bg-amber-400", soft: "bg-amber-400/10" };
  if (status === "error") return { label: "Erro", color: "text-rose-300", dot: "bg-rose-400", soft: "bg-rose-400/10" };
  return { label: "Não testado", color: "text-nexus-muted", dot: "bg-slate-500", soft: "bg-white/[0.04]" };
}

function StatusPill({ status }: { status: MCPConnector["last_test_status"] }) {
  const meta = statusMeta(status);
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[10px] font-semibold ${meta.color} ${meta.soft}`}><span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />{meta.label}</span>;
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return <div><p className="font-mono text-sm font-semibold tabular-nums text-nexus-text">{value}</p><p className="mt-0.5 text-[10px] text-nexus-faint">{label}</p></div>;
}

function ConnectorCard({ connector, onOpen, onTest, testing }: { connector: MCPConnector; onOpen: () => void; onTest: () => void; testing: boolean }) {
  const category = CATEGORY_LABELS[connector.template_id] ?? CATEGORY_LABELS.dev;
  const testable = connector.transport === "http" || connector.command;
  const tools = connector.tools ?? [];
  const toolCount = connector.tool_count ?? tools.length;
  return <motion.article layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="nx-elev-1 nx-surface nx-lift group rounded-nx p-4">
    <div className="flex items-start justify-between gap-3">
      <button onClick={onOpen} className="flex min-w-0 items-center gap-3 text-left">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-nexus-accent/12 text-lg font-bold text-nexus-accent-bright shadow-rim">{connector.name.slice(0, 2).toUpperCase()}</span>
        <span className="min-w-0"><span className="block truncate text-sm font-semibold text-nexus-text">{connector.name}</span><span className="mt-1 flex items-center gap-1.5 text-[10px] text-nexus-muted">{category} <span className="text-nexus-faint">·</span> {connector.transport.toUpperCase()}</span></span>
      </button>
      <div className="flex items-center gap-2"><StatusPill status={connector.last_test_status} /><button onClick={onOpen} aria-label={`Abrir ${connector.name}`} className="rounded-lg p-1 text-nexus-faint opacity-60 transition group-hover:opacity-100 hover:bg-white/5 hover:text-nexus-text"><MoreHorizontal className="h-4 w-4" /></button></div>
    </div>
    <div className="mt-4 grid grid-cols-4 gap-2 border-y border-nexus-border/70 py-3">
      <Metric label="tools" value={toolCount ? formatNumber(toolCount) : "—"} />
      <Metric label="latência" value={connector.latency_ms != null ? `${Math.round(connector.latency_ms)} ms` : "—"} />
      <Metric label="chamadas" value={connector.calls_today ? formatNumber(connector.calls_today) : "—"} />
      <Metric label="sucesso" value={connector.success_rate != null ? `${connector.success_rate.toFixed(1)}%` : "—"} />
    </div>
    {tools.length > 0 ? <div className="mt-3 space-y-1.5"><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-nexus-faint">Ferramentas disponíveis</p>{tools.slice(0, 3).map((tool) => <div key={tool.name} className="flex items-center justify-between gap-2 text-[11px] text-nexus-muted"><span className="truncate"><span className="mr-1 text-nexus-accent">›</span>{tool.name}</span><span className="font-mono text-[10px] text-nexus-faint">{tool.calls ? formatNumber(tool.calls) : "—"}</span></div>)}{tools.length > 3 && <p className="pt-1 text-[10px] text-nexus-accent-bright">Ver todas as {toolCount} tools <ArrowRight className="ml-1 inline h-3 w-3" /></p>}</div> : <div className="mt-3 flex items-center gap-2 text-[11px] text-nexus-faint"><CircleAlert className="h-3.5 w-3.5" />Tools ainda não descobertas nesta sessão</div>}
    <div className="mt-4 flex items-center justify-between gap-2"><span className="flex min-w-0 items-center gap-1.5 truncate text-[10px] text-nexus-faint"><Clock3 className="h-3 w-3 shrink-0" />último health check: {formatTime(connector.last_tested_at)}</span><div className="flex gap-1.5"><button onClick={onOpen} className="rounded-lg border border-nexus-border px-2.5 py-1.5 text-[10px] font-semibold text-nexus-muted transition hover:border-nexus-accent/50 hover:text-nexus-text">Abrir</button><button onClick={onTest} disabled={testing || !testable} className="rounded-lg bg-nexus-accent/12 px-2.5 py-1.5 text-[10px] font-semibold text-nexus-accent-bright transition hover:bg-nexus-accent/22 disabled:cursor-not-allowed disabled:opacity-40">{testing ? <Loader2 className="h-3 w-3 animate-spin" /> : "Testar"}</button></div></div>
  </motion.article>;
}

function CreateConnectorModal({ template, onClose, onCreated }: { template: MCPTemplateDetail; onClose: () => void; onCreated: (connector: MCPConnector) => void }) {
  const [name, setName] = useState(template.name);
  const [params, setParams] = useState<Record<string, string>>({});
  const [env, setEnv] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const missing = [...template.params.filter((field) => field.required && !params[field.key]?.trim()), ...template.env.filter((field) => field.required && !env[field.key]?.trim())];
  const submit = async () => { if (!name.trim() || missing.length) return; setSaving(true); setError(null); try { onCreated(await createMCPConnector({ name: name.trim(), template_id: template.id, params, env })); } catch (err) { setError(err instanceof Error ? err.message : "Não foi possível criar o MCP"); } finally { setSaving(false); } };
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}><motion.div initial={{ opacity: 0, scale: .97 }} animate={{ opacity: 1, scale: 1 }} onClick={(event) => event.stopPropagation()} className="nx-elev-3 max-h-[88vh] w-full max-w-xl overflow-y-auto rounded-nx-lg p-6">
    <div className="flex items-start justify-between"><div><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-nexus-accent-bright">Marketplace MCP</p><h2 className="mt-1 text-lg font-semibold text-nexus-text">Configurar {template.name}</h2><p className="mt-1 text-xs leading-relaxed text-nexus-muted">{template.description}</p></div><button onClick={onClose} className="rounded-lg p-2 text-nexus-muted hover:bg-white/5 hover:text-nexus-text"><X className="h-4 w-4" /></button></div>
    <div className="mt-5 space-y-4"><label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-nexus-muted">Nome no Nexus</span><input value={name} onChange={(event) => setName(event.target.value)} className="nx-inset w-full rounded-lg px-3 py-2 text-sm text-nexus-text" /></label>{[...template.params, ...template.env].map((field) => <label key={field.key} className="block"><span className="mb-1.5 block text-[11px] font-semibold text-nexus-muted">{field.label}{field.required && <span className="text-rose-300"> *</span>}</span><input type={field.secret ? "password" : "text"} placeholder={field.placeholder ?? field.key} value={(template.env.some((item) => item.key === field.key) ? env[field.key] : params[field.key]) ?? ""} onChange={(event) => template.env.some((item) => item.key === field.key) ? setEnv((current) => ({ ...current, [field.key]: event.target.value })) : setParams((current) => ({ ...current, [field.key]: event.target.value }))} className="nx-inset w-full rounded-lg px-3 py-2 text-sm text-nexus-text placeholder:text-nexus-faint" /></label>)}</div>
    {error && <p className="mt-4 rounded-lg bg-rose-400/10 px-3 py-2 text-xs text-rose-200">{error}</p>}<div className="mt-6 flex items-center justify-between"><a href={template.docs_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-nexus-muted hover:text-nexus-accent-bright">Documentação <ExternalLink className="h-3 w-3" /></a><button onClick={submit} disabled={saving || !name.trim() || missing.length > 0} className="flex items-center gap-2 rounded-lg bg-nexus-accent px-4 py-2 text-xs font-semibold text-white shadow-nx-accent disabled:opacity-40">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}Ligar MCP</button></div>
  </motion.div></div>;
}

function DetailDrawer({ connector, onClose, onTest, testing, onDelete }: { connector: MCPConnector; onClose: () => void; onTest: () => void; testing: boolean; onDelete: () => void }) {
  const meta = statusMeta(connector.last_test_status);
  const tools = connector.tools ?? [];
  const toolCount = connector.tool_count ?? tools.length;
  return <div className="fixed inset-0 z-40 bg-black/45" onClick={onClose}><motion.aside initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} onClick={(event) => event.stopPropagation()} className="nx-elev-3 absolute right-0 top-0 h-full w-full max-w-md overflow-y-auto border-l border-nexus-border p-6 shadow-nx-3"><div className="flex items-start justify-between"><div><div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-emerald-400" /><span className={`text-xs font-semibold ${meta.color}`}>{meta.label}</span></div><h2 className="mt-2 text-xl font-semibold text-nexus-text">{connector.name}</h2><p className="mt-1 text-xs text-nexus-muted">{connector.description}</p></div><button onClick={onClose} className="rounded-lg p-2 text-nexus-muted hover:bg-white/5 hover:text-nexus-text"><X className="h-4 w-4" /></button></div>
    <div className="mt-6 grid grid-cols-2 gap-2"><div className="nx-inset rounded-lg p-3"><p className="text-[10px] text-nexus-faint">Transport</p><p className="mt-1 text-sm font-semibold text-nexus-text">{connector.transport.toUpperCase()}</p></div><div className="nx-inset rounded-lg p-3"><p className="text-[10px] text-nexus-faint">Health score</p><p className={`mt-1 text-sm font-semibold ${meta.color}`}>{connector.health_score == null ? "—" : `${connector.health_score}/100`}</p></div><div className="nx-inset rounded-lg p-3"><p className="text-[10px] text-nexus-faint">Latência</p><p className="mt-1 text-sm font-semibold text-nexus-text">{connector.latency_ms == null ? "—" : `${Math.round(connector.latency_ms)} ms`}</p></div><div className="nx-inset rounded-lg p-3"><p className="text-[10px] text-nexus-faint">Tools</p><p className="mt-1 text-sm font-semibold text-nexus-text">{formatNumber(toolCount)}</p></div></div>
    <section className="mt-7"><div className="flex items-center justify-between"><h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-nexus-muted">Tools descobertas</h3><span className="text-[10px] text-nexus-faint">{tools.length} registadas</span></div>{tools.length ? <div className="mt-3 space-y-1.5">{tools.map((tool) => <div key={tool.name} className="flex items-center justify-between rounded-lg border border-nexus-border/60 bg-nexus-card/40 px-3 py-2 text-xs"><span className="flex items-center gap-2 text-nexus-text"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />{tool.name}</span><span className="text-[10px] text-nexus-faint">{tool.title}</span></div>)}</div> : <div className="mt-3 rounded-lg border border-dashed border-nexus-border p-4 text-center text-xs text-nexus-faint">A lista fica disponível quando o servidor fizer uma sessão MCP real.</div>}</section>
    <section className="mt-7"><h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-nexus-muted">Runtime</h3><div className="mt-3 space-y-2 text-xs"><div className="flex justify-between gap-4"><span className="text-nexus-faint">Comando</span><code className="max-w-[230px] truncate text-right text-nexus-muted">{connector.transport === "http" ? connector.url : `${connector.command} ${connector.args.join(" ")}`}</code></div>{connector.source_root && <div className="flex justify-between gap-4"><span className="text-nexus-faint">Projeto</span><code className="max-w-[230px] truncate text-right text-nexus-muted">{connector.source_root}</code></div>}<div className="flex justify-between"><span className="text-nexus-faint">Último teste</span><span className="text-nexus-muted">{formatTime(connector.last_tested_at)}</span></div>{connector.index_stats && <div className="rounded-lg border border-nexus-border/60 bg-nexus-card/45 p-3"><p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-nexus-faint">Índice local ProjectMind</p><div className="grid grid-cols-3 gap-2 text-center"><div><p className="font-mono text-sm font-semibold text-nexus-text">{formatNumber(connector.index_stats.files)}</p><p className="text-[9px] text-nexus-faint">ficheiros</p></div><div><p className="font-mono text-sm font-semibold text-nexus-text">{formatNumber(connector.index_stats.nodes)}</p><p className="text-[9px] text-nexus-faint">nós</p></div><div><p className="font-mono text-sm font-semibold text-nexus-text">{formatNumber(connector.index_stats.edges)}</p><p className="text-[9px] text-nexus-faint">relações</p></div></div></div>}{connector.last_test_detail && <p className="rounded-lg bg-nexus-card/70 p-3 text-[11px] leading-relaxed text-nexus-muted">{connector.last_test_detail}</p>}</div></section>
    <div className="mt-8 flex gap-2"><button onClick={onTest} disabled={testing} className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-nexus-accent px-3 py-2.5 text-xs font-semibold text-white disabled:opacity-50">{testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}Testar ligação</button><button onClick={onDelete} className="rounded-lg border border-rose-400/20 px-3 py-2.5 text-rose-300 hover:bg-rose-400/10"><Trash2 className="h-3.5 w-3.5" /></button></div>
  </motion.aside></div>;
}

function ActivityPanel({ activity }: { activity: MCPActivityItem[] }) {
  return <section className="nx-elev-1 rounded-nx p-5"><div className="flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-nexus-muted">Live activity</p><p className="mt-1 text-[11px] text-nexus-faint">Eventos persistidos pelo health check do Nexus</p></div><span className="flex items-center gap-1.5 text-[10px] text-nexus-faint"><span className="h-1.5 w-1.5 rounded-full bg-nexus-accent" />fonte real</span></div>{activity.length ? <div className="mt-5 space-y-2">{activity.map((item) => <div key={`${item.connector_id}-${item.at}`} className="flex items-center gap-3 rounded-lg border border-nexus-border/60 bg-nexus-card/35 px-3 py-2.5"><span className="w-14 shrink-0 font-mono text-[10px] text-nexus-faint">{new Date(item.at * 1000).toLocaleTimeString("pt-PT")}</span><span className="rounded-md bg-nexus-accent/10 px-2 py-1 text-[10px] font-semibold text-nexus-accent-bright">health</span><span className="min-w-0 flex-1 truncate text-xs text-nexus-text">{item.connector} <span className="text-nexus-faint">→</span> {item.tool}</span><span className={item.status === "ok" ? "text-emerald-300" : "text-amber-300"}>{item.latency_ms == null ? item.status : `${Math.round(item.latency_ms)} ms`}</span></div>)}</div> : <div className="mt-5 flex flex-col items-center justify-center rounded-lg border border-dashed border-nexus-border px-5 py-12 text-center"><Activity className="h-7 w-7 text-nexus-faint" /><p className="mt-3 text-xs font-semibold text-nexus-muted">Ainda não há atividade MCP</p><p className="mt-1 max-w-xs text-[11px] leading-relaxed text-nexus-faint">Testa um servidor ou faz a primeira chamada de ferramenta para começares a ver eventos aqui.</p></div>}</section>;
}

export default function MCPWizard() {
  const [templates, setTemplates] = useState<MCPTemplateSummary[]>([]);
  const [overview, setOverview] = useState<MCPOverview | null>(null);
  const [view, setView] = useState<View>("installed");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [sort, setSort] = useState<Sort>("recent");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MCPConnector | null>(null);
  const [template, setTemplate] = useState<MCPTemplateDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (showSpinner = false) => { if (showSpinner) setRefreshing(true); try { const [nextTemplates, nextOverview] = await Promise.all([getMCPTemplates(), getMCPOverview()]); setTemplates(nextTemplates); setOverview(nextOverview); setError(null); } catch (err) { setError(err instanceof Error ? err.message : "Falha ao carregar o Control Center"); } finally { setLoading(false); setRefreshing(false); } }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  const connectors = useMemo(() => overview?.connectors ?? [], [overview]);
  const filteredConnectors = useMemo(() => { const query = search.trim().toLowerCase(); const result = connectors.filter((connector) => { const matchesQuery = !query || `${connector.name} ${connector.description} ${connector.template_id} ${connector.last_test_status}`.toLowerCase().includes(query); const matchesCategory = category === "all" || connector.template_id === category; return matchesQuery && matchesCategory; }); return [...result].sort((a, b) => sort === "name" ? a.name.localeCompare(b.name) : sort === "tools" ? (b.tool_count ?? b.tools?.length ?? 0) - (a.tool_count ?? a.tools?.length ?? 0) : sort === "latency" ? (a.latency_ms ?? Number.MAX_SAFE_INTEGER) - (b.latency_ms ?? Number.MAX_SAFE_INTEGER) : (b.last_tested_at ?? 0) - (a.last_tested_at ?? 0)); }, [category, connectors, search, sort]);
  const filteredTemplates = useMemo(() => templates.filter((item) => { const matchesSearch = !search.trim() || `${item.name} ${item.description} ${item.category}`.toLowerCase().includes(search.toLowerCase()); return matchesSearch && (category === "all" || item.category === category); }), [category, search, templates]);
  const summary = overview?.summary;
  const doTest = async (id: string) => { setTestingId(id); try { await testMCPConnector(id); await load(); } catch (err) { setError(err instanceof Error ? err.message : "Falha no teste"); } finally { setTestingId(null); } };
  const testAll = async () => { for (const connector of connectors) await doTest(connector.id); };
  const openTemplate = async (id: string) => { try { setTemplate(await getMCPTemplate(id)); } catch (err) { setError(err instanceof Error ? err.message : "Template indisponível"); } };
  const onCreated = (connector: MCPConnector) => { setTemplate(null); setView("installed"); setOverview((current) => current ? { ...current, connectors: [...current.connectors, connector], summary: { ...current.summary, total: current.summary.total + 1, enabled: current.summary.enabled + 1, untested: current.summary.untested + 1 } } : current); void load(); };
  const remove = async () => { if (!detail || !window.confirm(`Remover ${detail.name}?`)) return; await deleteMCPConnector(detail.id); setDetail(null); await load(); };
  const exportAll = async () => { const data = await exportAllMCPConnectors(); await navigator.clipboard.writeText(JSON.stringify(data, null, 2)); };
  const tabs: Array<{ id: View; label: string; count?: number; icon: ReactNode }> = [{ id: "installed", label: "Instalados", count: connectors.length, icon: <Server className="h-3.5 w-3.5" /> }, { id: "marketplace", label: "Marketplace", count: templates.length, icon: <Layers3 className="h-3.5 w-3.5" /> }, { id: "activity", label: "Atividade", count: overview?.activity.length, icon: <Activity className="h-3.5 w-3.5" /> }, { id: "graph", label: "Grafo", icon: <Network className="h-3.5 w-3.5" /> }];

  if (loading) return <div className="nx-elev-1 flex min-h-[360px] items-center justify-center rounded-nx"><Loader2 className="h-6 w-6 animate-spin text-nexus-accent" /></div>;
  return <div className="space-y-5">
    <section className="nx-elev-1 nx-surface rounded-nx p-5"><div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center"><div><div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-nexus-accent/15 text-nexus-accent-bright"><Sparkles className="h-4 w-4" /></span><div><h2 className="text-lg font-semibold text-nexus-text">MCP Control Center</h2><p className="text-[11px] text-nexus-muted">Tools, memória, documentação e ligações dos teus agentes num só lugar.</p></div></div></div><div className="flex flex-wrap items-center gap-2"><button onClick={() => setView("marketplace")} className="flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white shadow-nx-accent"><Plus className="h-3.5 w-3.5" />Adicionar MCP</button><button onClick={testAll} disabled={!connectors.length || testingId !== null} className="flex items-center gap-1.5 rounded-lg border border-nexus-border px-3 py-2 text-xs font-semibold text-nexus-muted hover:border-nexus-accent/50 hover:text-nexus-text disabled:opacity-40"><Zap className="h-3.5 w-3.5" />Testar todos</button><button onClick={exportAll} disabled={!connectors.length} className="rounded-lg border border-nexus-border p-2 text-nexus-muted hover:border-nexus-accent/50 hover:text-nexus-text disabled:opacity-40" aria-label="Exportar configuração"><Copy className="h-3.5 w-3.5" /></button><button onClick={() => void load(true)} className="rounded-lg border border-nexus-border p-2 text-nexus-muted hover:border-nexus-accent/50 hover:text-nexus-text" aria-label="Atualizar">{refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}</button></div></div>
      <div className="mt-5 grid grid-cols-2 gap-2 border-t border-nexus-border/70 pt-4 sm:grid-cols-5"><Metric label="Total" value={summary?.total ?? 0} /><Metric label="Ativos" value={summary?.enabled ?? 0} /><Metric label="Saudáveis" value={<span className="text-emerald-300">{summary?.healthy ?? 0}</span>} /><Metric label="Degradados" value={<span className="text-amber-300">{summary?.warning ?? 0}</span>} /><Metric label="Erros" value={<span className="text-rose-300">{summary?.error ?? 0}</span>} /></div>
    </section>
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-nexus-border/70 bg-nexus-card/45 px-4 py-3 text-[11px]"><span className="flex items-center gap-1.5 text-emerald-300"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />{summary?.healthy ?? 0} Saudáveis</span><span className="flex items-center gap-1.5 text-amber-300"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" />{summary?.warning ?? 0} Degradados</span><span className="flex items-center gap-1.5 text-rose-300"><span className="h-1.5 w-1.5 rounded-full bg-rose-400" />{summary?.error ?? 0} Erros</span><span className="ml-auto flex items-center gap-1.5 text-nexus-faint"><Clock3 className="h-3 w-3" />último health check: {formatTime(summary?.last_health_check)} <span className="mx-1">·</span> média: {summary?.avg_latency_ms == null ? "—" : `${Math.round(summary.avg_latency_ms)} ms`}</span></div>
    <section className="nx-elev-1 rounded-nx p-3"><div className="flex flex-col gap-3 lg:flex-row lg:items-center"><label className="nx-inset flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-2"><Search className="h-4 w-4 shrink-0 text-nexus-faint" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Pesquisar MCPs, tools, estados..." className="min-w-0 flex-1 bg-transparent text-xs text-nexus-text outline-none placeholder:text-nexus-faint" /><kbd className="hidden rounded border border-nexus-border px-1.5 py-0.5 text-[9px] text-nexus-faint sm:block">Ctrl K</kbd></label><div className="flex items-center gap-1 overflow-x-auto">{tabs.map((tab) => <button key={tab.id} onClick={() => setView(tab.id)} className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-[11px] font-semibold transition ${view === tab.id ? "bg-nexus-accent/15 text-nexus-accent-bright" : "text-nexus-muted hover:bg-white/5 hover:text-nexus-text"}`}>{tab.icon}{tab.label}{tab.count != null && <span className="rounded-full bg-white/5 px-1.5 text-[9px] text-nexus-faint">{tab.count}</span>}</button>)}</div></div></section>
    {error && <div className="flex items-center justify-between rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-200"><span>{error}</span><button onClick={() => setError(null)}><X className="h-3.5 w-3.5" /></button></div>}
    {view === "installed" && <><div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-nexus-text">Os meus MCPs</h3><p className="mt-1 text-[11px] text-nexus-faint">Estado e ferramentas descobertas a partir das ligações configuradas.</p></div><div className="flex items-center gap-2"><div className="flex gap-1 overflow-x-auto">{["all", ...Array.from(new Set(connectors.map((item) => item.template_id)))].map((item) => <button key={item} onClick={() => setCategory(item)} className={`rounded-full px-2.5 py-1 text-[10px] ${category === item ? "bg-nexus-accent/15 text-nexus-accent-bright" : "text-nexus-muted hover:bg-white/5"}`}>{CATEGORY_LABELS[item] ?? item}</button>)}</div><select value={sort} onChange={(event) => setSort(event.target.value as Sort)} className="nx-inset rounded-lg px-2 py-1.5 text-[10px] text-nexus-muted"><option value="recent">Mais recentes</option><option value="latency">Menor latência</option><option value="tools">Mais tools</option><option value="name">Nome</option></select></div></div>{filteredConnectors.length ? <div className="grid gap-4 xl:grid-cols-2">{filteredConnectors.map((connector) => <ConnectorCard key={connector.id} connector={connector} onOpen={() => setDetail(connector)} onTest={() => void doTest(connector.id)} testing={testingId === connector.id} />)}</div> : <div className="nx-elev-1 flex flex-col items-center justify-center rounded-nx border-dashed px-5 py-16 text-center"><Server className="h-8 w-8 text-nexus-faint" /><p className="mt-3 text-sm font-semibold text-nexus-muted">Ainda não tens MCPs configurados</p><p className="mt-1 max-w-md text-xs leading-relaxed text-nexus-faint">Adiciona o ProjectMind local, Serena, Context7, Qdrant ou outro servidor do marketplace para começar.</p><button onClick={() => setView("marketplace")} className="mt-4 rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white">Explorar marketplace</button></div>}</>}
    {view === "marketplace" && <section><div className="mb-4 flex items-center justify-between"><div><h3 className="text-sm font-semibold text-nexus-text">Marketplace MCP</h3><p className="mt-1 text-[11px] text-nexus-faint">Instalações prontas, com requisitos visíveis apenas quando necessários.</p></div><span className="text-[10px] text-nexus-faint">{filteredTemplates.length} resultados</span></div><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{filteredTemplates.map((item) => <button key={item.id} onClick={() => void openTemplate(item.id)} className="nx-elev-1 nx-lift group rounded-nx p-4 text-left"><div className="flex items-center justify-between"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent-bright">{categoryIcon(item.category)}</span><Plus className="h-4 w-4 text-nexus-faint opacity-0 transition group-hover:opacity-100" /></div><p className="mt-3 text-sm font-semibold text-nexus-text">{item.name}</p><p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-nexus-muted">{item.description}</p><div className="mt-4 flex items-center justify-between text-[10px] text-nexus-faint"><span>{CATEGORY_LABELS[item.category] ?? item.category}</span><span className="rounded-full border border-nexus-border px-2 py-1">{item.transport.toUpperCase()}</span></div></button>)}</div></section>}
    {view === "activity" && <ActivityPanel activity={overview?.activity ?? []} />}
    {view === "graph" && <section className="nx-elev-1 rounded-nx p-5"><div className="flex items-center justify-between"><div><h3 className="text-sm font-semibold text-nexus-text">Grafo Agent ↔ MCP</h3><p className="mt-1 text-[11px] text-nexus-faint">A associação de agentes será mostrada quando as permissões estiverem atribuídas.</p></div><Network className="h-5 w-5 text-nexus-accent" /></div><div className="mt-6 grid gap-3 md:grid-cols-3"><div className="rounded-xl border border-dashed border-nexus-border p-4"><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-nexus-faint">Agentes</p><p className="mt-4 text-xs text-nexus-muted">Nenhum acesso MCP explícito registado.</p></div><div className="flex items-center justify-center text-nexus-accent"><ArrowRight className="h-5 w-5" /></div><div className="rounded-xl border border-nexus-border bg-nexus-card/45 p-4"><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-nexus-faint">MCPs configurados</p><div className="mt-3 space-y-2">{connectors.map((connector) => <button key={connector.id} onClick={() => setDetail(connector)} className="flex w-full items-center justify-between rounded-lg bg-nexus-surface/60 px-3 py-2 text-left text-xs text-nexus-text hover:bg-nexus-accent/10"><span className="flex items-center gap-2"><span className={`h-1.5 w-1.5 rounded-full ${statusMeta(connector.last_test_status).dot}`} />{connector.name}</span><ArrowRight className="h-3 w-3 text-nexus-faint" /></button>)}</div></div></div></section>}
    <AnimatePresence>{template && <CreateConnectorModal template={template} onClose={() => setTemplate(null)} onCreated={onCreated} />}{detail && <DetailDrawer connector={detail} onClose={() => setDetail(null)} onTest={() => void doTest(detail.id)} testing={testingId === detail.id} onDelete={() => void remove()} />}</AnimatePresence>
  </div>;
}
