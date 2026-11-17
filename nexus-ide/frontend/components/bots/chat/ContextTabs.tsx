"use client";

import { useState, type ReactNode } from "react";
import { X } from "lucide-react";
import type { Bot } from "../../../lib/bots";
import { BotStatusPill } from "../botsUi";
import GroupRuns from "../GroupRuns";
import { IdentityMark } from "./identity";
import {
  pathsFromRuns,
  recordKindLabel,
  recordsOfKind,
  runEngineLabel,
  runIdentity,
  runStateLabel,
  taskStatusLabel,
  verificationOf,
  type RoomRun,
} from "./model";

const TABS = [
  { id: "people", label: "Participantes" },
  { id: "plan", label: "Plano" },
  { id: "files", label: "Ficheiros" },
  { id: "tools", label: "Ferramentas" },
  { id: "verification", label: "Verificação" },
  { id: "events", label: "Eventos" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function availability(bot: Bot | undefined): { label: string; tone: "neutral" | "warn" | "danger" } {
  if (!bot) return { label: "Bot indisponível", tone: "danger" };
  if (!bot.provider || !bot.model) return { label: "Configuração em falta", tone: "warn" };
  return { label: "Configurado · inferência não verificada", tone: "neutral" };
}

function Panel({ id, tab, label, children }: { id: TabId; tab: TabId; label: string; children: ReactNode }) {
  if (tab !== id) return null;
  return (
    <div role="tabpanel" aria-label={label} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
      {children}
    </div>
  );
}

function recordTitle(kind: string): string {
  return recordKindLabel(kind);
}

export default function ContextTabs({
  groupId,
  groupName,
  botIds,
  bots,
  objective,
  executionLabel,
  runs,
  onClose,
}: {
  groupId: string;
  groupName: string;
  botIds: string[];
  bots: Bot[];
  objective: string;
  executionLabel: string;
  runs: RoomRun[];
  onClose: () => void;
}) {
  const [tab, setTab] = useState<TabId>("people");
  const participants = botIds.map((id) => bots.find((bot) => bot.id === id) ?? null);
  const files = pathsFromRuns(runs);
  const tools = recordsOfKind(runs, ["tool_call", "tool_result"]);
  const events = runs.flatMap((run) => run.records.map((record) => ({ runId: runIdentity(run), record })));
  const tasks = runs.flatMap((run) => run.tasks.map((task) => ({ run, task })));
  const verifications = runs.flatMap((run) => verificationOf(run).map((entry) => ({ run, entry })));

  return (
    <aside aria-label="Contexto do grupo" className="nx-bot-drawer flex h-full min-h-0 w-full flex-col border-l border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)]">
      <div className="flex items-center justify-between gap-3 border-b border-[color:var(--nx-line)] px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-[13px] font-semibold">Contexto</h2>
          <p className="truncate text-[11px] text-[color:var(--nx-text-faint)]">{groupName}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Fechar contexto" className="rounded-lg p-2 text-[color:var(--nx-text-faint)] hover:bg-[color:var(--nx-surface-3)] hover:text-[color:var(--nx-text)]">
          <X size={16} />
        </button>
      </div>
      <div role="tablist" aria-label="Secções do contexto" className="flex gap-0.5 overflow-x-auto border-b border-[color:var(--nx-line)] px-1.5 py-1.5">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className={`shrink-0 rounded-md px-1.5 py-1 text-[10px] font-medium ${tab === item.id ? "bg-[color:var(--nx-surface-3)] text-[color:var(--nx-text)]" : "text-[color:var(--nx-text-faint)] hover:text-[color:var(--nx-text)]"}`}
          >
            {item.label}
          </button>
        ))}
      </div>
      <Panel id="people" tab={tab} label="Participantes">
        <section>
          <h3 className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Objetivo</h3>
          <p className="mt-1 whitespace-pre-wrap break-words text-[13px] leading-6">{objective}</p>
        </section>
        <section>
          <h3 className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Execução</h3>
          <p className="mt-1 text-[13px]">Estado da sala: {executionLabel}</p>
        </section>
        <ul className="space-y-2">
          {participants.map((bot, index) => {
            const id = botIds[index] ?? `missing-${index}`;
            const state = availability(bot ?? undefined);
            const name = bot?.name || "Bot indisponível";
            return (
              <li key={id} className="rounded-xl border border-[color:var(--nx-line)] p-3">
                <div className="flex items-center gap-2">
                  <IdentityMark id={id} name={name} size={28} tone={state.tone === "warn" ? "warn" : state.tone === "danger" ? "down" : "idle"} />
                  <div className="min-w-0">
                    <span className="block truncate text-[13px] font-medium">{name}</span>
                    <span className="block truncate text-[11px] text-[color:var(--nx-text-faint)]">{bot?.description?.trim() || "Função não descrita"}</span>
                  </div>
                </div>
                <p className="mt-2 break-all text-[11px] text-[color:var(--nx-text-dim)]">
                  {bot?.provider || "Provedor não configurado"} · {bot?.model || "Modelo não configurado"}
                </p>
                <div className="mt-2"><BotStatusPill tone={state.tone}>{state.label}</BotStatusPill></div>
              </li>
            );
          })}
        </ul>
      </Panel>
      <Panel id="plan" tab={tab} label="Plano">
        {tasks.length === 0 ? (
          <p className="text-[12px] leading-5 text-[color:var(--nx-text-faint)]">
            Ainda não há trabalho atribuído registado. O compositor cria um run PRIMARY; a leitura de ficheiro usa o motor legacy e aparece aqui como execução separada.
          </p>
        ) : (
          <ol className="space-y-2">
            {tasks.map(({ task, run }) => (
              <li key={`${runIdentity(run)}:${task.id}`} className="rounded-xl border border-[color:var(--nx-line)] px-3 py-2 text-[12px]">
                <span className="block font-medium">{task.bot_name} · {taskStatusLabel(task.status)}</span>
                <span className="block text-[11px] text-[color:var(--nx-text-faint)]">
                  {runEngineLabel(run)} · {runIdentity(run).slice(0, 12)} · {runStateLabel(run.state ?? run.status)}
                </span>
                {run.file_path ? <span className="block break-all text-[11px] text-[color:var(--nx-text-faint)]">{run.file_path}</span> : null}
              </li>
            ))}
          </ol>
        )}
        <GroupRuns groupId={groupId} embedded />
      </Panel>
      <Panel id="files" tab={tab} label="Ficheiros">
        {files.length === 0 ? (
          <p className="text-[12px] leading-5 text-[color:var(--nx-text-faint)]">Nenhum ficheiro foi registado nesta conversa.</p>
        ) : (
          <ul className="space-y-2">
            {files.map((file) => (
              <li key={file} className="break-all rounded-xl border border-[color:var(--nx-line)] px-3 py-2 text-[12px]">{file}</li>
            ))}
          </ul>
        )}
        {runs[0]?.project_root ? <p className="text-[11px] text-[color:var(--nx-text-faint)]">Projeto: {runs[0].project_root}</p> : null}
      </Panel>
      <Panel id="tools" tab={tab} label="Ferramentas">
        {tools.length === 0 ? (
          <p className="text-[12px] leading-5 text-[color:var(--nx-text-faint)]">Nenhuma ferramenta foi registada neste run. A ausência de chamadas não é prova de conclusão.</p>
        ) : (
          <ul className="space-y-2">
            {tools.map(({ id, kind, payload }) => (
              <li key={id} className="rounded-xl border border-[color:var(--nx-line)] px-3 py-2 text-[12px]">
                <span className="block font-medium">{recordTitle(kind)}</span>
                <span className="mt-1 block break-all text-[color:var(--nx-text-dim)]">
                  {typeof payload.tool === "string" ? payload.tool : kind}
                  {typeof payload.path === "string" ? ` · ${payload.path}` : ""}
                  {typeof payload.error === "string" ? ` · ${payload.error}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel id="verification" tab={tab} label="Verificação">
        {verifications.length === 0 ? (
          <p className="text-[12px] leading-5 text-[color:var(--nx-text-dim)]">
            Sem verificação registada. As respostas dos bots são propostas; não são prova de que o objetivo foi concluído.
          </p>
        ) : (
          <ul className="space-y-2">
            {verifications.map(({ run, entry }) => (
              <li key={`${runIdentity(run)}:${entry.id}`} data-testid="context-verification" className="rounded-xl border border-[color:var(--nx-line)] px-3 py-2 text-[12px]">
                <span className={`block font-medium ${entry.verified === true ? "text-[color:var(--nx-emerald)]" : entry.verified === false ? "text-[color:var(--nx-rose)]" : "text-[color:var(--nx-amber)]"}`}>
                  {entry.verified === true ? "Verificado" : entry.verified === false ? "Não aprovado" : "Registo sem resultado explícito"}
                </span>
                <span className="mt-1 block text-[11px] leading-5 text-[color:var(--nx-text-dim)]">{entry.label}{entry.detail ? ` · ${entry.detail}` : ""}</span>
                <span className="mt-1 block break-all text-[11px] text-[color:var(--nx-text-faint)]">{runEngineLabel(run)} · {runIdentity(run).slice(0, 12)}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel id="events" tab={tab} label="Eventos">
        {events.length === 0 ? (
          <p className="text-[12px] leading-5 text-[color:var(--nx-text-faint)]">Sem eventos de execução. O histórico da conversa está na coluna central.</p>
        ) : (
          <ol className="space-y-2">
            {events.map(({ record, runId }, index) => (
              <li key={record.id} className="rounded-xl border border-[color:var(--nx-line)] px-3 py-2 text-[12px]">
                <span className="block font-medium">{index + 1}. {recordTitle(record.kind)}</span>
                <span className="mt-1 block break-all text-[11px] text-[color:var(--nx-text-faint)]">{record.kind} · {record.id} · {runId.slice(0, 12)}</span>
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </aside>
  );
}
