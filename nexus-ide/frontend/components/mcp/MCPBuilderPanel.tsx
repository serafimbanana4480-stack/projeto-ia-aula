"use client";

import { useState, type FormEvent } from "react";
import { CheckCircle2, CircleAlert, Code2, Loader2, Sparkles } from "lucide-react";
import {
  buildMCPFromDescription,
  getMCPOverview,
  type MCPActivityItem,
  type MCPBuildResult,
} from "../../lib/api";

function errorMessage(error: unknown): string {
  if (!(error instanceof Error)) return "Não foi possível gerar o MCP.";
  try {
    const parsed = JSON.parse(error.message) as { detail?: { message?: string } | string };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (parsed.detail?.message) return parsed.detail.message;
  } catch {
    // Keep the API client's readable fallback message.
  }
  return error.message;
}

export default function MCPBuilderPanel() {
  const [description, setDescription] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [authSecret, setAuthSecret] = useState("");
  const [building, setBuilding] = useState(false);
  const [result, setResult] = useState<MCPBuildResult | null>(null);
  const [progress, setProgress] = useState<MCPActivityItem | null>(null);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBuilding(true);
    setResult(null);
    setProgress(null);
    setError("");
    const startedAt = Date.now() / 1000;
    const pollActivity = async () => {
      try {
        const overview = await getMCPOverview();
        const current = overview.activity.find(
          (item) => item.kind === "builder" && item.at >= startedAt - 2,
        );
        if (current) setProgress(current);
      } catch {
        // Build status remains visible in the activity view if polling drops.
      }
    };
    const activityTimer = window.setInterval(() => void pollActivity(), 1200);
    try {
      const next = await buildMCPFromDescription({
        description: description.trim(),
        base_url: baseUrl.trim(),
        ...(authSecret ? { auth_secret: authSecret } : {}),
      });
      setResult(next);
      window.dispatchEvent(new CustomEvent("nexus:mcp-built"));
    } catch (buildError) {
      setError(errorMessage(buildError));
    } finally {
      window.clearInterval(activityTimer);
      await pollActivity();
      setAuthSecret("");
      setBuilding(false);
    }
  };

  return (
    <section className="nx-elev-1 mb-6 overflow-hidden rounded-nx border border-nexus-accent/20">
      <div className="flex flex-col gap-3 border-b border-nexus-border/70 bg-nexus-accent/[0.06] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-nexus-accent/15 text-nexus-accent-bright"><Sparkles className="h-4 w-4" /></span>
          <div><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-nexus-accent-bright">MCP Builder</p><h2 className="mt-1 text-sm font-semibold text-nexus-text">Descreve a API; o NEXUS monta e valida o MCP</h2><p className="mt-1 max-w-2xl text-[11px] leading-relaxed text-nexus-muted">Gera tools declarativas, schemas, servidor, configuração e testes. Só fica disponível ao agente depois de passar as validações.</p></div>
        </div>
        <span className="flex shrink-0 items-center gap-1.5 text-[10px] text-nexus-faint"><Code2 className="h-3.5 w-3.5" /> REST API · schemas fechados · sem Python gerado pelo modelo</span>
      </div>
      <form onSubmit={(event) => void submit(event)} className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(260px,0.8fr)]">
        <label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-nexus-muted">O que deve fazer?</span><textarea required minLength={8} maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Ex.: cria tools para pesquisar issues por repositório e consultar os detalhes de uma issue. Usa autenticação por token." className="nx-inset min-h-28 w-full resize-y rounded-lg px-3 py-2.5 text-xs leading-relaxed text-nexus-text placeholder:text-nexus-faint" /></label>
        <div className="flex flex-col gap-4">
          <label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-nexus-muted">Base URL da API</span><input required type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com" className="nx-inset w-full rounded-lg px-3 py-2.5 text-xs text-nexus-text placeholder:text-nexus-faint" /></label>
          <label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-nexus-muted">Token da API <span className="font-normal text-nexus-faint">(opcional)</span></span><input type="password" autoComplete="new-password" value={authSecret} onChange={(event) => setAuthSecret(event.target.value)} placeholder="••••••••" className="nx-inset w-full rounded-lg px-3 py-2.5 text-xs text-nexus-text placeholder:text-nexus-faint" /></label>
          <p className="text-[10px] leading-relaxed text-nexus-faint">O token é enviado ao backend autenticado, cifrado no store MCP e omitido dos eventos e exports. Também podes deixar vazio e configurar <code className="text-nexus-muted">NEXUS_MCP_*</code> no ambiente do backend.</p>
          <button type="submit" disabled={building || description.trim().length < 8 || !baseUrl.trim()} className="mt-auto flex items-center justify-center gap-2 rounded-lg bg-nexus-accent px-3 py-2.5 text-xs font-semibold text-white transition hover:bg-nexus-accent-bright disabled:cursor-not-allowed disabled:opacity-50">{building ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />A gerar e validar…</> : <><Sparkles className="h-3.5 w-3.5" />Construir e validar MCP</>}</button>
        </div>
        {error && <div role="alert" className="lg:col-span-2 flex items-start gap-2 rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2.5 text-xs text-rose-200"><CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span>{error}</span></div>}
        {progress && <div aria-live="polite" className="lg:col-span-2 flex items-start gap-2 rounded-lg border border-nexus-border bg-nexus-card/50 px-3 py-2.5 text-[11px] text-nexus-muted"><span className="mt-0.5 text-nexus-accent-bright">{progress.status === "running" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : progress.status === "error" ? <CircleAlert className="h-3.5 w-3.5 text-rose-300" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />}</span><span><span className="font-semibold text-nexus-text">{progress.status === "running" ? "Acontece agora" : progress.status === "error" ? "Builder terminou com erro" : "Builder concluído"}</span><span className="ml-2">{progress.detail}</span>{progress.duration_ms != null && <span className="ml-2 text-nexus-faint">{Math.round(progress.duration_ms)} ms</span>}</span></div>}
        {result && <div className="lg:col-span-2 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.06] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2 text-sm font-semibold text-emerald-200"><CheckCircle2 className="h-4 w-4" />{result.connector.name} disponível ao agente</div><button type="button" onClick={() => window.dispatchEvent(new CustomEvent("nexus:mcp-built"))} className="rounded-lg border border-emerald-300/20 px-3 py-1.5 text-[10px] font-semibold text-emerald-100 hover:bg-emerald-300/10">Atualizar conectores</button></div>
          <div className="mt-3 flex flex-wrap gap-2">{result.capabilities.map((tool) => <span key={tool.name} title={tool.description} className="rounded-full border border-nexus-border bg-nexus-card/60 px-2.5 py-1 font-mono text-[10px] text-nexus-text">{tool.name} <span className="text-nexus-faint">{tool.method}</span></span>)}</div>
          <div className="mt-3 grid gap-2 text-[10px] text-nexus-muted sm:grid-cols-4"><span>Schema: {result.validation.schema_validation}</span><span>HTTP simulado: {result.validation.mock_http.mock_http_operations} operações</span><span>Testes gerados: {result.validation.generated_tests.unittest}</span><span>Handshake MCP: {result.validation.mcp_handshake}</span></div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-emerald-300/10 pt-3 text-[10px] text-nexus-faint">{Object.entries(result.generated_files).map(([kind, path]) => <span key={kind}><span className="text-nexus-muted">{kind}:</span> {path.split(/[\\/]/).pop()}</span>)}</div>
        </div>}
      </form>
    </section>
  );
}
