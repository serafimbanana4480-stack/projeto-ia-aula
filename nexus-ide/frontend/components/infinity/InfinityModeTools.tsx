"use client";

import { useId, useState } from "react";
import { Loader2 } from "lucide-react";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import { useAdvancedModeStore, type AdvancedMode } from "../../stores/advancedModeStore";

const INPUT = "w-full rounded-lg border border-nexus-border bg-nexus-bg/50 px-2.5 py-2 text-xs text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent";
const BUTTON = "inline-flex min-h-9 items-center gap-2 rounded-lg border border-purple-400/25 bg-purple-400/10 px-3 text-xs font-semibold text-purple-300 hover:bg-purple-400/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-50";
const CRITERIA = [
  ["security", "Segurança"], ["complexity", "Simplicidade"],
  ["performance", "Desempenho"], ["maintainability", "Manutenção"],
  ["compatibility", "Compatibilidade"], ["test_coverage", "Cobertura de testes"],
  ["dependency_count", "Poucas dependências"],
] as const;
const EVIDENCE = [
  ["tests_passed", "Testes"], ["edge_cases_covered", "Casos limite"],
  ["security_reviewed", "Revisão de segurança"], ["documentation_complete", "Documentação"],
  ["regression_free", "Ausência de regressões"],
] as const;

interface ActionResult {
  gate_passed?: boolean;
  requires_approval?: boolean;
  findings?: string[];
  verdict?: string;
  reason?: string;
  status?: string;
  winner_name?: string | null;
  winner_score?: number | null;
}

