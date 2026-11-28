"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ChevronDown, FileText, Play } from "lucide-react";
import { BOT_INPUT } from "./botsUi";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";

type Task = { id: string; bot_name: string; provider: string; model: string; status: string; result: string | null; error: string | null };
type RecordItem = { id: string; task_id: string; kind: string; payload: Record<string, unknown> };
type Run = { id: string; status: string; request: string; project_root: string; file_path: string; tasks: Task[]; records: RecordItem[]; can_resume?: boolean };

const statusLabels: Record<string, string> = {
  pending: "Em fila", running: "Em curso", completed: "Concluída",
  interrupted: "Interrompida", failed: "Falhou", skipped: "Ignorada",
};

export default function GroupRuns({ groupId }: { groupId: string }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [message, setMessage] = useState("");
  const [file, setFile] = useState("");
  const [project, setProject] = useState(".");
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [action, setAction] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<Run | null>(null);
  const [detailError, setDetailError] = useState("");
  const actionPending = useRef(false);
  const path = `/api/bot-groups/${encodeURIComponent(groupId)}/runs`;
  const expandedRun = runs.find((run) => run.id === expanded);
  const detailVersion = expandedRun?.tasks.map((task) => task.status).join(",") ?? "";

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let timer: number | undefined;
    async function refresh() {
      try {
        const response = await authenticatedFetch(apiUrl(path + "?include_evidence=false"), { signal: controller.signal });
        if (!response.ok) throw new Error("Não foi possível carregar as execuções.");
        const data = await response.json() as { runs: Run[] };
        if (!controller.signal.aborted) {
          setRuns(data.runs);
          setListError("");
        }
      } catch {
        if (!controller.signal.aborted) setListError("Não foi possível carregar as execuções.");
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(() => void refresh(), 3000);
      }
    }
    void refresh();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [path, open, revision]);

  useEffect(() => {
    if (!open || !expanded) return;
    const controller = new AbortController();
    setDetailError("");
    async function loadDetail(id: string) {
      try {
        const response = await authenticatedFetch(apiUrl(path + "/" + encodeURIComponent(id)), { signal: controller.signal });
        if (!response.ok) throw new Error("Não foi possível carregar os detalhes.");
        const data = await response.json() as Run;
        if (!controller.signal.aborted) setDetail(data);
      } catch {
        if (!controller.signal.aborted) setDetailError("Não foi possível carregar os detalhes.");
      }
    }
    void loadDetail(expanded);
    return () => controller.abort();
  }, [path, open, expanded, detailVersion, revision]);

  async function start(event: FormEvent) {
    event.preventDefault();
    await submit(null);
  }

  async function submit(runId: string | null, operation: "resume" | "interrupt" = "resume") {
    if (actionPending.current || (!runId && (!message.trim() || !file.trim() || !project.trim()))) return;
    actionPending.current = true;
    setAction(runId ?? "new");
    setError("");
    try {
      const response = await authenticatedFetch(apiUrl(runId ? path + "/" + encodeURIComponent(runId) + "/" + operation : path), {
        method: "POST",
        ...(runId ? {} : {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: message.trim(), file_path: file.trim(), project_path: project.trim() }),
        }),
      });
      if (!response.ok) {
        const body = await response.json() as { detail?: string };
        throw new Error(body.detail || "Não foi possível lançar a execução.");
      }
      if (!runId) setMessage("");
      setRevision((value) => value + 1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível lançar a execução."); }
    finally { actionPending.current = false; setAction(null); }
  }
  return <section className="nx-bot-panel shrink-0 border-b px-4 py-2 text-sm sm:px-6" aria-label="Execuções persistentes">
    <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} className="nx-bot-action w-full justify-start border-transparent">
      <FileText size={16} className="shrink-0 text-[var(--nx-accent-bright)]" />
      <span className="flex-1 text-left">Execuções com leitura de ficheiro{open ? " (" + runs.length + ")" : ""}</span>
      <ChevronDown size={16} aria-hidden="true" className={open ? "rotate-180" : ""} />
    </button>
    {open && <div className="mx-auto max-h-[min(44dvh,26rem)] max-w-3xl space-y-4 overflow-y-auto px-1 pb-3 pt-2">
      <p className="text-xs leading-5 text-[var(--nx-text-dim)]">O primeiro bot analisa o ficheiro e os restantes fazem revisões em paralelo.</p>
      <form onSubmit={(event) => void start(event)} className="nx-bot-note grid gap-3 rounded-xl border p-3 sm:grid-cols-2">
        <label className="grid gap-1.5 text-xs font-medium">Projeto registado
          <input aria-label="Caminho do projeto" value={project} required onChange={(event) => setProject(event.target.value)} className={BOT_INPUT} />
        </label>
        <label className="grid gap-1.5 text-xs font-medium">Ficheiro a ler
          <input aria-label="Ficheiro a ler" required maxLength={1000} value={file} onChange={(event) => setFile(event.target.value)} className={BOT_INPUT} />
        </label>
        <label className="grid gap-1.5 text-xs font-medium sm:col-span-2">Pedido da execução
          <textarea aria-label="Pedido da execução" required maxLength={12000} rows={2} value={message} onChange={(event) => setMessage(event.target.value)} className={BOT_INPUT + " resize-y"} />
        </label>
        <button disabled={action !== null || !message.trim() || !file.trim() || !project.trim()} className="nx-bot-action nx-bot-primary w-fit sm:col-span-2">
          <Play size={14} /> {action === "new" ? "A iniciar…" : "Iniciar execução"}
        </button>
      </form>
      {(error || listError) && <p role="alert" className="nx-bot-error rounded-xl border p-3">{error || listError}</p>}
      {runs.map((run) => {
        const selected = expanded === run.id;
        const loaded = selected && detail?.id === run.id ? detail : null;
        const canInterrupt = run.status === "pending" || run.status === "running";
        return <article key={run.id} className="nx-bot-card rounded-xl border p-3">
          <button type="button" aria-expanded={selected} onClick={() => setExpanded(selected ? null : run.id)}>
            Execução {run.id} · {statusLabels[run.status] || run.status}
          </button>
          {run.can_resume && <button type="button" disabled={action !== null} onClick={() => void submit(run.id)} className="ml-3 text-[var(--nx-accent-bright)] underline disabled:opacity-40">
            {action === run.id ? "A retomar…" : "Retomar execução"}
          </button>}
          {canInterrupt && <button type="button" disabled={action !== null} onClick={() => void submit(run.id, "interrupt")} className="ml-3 text-[var(--nx-text)] underline disabled:opacity-40">
            {action === run.id ? "A interromper…" : "Interromper execução"}
          </button>}
          {selected && <>
            <p className="mt-2 whitespace-pre-wrap">{run.request}</p>
            <p className="break-all text-xs text-[var(--nx-text-dim)]">{run.project_root} / {run.file_path}</p>
            {detailError && <p role="alert" className="text-red-300">{detailError}</p>}
            {run.tasks.map((task) => {
              const result = loaded?.tasks.find((item) => item.id === task.id)?.result;
              return <div key={task.id} className="mt-3 border-t border-[var(--nx-line)] pt-2">
                <p className="font-medium">{task.bot_name} · {statusLabels[task.status] || task.status}</p>
                <p className="text-xs text-[var(--nx-text-dim)]">{task.provider} · {task.model}</p>
                {task.error && <p className="whitespace-pre-wrap text-red-300">{task.error}</p>}
                {task.status === "completed" && result && <pre className="mt-2 whitespace-pre-wrap break-words">{result}</pre>}
                {loaded?.records.filter((record) => record.task_id === task.id).map((record) => <details key={record.id} className="mt-2">
                  <summary>{record.kind} · {record.id}</summary>
                  <pre className="whitespace-pre-wrap break-all text-xs text-[var(--nx-text)]">{JSON.stringify(record.payload, null, 2)}</pre>
                </details>)}
              </div>;
            })}
          </>}
        </article>;
      })}
    </div>}
  </section>;
}
