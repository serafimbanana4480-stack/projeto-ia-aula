"use client";

import { useEffect, useId, useState } from "react";
import { ArrowLeft, Bot, ChevronDown, MessageSquareText, Wrench } from "lucide-react";
import type { ChatMessage, RunStep } from "../../lib/types";
import { formatRunDuration } from "../../lib/chatPresentation";
import { workerOf } from "../../lib/activityGroups";
import { StepStatusIcon, subagentPreview } from "./ActivityGroupRow";
import { compactActivityLine } from "../../lib/activityLine";
import { sanitizeAssistantContent } from "../../lib/chatPresentation";
import {
  buildAgentRoster,
  deliverySentence,
  memoryNotice,
  narrateStep,
  redactPayload,
  summarizeRunDelivery,
  type AgentRosterEntry,
  type DetailLevel,
} from "../../lib/plainNarration";
import { hydratePresentationLevel, usePresentationStore } from "../../stores/presentationStore";
import ChatContextDrawer from "./ChatContextDrawer";

const LEVELS: { id: DetailLevel; label: string }[] = [
  { id: "simple", label: "Normal" },
  { id: "detailed", label: "Expandido" },
  { id: "technical", label: "Debug" },
];

const STATUS_WORD: Record<string, string> = {
  running: "a trabalhar",
  success: "concluído",
  error: "com problema",
  warning: "com aviso",
  paused: "em pausa",
  cancelled: "cancelado",
  awaiting_confirmation: "à espera de autorização",
  pending: "ainda não começou",
};

export function RunDeliveryNote({ message }: { message: ChatMessage }) {
  const delivery = summarizeRunDelivery(message);
  if (!delivery || (!delivery.verification && delivery.agents.length === 0)) return null;
  const sentence = deliverySentence(delivery);
  if (!sentence) return null;
  return (
    <p data-testid="run-delivery" className="text-[13px] leading-relaxed text-nexus-text">
      {sentence}
    </p>
  );
}

