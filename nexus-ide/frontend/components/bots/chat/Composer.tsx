"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { ArrowUp, Paperclip, Square, X } from "lucide-react";
import { applyMention, mentionRange } from "./model";
import { IdentityMark } from "./identity";
import {
  COMPOSER_FIELD_MIN,
  composerFieldHeight,
  slashTokenAtCaret,
} from "./composerMetrics";
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

export interface ComposerModel {
  id: string;
  name: string;
  model: string;
  provider: string;
  project: string;
  status?: string;
}

function chipLabel(models: ComposerModel[]): string {
  if (models.length === 0) return "Sem modelo";
  const names = new Set(models.map((model) => model.model.trim()).filter(Boolean));
  if (names.size === 1) return [...names][0] ?? "Sem modelo";
  if (models.length === 1) return "Sem modelo";
  return `${models.length} modelos`;
}

function modelTooltip(models: ComposerModel[]): string {
  if (models.length === 0) return "Sem modelo";
  return models
    .map((model) => {
      const project = model.project || "Sem projeto selecionado";
      return `${model.name}: ${model.provider || "sem provedor"} · ${model.model || "sem modelo"} · ${project}`;
    })
    .join("\n");
}

function ModelChip({ models }: { models: ComposerModel[] }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const popoverId = useId();
  const label = chipLabel(models);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={root} className="relative shrink-0">
      <button
        type="button"
        className="nx-composer-chip"
        aria-label={`Modelo: ${label}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={popoverId}
        title={open ? undefined : modelTooltip(models)}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="truncate">{label}</span>
      </button>
      {open ? (
        <div id={popoverId} role="dialog" aria-label="Provedor e projeto" className="nx-composer-popover nx-composer-modelpop">
          {models.length === 0 ? <p className="px-3 py-2 text-[12px]">Sem modelo</p> : null}
          {models.map((model) => (
            <div key={model.id} className="nx-composer-modelrow">
              <p className="truncate text-[13px] font-medium">{model.name}</p>
              <p>Provedor: {model.provider || "não configurado"}</p>
              <p>Modelo: {model.model || "não configurado"}</p>
              <p>Projeto: {model.project || "Sem projeto selecionado"}</p>
              {model.status ? <p className="text-[color:var(--nx-text-faint)]">{model.status}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
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
  models = [],
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
  models?: ComposerModel[];
  sendLabel: string;
  stopLabel: string;
  focusTick?: number;
  maxLength?: number;
  /** Submit with the composed text (message + attached text files). */
  onSubmitText?: (text: string) => void;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const listId = useId();
  const keyboardId = useId();
  const hintId = useId();
  const footId = useId();
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const [focused, setFocused] = useState(false);
  const [grown, setGrown] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [notice, setNotice] = useState("");
  const range = agents.length > 0 ? mentionRange(value, caret) : null;
  const query = (range?.query ?? "").toLocaleLowerCase("pt");
  const matches = range ? agents.filter((agent) => agent.name.toLocaleLowerCase("pt").includes(query)).slice(0, 6) : [];
  const menuOpen = Boolean(range) && matches.length > 0;
  const slashOpen = !menuOpen && slashTokenAtCaret(value, caret);
  const ready = !disabled && (value.trim().length > 0 || files.length > 0);
  const remaining = typeof maxLength === "number" ? maxLength - value.length : null;
  const showCount = remaining !== null && remaining <= 400;
  const describedBy = [keyboardId, hint ? hintId : "", footnote ? footId : ""].filter(Boolean).join(" ");

  useLayoutEffect(() => {
    const node = area.current;
    if (!node) return;
    const fit = () => {
      const field = area.current;
      const box = shell.current;
      if (!field) return;
      const previous = field.getBoundingClientRect().height || COMPOSER_FIELD_MIN;
      field.style.transition = "none";
      field.style.height = "0px";
      const scroll = value.trim() ? field.scrollHeight : COMPOSER_FIELD_MIN;
      const fieldNow = field.offsetHeight;
      const shellNow = box?.offsetHeight ?? 0;
      const chrome = fieldNow > 0 && shellNow > fieldNow ? shellNow - fieldNow : 0;
      const next = composerFieldHeight(scroll, window.innerHeight, chrome);
      field.style.height = `${previous}px`;
      void field.offsetHeight;
      field.style.transition = "";
      field.style.height = `${next.height}px`;
      field.style.overflowY = next.overflow ? "auto" : "hidden";
      field.dataset.overflow = next.overflow ? "true" : "false";
      setGrown(next.height > COMPOSER_FIELD_MIN + 1);
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [value, files.length, notice]);

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

  const onKey = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
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

  const slashCopy = agents.length > 0
    ? "Nesta sala não há comandos /. Usa @ para mencionar um participante."
    : "Nesta sala não há comandos /.";

  return (
    <div data-testid="composer-dock" className="nx-composer-dock">
      <div className="nx-bot-read mx-auto">
        {hint ? <p id={hintId} className="sr-only">{hint}</p> : null}
        {footnote ? <p id={footId} className="sr-only">{footnote}</p> : null}
        <div ref={shell} className={`nx-bot-composer ${grown ? "is-grown" : ""}`}>
          {menuOpen && (
            <ul id={listId} role="listbox" aria-label="Mencionar participante" className="nx-composer-popover nx-composer-mention">
              <li className="nx-composer-pophead">Mencionar</li>
              {matches.map((agent, index) => (
                <li key={agent.id} role="option" aria-selected={index === active}>
                  <button
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(agent)}
                    className="nx-composer-mentionbtn"
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
          {slashOpen ? <p role="note" className="nx-composer-popover nx-composer-slash">{slashCopy}</p> : null}
          {files.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5 px-2 pt-2" aria-label="Ficheiros anexados">
              {files.map((file) => (
                <li key={`${file.name}-${file.size}`} className="inline-flex max-w-full items-center gap-1 rounded-full border border-[color:var(--nx-line)] bg-[color:var(--nx-surface-2)] px-2 py-0.5 text-[11px] text-[color:var(--nx-text-dim)]">
                  <span className="max-w-[12rem] truncate">{file.name}</span>
                  <button type="button" aria-label={`Remover ${file.name}`} onClick={() => setFiles((current) => current.filter((item) => item !== file))} className="rounded p-0.5 text-[color:var(--nx-text-faint)] hover:text-[color:var(--nx-text)]">
                    <X size={12} />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {notice ? <p role="status" className="px-3 pt-1 text-[11px] leading-4 text-[color:var(--nx-amber)]">{notice}</p> : null}
          <div className={`nx-composer-row ${grown ? "is-grown" : ""}`}>
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
            <button type="button" onClick={() => fileInput.current?.click()} disabled={disabled} aria-label="Anexar ficheiros de texto" className="nx-composer-icon">
              <Paperclip size={16} />
            </button>
            <textarea
              ref={area}
              aria-label={label}
              aria-describedby={describedBy}
              aria-keyshortcuts="Enter Shift+Enter"
              aria-autocomplete={menuOpen ? "list" : undefined}
              aria-controls={menuOpen ? listId : undefined}
              enterKeyHint="send"
              maxLength={maxLength}
              rows={1}
              value={value}
              disabled={disabled}
              placeholder={placeholder}
              title="Enter envia. Shift+Enter muda de linha."
              onChange={(event) => {
                onChange(event.target.value);
                setCaret(event.target.selectionStart ?? event.target.value.length);
              }}
              onKeyDown={onKey}
              onKeyUp={(event) => setCaret(event.currentTarget.selectionStart ?? 0)}
              onClick={(event) => setCaret(event.currentTarget.selectionStart ?? 0)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              className="nx-composer-field"
            />
            {models.length > 0 || !pill ? <ModelChip models={models} /> : <div className="min-w-0 shrink">{pill}</div>}
            {showCount ? <span className="nx-composer-count" aria-live="polite" aria-label={`${remaining} caracteres restantes`}>{remaining}</span> : null}
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => { if (busy) onStop?.(); else void submit(); }}
              disabled={!busy && (disabled || !ready)}
              aria-label={busy ? stopLabel : sendLabel}
              className={`nx-composer-go ${busy ? "is-stop" : ready ? "is-ready" : ""}`}
            >
              {busy ? <Square size={11} fill="currentColor" /> : <ArrowUp size={16} strokeWidth={2.4} />}
            </button>
          </div>
        </div>
        <p id={keyboardId} className={focused && !disabled && !busy ? "nx-composer-focusline" : "sr-only"}>
          Enter envia · Shift+Enter muda de linha.
        </p>
      </div>
    </div>
  );
}
