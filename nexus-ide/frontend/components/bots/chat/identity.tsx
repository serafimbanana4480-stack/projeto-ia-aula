"use client";

import type { ReactNode } from "react";

const HUES = [262, 214, 168, 32, 348, 198, 250, 18];

export function hueFromSeed(id: string): number {
  let hash = 0;
  for (const character of id) hash = (hash * 33 + character.charCodeAt(0)) | 0;
  return HUES[Math.abs(hash) % HUES.length] ?? 262;
}

function sigilIndex(id: string): number {
  let hash = 2166136261;
  for (const character of id) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % 8;
}

function Sigil({ index, ink }: { index: number; ink: string }) {
  const common = { fill: "none", stroke: ink, strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const marks: ReactNode[] = [
    <path key="a" {...common} d="M8 21 L16 9 L24 21 M11.5 21 H20.5" />,
    <g key="b"><circle {...common} cx="16" cy="16" r="6.5" /><path {...common} d="M9 16 H23" /></g>,
    <path key="c" {...common} d="M10 22 V14 M16 22 V9 M22 22 V16" />,
    <g key="d"><ellipse {...common} cx="16" cy="16" rx="8" ry="4.5" /><circle cx="22" cy="14" r="1.4" fill={ink} stroke="none" /></g>,
    <path key="e" {...common} d="M9 12 H21 M10 16 H22 M9 20 H20" />,
    <g key="f"><circle cx="11" cy="12" r="1.5" fill={ink} /><circle cx="21" cy="13" r="1.5" fill={ink} /><circle cx="16" cy="21" r="1.5" fill={ink} /><path {...common} d="M11 12 L21 13 L16 21 Z" /></g>,
    <path key="g" {...common} d="M12 9 H9 V23 H12 M20 9 H23 V23 H20" />,
    <path key="h" {...common} d="M16 8 L23 16 L16 24 L9 16 Z" />,
  ];
  return <g>{marks[index]}</g>;
}

export function IdentityMark({
  id,
  name,
  size = 36,
  live = false,
  tone = "idle",
  labelled = false,
}: {
  id: string;
  name: string;
  size?: number;
  live?: boolean;
  tone?: "idle" | "live" | "warn" | "down";
  labelled?: boolean;
}) {
  const hue = hueFromSeed(id || name || "nexus");
  const wash = `hsl(${hue} 42% 24%)`;
  const ink = `hsl(${hue} 62% 84%)`;
  const line = `hsl(${hue} 40% 52%)`;
  const dot = live || tone === "live" ? "var(--nx-emerald)" : tone === "warn" ? "var(--nx-amber)" : tone === "down" ? "var(--nx-rose)" : "var(--nx-text-faint)";
  return (
    <span
      data-sigil={id || name}
      className="relative inline-flex shrink-0"
      style={{ width: size, height: size }}
      role={labelled ? "img" : undefined}
      aria-label={labelled ? `Identidade de ${name}` : undefined}
      aria-hidden={labelled ? undefined : true}
    >
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="10" fill={wash} />
        <rect x="0.6" y="0.6" width="30.8" height="30.8" rx="9.4" fill="none" stroke={line} />
        <Sigil index={sigilIndex(id || name || "nexus")} ink={ink} />
      </svg>
      <span
        className={`absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full ring-2 ring-[color:var(--nx-bg)] ${live ? "nx-bot-pulse" : ""}`}
        style={{ background: dot, width: Math.max(7, size * 0.22), height: Math.max(7, size * 0.22) }}
      />
    </span>
  );
}

export function StackedMarks({
  people,
  liveId,
}: {
  people: Array<{ id: string; name: string }>;
  liveId?: string | null;
}) {
  const shown = people.slice(0, 4);
  return (
    <div className="flex items-center" aria-hidden="true">
      {shown.map((person, index) => (
        <span key={person.id} className="-ml-2 first:ml-0 rounded-[10px] ring-2 ring-[color:var(--nx-bg)]" style={{ zIndex: shown.length - index }}>
          <IdentityMark id={person.id} name={person.name} size={28} live={liveId === person.id} tone={liveId === person.id ? "live" : "idle"} />
        </span>
      ))}
      {people.length > shown.length && (
        <span className="-ml-1 rounded-full border border-[color:var(--nx-line)] px-1.5 py-0.5 text-[10px] text-[color:var(--nx-text-dim)]">
          +{people.length - shown.length}
        </span>
      )}
    </div>
  );
}
