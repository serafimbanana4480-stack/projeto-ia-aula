"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertCircle,
  Ban,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  ListTodo,
  RefreshCw,
  XCircle,
} from "lucide-react";
import AppShell from "../../../components/layout/AppShell";
import { apiUrl } from "../../../lib/api";
import { authenticatedFetch } from "../../../lib/auth";

type TaskGroup = "active" | "queued" | "failed" | "completed" | "cancelled";
type TaskFilter = "all" | TaskGroup;
type LoadMode = "initial" | "manual" | "poll" | "more";
const TASK_PAGE_SIZE = 50;
const TASK_API_MAX_LIMIT = 500;

interface PlanStep {
  id: string;
  title: string;
  description: string | null;
  agent: string | null;
  status: string;
  error: string | null;
}

interface DashboardTask {
  id: string;
  title: string;
  agent: string;
  status: string;
  progress: number | null;
  created_at: string | null;
  kind: "workflow" | "plan";
  approval_status: string | null;
  completed_steps: number | null;
  total_steps: number | null;
  steps: PlanStep[];
  error: string | null;
}

interface TaskListResponse {
  active: DashboardTask[];
  queued: DashboardTask[];
  failed: DashboardTask[];
  completed: DashboardTask[];
  cancelled: DashboardTask[];
  warnings: string[];
  sources: {
    workflows: { available: boolean };
    plans: { available: boolean };
  };
  pagination: Record<TaskGroup, { offset: number; limit: number; total: number; has_more: boolean }>;
}

const GROUPS: Array<{
  id: TaskFilter;
  label: string;
  icon: typeof ListTodo;
}> = [
  { id: "all", label: "Todas", icon: ListTodo },
  { id: "active", label: "Ativas ou pausadas", icon: Activity },
  { id: "queued", label: "Na fila", icon: Clock3 },
  { id: "failed", label: "Falhadas", icon: XCircle },
  { id: "completed", label: "Concluídas", icon: CheckCircle2 },
  { id: "cancelled", label: "Canceladas", icon: Ban },
];

const EMPTY_PAGINATION: TaskListResponse["pagination"] = {
  active: { offset: 0, limit: TASK_PAGE_SIZE, total: 0, has_more: false },
  queued: { offset: 0, limit: TASK_PAGE_SIZE, total: 0, has_more: false },
  failed: { offset: 0, limit: TASK_PAGE_SIZE, total: 0, has_more: false },
  completed: { offset: 0, limit: TASK_PAGE_SIZE, total: 0, has_more: false },
  cancelled: { offset: 0, limit: TASK_PAGE_SIZE, total: 0, has_more: false },
};

function parseTaskGroup(value: unknown): DashboardTask[] {
  if (!Array.isArray(value)) return [];

  return value.flatMap((item): DashboardTask[] => {
    if (!item || typeof item !== "object") return [];
    const task = item as Record<string, unknown>;
    if (typeof task.id !== "string" || typeof task.title !== "string") return [];

    const progress = typeof task.progress === "number" && Number.isFinite(task.progress)
      ? Math.max(0, Math.min(100, task.progress))
      : null;

    const rawSteps = Array.isArray(task.steps) ? task.steps : [];
    const steps = rawSteps.flatMap((value, index): PlanStep[] => {
      if (!value || typeof value !== "object") return [];
      const step = value as Record<string, unknown>;
      if (typeof step.id !== "string" || typeof step.title !== "string") return [];
      return [{
        id: step.id || `step-${index + 1}`,
        title: step.title,
        description: typeof step.description === "string" ? step.description : null,
        agent: typeof step.agent === "string" && step.agent.trim() ? step.agent : null,
        status: typeof step.status === "string" && step.status.trim() ? step.status : "unknown",
        error: typeof step.error === "string" && step.error.trim() ? step.error : null,
      }];
    });

    const kind = task.kind === "plan" ? "plan" : "workflow";
    return [{
      id: task.id,
      title: task.title,
      agent: kind === "plan"
        ? ""
        : typeof task.agent === "string" && task.agent.trim() ? task.agent : "Agente não identificado",
      status: typeof task.status === "string" && task.status.trim() ? task.status : "unknown",
      progress,
      created_at: typeof task.created_at === "string" ? task.created_at : null,
      kind,
      approval_status: typeof task.approval_status === "string" ? task.approval_status : null,
      completed_steps: typeof task.completed_steps === "number" && Number.isFinite(task.completed_steps)
        ? task.completed_steps
        : null,
      total_steps: typeof task.total_steps === "number" && Number.isFinite(task.total_steps)
        ? task.total_steps
        : null,
      steps,
      error: typeof task.error === "string" && task.error.trim() ? task.error : null,
    }];
  });
}

