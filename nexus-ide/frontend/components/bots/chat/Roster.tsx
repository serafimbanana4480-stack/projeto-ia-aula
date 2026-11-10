"use client";

import type { ReactNode } from "react";
import { Pin, Search } from "lucide-react";
import { IdentityMark } from "./identity";

export function SectionLabel({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 px-2 pb-1 pt-3">
      <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-[color:var(--nx-text-faint)]">{children}</p>
      {aside}
    </div>
  );
}

export function RosterSearch({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="relative block">
      <Search size={14} className="pointer-events-none absolute left-2.5 top-2.5 text-[color:var(--nx-text-faint)]" />
      <input
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={label}
        className="h-9 w-full rounded-lg border border-[color:var(--nx-line)] bg-[color:var(--nx-bg)] pl-8 pr-2 text-[13px] text-[color:var(--nx-text)] outline-none placeholder:text-[color:var(--nx-text-faint)] focus:border-[color:var(--nx-accent)]"
      />
    </label>
  );
}

export function RosterRow({
  id,
  name,
  role,
  chip,
  preview,
  time,
  active,
  live,
  warn,
  down,
  pinned,
  unread,
  onSelect,
  onPin,
}: {
  id: string;
  name: string;
  role: string;
  chip?: string;
  preview: string;
  time?: string;
  active?: boolean;
  live?: boolean;
  warn?: boolean;
  down?: boolean;
  pinned?: boolean;
  unread?: boolean;
  onSelect: () => void;
  onPin?: () => void;
}) {
  return (
    <div className={`group/row flex items-stretch rounded-lg ${active ? "bg-[color:var(--nx-surface-2)] shadow-[inset_2px_0_0_var(--nx-accent)]" : "hover:bg-[color:var(--nx-surface-2)]"}`}>
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        className="flex min-w-0 flex-1 items-start gap-2.5 px-2 py-2 text-left"
      >
        <IdentityMark id={id} name={name} size={34} live={live} tone={live ? "live" : down ? "down" : warn ? "warn" : "idle"} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[13px] font-medium tracking-tight text-[color:var(--nx-text)]">{name}</span>
            {time ? <time className="shrink-0 text-[10px] text-[color:var(--nx-text-faint)]">{time}</time> : null}
          </span>
          <span className="mt-0.5 flex items-center gap-1.5">
            <span className="truncate text-[11px] text-[color:var(--nx-text-dim)]">{role}</span>
            {chip ? (
              <span className="shrink-0 rounded-md border border-[color:var(--nx-line)] px-1.5 py-px text-[10px] text-[color:var(--nx-text-faint)]">{chip}</span>
            ) : null}
            {unread ? <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-[color:var(--nx-accent)]" title="Atividade por ler" /> : null}
          </span>
          <span className="mt-0.5 block truncate text-[12px] leading-4 text-[color:var(--nx-text-faint)]">{preview}</span>
        </span>
      </button>
      {onPin ? (
        <button
          type="button"
          aria-label={pinned ? "Remover fixação" : "Fixar"}
          aria-pressed={pinned}
          onClick={onPin}
          className={`mr-1 self-center rounded-md p-1.5 text-[color:var(--nx-text-faint)] hover:bg-[color:var(--nx-surface-3)] hover:text-[color:var(--nx-text)] ${pinned ? "text-[color:var(--nx-accent-bright)]" : "sm:opacity-0 sm:group-hover/row:opacity-100 sm:focus:opacity-100"}`}
        >
          <Pin size={13} fill={pinned ? "currentColor" : "none"} />
        </button>
      ) : null}
    </div>
  );
}