export function DetailLevelSwitch({ className = "" }: { className?: string }) {
  const level = usePresentationStore((state) => state.level);
  const setLevel = usePresentationStore((state) => state.setLevel);
  const groupId = useId();

  useEffect(() => {
    hydratePresentationLevel();
  }, []);

  return (
    <div
      role="radiogroup"
      aria-labelledby={groupId}
      data-testid="detail-level-switch"
      className={`inline-flex items-center gap-2 text-[11px] ${className}`}
    >
      <span id={groupId} className="sr-only">
        Nível de detalhe
      </span>
      {LEVELS.map((option) => {
        const selected = level === option.id;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => setLevel(option.id)}
            className={`rounded-sm px-0.5 underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
              selected ? "text-nexus-text underline decoration-nexus-accent" : "text-nexus-faint hover:text-nexus-text"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function stepsForWorker(steps: RunStep[] | undefined, entry: AgentRosterEntry, ambiguousName: boolean): RunStep[] {
  return (steps ?? [])
    .filter((step) => {
      if (workerOf(step) !== entry.name) return false;
      if (step.taskId) return step.taskId === entry.taskId;
      return !ambiguousName || !entry.taskId;
    })
    .sort((a, b) => a.seq - b.seq);
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function workerResult(steps: RunStep[]): string {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const detail = record(steps[index].detail);
    const completed = record(detail?.completed);
    const nested = record(detail?.result);
    const output = completed?.result ?? completed?.output ?? nested?.output;
    if (typeof output === "string" && output.trim()) return sanitizeAssistantContent(output);
  }
  return "";
}

function safePayload(value: unknown): string {
  try {
    const text = JSON.stringify(redactPayload(value), null, 2) ?? String(value);
    return text.length > 12_000 ? `${text.slice(0, 12_000)}\n… resultado truncado` : text;
  } catch {
    return "Detalhe indisponível.";
  }
}

function WorkerStep({ step }: { step: RunStep }) {
  const detail = record(step.detail);
  if (step.verb === "thinking") {
    const visible = detail?.visibility === "label" ? step.label : "A pensar…";
    return <li className="pl-5 text-[12px] leading-relaxed text-nexus-faint">{visible}</li>;
  }
  if (step.verb === "message") {
    const text = sanitizeAssistantContent(step.label).trim();
    return text ? (
      <li className="rounded-xl rounded-tl-sm bg-nexus-card/65 px-3 py-2 text-[13px] leading-relaxed text-nexus-text whitespace-pre-wrap break-words">
        {text}
      </li>
    ) : null;
  }
  const line = compactActivityLine(step) ?? narrateStep(step).sentence;
  if (!line.trim()) return null;
  const args = step.event?.tool_args;
  const result = detail?.result;
  if (step.verb === "tool" && (args || result !== undefined)) {
    return (
      <li>
        <details className="group/tool rounded-lg border border-nexus-border/40 bg-nexus-bg/30">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 text-[12px] text-nexus-muted hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
            <Wrench className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="min-w-0 flex-1 break-words">{line}</span>
            <StepStatusIcon status={step.status} />
            <ChevronDown className="h-3.5 w-3.5 shrink-0 transition-transform group-open/tool:rotate-180" aria-hidden="true" />
          </summary>
          <div className="space-y-2 border-t border-nexus-border/30 px-3 py-2">
            <div className="text-[10px] text-nexus-faint">Ferramenta: <code>{step.target}</code></div>
            {args && <div><span className="text-[10px] text-nexus-faint">Pedido</span><pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all text-[11px] text-nexus-muted">{safePayload(args)}</pre></div>}
            {result !== undefined && <div><span className="text-[10px] text-nexus-faint">Resultado</span><pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[11px] text-nexus-muted">{safePayload(result)}</pre></div>}
          </div>
        </details>
      </li>
    );
  }
  return (
    <li className="flex items-start gap-2 text-[12px] leading-relaxed text-nexus-muted">
      <StepStatusIcon status={step.status} className="mt-0.5 h-3 w-3" />
      <span className="min-w-0 break-words">{line}</span>
    </li>
  );
}

function WorkerConversation({ entry, own }: { entry: AgentRosterEntry; own: RunStep[] }) {
  const result = workerResult(own);
  return (
    <div role="region" aria-label={`Conversa de ${entry.name}`} className="px-3 py-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-[12px] font-semibold text-nexus-text">Conversa de {entry.name}</span>
        {entry.durationMs !== undefined && <span className="text-[11px] text-nexus-faint">{formatRunDuration(entry.durationMs)}</span>}
      </div>
      {(entry.objective || entry.task) && <div className="ml-auto mb-3 max-w-[90%] rounded-xl rounded-tr-sm bg-nexus-card/70 px-3 py-2 text-[12px] text-nexus-text"><span className="mb-1 block text-[10px] text-nexus-faint">Tarefa atribuída</span>{entry.objective || entry.task}</div>}
      {own.length > 0 ? (
        <ol className="space-y-2 border-l border-nexus-border/50 pl-3">
          {own.map((step, index) => <WorkerStep key={`${entry.name}-${step.seq}-${index}`} step={step} />)}
        </ol>
      ) : <p className="text-[12px] text-nexus-muted">Ainda não foram comunicadas atualizações detalhadas deste agente.</p>}
      {result && <div className="mt-3 rounded-xl rounded-tl-sm bg-nexus-card/65 px-3 py-2 text-[13px] leading-relaxed text-nexus-text whitespace-pre-wrap break-words"><span className="mb-1 block text-[10px] text-nexus-faint">Resultado comunicado</span>{result}</div>}
      {!result && entry.status !== "running" && <p className="mt-3 text-[11px] text-nexus-faint">Não foi comunicada uma resposta separada deste agente.</p>}
      <p className="mt-3 border-t border-nexus-border/30 pt-2 text-[11px] leading-relaxed text-nexus-faint">
        As instruções diretas a este subagente não estão disponíveis nesta execução.
      </p>
    </div>
  );
}

function workerKey(entry: AgentRosterEntry): string {
  return `${entry.name}\u0000${entry.taskId ?? ""}`;
}

export function AgentRoster({ message }: { message: ChatMessage }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [wide, setWide] = useState(false);
  const roster = buildAgentRoster(message);
  if (roster.length === 0) return null;
  const running = roster.filter((entry) => entry.status === "running").length;
  const selectedEntry = roster.find((entry) => workerKey(entry) === selected);

  return (
    <section aria-label="Equipa de agentes" data-testid="agent-roster" className="px-3 py-2">
      <p className="flex items-baseline gap-2 text-[12px]">
        <span className="font-medium text-nexus-text">{roster.length} {roster.length === 1 ? "agente envolvido" : "agentes envolvidos"}</span>
        <span className="text-[11px] text-nexus-faint">
          {running > 0 ? `${running} a trabalhar` : "iniciados nesta execução"}
        </span>
      </p>
      <div className="mt-2 space-y-1.5">
        {roster.map((entry) => {
          const own = stepsForWorker(message.steps, entry, roster.filter((item) => item.name === entry.name).length > 1);
          const preview = subagentPreview(own) || entry.sentence;
          return (
            <details key={entry.taskId || entry.name} data-testid="agent-roster-entry" data-agent={entry.name} className="group/agent overflow-hidden rounded-xl border border-nexus-border/50 bg-nexus-bg/35">
              <summary className="flex cursor-pointer list-none items-start gap-2.5 px-3 py-2.5 text-left hover:bg-nexus-card/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-accent">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent"><Bot className="h-4 w-4" aria-hidden="true" /></span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-x-2 text-[12px]"><span className="font-semibold text-nexus-text">{entry.name}</span><span className="text-nexus-faint">{entry.role}</span><span className="text-nexus-muted">· {STATUS_WORD[entry.status] ?? entry.status}</span></span>
                  {preview && <span className="mt-0.5 block break-words text-[12px] leading-relaxed text-nexus-muted">{preview}</span>}
                </span>
                <span className="flex shrink-0 items-center gap-1 text-[11px] text-nexus-accent"><MessageSquareText className="h-3.5 w-3.5" aria-hidden="true" /><span className="hidden sm:inline">Ver conversa</span><ChevronDown className="h-3.5 w-3.5 transition-transform group-open/agent:rotate-180" aria-hidden="true" /></span>
              </summary>
              <div className="border-t border-nexus-border/40 bg-nexus-bg/25">
                <WorkerConversation entry={entry} own={own} />
                <button type="button" onClick={() => setSelected(workerKey(entry))}
                  className="mx-3 mb-3 rounded-md border border-nexus-border/60 px-2.5 py-1.5 text-[11px] text-nexus-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
                  Abrir conversa no painel
                </button>
              </div>
            </details>
          );
        })}
      </div>
      {selectedEntry && (
        <ChatContextDrawer label={`Painel do agente ${selectedEntry.name}`} wide={wide}
          onClose={() => { setSelected(null); setWide(false); }}>
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between gap-2 border-b border-nexus-border/40 px-3 py-3">
              <button type="button" onClick={() => { setSelected(null); setWide(false); }}
                className="inline-flex items-center gap-1.5 rounded px-1 py-1 text-xs text-nexus-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" /> Chat
              </button>
              <span className="min-w-0 flex-1 truncate text-xs font-semibold text-nexus-text">{selectedEntry.name}</span>
              <button type="button" onClick={() => setWide((value) => !value)}
                className="rounded px-1 py-1 text-xs text-nexus-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
                {wide ? "Reduzir" : "Expandir"}
              </button>
            </div>
            <div aria-label="Alternar agente" className="flex gap-1 overflow-x-auto border-b border-nexus-border/30 px-3 py-2">
              {roster.map((entry) => <button key={workerKey(entry)} type="button"
                onClick={() => setSelected(workerKey(entry))} aria-pressed={workerKey(entry) === selected}
                className="shrink-0 rounded-md px-2 py-1 text-[11px] text-nexus-muted aria-pressed:bg-nexus-accent/15 aria-pressed:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
                {entry.name}{roster.filter((item) => item.name === entry.name).length > 1 && entry.taskId ? ` · ${entry.taskId}` : ""}
              </button>)}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <WorkerConversation entry={selectedEntry} own={stepsForWorker(message.steps, selectedEntry, roster.filter((item) => item.name === selectedEntry.name).length > 1)} />
            </div>
          </div>
        </ChatContextDrawer>
      )}
    </section>
  );
}

export function MemoryNotice({ message }: { message: ChatMessage }) {
  const notice = memoryNotice(message);
  const [open, setOpen] = useState(false);
  const panelId = useId();
  if (!notice) return null;
  return (
    <div data-testid="memory-notice" className="px-3 py-1.5 text-[12px]">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="text-left text-nexus-muted hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
      >
        {notice.sentence}
      </button>
      {open && (
        <ul id={panelId} className="mt-1 list-disc pl-4 text-[11px] text-nexus-faint">
          {notice.sources.map((source) => (
            <li key={source}>{source}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
