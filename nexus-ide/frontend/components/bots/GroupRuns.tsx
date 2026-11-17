"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import {
  canCancelRun,
  canResumeRun,
  handoffRecords,
  mergeRuns,
  recordKindLabel,
  runEngineLabel,
  runIdentity,
  runIsActive,
  runState,
  runStateLabel,
  taskStatusLabel,
  taskVerification,
  verificationOf,
  type RoomRun,
  type RoomRunRecord,
} from "./chat/model";

function recordDetail(record: RoomRunRecord): string {
  const payload = record.payload;
  if (record.kind === "tool_call") {
    const tool = typeof payload.tool === "string" ? payload.tool : "ferramenta";
    const path = typeof payload.path === "string" ? payload.path : "";
    return path ? `${tool} · ${path}` : tool;
  }
  if (record.kind === "tool_result") {
    return typeof payload.error === "string" ? payload.error : "Sem erro registado";
  }
  if (record.kind === "handoff" || record.kind === "reassignment" || record.kind === "transfer" || record.kind === "delegation") {
    const from = typeof payload.from === "string" ? payload.from : typeof payload.from_bot_name === "string" ? payload.from_bot_name : "";
    const to = typeof payload.to === "string" ? payload.to : typeof payload.to_bot_name === "string" ? payload.to_bot_name : "";
    const reason = typeof payload.reason === "string" ? payload.reason : "";
    if (from || to) return `${from || "origem"} → ${to || "destino"}${reason ? ` · ${reason}` : ""}`;
    return "As análises anteriores seguem como dados não verificados";
  }
  if (record.kind === "verification" || record.kind === "verified" || record.kind === "verification_result") {
    if (typeof payload.detail === "string") return payload.detail;
    if (typeof payload.summary === "string") return payload.summary;
    if (typeof payload.verdict === "string") return `Veredicto: ${payload.verdict}`;
    return "Registo de verificação";
  }
  return "Evento sem descrição específica";
}

function ActivityList({ records }: { records: RoomRunRecord[] }) {
  if (records.length === 0) {
    return <p className="mt-2 text-xs text-zinc-500">Sem eventos de ferramenta nesta etapa.</p>;
  }
  return (
    <ol className="mt-2 space-y-2" aria-label="Eventos desta etapa">
      {records.map((record, index) => (
        <li key={record.id} className="rounded border border-white/10 px-2 py-1.5">
          <p className="text-xs font-medium text-zinc-200">
            {index + 1}. {recordKindLabel(record.kind)}
          </p>
          <p className="text-xs text-zinc-400">{recordDetail(record)}</p>
          <details className="mt-1">
            <summary className="cursor-pointer text-[11px] text-zinc-500">{record.kind} · {record.id}</summary>
            <pre className="whitespace-pre-wrap break-all text-xs text-zinc-300">{JSON.stringify(record.payload, null, 2)}</pre>
          </details>
        </li>
      ))}
    </ol>
  );
}

function verificationText(verified: boolean | null): string {
  if (verified === true) return "Verificado";
  if (verified === false) return "Não aprovado";
  return "Registo sem resultado explícito";
}

