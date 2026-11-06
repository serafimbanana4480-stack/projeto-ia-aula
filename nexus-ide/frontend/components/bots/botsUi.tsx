"use client";

import { lazy, Suspense, useState } from "react";
import Image from "next/image";
import { Check, Copy } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage } from "../../lib/types";

export const BOT_INPUT =
  "w-full rounded-xl border border-[color:var(--nx-line-strong)] bg-[color:var(--nx-surface-1)] px-3 py-2.5 text-sm text-[color:var(--nx-text)] outline-none placeholder:text-[color:var(--nx-text-faint)] transition-[border-color,box-shadow] duration-[var(--nx-dur-fast)] focus:border-[color:var(--nx-accent)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--nx-accent)_18%,transparent)]";

export function hueFromId(id: string): number {
  let hash = 0;
  for (const character of id) hash = (hash * 31 + character.charCodeAt(0)) | 0;
  return [262, 198, 168, 42, 12, 320][Math.abs(hash) % 6];
}

export function formatBotTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  return date.toDateString() === now.toDateString()
    ? date.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("pt-PT", { day: "2-digit", month: "short" });
}

export function BotAvatar({
  name,
  id = name,
  large = false,
  thinking = false,
  compact = false,
}: {
  name: string;
  id?: string;
  large?: boolean;
  thinking?: boolean;
  compact?: boolean;
}) {
  const hue = hueFromId(id);
  const size = large ? 112 : compact ? 32 : 44;
  return (
    <span
      aria-hidden="true"
      className={`nx-bots-avatar relative flex shrink-0 items-center justify-center overflow-hidden border bg-[radial-gradient(circle_at_50%_35%,rgba(255,255,255,.16),rgba(255,255,255,.03)_62%,rgba(0,0,0,.28))] shadow-[inset_0_1px_0_rgba(255,255,255,.14),0_8px_24px_rgba(0,0,0,.28)] ${
        thinking ? "nx-bots-avatar-live border-cyan-300/60" : "border-white/10"
      } ${large ? "h-28 w-28 rounded-[1.75rem] p-1" : compact ? "h-8 w-8 rounded-lg p-0.5" : "h-11 w-11 rounded-xl p-0.5"}`}
      style={{ borderColor: thinking ? undefined : `hsla(${hue}, 78%, 68%, .34)` }}
    >
      {thinking && <span className="absolute inset-0 animate-pulse rounded-[inherit] bg-cyan-300/10" />}
      <Image
        src="/images/bot-pet-skull-v2.png"
        alt=""
        width={size}
        height={size}
        draggable={false}
        className="relative h-full w-full object-contain transition-transform duration-300 hover:rotate-[-7deg] hover:scale-110"
        style={{ filter: `hue-rotate(${hue}deg) saturate(1.18) drop-shadow(0 4px 8px hsla(${hue}, 85%, 58%, .32))` }}
      />
    </span>
  );
}

export function BotStatusPill({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "live" | "warn" | "ok" | "danger";
  children: React.ReactNode;
}) {
  const tones = {
    neutral: "border-white/10 bg-white/[0.04] text-[color:var(--nx-text-dim)]",
    live: "border-cyan-300/25 bg-cyan-400/10 text-cyan-100",
    warn: "border-amber-300/25 bg-amber-400/10 text-amber-100",
    ok: "border-emerald-300/25 bg-emerald-400/10 text-emerald-100",
    danger: "border-rose-300/25 bg-rose-400/10 text-rose-100",
  } as const;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-wide ${tones[tone]}`}>
      {children}
    </span>
  );
}

const MessageCodeBlock = lazy(() => import("../chat/MessageCodeBlock"));

export function BotMessageBubble({ message, author }: { message: ChatMessage; author?: string }) {
  const [copied, setCopied] = useState(false);
  const mine = message.role === "user";
  return (
    <div className={`group flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`nx-bots-bubble max-w-[92%] min-w-0 rounded-2xl px-4 py-3 text-sm leading-6 sm:max-w-[78%] ${
          mine
            ? "rounded-br-md bg-[linear-gradient(160deg,#4b3d7a_0%,#393154_70%)] text-zinc-100 shadow-[inset_0_1px_0_rgba(255,255,255,.08)]"
            : "rounded-bl-md border border-white/[0.07] bg-[color:var(--nx-surface-2)] text-zinc-200 shadow-[inset_0_1px_0_rgba(255,255,255,.05)]"
        }`}
      >
        {!mine && author && <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-300/90">{author}</p>}
        <div className="nx-prose min-w-0 break-words [&_pre]:max-w-full [&_pre]:overflow-x-auto">
          <ReactMarkdown
            components={{
              code({ className, children, node: _node, ...props }) {
                const language = /language-([\w-]+)/.exec(className || "")?.[1];
                return language ? (
                  <Suspense fallback={<code className={className}>{children}</code>}>
                    <MessageCodeBlock language={language} code={String(children).replace(/\n$/, "")} theme="dark" />
                  </Suspense>
                ) : (
                  <code className={className} {...props}>{children}</code>
                );
              },
            }}
          >
            {message.content}
          </ReactMarkdown>
        </div>
        <div className="mt-1.5 flex items-center justify-end gap-2 text-[10px] text-zinc-500">
          <time>{formatBotTime(message.timestamp)}</time>
          <button
            type="button"
            aria-label="Copiar mensagem"
            onClick={() =>
              void navigator.clipboard.writeText(message.content).then(() => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1200);
              })
            }
            className="rounded-md p-1 text-zinc-500 opacity-70 transition hover:bg-white/5 hover:text-zinc-200 group-hover:opacity-100"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
        </div>
      </div>
    </div>
  );
}

export function AvatarStack({
  items,
  speakingId,
}: {
  items: Array<{ id: string; name: string }>;
  speakingId?: string | null;
}) {
  return (
    <div className="flex items-center" aria-hidden="true">
      {items.slice(0, 5).map((item, index) => (
        <span
          key={item.id}
          className={`-ml-2 first:ml-0 ring-2 ring-[color:var(--nx-bg)] ${speakingId === item.id ? "z-10 scale-105" : ""}`}
          style={{ zIndex: items.length - index }}
          title={item.name}
        >
          <BotAvatar name={item.name} id={item.id} compact thinking={speakingId === item.id} />
        </span>
      ))}
      {items.length > 5 && (
        <span className="-ml-1 rounded-lg border border-white/10 bg-white/[0.06] px-2 py-1 text-[10px] font-semibold text-zinc-300">
          +{items.length - 5}
        </span>
      )}
    </div>
  );
}
