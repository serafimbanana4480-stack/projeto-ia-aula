"use client";

import { useState } from "react";
import { ArrowDown, Check, Copy, Quote, Reply, RotateCcw } from "lucide-react";
import type { ChatMessage, ToolCallItem } from "../../../lib/types";
import { AssistantMarkdown } from "../../chat/MessageBubble";
import { useThemeStore } from "../../../stores/themeStore";
import { formatBotTime } from "../botsUi";
import { hueFromSeed, IdentityMark } from "./identity";
import { dayLabel } from "./model";

function toolStatus(status: ToolCallItem["status"]): string {
  if (status === "running") return "Em curso";
  if (status === "success") return "Concluída";
  if (status === "error") return "Falhou";
  if (status === "awaiting_confirmation") return "A aguardar confirmação";
  return "Resultado desconhecido";
}

export function ToolActivity({ tools }: { tools: ToolCallItem[] }) {
  if (tools.length === 0) return null;
  return (
    <details data-testid="tool-call" className="mb-3 overflow-hidden rounded-xl border border-[color:var(--nx-line)] bg-[color:var(--nx-bg)]">
      <summary className="cursor-pointer list-none px-3 py-2 text-[12px] font-medium text-[color:var(--nx-text-dim)] [&::-webkit-details-marker]:hidden">
        Atividade · {tools.length} {tools.length === 1 ? "chamada" : "chamadas"}
      </summary>
      <ul className="space-y-2 border-t border-[color:var(--nx-line)] px-3 py-2.5">
        {tools.map((tool) => {
          const path = typeof tool.args?.path === "string" ? tool.args.path : "";
          return (
            <li key={tool.id} className="text-[12px] leading-5">
              <span className="flex items-start justify-between gap-3">
                <span className="break-all font-medium text-[color:var(--nx-text)]">{tool.name}</span>
                <span className={tool.status === "error" ? "shrink-0 text-[color:var(--nx-rose)]" : "shrink-0 text-[color:var(--nx-text-faint)]"}>{toolStatus(tool.status)}</span>
              </span>
              {path ? <span className="mt-0.5 block break-all text-[color:var(--nx-text-faint)]">{path}</span> : null}
              {tool.error ? <span className="mt-1 block whitespace-pre-wrap text-[color:var(--nx-rose)]">{tool.error}</span> : null}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function ActionButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} onClick={onClick} className="rounded-md p-1 text-[color:var(--nx-text-faint)] hover:bg-[color:var(--nx-surface-3)] hover:text-[color:var(--nx-text)]">
      {children}
    </button>
  );
}

export function DirectMessage({
  message,
  author,
  authorId,
  roleLabel,
  onQuote,
  onRegenerate,
  onReply,
}: {
  message: ChatMessage;
  author?: string;
  authorId?: string;
  roleLabel?: string;
  onQuote?: (text: string) => void;
  onRegenerate?: () => void;
  onReply?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const theme = useThemeStore((state) => state.theme);
  const mine = message.role === "user";
  const tools = message.toolCalls ?? [];
  if (!message.content && tools.length === 0) return null;
  const hue = hueFromSeed(authorId || author || "bot");
  const copy = () => {
    const text = message.content || tools.map((tool) => tool.name).join("\n");
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <article className={`nx-bot-msg group flex ${mine ? "justify-end" : "justify-start"}`}>
      <div className={mine ? "max-w-[min(100%,34rem)]" : "flex w-full max-w-full gap-3"}>
        {!mine && <IdentityMark id={authorId || author || "bot"} name={author || "Bot"} size={32} labelled />}
        <div
          className={mine
            ? "rounded-2xl rounded-br-md bg-[color:var(--nx-surface-3)] px-3.5 py-2.5 text-[color:var(--nx-text)]"
            : "min-w-0 flex-1 border-l-2 pl-3"}
          style={mine ? undefined : { borderColor: `hsl(${hue} 42% 58%)` }}
        >
          {!mine && (
            <div className="mb-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <p className="text-[13px] font-semibold tracking-tight">{author || "Bot"}</p>
              {roleLabel ? <span className="text-[11px] text-[color:var(--nx-text-faint)]">{roleLabel}</span> : null}
            </div>
          )}
          {mine && <p className="mb-1 text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Tu</p>}
          <ToolActivity tools={tools} />
          {message.content ? (
            <div className="min-w-0 break-words text-[15px] leading-7">
              <AssistantMarkdown text={message.content} theme={theme === "light" ? "light" : "dark"} />
            </div>
          ) : null}
          <div className="mt-1.5 flex items-center justify-end gap-1 text-[10px] text-[color:var(--nx-text-faint)]">
            <time className="mr-auto">{formatBotTime(message.timestamp)}</time>
            <span className="flex opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
              <ActionButton label="Copiar mensagem" onClick={copy}>{copied ? <Check size={13} /> : <Copy size={13} />}</ActionButton>
              {onReply ? <ActionButton label="Responder" onClick={onReply}><Reply size={13} /></ActionButton> : null}
              {onQuote && message.content ? <ActionButton label="Citar mensagem" onClick={() => onQuote(message.content)}><Quote size={13} /></ActionButton> : null}
              {onRegenerate ? <ActionButton label="Regenerar resposta" onClick={onRegenerate}><RotateCcw size={13} /></ActionButton> : null}
            </span>
          </div>
        </div>
      </div>
    </article>
  );
}

export function GroupTurn({
  mine,
  name,
  botId,
  roleLabel,
  content,
  time,
  onQuote,
  onRegenerate,
  onReply,
}: {
  mine: boolean;
  name: string;
  botId?: string | null;
  roleLabel?: string;
  content: string;
  time?: string;
  onQuote?: (text: string) => void;
  onRegenerate?: () => void;
  onReply?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const theme = useThemeStore((state) => state.theme);
  const hue = hueFromSeed(botId || name);
  return (
    <article className={`nx-bot-msg group flex ${mine ? "justify-end" : "justify-start"}`}>
      <div className={mine ? "max-w-[min(100%,34rem)]" : "flex w-full gap-3"}>
        {!mine && <IdentityMark id={botId || name} name={name} size={32} labelled />}
        <div
          className={mine ? "rounded-2xl rounded-br-md bg-[color:var(--nx-surface-3)] px-3.5 py-2.5" : "min-w-0 flex-1 border-l-2 pl-3"}
          style={mine ? undefined : { borderColor: `hsl(${hue} 42% 58%)` }}
        >
          <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
            <p className="text-[13px] font-semibold tracking-tight">{mine ? "Tu" : name}</p>
            <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-[color:var(--nx-text-faint)]">{mine ? "Utilizador" : "Agente"}</span>
            {!mine && roleLabel ? <span className="text-[11px] text-[color:var(--nx-text-faint)]">{roleLabel}</span> : null}
          </div>
          <div className="min-w-0 break-words text-[15px] leading-7 text-[color:var(--nx-text)]">
            <AssistantMarkdown text={content} theme={theme === "light" ? "light" : "dark"} />
          </div>
          <div className="mt-1.5 flex items-center justify-end gap-1 text-[10px] text-[color:var(--nx-text-faint)]">
            {time ? <time className="mr-auto">{formatBotTime(time)}</time> : <span className="mr-auto" />}
            <span className="flex opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
              <ActionButton label="Copiar mensagem" onClick={() => void navigator.clipboard.writeText(content).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1200); })}>
                {copied ? <Check size={13} /> : <Copy size={13} />}
              </ActionButton>
              {onReply ? <ActionButton label="Responder" onClick={onReply}><Reply size={13} /></ActionButton> : null}
              {onQuote ? <ActionButton label="Citar mensagem" onClick={() => onQuote(content)}><Quote size={13} /></ActionButton> : null}
              {onRegenerate ? <ActionButton label="Regenerar resposta" onClick={onRegenerate}><RotateCcw size={13} /></ActionButton> : null}
            </span>
          </div>
        </div>
      </div>
    </article>
  );
}

export function DayRule({ stamp, previous }: { stamp: string; previous?: string }) {
  const label = dayLabel(stamp);
  if (!label || (previous && dayLabel(previous) === label)) return null;
  return (
    <div className="flex items-center gap-3 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-[color:var(--nx-text-faint)]">
      <span className="h-px flex-1 bg-[color:var(--nx-line)]" />
      {label}
      <span className="h-px flex-1 bg-[color:var(--nx-line)]" />
    </div>
  );
}

export function HandoffRule({ from, to }: { from: string; to: string }) {
  return (
    <div className="nx-bot-msg flex items-center gap-2 py-1 text-[11px] text-[color:var(--nx-text-faint)]" role="note">
      <span className="h-px flex-1 bg-[color:var(--nx-line)]" />
      <span>{from} passou a {to}</span>
      <span className="h-px flex-1 bg-[color:var(--nx-line)]" />
    </div>
  );
}

export function TypingRow({ name, id, label, detail }: { name: string; id?: string; label: string; detail?: string }) {
  return (
    <div role="status" aria-live="polite" className="nx-bot-msg flex items-center gap-3 py-1">
      <IdentityMark id={id || name} name={name} size={32} live tone="live" />
      <span>
        <span className="block text-[13px] font-medium">{name} · {label}</span>
        {detail ? <span className="mt-0.5 block text-[11px] text-[color:var(--nx-text-faint)]">{detail}</span> : null}
      </span>
    </div>
  );
}

export function JumpToLatest({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <button type="button" aria-label="Ir para o fim" onClick={onClick} className="absolute -top-11 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full border border-[color:var(--nx-line-strong)] bg-[color:var(--nx-surface-2)] px-3 py-1.5 text-[12px] font-medium text-[color:var(--nx-text)] shadow-[var(--nx-shadow-1)]">
      <ArrowDown size={13} />
      Ir para o fim
      {count > 0 ? <span aria-hidden="true" className="rounded-full bg-[color:var(--nx-accent)] px-1.5 text-[10px] text-white">{count}</span> : null}
    </button>
  );
}
