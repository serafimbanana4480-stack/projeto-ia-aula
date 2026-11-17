"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Paperclip, Send, Square, X } from "lucide-react";
import { applyMention, mentionRange } from "./model";
import { IdentityMark } from "./identity";
import {
  MAX_CHAT_ATTACHMENTS,
  composeChatMessageWithAttachments,
  getChatAttachmentRejection,
} from "../../../lib/chatAttachments";
import { stripAnsiCodes } from "../../../lib/utils";

export interface MentionAgent {
  id: string;
  name: string;
  role?: string;
}

export function RoomComposer({
  label,
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  disabled,
  placeholder,
  hint,
  footnote,
  agents = [],
  pill,
  sendLabel,
  stopLabel,
  focusTick = 0,
  maxLength,
  onSubmitText,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  busy: boolean;
  disabled: boolean;
  placeholder: string;
  hint?: string;
  footnote?: string;
  agents?: MentionAgent[];
  pill?: ReactNode;
  sendLabel: string;
  stopLabel: string;
  focusTick?: number;
  maxLength?: number;
  /** Submit with the composed text (message + attached text files). */
  onSubmitText?: (text: string) => void;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [notice, setNotice] = useState("");
  const range = agents.length > 0 ? mentionRange(value, caret) : null;
  const query = (range?.query ?? "").toLocaleLowerCase("pt");
  const matches = range ? agents.filter((agent) => agent.name.toLocaleLowerCase("pt").includes(query)).slice(0, 6) : [];
  const menuOpen = Boolean(range) && matches.length > 0;

  useEffect(() => {
    const node = area.current;
    if (!node) return;
    node.style.height = "0px";
    node.style.height = `${Math.min(node.scrollHeight, 168)}px`;
  }, [value]);

  useEffect(() => {
    if (focusTick > 0) area.current?.focus();
  }, [focusTick]);

  useEffect(() => {
    setActive(0);
  }, [query, menuOpen]);

  const choose = (agent: MentionAgent) => {
    const next = applyMention(value, caret, agent.name);
    if (!next) return;
    onChange(next.value);
    setCaret(next.caret);
    requestAnimationFrame(() => {
      const node = area.current;
      if (!node) return;
      node.focus();
      node.setSelectionRange(next.caret, next.caret);
    });
  };

  const addFiles = (incoming: FileList | null) => {
    if (!incoming || incoming.length === 0) return;
    const accepted: File[] = [];
    const rejected = new Set<string>();
    for (const file of Array.from(incoming)) {
      if (files.length + accepted.length >= MAX_CHAT_ATTACHMENTS) {
        rejected.add("too_many");
        break;
      }
      const reason = getChatAttachmentRejection(file);
      if (reason) {
        rejected.add(reason);
        continue;
      }
      accepted.push(file);
    }
    if (accepted.length) setFiles((current) => [...current, ...accepted]);
    if (rejected.size) {
      const reasons = [
        rejected.has("sensitive") ? "Ficheiros com nomes de credenciais foram bloqueados." : "",
        rejected.has("too_large") ? "Cada ficheiro pode ter no máximo 50 KB." : "",
        rejected.has("unsupported") ? "Só ficheiros de texto são enviados; imagens e binários ainda não são suportados." : "",
        rejected.has("too_many") ? `O limite é ${MAX_CHAT_ATTACHMENTS} ficheiros por mensagem.` : "",
      ].filter(Boolean);
      setNotice(reasons.join(" "));
    } else {
      setNotice("");
    }
  };

  const submit = async () => {
    if (disabled || busy) return;
    const text = value.trim();
    if (!text && files.length === 0) return;
    if (files.length === 0) {
      onSubmit();
      return;
    }
    try {
      const composed = await composeChatMessageWithAttachments(text, files, stripAnsiCodes);
      setFiles([]);
      setNotice("");
      if (onSubmitText) onSubmitText(composed);
      else onSubmit();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "Não foi possível anexar os ficheiros.");
    }
  };

  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (menuOpen && event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index + 1) % matches.length);
      return;
    }
    if (menuOpen && event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index - 1 + matches.length) % matches.length);
      return;
    }
    if (menuOpen && (event.key === "Enter" || event.key === "Tab")) {
      event.preventDefault();
      const agent = matches[active];
      if (agent) choose(agent);
      return;
    }
    if (menuOpen && event.key === "Escape") {
      event.preventDefault();
      const node = area.current;
      const at = node?.selectionStart ?? value.length;
      onChange(`${value.slice(0, Math.max(0, at - (range?.query.length ?? 0) - 1))}${value.slice(at)}`);
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <div className="border-t border-[color:var(--nx-line)] bg-[color:var(--nx-bg)] px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:px-5">
      <div className="nx-bot-read mx-auto">
        {hint ? <p className="mb-2 text-[11px] leading-5 text-[color:var(--nx-text-faint)]">{hint}</p> : null}
        <div className="nx-bot-composer relative rounded-2xl border border-[color:var(--nx-line-strong)] bg-[color:var(--nx-surface-1)] focus-within:border-[color:var(--nx-accent)]">
          {menuOpen && (
            <ul id={listId} role="listbox" aria-label="Mencionar participante" className="absolute bottom-[calc(100%+6px)] left-2 z-20 w-[min(100%-1rem,280px)] overflow-hidden rounded-xl border border-[color:var(--nx-line-strong)] bg-[color:var(--nx-surface-2)] py-1 shadow-[var(--nx-shadow-2)]">
              {matches.map((agent, index) => (
                <li key={agent.id} role="option" aria-selected={index === active}>
                  <button
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(agent)}
                    className={`flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px] ${index === active ? "bg-[color:var(--nx-surface-3)]" : ""}`}
                  >
                    <IdentityMark id={agent.id} name={agent.name} size={22} />
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{agent.name}</span>
                      {agent.role ? <span className="block truncate text-[11px] text-[color:var(--nx-text-faint)]">{agent.role}</span> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <textarea
            ref={area}
            aria-label={label}
            maxLength={maxLength}
            rows={1}
            value={value}
            disabled={disabled}
            placeholder={placeholder}
            onChange={(event) => {
              onChange(event.target.value);
              setCaret(event.target.selectionStart ?? event.target.value.length);
            }}
            onKeyDown={onKey}
            onKeyUp={(event) => setCaret(event.currentTarget.selectionStart ?? 0)}
            onClick={(event) => setCaret(event.currentTarget.selectionStart ?? 0)}
            className="max-h-40 min-h-12 w-full resize-none bg-transparent px-3.5 py-3 text-[15px] leading-6 text-[color:var(--nx-text)] outline-none placeholder:text-[color:var(--nx-text-faint)] disabled:opacity-50"
          />
          {files.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5 px-3 pb-1" aria-label="Ficheiros anexados">
              {files.map((file) => (
                <li key={`${file.name}-${file.size}`} className="inline-flex max-w-full items-center gap-1 rounded-lg border border-[color:var(--nx-line)] bg-[color:var(--nx-surface-2)] px-2 py-1 text-[11px] text-[color:var(--nx-text-dim)]">
                  <span className="max-w-[12rem] truncate">{file.name}</span>
                  <button type="button" aria-label={`Remover ${file.name}`} onClick={() => setFiles((current) => current.filter((item) => item !== file))} className="rounded p-0.5 text-[color:var(--nx-text-faint)] hover:text-[color:var(--nx-text)]">
                    <X size={12} />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {notice ? <p role="status" className="px-3 pb-1 text-[11px] leading-4 text-[color:var(--nx-amber)]">{notice}</p> : null}
          <div className="flex items-center gap-2 px-2 pb-2">
            <input
              ref={fileInput}
              type="file"
              multiple
              className="hidden"
              aria-hidden="true"
              tabIndex={-1}
              onChange={(event) => {
                addFiles(event.target.files);
                event.target.value = "";
              }}
            />
            <button type="button" onClick={() => fileInput.current?.click()} disabled={disabled} aria-label="Anexar ficheiros de texto" className="rounded-xl p-2 text-[color:var(--nx-text-faint)] hover:bg-[color:var(--nx-surface-3)] hover:text-[color:var(--nx-text)] disabled:opacity-40">
              <Paperclip size={16} />
            </button>
            <div className="min-w-0 flex-1">{pill}</div>
            {busy ? (
              <button type="button" onClick={onStop} aria-label={stopLabel} className="rounded-xl bg-[color:var(--nx-surface-4)] p-2.5 text-[color:var(--nx-text)] hover:bg-[color:var(--nx-surface-3)]">
                <Square size={15} fill="currentColor" />
              </button>
            ) : (
              <button type="button" onClick={() => void submit()} disabled={disabled || (!value.trim() && files.length === 0)} aria-label={sendLabel} className="rounded-xl bg-[color:var(--nx-accent)] p-2.5 text-white hover:bg-[color:var(--nx-accent-bright)] disabled:opacity-30">
                <Send size={15} />
              </button>
            )}
          </div>
        </div>
        {footnote ? <p className="pt-2 text-[11px] text-[color:var(--nx-text-faint)]">{footnote}</p> : null}
      </div>
    </div>
  );
}
