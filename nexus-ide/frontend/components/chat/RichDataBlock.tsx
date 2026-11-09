"use client";

import type { ComponentType } from "react";
import {
  AlertTriangle,
  BarChart3,
  Bot,
  CheckCircle2,
  Code2,
  Database,
  FileText,
  Globe,
  Image as ImageIcon,
  ListTodo,
  Search,
  Shield,
  Sparkles,
  Terminal,
} from "lucide-react";

import type {
  RichBlock,
  RichIconName,
  RichStatus,
  RichTone,
} from "../../lib/richBlocks";

const ICONS: Record<RichIconName, ComponentType<{ className?: string }>> = {
  chart: BarChart3,
  globe: Globe,
  code: Code2,
  image: ImageIcon,
  search: Search,
  bot: Bot,
  file: FileText,
  check: CheckCircle2,
  alert: AlertTriangle,
  database: Database,
  terminal: Terminal,
  spark: Sparkles,
  list: ListTodo,
  shield: Shield,
};

const STATUS_CLASS: Record<RichStatus, string> = {
  ok: "bg-emerald-400/12 text-nexus-accent2",
  pending: "bg-amber-400/12 text-nexus-accent3",
  warn: "bg-amber-400/12 text-nexus-accent3",
  fail: "bg-rose-400/12 text-nexus-accent4",
  info: "bg-nexus-bg text-nexus-muted",
};

const TONE_CLASS: Record<RichTone, string> = {
  info: "border-nexus-accent/40 bg-nexus-accent/8 text-nexus-text",
  warning: "border-amber-400/40 bg-amber-400/8 text-nexus-text",
  success: "border-emerald-400/40 bg-emerald-400/8 text-nexus-text",
  danger: "border-rose-400/40 bg-rose-400/8 text-nexus-text",
};

function formatAmount(value: number): string {
  return new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 1 }).format(value);
}

function surface(className: string) {
  return `my-3 overflow-hidden rounded-xl border border-nexus-border/50 bg-nexus-card/30 ${className}`;
}

function StatsBlock({ block }: { block: Extract<RichBlock, { kind: "stats" }> }) {
  return (
    <div data-testid="rich-stats" className={surface("grid gap-px sm:grid-cols-2")}>
      {block.items.map((item) => (
        <div key={`${item.label}-${item.value}`} className="px-4 py-3">
          <p className="text-[28px] font-semibold leading-none tracking-tight text-nexus-text tabular-nums">
            {item.value}
          </p>
          <p className="mt-1.5 text-[12px] text-nexus-muted">{item.label}</p>
          {item.hint ? <p className="mt-0.5 text-[11px] text-nexus-faint">{item.hint}</p> : null}
        </div>
      ))}
    </div>
  );
}

function ChartBlock({ block }: { block: Extract<RichBlock, { kind: "chart" }> }) {
  const peak = Math.max(...block.bars.map((bar) => bar.value), 0);
  const summary = block.bars.map((bar) => `${bar.label} ${formatAmount(bar.value)}`).join(", ");
  return (
    <figure data-testid="rich-chart" className={surface("px-4 py-3")} aria-label={block.title}>
      <figcaption className="text-[13px] font-medium text-nexus-text">{block.title}</figcaption>
      <div className="mt-3 space-y-2" role="img" aria-label={summary}>
        {block.bars.map((bar) => {
          const width = peak === 0 || bar.value === 0 ? 0 : Math.max(2, (bar.value / peak) * 100);
          return (
            <div key={bar.label} className="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto] items-center gap-2">
              <span className="truncate text-[12px] text-nexus-muted">{bar.label}</span>
              <span className="h-2 overflow-hidden rounded-full bg-nexus-bg">
                <span className="block h-full rounded-full bg-nexus-accent" style={{ width: `${width}%` }} />
              </span>
              <span className="text-[12px] tabular-nums text-nexus-text">{formatAmount(bar.value)}</span>
            </div>
          );
        })}
      </div>
      {block.unit ? <p className="mt-2 text-[11px] text-nexus-faint">{block.unit}</p> : null}
    </figure>
  );
}