export function InfinityModeTools({ mode }: { mode: AdvancedMode }) {
  const { refreshHealth } = useAdvancedModeStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ActionResult | null>(null);
  const [action, setAction] = useState("");
  const [risk, setRisk] = useState("0");
  const [sessionId, setSessionId] = useState("");
  const [claim, setClaim] = useState("");
  const [sources, setSources] = useState<Record<string, string>>({});
  const [names, setNames] = useState(["", ""]);
  const [scores, setScores] = useState<Array<Record<string, string>>>([{}, {}]);
  const formId = useId();
  if (!["sentinel", "multiverse", "advisor-infinity"].includes(mode.mode_id)) return null;

  const submit = async (path: string, body: unknown) => {
    setBusy(true); setError(null); setResult(null);
    try {
      const response = await authenticatedFetch(apiUrl(path), {
        method: "POST", body: JSON.stringify(body), signal: AbortSignal.timeout(10_000),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `O pedido foi recusado (HTTP ${response.status}).`);
      setResult(payload as ActionResult);
      if (mode.mode_id === "advisor-infinity") await refreshHealth();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Não foi possível concluir a verificação.");
    } finally { setBusy(false); }
  };

  return <div className="space-y-3 rounded-xl border border-nexus-border bg-nexus-bg/25 p-3">
    {mode.mode_id === "sentinel" && <form className="space-y-3" onSubmit={(event) => {
      event.preventDefault();
      if (!action.trim()) { setError("Descreve a ação que queres verificar."); return; }
      void submit("/api/advanced-modes/sentinel/check", { action: action.trim(), risk_level: Number(risk), files: [] });
    }}>
      <h5 className="font-semibold text-nexus-text">Verificar uma ação</h5>
      <p className="text-[11px]">Análise estática de risco. A ação descrita fica por executar.</p>
      <label className="block" htmlFor={`${formId}-action`}>Ação a verificar</label>
      <textarea id={`${formId}-action`} value={action} onChange={(event) => { setAction(event.target.value); setResult(null); }} required maxLength={100_000} rows={2} className={INPUT} placeholder="Ex.: instalar uma dependência no projeto" />
      <label className="block" htmlFor={`${formId}-risk`}>Nível de risco</label>
      <select id={`${formId}-risk`} value={risk} onChange={(event) => { setRisk(event.target.value); setResult(null); }} className={INPUT}>
        <option value="0">0 · Leitura</option><option value="1">1 · Alteração local reversível</option>
        <option value="2">2 · Instalação ou migração</option><option value="3">3 · Operação destrutiva</option><option value="4">4 · Produção ou dados reais</option>
      </select>
      <button type="submit" disabled={busy} className={BUTTON}>{busy && <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />}Verificar risco</button>
    </form>}
    {mode.mode_id === "advisor-infinity" && <form className="space-y-3" onSubmit={(event) => {
      event.preventDefault();
      if (!sessionId || !claim.trim()) { setError("Escolhe uma sessão e descreve a conclusão."); return; }
      const evidence = Object.fromEntries(Object.entries(sources).filter(([, value]) => value.trim()).map(([category, source]) => [category, { status: "PASS", source: source.trim() }]));
      void submit("/api/advanced-modes/advisor-infinity/review", { session_id: sessionId, claim: claim.trim(), evidence });
    }}>
      <h5 className="font-semibold text-nexus-text">Rever uma conclusão</h5>
      <p className="text-[11px]">Verifica a cobertura das provas que indicas. O resultado mantém-se pendente até validação independente.</p>
      <label className="block" htmlFor={`${formId}-session`}>Sessão do Advisor</label>
      <select id={`${formId}-session`} required value={sessionId} onChange={(event) => { setSessionId(event.target.value); setResult(null); }} className={INPUT}>
        <option value="">Escolher sessão guardada</option>{mode.sessions?.map((session) => <option key={session.session_id} value={session.session_id}>{session.session_id} · {session.state}</option>)}
      </select>
      <label className="block" htmlFor={`${formId}-claim`}>Conclusão a rever</label>
      <textarea id={`${formId}-claim`} required value={claim} onChange={(event) => { setClaim(event.target.value); setResult(null); }} rows={2} maxLength={100_000} className={INPUT} />
      <fieldset className="space-y-2"><legend className="mb-2 text-[11px]">Referências das provas que afirmas ter validado</legend>
        {EVIDENCE.map(([category, label]) => <label key={category} className="block text-[11px]">{label}<input value={sources[category] ?? ""} onChange={(event) => { setSources((current) => ({ ...current, [category]: event.target.value })); setResult(null); }} placeholder="Caminho do resultado, evento ou relatório" className={`mt-1 ${INPUT}`} /></label>)}
      </fieldset>
      <button type="submit" disabled={busy || !mode.sessions?.length} className={BUTTON}>{busy && <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />}Rever conclusão</button>
    </form>}
    {mode.mode_id === "multiverse" && <form className="space-y-3" onSubmit={(event) => {
      event.preventDefault();
      if (names.some((name) => !name.trim()) || scores.some((entry) => CRITERIA.some(([key]) => !entry[key]?.trim() || !Number.isFinite(Number(entry[key])) || Number(entry[key]) < 0 || Number(entry[key]) > 100))) {
        setError("Indica os dois nomes e todas as pontuações entre 0 e 100."); return;
      }
      void submit("/api/advanced-modes/multiverse/evaluate", { entries: names.map((name, index) => ({ id: `alternative-${index + 1}`, name: name.trim(), scores: Object.fromEntries(CRITERIA.map(([key]) => [key, Number(scores[index][key])])) })) });
    }}>
      <h5 className="font-semibold text-nexus-text">Comparar duas alternativas</h5>
      <p className="text-[11px]">Pontuações fornecidas por ti, entre 0 e 100. Em todos os critérios, mais alto significa melhor. Esta comparação não executa as alternativas.</p>
      {names.map((name, index) => <label key={index} className="block">Alternativa {index + 1}<input required maxLength={256} value={name} onChange={(event) => { setNames((current) => current.map((value, item) => item === index ? event.target.value : value)); setResult(null); }} className={`mt-1 ${INPUT}`} /></label>)}
      <div className="space-y-2">{CRITERIA.map(([criterion, label]) => <div key={criterion} className="grid grid-cols-[minmax(0,1fr)_3.5rem_3.5rem] items-center gap-2"><span className="text-[11px]">{label}</span>{scores.map((entry, index) => <input key={index} type="number" required min={0} max={100} step="any" aria-label={`${label} da alternativa ${index + 1}`} value={entry[criterion] ?? ""} onChange={(event) => { setScores((current) => current.map((value, item) => item === index ? { ...value, [criterion]: event.target.value } : value)); setResult(null); }} className={`${INPUT} !px-1.5`} />)}</div>)}</div>
      <button type="submit" disabled={busy} className={BUTTON}>{busy && <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />}Comparar pontuações</button>
    </form>}
    {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
    {result && <div role="status" className="space-y-1 rounded-lg border border-nexus-border bg-nexus-bg/40 p-3 text-xs">
      <p className="font-semibold text-nexus-text">{mode.mode_id === "sentinel" ? result.requires_approval ? "Aprovação necessária" : "Sem bloqueio identificado nesta análise estática" : mode.mode_id === "advisor-infinity" ? result.verdict === "BLOCKED" ? "Conclusão bloqueada" : "Revisão pendente de validação" : result.winner_name ? `Melhor pontuação: ${result.winner_name} (${result.winner_score}/100)` : result.status === "TIE" ? "Empate nas pontuações submetidas" : "Sem vencedor determinado"}</p>
      {result.findings?.map((finding, index) => <p key={index} className="break-words text-nexus-muted">{finding}</p>)}
      <p className="text-[11px] text-nexus-muted">Execução e validação independente: não medidas por este formulário.</p>
    </div>}
  </div>;
}