function parseTaskList(payload: unknown): TaskListResponse {
  if (!payload || typeof payload !== "object") {
    throw new Error("O servidor devolveu uma resposta de tarefas inválida.");
  }
  const data = payload as Record<string, unknown>;
  if (!["active", "queued", "completed"].every((key) => Array.isArray(data[key]))) {
    throw new Error("A resposta do servidor não contém as três listas de tarefas esperadas.");
  }
  if (data.failed !== undefined && !Array.isArray(data.failed)) {
    throw new Error("A lista de tarefas falhadas tem um formato inválido.");
  }
  if (data.cancelled !== undefined && !Array.isArray(data.cancelled)) {
    throw new Error("A lista de tarefas canceladas tem um formato inválido.");
  }
  const sources = data.sources && typeof data.sources === "object"
    ? data.sources as Record<string, unknown>
    : {};
  const sourceAvailable = (key: "workflows" | "plans") => {
    const source = sources[key] && typeof sources[key] === "object"
      ? sources[key] as Record<string, unknown>
      : {};
    return source.available !== false;
  };
  const paginationData = data.pagination && typeof data.pagination === "object"
    ? data.pagination as Record<string, unknown>
    : {};
  const pagination = Object.fromEntries(([
    "active", "queued", "failed", "completed", "cancelled",
  ] as TaskGroup[]).map((group) => {
    const item = paginationData[group] && typeof paginationData[group] === "object"
      ? paginationData[group] as Record<string, unknown>
      : {};
    const total = typeof item.total === "number" && Number.isFinite(item.total)
      ? Math.max(0, item.total)
      : parseTaskGroup(data[group]).length;
    const offset = typeof item.offset === "number" && Number.isFinite(item.offset) ? Math.max(0, item.offset) : 0;
    const limit = typeof item.limit === "number" && Number.isFinite(item.limit) ? Math.max(1, item.limit) : TASK_PAGE_SIZE;
    return [group, { offset, limit, total, has_more: item.has_more === true }];
  })) as TaskListResponse["pagination"];
  return {
    active: parseTaskGroup(data.active),
    queued: parseTaskGroup(data.queued),
    failed: data.failed === undefined ? [] : parseTaskGroup(data.failed),
    completed: parseTaskGroup(data.completed),
    cancelled: data.cancelled === undefined ? [] : parseTaskGroup(data.cancelled),
    warnings: Array.isArray(data.warnings)
      ? data.warnings.filter((warning): warning is string => typeof warning === "string")
      : [],
    sources: {
      workflows: { available: sourceAvailable("workflows") },
      plans: { available: sourceAvailable("plans") },
    },
    pagination,
  };
}

function mergeTaskRows(primary: DashboardTask[], secondary: DashboardTask[]): DashboardTask[] {
  const seen = new Set<string>();
  return [...primary, ...secondary].filter((task) => {
    if (seen.has(task.id)) return false;
    seen.add(task.id);
    return true;
  });
}

function retainUnavailableSourceRows(
  fresh: DashboardTask[],
  previous: DashboardTask[],
  sources: TaskListResponse["sources"],
): DashboardTask[] {
  const freshIds = new Set(fresh.map((task) => task.id));
  const retained = previous.filter((task) => {
    const unavailable = task.kind === "plan" ? !sources.plans.available : !sources.workflows.available;
    return unavailable && !freshIds.has(task.id);
  });
  return [...fresh, ...retained];
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    running: "Em curso",
    active: "Em curso",
    pending: "Na fila",
    queued: "Na fila",
    completed: "Concluída",
    failed: "Falhou",
    paused: "Pausada",
    cancelled: "Cancelada",
    canceled: "Cancelada",
    awaiting_approval: "A aguardar aprovação",
    approved: "Aprovada · na fila",
    retrying: "A tentar novamente",
    blocked: "Bloqueada",
    unknown: "Estado desconhecido",
    ready: "Pronta",
    waiting_dependency: "À espera de dependência",
    skipped: "Ignorada",
  };
  return labels[status.toLowerCase()] ?? status.replaceAll("_", " ");
}

