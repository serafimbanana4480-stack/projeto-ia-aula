"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { Bot } from "../../../lib/bots";
import { IdentityMark } from "./identity";
import { agentActivity, fileRunRole, taskStatusLabel, type RoomRun, type RoomRunRecord } from "./model";

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
  return record.kind;
}

export function RunCard({ run }: { run: RoomRun }) {
  const hot = run.status === "running" || run.status === "pending" || run.status === "cancelling";
  const [open, setOpen] = useState(hot || run.status === "completed");
  useEffect(() => {
    setOpen(run.status === "running" || run.status === "pending" || run.status === "cancelling" || run.status === "completed");
  }, [run.id, run.status]);
  return (
    <section data-testid="run-card" className="rounded-2xl border border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)]">
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="flex w-full items-start gap-3 px-3 py-3 text-left">
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-semibold">Leitura de ficheiro</span>
            <span className="text-[11px] text-[color:var(--nx-text-dim)]">{taskStatusLabel(run.status)}</span>
          </span>
          <span className="mt-0.5 block truncate text-[11px] text-[color:var(--nx-text-faint)]">{run.file_path}</span>
        </span>
        <ChevronDown size={15} className={`mt-0.5 shrink-0 text-[color:var(--nx-text-faint)] transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="space-y-2 border-t border-[color:var(--nx-line)] px-3 py-2.5">
          <p className="line-clamp-2 text-[12px] leading-5 text-[color:var(--nx-text-dim)]">{run.request}</p>
          <ol className="space-y-2">
            {run.tasks.map((task, index) => {
              const records = run.records.filter((record) => record.task_id === task.id);
              const handoff = records.find((record) => record.kind === "handoff");
              return (
                <li key={task.id} className="border-t border-[color:var(--nx-line)] pt-2 first:border-t-0 first:pt-0">
                  {handoff ? (
                    <p className="mb-1.5 text-[11px] leading-4 text-[color:var(--nx-text-faint)]">{recordLine(handoff)}</p>
                  ) : null}
                  <div className="flex items-start gap-2">
                    <IdentityMark id={task.bot_id || task.bot_name} name={task.bot_name} size={22} live={task.status === "running"} tone={task.status === "running" ? "live" : task.status === "failed" ? "down" : "idle"} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12px] font-medium">{task.bot_name}<span className="ml-2 font-normal text-[color:var(--nx-text-faint)]">{fileRunRole(index, run.tasks.length)} · {taskStatusLabel(task.status)} · {task.provider} · {task.model}</span></p>
                      {task.error ? <p className="mt-0.5 line-clamp-2 whitespace-pre-wrap text-[12px] leading-5 text-[color:var(--nx-rose)]">{task.error}</p> : null}
                      {task.result ? <p className="mt-0.5 text-[12px] leading-5"><span className="mr-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Resultado</span>{task.result}</p> : null}
                      {records.filter((record) => record.kind !== "handoff").length > 0 && (
                        <ul className="mt-0.5">
                          {records.filter((record) => record.kind !== "handoff").map((record) => (
                            <li key={record.id} className="truncate text-[11px] leading-4 text-[color:var(--nx-text-dim)]">{recordLine(record)}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </section>
  );
}