function StatusBlock({ block }: { block: Extract<RichBlock, { kind: "status" }> }) {
  return (
    <div data-testid="rich-status" className={surface("px-4 py-2")}>
      {block.title ? <p className="py-1.5 text-[13px] font-medium text-nexus-text">{block.title}</p> : null}
      <ul>
        {block.rows.map((row) => (
          <li key={`${row.name}-${row.label}`} className="flex items-center gap-3 border-t border-nexus-border/30 py-2 first:border-t-0">
            <span className="min-w-0 flex-1 truncate text-[13px] text-nexus-text">{row.name}</span>
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_CLASS[row.state]}`}>
              {row.label}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CardsBlock({ block }: { block: Extract<RichBlock, { kind: "cards" }> }) {
  return (
    <div data-testid="rich-cards" className="my-3 grid gap-2 sm:grid-cols-2">
      {block.items.map((item) => {
        const Icon = ICONS[item.icon];
        return (
          <div key={`${item.icon}-${item.title}`} className="rounded-xl border border-nexus-border/50 bg-nexus-card/30 px-3 py-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-nexus-accent/12 text-nexus-accent-bright">
              <Icon className="h-4 w-4" aria-hidden="true" />
            </span>
            <p className="mt-2 text-[13px] font-medium text-nexus-text">{item.title}</p>
            {item.text ? <p className="mt-1 text-[12px] leading-relaxed text-nexus-muted">{item.text}</p> : null}
          </div>
        );
      })}
    </div>
  );
}

function CalloutBlock({ block }: { block: Extract<RichBlock, { kind: "callout" }> }) {
  return (
    <aside data-testid="rich-callout" data-tone={block.tone} className={`my-3 rounded-r-xl border-l-2 px-3 py-2.5 ${TONE_CLASS[block.tone]}`}>
      {block.title ? <p className="text-[13px] font-medium">{block.title}</p> : null}
      <p className={`${block.title ? "mt-1" : ""} text-[13px] leading-relaxed text-nexus-text/90`}>{block.text}</p>
    </aside>
  );
}

function SourcesBlock({ block }: { block: Extract<RichBlock, { kind: "sources" }> }) {
  return (
    <ul data-testid="rich-sources" className={surface("divide-y divide-nexus-border/30")}>
      {block.items.map((item) => {
        let host = item.url;
        try {
          host = new URL(item.url).host;
        } catch {
          host = item.url;
        }
        return (
          <li key={item.url}>
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="flex items-start gap-2.5 px-3 py-2.5 hover:bg-nexus-bg/40"
            >
              <Globe className="mt-0.5 h-3.5 w-3.5 shrink-0 text-nexus-accent" aria-hidden="true" />
              <span className="min-w-0">
                <span className="block truncate text-[13px] text-nexus-text">{item.title}</span>
                <span className="block truncate text-[11px] text-nexus-faint">
                  {host}
                  {item.note ? ` · ${item.note}` : ""}
                </span>
              </span>
            </a>
          </li>
        );
      })}
    </ul>
  );
}

function FlowBlock({ block }: { block: Extract<RichBlock, { kind: "flow" }> }) {
  return (
    <div data-testid="rich-flow" className={surface("px-4 py-3")}>
      {block.title ? <p className="mb-2 text-[13px] font-medium text-nexus-text">{block.title}</p> : null}
      <ol className="space-y-0">
        {block.nodes.map((node, index) => (
          <li key={`${node.label}-${index}`} className="relative pl-5">
            {index < block.nodes.length - 1 ? (
              <span className="absolute left-[5px] top-3 h-full w-px bg-nexus-border/70" aria-hidden="true" />
            ) : null}
            <span className="absolute left-0 top-1.5 h-2.5 w-2.5 rounded-full border border-nexus-accent bg-nexus-panel" aria-hidden="true" />
            <p className="text-[13px] text-nexus-text">{node.label}</p>
            {node.hint ? <p className="pb-2 text-[11px] text-nexus-faint">{node.hint}</p> : <span className="block pb-2" />}
          </li>
        ))}
      </ol>
    </div>
  );
}

function TableBlock({ block }: { block: Extract<RichBlock, { kind: "table" }> }) {
  return (
    <div data-testid="rich-table" className="my-3 overflow-x-auto rounded-xl border border-nexus-border/50">
      <table className="w-full border-collapse text-left text-[13px]">
        <thead>
          <tr>
            {block.columns.map((column) => (
              <th key={column} scope="col" className="bg-nexus-bg/60 px-3 py-2 font-medium text-nexus-muted">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, index) => (
            <tr key={index} className="border-t border-nexus-border/30">
              {row.map((cell, cellIndex) => (
                <td key={`${block.columns[cellIndex] ?? cellIndex}-${index}`} className="px-3 py-2 text-nexus-text">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MeterBlock({ block }: { block: Extract<RichBlock, { kind: "meter" }> }) {
  const percent = Math.round((block.value / block.max) * 100);
  return (
    <div data-testid="rich-meter" className={surface("px-4 py-3")}>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[13px] text-nexus-muted">{block.label}</p>
        <p className="text-[22px] font-semibold tabular-nums tracking-tight text-nexus-text">{percent}%</p>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-nexus-bg" aria-hidden="true">
        <div className="h-full rounded-full bg-nexus-accent2" style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-1.5 text-[11px] tabular-nums text-nexus-faint">
        {formatAmount(block.value)} de {formatAmount(block.max)}
      </p>
      {block.parts.length > 0 ? (
        <div className="mt-3 grid grid-cols-2 gap-3">
          {block.parts.map((part) => (
            <div key={part.label}>
              <p className="text-[18px] font-semibold tabular-nums text-nexus-text">{part.value}</p>
              <p className="text-[11px] text-nexus-muted">{part.label}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function RichDataBlock({ block }: { block: RichBlock }) {
  switch (block.kind) {
    case "stats":
      return <StatsBlock block={block} />;
    case "chart":
      return <ChartBlock block={block} />;
    case "status":
      return <StatusBlock block={block} />;
    case "cards":
      return <CardsBlock block={block} />;
    case "callout":
      return <CalloutBlock block={block} />;
    case "sources":
      return <SourcesBlock block={block} />;
    case "flow":
      return <FlowBlock block={block} />;
    case "meter":
      return <MeterBlock block={block} />;
    case "table":
      return <TableBlock block={block} />;
    default:
      return null;
  }
}