function taskDate(value: string | null): string {
  if (!value) return "Data não disponível";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Data não disponível";
  return new Intl.DateTimeFormat("pt-PT", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && /failed to (?:fetch|connect)|network error/i.test(error.message)) {
    return "Não foi possível ligar ao serviço de tarefas. Confirma se o backend está ativo e tenta novamente.";
  }
  if (error instanceof Error && error.message) return error.message;
  return "Não foi possível carregar as tarefas. Confirma a ligação e tenta novamente.";
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskListResponse>({
    active: [], queued: [], failed: [], completed: [], cancelled: [], warnings: [],
    sources: { workflows: { available: true }, plans: { available: true } },
    pagination: EMPTY_PAGINATION,
  });
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceWarnings, setSourceWarnings] = useState<string[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const requestInProgress = useRef(false);
  const activeRequestSignal = useRef<AbortSignal | null>(null);
  const pageOffset = useRef(0);
  const requestControllers = useRef(new Set<AbortController>());

  const loadTasks = useCallback(async (
    signal?: AbortSignal,
    mode: LoadMode = "initial",
  ) => {
    // React Strict Mode replays effects in development. If cleanup aborted the
    // first request, let the replay start immediately instead of waiting for its
    // finally block (or the 10-second poll) to release this guard.
    if (
      requestInProgress.current
      && activeRequestSignal.current
      && !activeRequestSignal.current.aborted
    ) return;
    const ownedController = signal ? null : new AbortController();
    const requestSignal = signal ?? ownedController!.signal;
    if (ownedController) requestControllers.current.add(ownedController);
    requestInProgress.current = true;
    activeRequestSignal.current = requestSignal;
    if (mode === "manual") setRefreshing(true);
    if (mode === "initial") setLoading(true);
    if (mode === "more") setLoadingMore(true);
    setUpdating(true);
    const offset = mode === "more" ? pageOffset.current + TASK_PAGE_SIZE : 0;
    const requestedCount = mode === "more"
      ? TASK_PAGE_SIZE
      : mode === "initial"
        ? TASK_PAGE_SIZE
        : pageOffset.current + TASK_PAGE_SIZE;

    try {
      const pages: TaskListResponse[] = [];
      let nextOffset = offset;
      let remaining = requestedCount;
      while (remaining > 0) {
        const limit = Math.min(remaining, TASK_API_MAX_LIMIT);
        const response = await authenticatedFetch(
          apiUrl(`/api/tasks/list?limit=${limit}&offset=${nextOffset}`),
          {
            method: "GET",
            cache: "no-store",
            signal: requestSignal,
          },
        );
        if (!response.ok) {
          let detail = `O servidor respondeu com o estado ${response.status}.`;
          try {
            const body = await response.json() as { detail?: unknown; message?: unknown };
            if (typeof body.detail === "string") detail = body.detail;
            else if (typeof body.message === "string") detail = body.message;
          } catch {
            // Keep the readable HTTP status when the response has no JSON body.
          }
          throw new Error(detail);
        }

        pages.push(parseTaskList(await response.json()));
        if (requestSignal.aborted) return;
        nextOffset += limit;
        remaining -= limit;
      }

      const lastPage = pages[pages.length - 1]!;
      const result: TaskListResponse = pages.length === 1
        ? lastPage
        : {
          ...lastPage,
          active: pages.flatMap((page) => page.active),
          queued: pages.flatMap((page) => page.queued),
          failed: pages.flatMap((page) => page.failed),
          completed: pages.flatMap((page) => page.completed),
          cancelled: pages.flatMap((page) => page.cancelled),
          warnings: [...new Set(pages.flatMap((page) => page.warnings))],
          sources: {
            workflows: { available: pages.every((page) => page.sources.workflows.available) },
            plans: { available: pages.every((page) => page.sources.plans.available) },
          },
        };
      if (requestSignal.aborted) return;
      if (mode === "more") pageOffset.current = offset;
      else if (mode === "initial") pageOffset.current = 0;
      setTasks((previous) => {
        const mergeGroup = (group: TaskGroup) => {
          const older = previous[group];
          // The API sorts newest-first, so the next offset belongs after the
          // rows already on screen. Preserve that order while deduplicating.
          const rows = mode === "more" ? mergeTaskRows(older, result[group]) : result[group];
          return retainUnavailableSourceRows(rows, previous[group], result.sources);
        };
        return {
          ...result,
          active: mergeGroup("active"),
          queued: mergeGroup("queued"),
          failed: mergeGroup("failed"),
          completed: mergeGroup("completed"),
          cancelled: mergeGroup("cancelled"),
        };
      });
      setSourceWarnings(result.warnings);
      setError(null);
      setLastUpdated(new Date());
    } catch (cause) {
      if (requestSignal.aborted) return;
      setError(errorMessage(cause));
    } finally {
      const ownsRequest = activeRequestSignal.current === requestSignal;
      if (ownsRequest) {
        requestInProgress.current = false;
        activeRequestSignal.current = null;
      }
      if (ownedController) requestControllers.current.delete(ownedController);
      if (!ownsRequest || requestSignal.aborted) return;
      setLoading(false);
      setUpdating(false);
      if (mode === "manual") setRefreshing(false);
      if (mode === "more") setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const controllers = requestControllers.current;
    void loadTasks(controller.signal, "initial");
    const timer = window.setInterval(() => {
      void loadTasks(controller.signal, "poll");
    }, 10_000);
    return () => {
      controller.abort();
      controllers.forEach((requestController) => requestController.abort());
      window.clearInterval(timer);
    };
  }, [loadTasks]);

  const counts = useMemo(() => {
    const count = (group: TaskGroup) => Math.max(tasks.pagination[group].total, tasks[group].length);
    return {
      all: count("active") + count("queued") + count("failed") + count("completed") + count("cancelled"),
      active: count("active"),
      queued: count("queued"),
      failed: count("failed"),
      completed: count("completed"),
      cancelled: count("cancelled"),
    };
  }, [tasks]);

  const visibleGroups = useMemo(() => {
    const groupOrder: TaskGroup[] = filter === "all"
      ? ["active", "queued", "failed", "completed", "cancelled"]
      : [filter];
    return groupOrder.map((group) => ({
      id: group,
      tasks: tasks[group],
      meta: GROUPS.find((item) => item.id === group)!,
    }));
  }, [filter, tasks]);

  const updatedTime = lastUpdated
    ? new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" }).format(lastUpdated)
    : null;

  return (
    <AppShell title="Tarefas" noPadding>
      <div className="min-h-full bg-[radial-gradient(ellipse_at_top_left,rgba(124,106,251,0.10),transparent_44%)] px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <div className="mx-auto max-w-7xl">
          <motion.header
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-7 flex flex-col gap-5 sm:mb-8 sm:flex-row sm:items-end sm:justify-between"
          >
            <div>
              <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-nexus-accent">
                <span className="h-1.5 w-1.5 rounded-full bg-nexus-accent shadow-[0_0_12px_rgba(124,106,251,0.8)]" />
                Centro de execução
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-nexus-text sm:text-4xl">
                Tarefas <span className="bg-gradient-to-r from-cyan-300 to-violet-300 bg-clip-text text-transparent">do NEXUS</span>
              </h1>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-nexus-muted">
                Acompanha o trabalho ativo ou pausado, na fila, concluído ou falhado nesta execução.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <p className="text-xs text-nexus-muted" aria-live="polite">
                {updatedTime ? `Atualizado às ${updatedTime}` : "Estado das tarefas"}
              </p>
              <button
                type="button"
                onClick={() => void loadTasks(undefined, "manual")}
                disabled={refreshing || loading || updating}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-nexus-border bg-nexus-card/80 px-4 text-sm font-medium text-nexus-text shadow-rim transition hover:border-nexus-accent/50 hover:bg-nexus-card disabled:cursor-wait disabled:opacity-60"
                aria-label="Atualizar tarefas"
              >
                <RefreshCw className={`h-4 w-4 text-nexus-accent ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />
                Atualizar
              </button>
            </div>
          </motion.header>

          <section aria-label="Resumo das tarefas" className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <SummaryCard
              label="Ativas ou pausadas"
              value={counts.active}
              caption="Em curso, a tentar novamente ou em pausa"
              icon={Activity}
              tone="cyan"
              loading={loading}
            />
            <SummaryCard
              label="Na fila"
              value={counts.queued}
              caption="À espera de execução"
              icon={Clock3}
              tone="violet"
              loading={loading}
            />
            <SummaryCard
              label="Falhadas"
              value={counts.failed}
              caption="Precisam de atenção"
              icon={XCircle}
              tone="red"
              loading={loading}
            />
            <SummaryCard
              label="Concluídas"
              value={counts.completed}
              caption="Registos recentes"
              icon={CheckCircle2}
              tone="green"
              loading={loading}
            />
            <SummaryCard
              label="Canceladas"
              value={counts.cancelled}
              caption="Paradas antes de concluir"
              icon={Ban}
              tone="amber"
              loading={loading}
            />
          </section>

          {sourceWarnings.length > 0 && (
            <div className="mb-4 rounded-xl border border-amber-300/25 bg-amber-300/[0.07] px-4 py-3 text-xs text-amber-100/90" role="status">
              <p className="font-medium">Algumas fontes estão indisponíveis; os dados que chegaram continuam visíveis.</p>
              <ul className="mt-1 list-inside list-disc text-amber-100/70">
                {sourceWarnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          )}

          <section className="overflow-hidden rounded-2xl border border-nexus-border/80 bg-nexus-panel/75 shadow-[0_16px_50px_rgba(0,0,0,0.18)] backdrop-blur-sm" aria-label="Lista de tarefas">
            <div className="flex flex-col gap-4 border-b border-nexus-border/70 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
              <div>
                <h2 className="text-base font-semibold text-nexus-text">Atividade recente</h2>
                <p className="mt-1 text-xs text-nexus-muted">
                  {loading ? "A sincronizar com o sistema…" : `${counts.all} ${counts.all === 1 ? "tarefa" : "tarefas"} no total`}
                </p>
              </div>
              <div className="flex max-w-full gap-1 overflow-x-auto rounded-xl border border-nexus-border/70 bg-nexus-bg/55 p-1" role="group" aria-label="Filtrar tarefas">
                {GROUPS.map(({ id, label, icon: Icon }) => {
                  const selected = filter === id;
                  return (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => setFilter(id)}
                      className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition ${selected
                        ? "bg-nexus-accent/20 text-nexus-text shadow-sm ring-1 ring-inset ring-nexus-accent/30"
                        : "text-nexus-muted hover:bg-nexus-card hover:text-nexus-text"
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                      {label}
                      <span className={`ml-0.5 tabular-nums ${selected ? "text-nexus-text" : "text-nexus-muted"}`}>
                      {loading ? "–" : counts[id]}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {error && (
              <div className="mx-4 mt-4 flex items-start gap-3 rounded-xl border border-rose-400/25 bg-rose-400/[0.07] p-4 sm:mx-5" role="alert">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-rose-200">Não foi possível atualizar as tarefas</p>
                  <p className="mt-1 break-words text-xs leading-relaxed text-rose-100/70">{error}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void loadTasks(undefined, counts.all > 0 ? "manual" : "initial")}
                  className="shrink-0 rounded-lg px-2 py-1 text-xs font-semibold text-rose-200 transition hover:bg-rose-300/10"
                >
                  Tentar de novo
                </button>
              </div>
            )}

            {loading ? (
              <TaskListSkeleton />
            ) : counts.all === 0 ? (
              <div className="px-5 py-16 text-center sm:py-20">
                <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-nexus-border bg-nexus-bg/70 text-nexus-accent shadow-inner">
                  {error
                    ? <AlertCircle className="h-6 w-6" aria-hidden="true" />
                    : <ListTodo className="h-6 w-6" aria-hidden="true" />}
                </div>
                <h3 className="text-base font-semibold text-nexus-text">
                  {error ? "A lista ainda não está disponível" : "Ainda não há tarefas"}
                </h3>
                <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-nexus-muted">
                  {error
                    ? "Tenta atualizar quando o serviço estiver acessível."
                    : "Quando houver trabalho em curso, na fila, concluído ou falhado, vais encontrá-lo aqui."}
                </p>
                <button
                  type="button"
                  onClick={() => void loadTasks(undefined, "manual")}
                  className="mt-5 inline-flex min-h-10 items-center gap-2 rounded-xl border border-nexus-border bg-nexus-card/80 px-4 text-sm font-medium text-nexus-text transition hover:border-nexus-accent/50"
                >
                  <RefreshCw className="h-4 w-4 text-nexus-accent" aria-hidden="true" />
                  Atualizar lista
                </button>
              </div>
            ) : (
              <div className="divide-y divide-nexus-border/50">
                {visibleGroups.map(({ id, tasks: groupTasks, meta }) => (
                  <section key={id} aria-labelledby={`task-group-${id}`}>
                    {filter === "all" && (
                      <div className="flex items-center justify-between px-4 pb-2 pt-5 sm:px-5">
                        <h3 id={`task-group-${id}`} className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-nexus-muted">
                          <meta.icon className="h-3.5 w-3.5 text-nexus-accent" aria-hidden="true" />
                          {meta.label}
                        </h3>
                        <span className="rounded-md border border-nexus-border/70 bg-nexus-bg/50 px-2 py-0.5 text-[10px] tabular-nums text-nexus-muted">
                          {Math.max(tasks.pagination[id].total, groupTasks.length)}
                        </span>
                      </div>
                    )}

                    {groupTasks.length === 0 ? (
                      filter !== "all" && (
                      <EmptyGroup label={id === "failed" ? "com falhas" : meta.label.toLowerCase()} />
                      )
                    ) : (
                      <div className="space-y-2 px-3 pb-4 sm:px-4">
                        {groupTasks.map((task, index) => (
                          <TaskRow key={task.id} task={task} group={id} index={index} />
                        ))}
                      </div>
                    )}
                  </section>
                ))}
                {visibleGroups.some(({ id }) => tasks.pagination[id].has_more) && (
                  <div className="flex justify-center px-4 py-4">
                    <button
                      type="button"
                      disabled={loadingMore || updating}
                      onClick={() => void loadTasks(undefined, "more")}
                      className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-nexus-border bg-nexus-card/80 px-4 text-sm font-medium text-nexus-text transition hover:border-nexus-accent/50 disabled:cursor-wait disabled:opacity-60"
                      aria-label="Carregar mais tarefas"
                    >
                      <RefreshCw className={`h-4 w-4 text-nexus-accent ${loadingMore ? "animate-spin" : ""}`} aria-hidden="true" />
                      {loadingMore ? "A carregar…" : "Carregar tarefas mais antigas"}
                    </button>
                  </div>
                )}
              </div>
            )}
          </section>
      <p className="mt-4 px-1 text-[11px] leading-relaxed text-nexus-muted/75">
            A lista atualiza automaticamente a cada 10 segundos. Também podes usar <span className="font-medium text-nexus-muted">Atualizar</span> para verificar já.
          </p>
        </div>
      </div>
    </AppShell>
  );
}

function SummaryCard({
  label,
  value,
  caption,
  icon: Icon,
  tone,
  loading,
}: {
  label: string;
  value: number;
  caption: string;
  icon: typeof Activity;
  tone: "cyan" | "violet" | "green" | "red" | "amber";
  loading: boolean;
}) {
  const tones = {
    cyan: "text-cyan-300 bg-cyan-300/10 ring-cyan-300/20",
    violet: "text-violet-300 bg-violet-300/10 ring-violet-300/20",
    green: "text-emerald-300 bg-emerald-300/10 ring-emerald-300/20",
    red: "text-rose-300 bg-rose-300/10 ring-rose-300/20",
    amber: "text-amber-300 bg-amber-300/10 ring-amber-300/20",
  };

  return (
    <div className="group relative overflow-hidden rounded-2xl border border-nexus-border/80 bg-nexus-panel/70 p-4 shadow-rim transition hover:-translate-y-0.5 hover:border-nexus-accent/30 sm:p-5">
      <div className="pointer-events-none absolute -right-8 -top-10 h-28 w-28 rounded-full bg-nexus-accent/[0.06] blur-2xl transition group-hover:bg-nexus-accent/[0.1]" />
      <div className="relative flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium text-nexus-muted">{label}</p>
          {loading ? (
            <div className="nx-shimmer mt-2 h-9 w-12 rounded-md" aria-label="A carregar" />
          ) : (
            <p className="mt-1 text-3xl font-semibold tracking-tight text-nexus-text tabular-nums" aria-live="polite">{value}</p>
          )}
          <p className="mt-1.5 text-[11px] text-nexus-muted/80">{caption}</p>
        </div>
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ring-1 ${tones[tone]}`}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
      </div>
    </div>
  );
}

function TaskRow({ task, group, index }: { task: DashboardTask; group: TaskGroup; index: number }) {
  const [showPlanSteps, setShowPlanSteps] = useState(false);
  const isPaused = task.status.toLowerCase() === "paused";
  const isActivelyRunning = ["running", "active", "retrying"].includes(task.status.toLowerCase());
  const isCompleted = group === "completed";
  const isFailed = group === "failed";
  const isCancelled = group === "cancelled";
  const hasProgress = !isCompleted && !isCancelled && task.progress !== null && task.progress > 0;
  const statusTone = isPaused
    ? "border-amber-300/20 bg-amber-300/[0.08] text-amber-200"
    : isCompleted
      ? "border-emerald-300/20 bg-emerald-300/[0.08] text-emerald-200"
      : isFailed
        ? "border-rose-300/20 bg-rose-300/[0.08] text-rose-200"
        : isCancelled
          ? "border-slate-300/20 bg-slate-300/[0.06] text-slate-300"
          : group === "active"
            ? "border-cyan-300/20 bg-cyan-300/[0.08] text-cyan-200"
            : "border-violet-300/20 bg-violet-300/[0.08] text-violet-200";

  return (
    <motion.article
      initial={{ opacity: 0, y: 7 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.035, 0.21) }}
      className="rounded-xl border border-nexus-border/65 bg-nexus-bg/40 px-3.5 py-3 transition hover:border-nexus-accent/30 hover:bg-nexus-bg/70 sm:px-4"
    >
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border ${statusTone}`}>
          {isCompleted
            ? <Check className="h-4 w-4" aria-hidden="true" />
            : isFailed
              ? <XCircle className="h-4 w-4" aria-hidden="true" />
              : isCancelled
                ? <Ban className="h-4 w-4" aria-hidden="true" />
              : group === "active" && !isPaused
                ? <Activity className="h-4 w-4" aria-hidden="true" />
                : <Clock3 className="h-4 w-4" aria-hidden="true" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <h4 className="break-words text-sm font-medium leading-snug text-nexus-text">{task.title}</h4>
            <span className={`inline-flex w-fit shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold ${statusTone}`}>
              {isActivelyRunning && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
              {statusLabel(task.status)}
            </span>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-nexus-muted">
            {task.kind === "workflow" && task.agent && (
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <Bot className="h-3.5 w-3.5 shrink-0 text-nexus-accent/90" aria-hidden="true" />
                <span className="truncate">{task.agent}</span>
              </span>
            )}
            <span className="inline-flex items-center gap-1.5">
              <Clock3 className="h-3 w-3 shrink-0" aria-hidden="true" />
              {taskDate(task.created_at)}
            </span>
            {task.kind === "plan" && task.completed_steps !== null && task.total_steps !== null && (
              <span className="tabular-nums">
                {task.completed_steps} de {task.total_steps} etapas concluídas
              </span>
            )}
            {task.kind === "plan" && task.approval_status === "approved" && (
              <span className="text-emerald-300">Plano aprovado</span>
            )}
            {hasProgress && (
              <span className="ml-auto tabular-nums text-nexus-muted">
                {Math.round(task.progress!)}% reportado
              </span>
            )}
          </div>

          {hasProgress ? (
            <div
              className="mt-3 h-1.5 overflow-hidden rounded-full bg-nexus-border/60"
              role="progressbar"
              aria-label={`Progresso reportado: ${Math.round(task.progress!)}%`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(task.progress!)}
            >
              <div
                className={`h-full rounded-full transition-[width] duration-500 ${group === "active" ? "bg-gradient-to-r from-cyan-400 to-nexus-accent" : group === "failed" ? "bg-rose-400" : "bg-violet-400"}`}
                style={{ width: `${task.progress}%` }}
              />
            </div>
          ) : null}
          {task.kind === "plan" && task.approval_status === "awaiting_approval" && (
            <p className="mt-2 text-[11px] text-amber-200/90">
              Revê este plano e aprova-o no chat antes da execução.
            </p>
          )}
          {task.error && (
            <p className="mt-2 break-words text-xs text-rose-200" role="status">{task.error}</p>
          )}
          {task.kind === "plan" && task.steps.length > 0 && (
            <div className="mt-3 border-t border-nexus-border/50 pt-2">
              <button
                type="button"
                aria-expanded={showPlanSteps}
                aria-controls={`plan-steps-${task.id}`}
                onClick={() => setShowPlanSteps((visible) => !visible)}
                className="inline-flex min-h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-nexus-accent transition hover:bg-nexus-accent/10"
              >
                <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showPlanSteps ? "rotate-180" : ""}`} aria-hidden="true" />
                {showPlanSteps ? "Esconder etapas" : `Ver ${task.steps.length} etapas do plano`}
              </button>
              {showPlanSteps && (
                <ol id={`plan-steps-${task.id}`} className="mt-2 space-y-2 rounded-lg bg-nexus-bg/55 p-3">
                  {task.steps.map((step, stepIndex) => (
                    <li key={step.id} className="flex gap-2 text-xs">
                      <span className="mt-0.5 w-5 shrink-0 text-right tabular-nums text-nexus-muted">{stepIndex + 1}.</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <span className="font-medium text-nexus-text">{step.title}</span>
                          <span className="rounded-full border border-nexus-border/70 px-2 py-0.5 text-[10px] text-nexus-muted">
                            {statusLabel(step.status)}
                          </span>
                          {step.agent && <span className="text-[10px] text-nexus-accent">{step.agent}</span>}
                        </div>
                        {step.description && <p className="mt-1 text-[11px] text-nexus-muted">{step.description}</p>}
                        {step.error && <p className="mt-1 text-[11px] text-rose-300">{step.error}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      </div>
    </motion.article>
  );
}

function EmptyGroup({ label }: { label: string }) {
  return (
    <div className="px-5 py-12 text-center">
      <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl border border-nexus-border/70 bg-nexus-bg/60 text-nexus-muted">
        <ListTodo className="h-5 w-5" aria-hidden="true" />
      </div>
      <p className="mt-3 text-sm font-medium text-nexus-text">Sem tarefas {label.toLowerCase()}</p>
      <p className="mt-1 text-xs text-nexus-muted">
        A lista verifica automaticamente a cada 10 segundos; também podes atualizar já.
      </p>
    </div>
  );
}

function TaskListSkeleton() {
  return (
    <div className="space-y-2 px-3 py-4 sm:px-4" aria-label="A carregar tarefas" aria-busy="true">
      {["task-skeleton-1", "task-skeleton-2", "task-skeleton-3"].map((key) => (
        <div key={key} className="flex items-start gap-3 rounded-xl border border-nexus-border/60 bg-nexus-bg/35 p-4">
          <div className="nx-shimmer h-9 w-9 shrink-0 rounded-xl" />
          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="nx-shimmer h-4 w-2/3 rounded" />
              <div className="nx-shimmer h-6 w-20 rounded-full" />
            </div>
            <div className="nx-shimmer h-3 w-44 max-w-full rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}
