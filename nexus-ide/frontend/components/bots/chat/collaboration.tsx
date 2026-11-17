"use client";

import { useEffect, useState } from "react";
import { ChevronDown, RotateCcw, Square } from "lucide-react";
import type { Bot } from "../../../lib/bots";
import { IdentityMark } from "./identity";
import {
  agentActivity,
  canCancelRun,
  canResumeRun,
  fileRunRole,
  handoffRecords,
  recordKindLabel,
  runEngineLabel,
  runIdentity,
  runState,
  runStateLabel,
  taskStatusLabel,
  taskVerification,
  verificationOf,
  type RoomRun,
  type RoomRunRecord,
} from "./model";

export function ParticipantStrip({
  participants,
  partialName,
  tasks,
}: {
  participants: Bot[];
  partialName: string | null;
  tasks: RoomRun["tasks"];
}) {
  if (participants.length === 0) return null;
  return (
    <div className="border-b border-[color:var(--nx-line)] bg-[color:var(--nx-bg)]" aria-label="Quem está a fazer o quê">
      <ul className="nx-bot-read mx-auto flex gap-2 overflow-x-auto px-3 py-2 sm:px-5">
        {participants.map((bot) => {
          const task = tasks.find((item) => item.bot_id === bot.id || item.bot_name === bot.name);
          const activity = agentActivity({
            name: bot.name,
            configured: Boolean(bot.provider && bot.model),
            partialName,
            taskStatus: task?.status,
          });
          const live = activity === "A responder" || activity === "A executar";
          return (
            <li key={bot.id} className="flex min-w-[9.5rem] shrink-0 items-center gap-2 rounded-xl border border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)] px-2 py-1.5">
              <IdentityMark id={bot.id} name={bot.name} size={26} live={live} tone={live ? "live" : activity === "Falhou" ? "down" : !bot.provider || !bot.model ? "warn" : "idle"} />
              <span className="min-w-0">
                <span className="block truncate text-[12px] font-medium">{bot.name}</span>
                <span className="block truncate text-[10px] text-[color:var(--nx-text-faint)]">{bot.description?.trim() || "Função não descrita"}</span>
                <span className="block truncate text-[11px] text-[color:var(--nx-text-dim)]">{activity}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function recordLine(record: RoomRunRecord): string {
  const payload = record.payload;
  if (record.kind === "tool_call") {
    const tool = typeof payload.tool === "string" ? payload.tool : "ferramenta";
    const path = typeof payload.path === "string" ? payload.path : "";
    return path ? `${tool} · ${path}` : tool;
  }
  if (record.kind === "tool_result") {
    if (typeof payload.error === "string" && payload.error) return payload.error;
    if (typeof payload.path === "string") return `Leitura registada · ${payload.path}`;
    return "Sem erro registado";
  }
  if (record.kind === "handoff") return "As análises anteriores seguem como dados não verificados";
  return recordKindLabel(record.kind);
}

function verifiedText(verified: boolean | null): string {
  if (verified === true) return "Verificado";
  if (verified === false) return "Não aprovado";
  return "Registo sem resultado explícito";
}

export function RunCard({
  run,
  onResume,
  onCancel,
  pendingAction = null,
}: {
  run: RoomRun;
  onResume?: () => void;
  onCancel?: () => void;
  pendingAction?: "resume" | "cancel" | null;
}) {
  const state = runState(run);
  const hot = canCancelRun(run);
  const completed = state === "completed";
  const [open, setOpen] = useState(hot || completed);
  useEffect(() => {
    setOpen(hot || completed);
  }, [hot, completed]);

  const engine = runEngineLabel(run);
  const legacyFile = run.execution_engine === "legacy_file";
  const identity = runIdentity(run);
  const verifications = verificationOf(run);
  const handoffs = handoffRecords(run);
  const tools = run.records.filter((record) => record.kind === "tool_call" || record.kind === "tool_result");
  const resumable = canResumeRun(run);
  const cancelable = canCancelRun(run);

  return (
    <section
      data-testid="run-card"
      data-run-id={identity}
      data-run-state={state}
      aria-label={`Execução ${engine}`}
      className="rounded-2xl border border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)]"
    >
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="flex w-full items-start gap-3 px-3 py-3 text-left">
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-semibold">{engine}</span>
            <span data-testid="run-state" className="text-[11px] text-[color:var(--nx-text-dim)]">{runStateLabel(state)}</span>
            <span className="truncate text-[10px] text-[color:var(--nx-text-faint)]">{identity.slice(0, 12)}</span>
          </span>
          <span className="mt-0.5 block truncate text-[11px] text-[color:var(--nx-text-faint)]">
            {run.request || "Sem objetivo registado"}{run.file_path ? ` · ${run.file_path}` : ""}
          </span>
        </span>
        <ChevronDown size={15} className={`mt-0.5 shrink-0 text-[color:var(--nx-text-faint)] transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="space-y-3 border-t border-[color:var(--nx-line)] px-3 py-2.5">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Objetivo do run</p>
            <p className="mt-1 line-clamp-3 text-[12px] leading-5 text-[color:var(--nx-text-dim)]">{run.request || "Sem objetivo registado"}</p>
            {run.project_root || run.file_path ? (
              <p className="mt-1 break-all text-[11px] text-[color:var(--nx-text-faint)]">{run.project_root}{run.file_path ? ` / ${run.file_path}` : ""}</p>
            ) : null}
          </div>

          {handoffs.length > 0 ? (
            <div>
              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Reatribuições e passagens</p>
              <ul className="mt-1 space-y-1">
                {handoffs.map((handoff) => (
                  <li key={handoff.id} className="text-[11px] leading-4 text-[color:var(--nx-text-dim)]">
                    <span className="font-medium text-[color:var(--nx-text)]">
                      {handoff.from && handoff.to ? `${handoff.from} → ${handoff.to}` : recordKindLabel(handoff.kind)}
                    </span>
                    {handoff.detail ? <span> · {handoff.detail}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {run.tasks.length > 0 ? (
            <ol className="space-y-2" aria-label="Trabalho atribuído">
              {run.tasks.map((task, index) => {
                const records = run.records.filter((record) => record.task_id === task.id);
                const handoff = records.find((record) => record.kind === "handoff");
                const verified = taskVerification(run, task.id);
                return (
                  <li key={task.id} className="border-t border-[color:var(--nx-line)] pt-2 first:border-t-0 first:pt-0">
                    {handoff ? (
                      <p className="mb-1.5 text-[11px] leading-4 text-[color:var(--nx-text-faint)]">{recordLine(handoff)}</p>
                    ) : null}
                    <div className="flex items-start gap-2">
                      <IdentityMark id={task.bot_id || task.bot_name} name={task.bot_name} size={22} live={task.status === "running"} tone={task.status === "running" ? "live" : task.status === "failed" || task.status === "blocked" ? "down" : !task.provider || !task.model ? "warn" : "idle"} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[12px] font-medium">
                          {task.bot_name}
                          <span className="ml-2 font-normal text-[color:var(--nx-text-faint)]">
                            {legacyFile ? `${fileRunRole(index, run.tasks.length)} · ` : "Trabalho atribuído · "}
                            {taskStatusLabel(task.status)} · {task.provider || "sem provedor"} · {task.model || "sem modelo"}
                          </span>
                        </p>
                        {task.error ? <p className="mt-0.5 line-clamp-2 whitespace-pre-wrap text-[12px] leading-5 text-[color:var(--nx-rose)]">{task.error}</p> : null}
                        {task.result ? (
                          <div className="mt-0.5 text-[12px] leading-5">
                            <span className="mr-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">
                              {verified ? "Resultado verificado" : "Resposta do bot (não verificada)"}
                            </span>
                            {task.result}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : null}

          {tools.length > 0 ? (
            <div>
              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Ferramentas</p>
              <ul className="mt-1 space-y-1">
                {tools.map((record) => (
                  <li key={record.id} className="truncate text-[11px] leading-4 text-[color:var(--nx-text-dim)]">{recordLine(record)}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <section
            data-testid="run-verification"
            aria-label="Verificação do resultado"
            aria-live="polite"
            className="rounded-xl border border-[color:var(--nx-line)] bg-[color:var(--nx-bg)] px-2.5 py-2"
          >
            <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Verificação</p>
            {verifications.length === 0 ? (
              <p className="mt-1 text-[11px] leading-5 text-[color:var(--nx-text-dim)]">
                Sem verificação registada. A resposta de um bot é uma proposta, não prova de conclusão.
              </p>
            ) : (
              <ul className="mt-1 space-y-1.5">
                {verifications.map((entry) => (
                  <li key={entry.id} data-testid="run-verification-entry" className="text-[11px] leading-5">
                    <span className={entry.verified === true ? "font-medium text-[color:var(--nx-emerald)]" : entry.verified === false ? "font-medium text-[color:var(--nx-rose)]" : "font-medium text-[color:var(--nx-amber)]"}>
                      {verifiedText(entry.verified)}
                    </span>
                    <span className="text-[color:var(--nx-text-dim)]"> · {entry.label}{entry.detail ? ` · ${entry.detail}` : ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {resumable || cancelable ? (
            <div className="flex flex-wrap gap-2">
              {resumable && onResume ? (
                <button
                  type="button"
                  disabled={pendingAction !== null}
                  onClick={onResume}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300/40 px-2.5 py-1.5 text-[12px] font-medium text-emerald-200 hover:bg-emerald-400/10 disabled:opacity-40"
                >
                  <RotateCcw size={13} aria-hidden="true" />
                  {pendingAction === "resume" ? "A retomar…" : "Retomar"}
                </button>
              ) : null}
              {cancelable && onCancel ? (
                <button
                  type="button"
                  disabled={pendingAction !== null}
                  onClick={onCancel}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-300/40 px-2.5 py-1.5 text-[12px] font-medium text-red-200 hover:bg-red-400/10 disabled:opacity-40"
                >
                  <Square size={12} aria-hidden="true" />
                  {pendingAction === "cancel" ? "A parar…" : "Parar"}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