function VerificationBlock({ run }: { run: RoomRun }) {
  const entries = verificationOf(run);
  return (
    <section className="mt-3" aria-label={`Verificação da execução ${runIdentity(run).slice(0, 8)}`} data-testid="group-run-verification">
      <p className="font-medium">Verificação</p>
      {entries.length === 0 ? (
        <p className="mt-1 text-xs leading-5 text-zinc-400">Sem verificação registada. As respostas dos bots são propostas, não prova de conclusão.</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {entries.map((entry) => (
            <li key={entry.id} className="text-xs leading-5">
              <span className={entry.verified === true ? "font-medium text-emerald-300" : entry.verified === false ? "font-medium text-red-300" : "font-medium text-amber-200"}>{verificationText(entry.verified)}</span>
              <span className="text-zinc-400"> · {entry.label}{entry.detail ? ` · ${entry.detail}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function GroupRuns({ groupId, embedded = false }: { groupId: string; embedded?: boolean }) {
  const [runs, setRuns] = useState<RoomRun[]>([]);
  const [message, setMessage] = useState("");
  const [file, setFile] = useState("");
  const [project, setProject] = useState(".");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState("");
  const [open, setOpen] = useState(false);
  const [expandedRuns, setExpandedRuns] = useState<Record<string, boolean>>({});
  const load = useCallback(async () => {
    const response = await authenticatedFetch(apiUrl(`/api/bot-groups/${encodeURIComponent(groupId)}/runs`));
    if (!response.ok) throw new Error("Não foi possível carregar as execuções.");
    const data = await response.json() as { runs: RoomRun[] };
    // Merge in place: a failed refresh preserves what the operator already
    // saw, and incoming rows only advance their own identity.
    setRuns((current) => mergeRuns(current, Array.isArray(data.runs) ? data.runs : []));
  }, [groupId]);
  useEffect(() => {
    setRuns([]);
    setExpandedRuns({});
    setError("");
  }, [groupId]);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const refresh = () => {
      void load().catch(() => {
        if (alive) setError("Não foi possível atualizar as execuções. O histórico já carregado mantém-se.");
      });
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [load, open]);
  async function start(event: FormEvent) {
    event.preventDefault();
    if (sending) return;
    setSending(true); setError("");
    try {
      const response = await authenticatedFetch(apiUrl(`/api/bot-groups/${encodeURIComponent(groupId)}/runs`), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, file_path: file, project_path: project }),
      });
      if (!response.ok) {
        const body = await response.json() as { detail?: string };
        throw new Error(body.detail || "Não foi possível iniciar a execução.");
      }
      setMessage(""); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível iniciar a execução."); }
    finally { setSending(false); }
  }
  async function resume(runId: string) {
    if (stopping) return;
    setStopping(runId); setError("");
    try {
      const response = await authenticatedFetch(apiUrl(`/api/bot-groups/${encodeURIComponent(groupId)}/runs/${encodeURIComponent(runId)}/resume`), { method: "POST" });
      if (!response.ok) {
        const body = await response.json() as { detail?: string };
        throw new Error(body.detail || "Nao foi possivel retomar a execucao.");
      }
      const payload = await response.json() as { resumed?: boolean; detail?: string };
      if (payload.resumed === false && payload.detail) setError(payload.detail);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Nao foi possivel retomar a execucao."); }
    finally { setStopping(""); }
  }
  async function stop(runId: string) {
    if (stopping) return;
    setStopping(runId); setError("");
    try {
      const response = await authenticatedFetch(apiUrl(`/api/bot-groups/${encodeURIComponent(groupId)}/runs/${encodeURIComponent(runId)}/cancel`), { method: "POST" });
      if (!response.ok) {
        const body = await response.json() as { detail?: string };
        throw new Error(body.detail || "Não foi possível pedir a paragem.");
      }
      const payload = await response.json() as { cancelled?: boolean; detail?: string };
      if (payload.cancelled === false && payload.detail) setError(payload.detail);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível pedir a paragem."); }
    finally { setStopping(""); }
  }
  return <section className={embedded ? "text-sm" : "border-b border-white/10 p-4 text-sm"} aria-label="Execuções persistentes">
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="font-semibold text-violet-300">Execuções de equipa{open ? ` (${runs.length})` : ""}</button>
    {open && <div className="mt-3 max-h-96 space-y-4 overflow-y-auto">
      <p className="text-xs text-zinc-400">Cada execução mostra o motor que a produziu. `PRIMARY` é o compositor e tem o run_state como autoridade; `Leitura de ficheiro` é o motor legacy, que continua legível e retomável. As respostas dos bots só contam como verificadas quando existe um registo de verificação.</p>
      <form onSubmit={(event) => void start(event)} className="grid gap-2">
        <p className="text-[11px] text-zinc-500">Esta entrada inicia o motor legacy de leitura de ficheiro; o compositor usa o motor PRIMARY.</p>
        <label className="text-[12px]">Projeto registado <input aria-label="Caminho do projeto" value={project} onChange={(event) => setProject(event.target.value)} className="mt-1 w-full rounded-lg border border-white/10 bg-[color:var(--nx-bg)] p-2" /></label>
        <label className="text-[12px]">Ficheiro <input aria-label="Ficheiro a ler" required maxLength={1000} value={file} onChange={(event) => setFile(event.target.value)} className="mt-1 w-full rounded-lg border border-white/10 bg-[color:var(--nx-bg)] p-2" /></label>
        <label className="text-[12px]">Pedido <textarea aria-label="Pedido da execução" required maxLength={12000} value={message} onChange={(event) => setMessage(event.target.value)} className="mt-1 w-full rounded-lg border border-white/10 bg-[color:var(--nx-bg)] p-2" /></label>
        <button disabled={sending} className="w-fit rounded-lg bg-[color:var(--nx-accent)] px-3 py-2 text-white disabled:opacity-40">{sending ? "A iniciar…" : "Iniciar execução"}</button>
      </form>
      {error && <p role="alert" className="text-red-300">{error}</p>}
      <p role="status" aria-live="polite" className="text-[11px] text-zinc-500">
        {runs.length === 0 ? "Sem execuções carregadas." : `${runs.length} ${runs.length === 1 ? "execução" : "execuções"}; a lista é atualizada enquanto houver trabalho ativo.`}
      </p>
      {runs.map((run) => {
        const identity = runIdentity(run);
        const state = runState(run);
        const resumable = canResumeRun(run);
        const cancelable = canCancelRun(run);
        const handoffs = handoffRecords(run);
        const expanded = expandedRuns[identity] ?? runIsActive(run);
        return <details
          key={identity}
          data-testid="group-run"
          data-run-id={identity}
          data-run-engine={run.execution_engine ?? "unknown"}
          data-run-state={state}
          className="rounded border border-white/10 p-3"
          open={expanded}
          onToggle={(event) => {
            const next = event.currentTarget.open;
            setExpandedRuns((current) => current[identity] === next ? current : { ...current, [identity]: next });
          }}
        >
          <summary className="cursor-pointer">
            <span className="font-medium">Execução {identity.slice(0, 8)} · {runEngineLabel(run)}</span>
            <span data-testid="group-run-state" className="ml-2 text-zinc-300">{runStateLabel(state)}</span>
            {resumable && <button type="button" disabled={stopping === identity} onClick={(event) => { event.preventDefault(); void resume(identity); }} className="ml-3 rounded border border-emerald-300/40 px-2 py-0.5 text-xs text-emerald-200 hover:bg-emerald-400/10 disabled:opacity-40">{stopping === identity ? "A retomar…" : "Retomar"}</button>}
            {cancelable && <button type="button" disabled={stopping === identity} onClick={(event) => { event.preventDefault(); void stop(identity); }} className="ml-3 rounded border border-red-300/40 px-2 py-0.5 text-xs text-red-200 hover:bg-red-400/10 disabled:opacity-40">{stopping === identity ? "A parar…" : "Parar"}</button>}
          </summary>
          <p className="mt-2 whitespace-pre-wrap">{run.request}</p>
          {run.project_root || run.file_path ? <p className="break-all text-xs text-zinc-400">{run.project_root ?? ""}{run.project_root && run.file_path ? " / " : ""}{run.file_path ?? ""}</p> : null}
          {handoffs.length > 0 ? (
            <div className="mt-3 border-t border-white/10 pt-2">
              <p className="font-medium">Reatribuições e passagens</p>
              <ul className="mt-1 space-y-1 text-xs text-zinc-300">
                {handoffs.map((handoff) => (
                  <li key={handoff.id}>{handoff.from && handoff.to ? `${handoff.from} → ${handoff.to}` : recordKindLabel(handoff.kind)}{handoff.detail ? ` · ${handoff.detail}` : ""}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {run.tasks.map((task) => {
            const verified = taskVerification(run, task.id);
            const records = run.records.filter((record) => record.task_id === task.id);
            return <div key={task.id} className="mt-3 border-t border-white/10 pt-2">
              <p className="font-medium">{task.bot_name} · {taskStatusLabel(task.status)}</p>
              <p className="text-xs text-zinc-400">{task.provider} · {task.model}{task.attempt ? ` · tentativa ${task.attempt}` : ""}</p>
              {task.error && <p className="whitespace-pre-wrap text-red-300">{task.error}</p>}
              {task.result && <div className="mt-2 text-xs text-zinc-400"><p className="font-medium text-zinc-200">{verified ? "Resultado verificado" : "Resposta do bot (não verificada)"}</p><pre className="mt-1 whitespace-pre-wrap break-words text-zinc-100">{task.result}</pre></div>}
              <ActivityList records={records} />
            </div>;
          })}
          <VerificationBlock run={run} />
        </details>;
      })}
    </div>}
  </section>;
}
