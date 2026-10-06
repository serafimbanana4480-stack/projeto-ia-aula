"use client";

import { memo, useEffect, useId, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Bot,
  Check,
  ChevronDown,
  CircleDashed,
  ListChecks,
  Loader2,
  Pause,
  ShieldCheck,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import type { ActivityItem } from "../../lib/types";
import { formatRunClock, groupAdjacentFileReads } from "../../lib/chatPresentation";
import { isFailingActivityStatus } from "../../lib/foldRun";

const ACTIVITY_VIRTUAL_THRESHOLD = 80;
const ACTIVITY_ROW_HEIGHT = 48;
const ACTIVITY_VIEWPORT_HEIGHT = 360;
const ACTIVITY_OVERSCAN = 6;
const FILE_READ_ROW_HEIGHT = 24;
const FILE_READ_VIEWPORT_HEIGHT = 192;
const FILE_READ_OVERSCAN = 4;

function statusIcon(status: ActivityItem["status"]) {
  if (status === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-300" />;
  if (status === "error") return <XCircle className="h-3.5 w-3.5 text-rose-400" />;
  if (status === "success") return <Check className="h-3.5 w-3.5 text-emerald-400" />;
  if (status === "warning") return <TriangleAlert className="h-3.5 w-3.5 text-amber-300" />;
  if (status === "paused") return <Pause className="h-3.5 w-3.5 text-amber-300" />;
  if (status === "cancelled") return <CircleDashed className="h-3.5 w-3.5 text-nexus-muted" />;
  return <CircleDashed className="h-3.5 w-3.5 text-nexus-muted" />;
}

function kindIcon(kind: ActivityItem["kind"]) {
  if (kind === "agent") return Bot;
  if (kind === "plan") return ListChecks;
  if (kind === "verification") return ShieldCheck;
  return CircleDashed;
}

function VirtualFileReadList({ items }: { items: ActivityItem[] }) {
  const [scrollTop, setScrollTop] = useState(0);
  const first = Math.max(0, Math.floor(scrollTop / FILE_READ_ROW_HEIGHT) - FILE_READ_OVERSCAN);
  const last = Math.min(
    items.length,
    Math.ceil((scrollTop + FILE_READ_VIEWPORT_HEIGHT) / FILE_READ_ROW_HEIGHT) + FILE_READ_OVERSCAN,
  );

  return (
    <div
      data-testid="file-read-viewport"
      className="max-h-48 overflow-y-auto border-l border-nexus-border/50 pl-2"
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
    >
      <ol className="relative list-none" style={{ height: items.length * FILE_READ_ROW_HEIGHT }}>
        {items.slice(first, last).map((read, offset) => {
          const index = first + offset;
          return (
            <li
              key={read.id}
              data-testid="file-read-row"
              aria-posinset={index + 1}
              aria-setsize={items.length}
              className="absolute left-0 right-0 truncate py-0.5 text-[10px] text-nexus-muted"
              style={{ top: index * FILE_READ_ROW_HEIGHT, height: FILE_READ_ROW_HEIGHT }}
              title={read.detail || read.title}
            >
              {read.detail || read.title}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function GroupedFileReads({ group }: { group: { items: ActivityItem[]; fileCount?: number } }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      open={open}
      className="min-w-0 flex-1"
    >
      <summary
        onClick={(event) => {
          event.preventDefault();
          setOpen((value) => !value);
        }}
        className="flex cursor-pointer flex-wrap items-center gap-1.5"
      >
        <span className="text-[11px] font-medium text-nexus-text/90">
          Leu {group.fileCount} ficheiro{group.fileCount === 1 ? "" : "s"}
        </span>
        <span className="text-[9px] text-nexus-muted">
          {group.items.length} leituras
        </span>
      </summary>
      {open && <VirtualFileReadList items={group.items} />}
    </details>
  );
}

function ExecutionActivity({
  items,
  isStreaming = false,
  hasErrors = false,
}: {
  items: ActivityItem[];
  isStreaming?: boolean;
  hasErrors?: boolean;
}) {
  const [open, setOpen] = useState(isStreaming);
  const activityBodyId = `execution-activity-${useId().replace(/:/g, "")}`;
  const [scrollTop, setScrollTop] = useState(0);
  const displayGroups = useMemo(() => groupAdjacentFileReads(items), [items]);
  const virtualized = displayGroups.length > ACTIVITY_VIRTUAL_THRESHOLD;
  const firstVisible = virtualized
    ? Math.max(0, Math.floor(scrollTop / ACTIVITY_ROW_HEIGHT) - ACTIVITY_OVERSCAN)
    : 0;
  const lastVisible = virtualized
    ? Math.min(
        displayGroups.length,
        Math.ceil((scrollTop + ACTIVITY_VIEWPORT_HEIGHT) / ACTIVITY_ROW_HEIGHT) + ACTIVITY_OVERSCAN,
      )
    : displayGroups.length;
  const visibleGroups = displayGroups.slice(firstVisible, lastVisible);

  useEffect(() => {
    if (isStreaming) setOpen(true);
  }, [isStreaming]);

  // "Trabalho concluído" is a completion CLAIM, so it needs positive evidence:
  // an activity the run actually reported as successful. No failure and no
  // success means the run never reported its final state — which is what an
  // interrupted run looks like from here — and claiming completion there is the
  // same lie as a green check, just in words.
  const summary = useMemo(() => {
    const agents = new Set(items.map((item) => item.agent).filter(Boolean));
    // A `warning` activity is a problem too: `sessionRecovery` injects one
    // ("Execução interrompida", `status:"warning"`) for a run the backend
    // recorded as interrupted, and counting only `error` left "Trabalho
    // concluído" + a green check sitting on top of that very warning.
    const failures = items.filter((item) => isFailingActivityStatus(item.status)).length;
    const succeeded = items.filter((item) => item.status === "success").length;
    const cancelled = items.some((item) => item.status === "cancelled");
    const paused = items.some((item) => item.status === "paused");
    if (isStreaming) return "A executar";
    if (failures) return `${failures} problema${failures === 1 ? "" : "s"} durante a execução`;
    if (paused) return "Execução em pausa";
    if (cancelled) return "Execução cancelada";
    if (hasErrors) return "Execução concluída com problemas";
    if (succeeded > 0 && agents.size > 1) return `${agents.size} agentes colaboraram`;
    if (succeeded > 0) return "Trabalho concluído";
    return "Execução sem estado final confirmado";
  }, [hasErrors, isStreaming, items]);

  // Editorial derived state: Activity → Group → Detail. Kept out of `summary`
  // so the accessible header strings the tests assert on never change.
  const editorial = useMemo(() => {
    const agentNames = Array.from(new Set(items.map((item) => item.agent).filter(Boolean) as string[]));
    const runningAgents = items.filter((item) => item.kind === "agent" && item.status === "running");
    const verifications = items.filter((item) => item.kind === "verification");
    const passed = verifications.filter((item) => item.status === "success").length;
    const failed = verifications.filter((item) => item.status === "error").length;
    const stamps = items
      .map((item) => Date.parse(item.timestamp ?? ""))
      .filter((value) => Number.isFinite(value));
    const t0 = stamps.length > 0 ? Math.min(...stamps) : undefined;
    return { agentNames, runningAgents, verifications, passed, failed, t0, parallel: runningAgents.length > 1 || agentNames.length > 1 };
  }, [items]);

  if (items.length === 0 && !hasErrors) return null;

  // Same decision the summary made, so the icon can never contradict the words
  // next to it: rose while anything failed, dashed when the run was cancelled,
  // green only on reported successes, neutral when the run never said.
  const hasProblems = hasErrors || items.some((item) => isFailingActivityStatus(item.status));
  const wasCancelled = items.some((item) => item.status === "cancelled");
  const hasSucceeded = items.some((item) => item.status === "success");
  const badgeIcon = hasProblems ? (
    <XCircle className="h-3 w-3 text-rose-400" />
  ) : wasCancelled ? (
    <CircleDashed className="h-3 w-3 text-nexus-muted" />
  ) : hasSucceeded ? (
    <Check className="h-3 w-3 text-emerald-400" />
  ) : (
    <Activity className="h-3 w-3 text-nexus-muted" />
  );

  return (
    <div className="my-2 overflow-hidden rounded-xl border border-violet-400/15 bg-violet-400/[0.025]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="nx-motion-feedback flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-violet-400/[0.04]"
        aria-expanded={open}
        aria-controls={open ? activityBodyId : undefined}
      >
        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-violet-400/10">
          {isStreaming ? <Loader2 className="h-3 w-3 animate-spin text-violet-300" /> : badgeIcon}
        </span>
        <span className="text-[11px] font-semibold text-nexus-text">{summary}</span>
        <span className="text-[10px] text-nexus-muted">
          {/* Was `{items.length} atualização{...ões}`, which rendered
              "atualizaçãoões" for every count above one. */}
          {items.length === 1 ? "1 atualização" : `${items.length} atualizações`}
        </span>
        {/* Editorial Activity level: agents in parallel + test tally. Inside the
            toggle so the collapsed one-liner already tells the story. */}
        {editorial.agentNames.length > 1 && (
          <span className="hidden rounded-full bg-violet-400/10 px-1.5 py-px text-[9px] text-violet-200/80 sm:inline">
            {editorial.agentNames.length} agentes{editorial.parallel ? " · em paralelo" : ""}
          </span>
        )}
        {editorial.verifications.length > 0 && (
          <span className="hidden rounded-full bg-nexus-bg/60 px-1.5 py-px text-[9px] tabular-nums text-nexus-muted sm:inline">
            {editorial.passed}✓·{editorial.failed}✕ testes
          </span>
        )}
        <ChevronDown
          className={`ml-auto h-3.5 w-3.5 text-nexus-muted transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.ol
            id={activityBodyId}
            data-testid="execution-activity-body"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            className={`border-t border-violet-400/10 px-3 py-2 [content-visibility:auto] ${virtualized ? "max-h-[360px] overflow-y-auto" : "overflow-hidden"}`}
            onScroll={virtualized ? (event) => setScrollTop(event.currentTarget.scrollTop) : undefined}
          >
            {virtualized && <li aria-hidden="true" className="list-none" style={{ height: firstVisible * ACTIVITY_ROW_HEIGHT }} />}
            {visibleGroups.map((group, offset) => {
              const index = firstVisible + offset;
              const item = group.items[0];
              const Icon = kindIcon(item.kind);
              const parsed = Date.parse(item.timestamp ?? "");
              const clock = editorial.t0 !== undefined && Number.isFinite(parsed)
                ? formatRunClock(parsed - editorial.t0)
                : null;
              if (group.items.length > 1 && group.fileCount !== undefined) {
                return (
                  <li
                    key={group.key}
                    data-testid="execution-activity-row"
                    aria-posinset={index + 1}
                    aria-setsize={displayGroups.length}
                    className={`relative flex list-none gap-2.5 py-1.5 ${virtualized ? "h-12 overflow-hidden" : ""}`}
                  >
                    {index < displayGroups.length - 1 && (
                      <span className="absolute left-[7px] top-5 h-[calc(100%-8px)] w-px bg-nexus-border" />
                    )}
                    <span className="relative z-10 mt-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-nexus-card">
                      {statusIcon("success")}
                    </span>
                    <GroupedFileReads group={group} />
                  </li>
                );
              }
              return (
                <li
                  key={group.key}
                  data-testid="execution-activity-row"
                  aria-posinset={index + 1}
                  aria-setsize={displayGroups.length}
                  className={`relative flex list-none gap-2.5 py-1.5 ${virtualized ? "h-12 overflow-hidden" : ""}`}
                >
                  {index < displayGroups.length - 1 && (
                    <span className="absolute left-[7px] top-5 h-[calc(100%-8px)] w-px bg-nexus-border" />
                  )}
                  <span className="relative z-10 mt-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-nexus-card">
                    {item.status === "pending" ? <Icon className="h-3 w-3 text-nexus-muted" /> : statusIcon(item.status)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {clock && (
                        <time className="shrink-0 font-mono text-[9px] tabular-nums text-nexus-muted/60">
                          {clock}
                        </time>
                      )}
                      <span className={`text-[11px] font-medium text-nexus-text/90 ${virtualized ? "truncate" : ""}`}>{item.title}</span>
                      {item.agent && (
                        <span className="inline-flex items-center gap-1 rounded bg-violet-400/8 px-1.5 py-0.5 text-[9px] font-medium text-violet-200/75">
                          {item.kind === "agent" && item.status === "running" && (
                            <span aria-hidden="true" className="animate-pulse text-[9px] leading-none">◉</span>
                          )}
                          {item.kind === "agent" && item.status === "success" && (
                            <span aria-hidden="true" className="text-[9px] leading-none text-emerald-400">✓</span>
                          )}
                          {item.agent}
                        </span>
                      )}
                      {item.kind === "verification" && (
                        <span className="rounded bg-nexus-bg/60 px-1 py-px font-mono text-[8px] uppercase tracking-wide text-nexus-muted/70">
                          teste
                        </span>
                      )}
                    </div>
                    {item.detail && item.detail !== item.title && (
                      <p className={`mt-0.5 truncate text-[10px] text-nexus-muted ${virtualized ? "hidden" : ""}`} title={item.detail}>
                        {item.detail}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
            {virtualized && <li aria-hidden="true" className="list-none" style={{ height: Math.max(0, displayGroups.length - lastVisible) * ACTIVITY_ROW_HEIGHT }} />}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}

export default memo(ExecutionActivity);
