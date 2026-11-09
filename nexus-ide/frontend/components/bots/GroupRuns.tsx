"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";

type Task = { id: string; bot_name: string; provider: string; model: string; status: string; result: string | null; error: string | null };
type RecordItem = { id: string; task_id: string; kind: string; payload: Record<string, unknown> };
type Run = { id: string; status: string; request: string; project_root: string; file_path: string; tasks: Task[]; records: RecordItem[] };

const statusLabel: Record<string, string> = {
  pending: "Pendente",
  running: "Em curso",
  completed: "Concluída",
  failed: "Falhou",
  interrupted: "Interrompida",
  cancelled: "Cancelada",
  cancelling: "A cancelar",
  skipped: "Não correu",
};

export default function GroupRuns({ groupId }: { groupId: string }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [message, setMessage] = useState("");
  const [file, setFile] = useState("");
  const [project, setProject] = useState(".");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState("");
  const [open, setOpen] = useState(false);
  const load = useCallback(async () => {
    const response = await authenticatedFetch(apiUrl(`/api/bot-groups/${encodeURIComponent(groupId)}/runs`));
    if (!response.ok) throw new Error("Não foi possível carregar as execuções.");
    const data = await response.json() as { runs: Run[] };
    setRuns(data.runs);
  }, [groupId]);
  useEffect(() => {
    if (!open) return;
    setRuns([]); setError("");
    let alive = true;
    const refresh = () => { void load().catch(() => { if (alive) setError("Não foi possível carregar as execuções."); }); };
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
  return <section className="border-b border-white/10 p-4 text-sm" aria-label="Execuções persistentes">
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="font-semibold text-violet-300">Execuções de equipa com leitura de ficheiro{open ? ` (${runs.length})` : ""}</button>
    {open && <div className="mt-3 max-h-96 space-y-4 overflow-y-auto">
      <p className="text-xs text-zinc-400">Todos os bots do grupo trabalham por ordem sobre o ficheiro: o primeiro lê e analisa; os seguintes contribuem; o último revê criticamente. A execução continua se fechares o browser; podes pará-la a qualquer momento.</p>
      <form onSubmit={(event) => void start(event)} className="grid gap-2">
        <label>Projeto registado <input aria-label="Caminho do projeto" value={project} onChange={(event) => setProject(event.target.value)} className="ml-2 rounded bg-zinc-800 p-2" /></label>
        <label>Ficheiro <input aria-label="Ficheiro a ler" required maxLength={1000} value={file} onChange={(event) => setFile(event.target.value)} className="ml-2 rounded bg-zinc-800 p-2" /></label>
        <label>Pedido <textarea aria-label="Pedido da execução" required maxLength={12000} value={message} onChange={(event) => setMessage(event.target.value)} className="ml-2 w-full rounded bg-zinc-800 p-2" /></label>
        <button disabled={sending} className="w-fit rounded bg-violet-500 px-3 py-2 disabled:opacity-40">{sending ? "A iniciar…" : "Iniciar execução"}</button>
      </form>
      {error && <p role="alert" className="text-red-300">{error}</p>}
      {runs.map((run) => <details key={run.id} className="rounded border border-white/10 p-3" open={run.status === "running" || run.status === "pending"}>
        <summary className="cursor-pointer">Execução {run.id.slice(0, 8)} · {statusLabel[run.status] ?? run.status}
          {(run.status === "running" || run.status === "pending") && <button type="button" disabled={stopping === run.id} onClick={(event) => { event.preventDefault(); void stop(run.id); }} className="ml-3 rounded border border-red-300/40 px-2 py-0.5 text-xs text-red-200 hover:bg-red-400/10 disabled:opacity-40">{stopping === run.id ? "A parar…" : "Parar"}</button>}
        </summary><p className="mt-2 whitespace-pre-wrap">{run.request}</p><p className="break-all text-xs text-zinc-400">{run.project_root} / {run.file_path}</p>
        {run.tasks.map((task) => <div key={task.id} className="mt-3 border-t border-white/10 pt-2"><p className="font-medium">{task.bot_name} · {statusLabel[task.status] ?? task.status}</p><p className="text-xs text-zinc-400">{task.provider} · {task.model}</p>
          {task.error && <p className="whitespace-pre-wrap text-red-300">{task.error}</p>}
          {task.result && <pre className="mt-2 whitespace-pre-wrap break-words">{task.result}</pre>}
          {run.records.filter((record) => record.task_id === task.id).map((record) => <details key={record.id} className="mt-2"><summary>{record.kind} · {record.id}</summary><pre className="whitespace-pre-wrap break-all text-xs text-zinc-300">{JSON.stringify(record.payload, null, 2)}</pre></details>)}
        </div>)}
      </details>)}
    </div>}
  </section>;
}
