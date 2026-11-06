"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";

type Task = { id: string; bot_name: string; provider: string; model: string; status: string; result: string | null; error: string | null };
type RecordItem = { id: string; task_id: string; kind: string; payload: Record<string, unknown> };
type Run = { id: string; status: string; request: string; project_root: string; file_path: string; tasks: Task[]; records: RecordItem[] };

export default function GroupRuns({ groupId }: { groupId: string }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [message, setMessage] = useState("");
  const [file, setFile] = useState("");
  const [project, setProject] = useState(".");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
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
  return <section className="border-b border-white/10 p-4 text-sm" aria-label="Execuções persistentes">
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="font-semibold text-violet-300">Execuções com leitura de ficheiro{open ? ` (${runs.length})` : ""}</button>
    {open && <div className="mt-3 max-h-96 space-y-4 overflow-y-auto">
      <p className="text-xs text-zinc-400">Os dois primeiros bots trabalham por ordem. A execução continua se fechares o browser.</p>
      <form onSubmit={(event) => void start(event)} className="grid gap-2">
        <label>Projeto registado <input aria-label="Caminho do projeto" value={project} onChange={(event) => setProject(event.target.value)} className="ml-2 rounded bg-zinc-800 p-2" /></label>
        <label>Ficheiro <input aria-label="Ficheiro a ler" required maxLength={1000} value={file} onChange={(event) => setFile(event.target.value)} className="ml-2 rounded bg-zinc-800 p-2" /></label>
        <label>Pedido <textarea aria-label="Pedido da execução" required maxLength={12000} value={message} onChange={(event) => setMessage(event.target.value)} className="ml-2 w-full rounded bg-zinc-800 p-2" /></label>
        <button disabled={sending} className="w-fit rounded bg-violet-500 px-3 py-2 disabled:opacity-40">{sending ? "A iniciar…" : "Iniciar execução"}</button>
      </form>
      {error && <p role="alert" className="text-red-300">{error}</p>}
      {runs.map((run) => <details key={run.id} className="rounded border border-white/10 p-3" open={run.status === "running" || run.status === "pending"}>
        <summary>Execução {run.id} · {run.status}</summary><p className="mt-2 whitespace-pre-wrap">{run.request}</p><p className="break-all text-xs text-zinc-400">{run.project_root} / {run.file_path}</p>
        {run.tasks.map((task) => <div key={task.id} className="mt-3 border-t border-white/10 pt-2"><p className="font-medium">{task.bot_name} · {task.status}</p><p className="text-xs text-zinc-400">{task.provider} · {task.model}</p>
          {task.error && <p className="whitespace-pre-wrap text-red-300">{task.error}</p>}
          {task.result && <pre className="mt-2 whitespace-pre-wrap break-words">{task.result}</pre>}
          {run.records.filter((record) => record.task_id === task.id).map((record) => <details key={record.id} className="mt-2"><summary>{record.kind} · {record.id}</summary><pre className="whitespace-pre-wrap break-all text-xs text-zinc-300">{JSON.stringify(record.payload, null, 2)}</pre></details>)}
        </div>)}
      </details>)}
    </div>}
  </section>;
}
