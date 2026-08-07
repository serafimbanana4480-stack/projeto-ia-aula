"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Bot,
  CalendarDays,
  Clock3,
  Database,
  Gauge,
  Layers3,
  RefreshCw,
  Sparkles,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import AppShell from "../../components/layout/AppShell";
import { apiUrl, authHeaders } from "../../lib/api";
import { formatRelativeTime } from "../../lib/format";

type PeriodKey = "today" | "week" | "month" | "all";
type ChartRange = "7d" | "30d" | "all";

type PeriodStats = {
  total_tokens: number;
  tokens_in: number;
  tokens_out: number;
  requests: number;
  sessions: number;
  cost: number;
  avg_tokens_per_second: number;
};

type ModelUsage = {
  name: string;
  total_tokens: number;
  tokens_in: number;
  tokens_out: number;
  requests: number;
  cost: number;
  avg_tokens_per_second: number;
};

type TimelinePoint = {
  day: string;
  total_tokens: number;
  tokens_in: number;
  tokens_out: number;
  requests: number;
  avg_tokens_per_second: number;
};

type UsageOverview = {
  periods: Record<PeriodKey, PeriodStats>;
  timeline: TimelinePoint[];
  by_model: ModelUsage[];
  generated_at: number;
  currency: string;
  current?: {
    tokens_per_second: number;
    active_model?: string | null;
    timestamp?: number;
  };
};

const PERIODS: Array<{ key: PeriodKey; label: string; short: string }> = [
  { key: "today", label: "Hoje", short: "hoje" },
  { key: "week", label: "Esta semana", short: "esta semana" },
  { key: "month", label: "Este mês", short: "este mês" },
  { key: "all", label: "Desde sempre", short: "todo o histórico" },
];

const MODEL_COLORS = ["#8b7bff", "#31d6d1", "#ffb454", "#f27fa4", "#7ea7ff", "#9aa3b2"];

function compact(value: number | null | undefined): string {
  const n = Number(value || 0);
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("pt-PT");
}

function exact(value: number | null | undefined): string {
  return Number(value || 0).toLocaleString("pt-PT");
}

function dateLabel(day: string): string {
  const date = new Date(`${day}T12:00:00Z`);
  return date.toLocaleDateString("pt-PT", { day: "2-digit", month: "short" }).replace(".", "");
}

function percent(value: number): string {
  return `${Math.min(100, Math.max(0, value)).toFixed(value < 10 ? 1 : 0)}%`;
}

function Panel({
  title,
  subtitle,
  icon,
  action,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  icon: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`nx-surface nx-elev-1 rounded-2xl border border-nexus-border/70 ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-nexus-border/60 px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg border border-nexus-accent/25 bg-nexus-accent/10 text-nexus-accent-bright">
            {icon}
          </div>
          <div>
            <h2 className="text-sm font-semibold text-nexus-text">{title}</h2>
            {subtitle ? <p className="mt-0.5 text-[11px] text-nexus-muted">{subtitle}</p> : null}
          </div>
        </div>
        {action}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function MetricCard({ period, stats, active }: { period: (typeof PERIODS)[number]; stats: PeriodStats; active: boolean }) {
  return (
    <article
      className={`relative overflow-hidden rounded-2xl border p-4 transition-colors ${
        active
          ? "border-nexus-accent/45 bg-nexus-accent/[0.10] shadow-[0_0_24px_rgba(124,106,251,0.12)]"
          : "border-nexus-border/70 bg-nexus-card/70 hover:border-nexus-accent/25"
      }`}
    >
      {active ? <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-nexus-accent to-transparent" /> : null}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-nexus-muted">{period.label}</span>
        <CalendarDays className="h-3.5 w-3.5 text-nexus-faint" />
      </div>
      <div className="mt-3 flex items-end gap-2">
        <span className="font-mono text-2xl font-bold tabular-nums tracking-tight text-nexus-text">{compact(stats.total_tokens)}</span>
        <span className="mb-1 text-[11px] text-nexus-muted">tokens</span>
      </div>
      <div className="mt-3 flex items-center gap-3 text-[10px]">
        <span className="text-cyan-300">{compact(stats.tokens_in)} entrada</span>
        <span className="text-nexus-faint">/</span>
        <span className="text-nexus-accent-bright">{compact(stats.tokens_out)} saída</span>
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-nexus-border/60 pt-3 text-[10px] text-nexus-muted">
        <span>{exact(stats.requests)} pedidos</span>
        <span className="font-mono tabular-nums text-nexus-text">{stats.avg_tokens_per_second > 0 ? `${stats.avg_tokens_per_second.toFixed(1)} t/s méd.` : "—"}</span>
      </div>
    </article>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-[278px] flex-col items-center justify-center rounded-xl border border-dashed border-nexus-border bg-nexus-card/30 text-center">
      <BarChart3 className="h-6 w-6 text-nexus-faint" />
      <p className="mt-2 text-xs font-medium text-nexus-muted">Ainda não há dados para {label}</p>
      <p className="mt-1 max-w-xs text-[10px] leading-relaxed text-nexus-faint">A série começa a preencher assim que houver pedidos persistidos.</p>
    </div>
  );
}

function ChartTooltip({ active, payload, label, kind }: { active?: boolean; payload?: Array<{ value?: number; name?: string; color?: string }>; label?: string; kind: "tokens" | "speed" }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="nx-elev-2 rounded-xl border border-nexus-border bg-nexus-elevated px-3 py-2.5 shadow-xl">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">{label}</p>
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center justify-between gap-5 text-[11px]">
          <span className="flex items-center gap-1.5 text-nexus-muted"><span className="h-1.5 w-1.5 rounded-full" style={{ background: entry.color }} />{entry.name === "tokens_in" ? "Entrada" : entry.name === "tokens_out" ? "Saída" : "Média"}</span>
          <span className="font-mono font-semibold tabular-nums text-nexus-text">{kind === "speed" ? `${Number(entry.value || 0).toFixed(1)} t/s` : `${compact(Number(entry.value || 0))} tok`}</span>
        </div>
      ))}
    </div>
  );
}

export default function AnalyticsPage() {
  const [data, setData] = useState<UsageOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activePeriod, setActivePeriod] = useState<PeriodKey>("today");
  const [chartRange, setChartRange] = useState<ChartRange>("30d");
  const [lastRefresh, setLastRefresh] = useState<number | null>(null);

  const fetchOverview = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/metrics/usage/overview"), {
        headers: authHeaders(),
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const next = (await response.json()) as UsageOverview;
      setData(next);
      setLastRefresh(Date.now());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar as métricas");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOverview();
    const interval = setInterval(fetchOverview, 30_000);
    return () => clearInterval(interval);
  }, [fetchOverview]);

  const timeline = useMemo(() => {
    const source = data?.timeline ?? [];
    if (chartRange === "7d") return source.slice(-7);
    return source;
  }, [data, chartRange]);

  const models = useMemo(() => {
    const total = data?.periods.all.total_tokens ?? 0;
    return (data?.by_model ?? []).map((model, index) => ({
      ...model,
      share: total > 0 ? (model.total_tokens / total) * 100 : 0,
      color: MODEL_COLORS[index % MODEL_COLORS.length],
    }));
  }, [data]);

  const tokenMix = useMemo(() => {
    const stats = data?.periods[activePeriod];
    return stats
      ? [
          { name: "Entrada", value: stats.tokens_in, color: "#31d6d1" },
          { name: "Saída", value: stats.tokens_out, color: "#8b7bff" },
        ]
      : [];
  }, [activePeriod, data]);

  const selectedStats = data?.periods[activePeriod];
  const hasTimeline = timeline.some((point) => point.total_tokens > 0);
  const hasModels = models.some((model) => model.total_tokens > 0);
  const currentTps = data?.current?.tokens_per_second ?? 0;

  return (
    <AppShell title="Métricas" noPadding>
      <div className="min-h-full bg-nexus-bg pb-10">
        <header className="relative overflow-hidden border-b border-nexus-border/70 px-6 py-7 sm:px-8">
          <div className="pointer-events-none absolute inset-0 bg-nx-mesh opacity-60" />
          <div className="relative mx-auto flex max-w-[1480px] flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.18em] text-nexus-accent-bright">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                Telemetria de uso
              </div>
              <h1 className="nx-title mt-2 text-3xl font-bold tracking-tight sm:text-4xl">Métricas</h1>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-nexus-muted">Entende o ritmo do teu workspace: tokens consumidos, velocidade de geração e os modelos que mais trabalham.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card/70 px-3 py-2 text-[11px] text-nexus-muted">
                <Database className="h-3.5 w-3.5 text-emerald-400" /> Dados persistentes
              </div>
              <span className="text-[11px] text-nexus-faint">{lastRefresh ? `Atualizado ${formatRelativeTime(lastRefresh / 1000)}` : "A carregar…"}</span>
              <button type="button" onClick={() => { setLoading(true); fetchOverview(); }} className="flex items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card px-3 py-2 text-xs font-medium text-nexus-text transition hover:border-nexus-accent/45 hover:text-nexus-accent-bright" aria-label="Atualizar métricas">
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Atualizar
              </button>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1480px] space-y-5 px-6 py-6 sm:px-8">
          {error ? (
            <div className="flex items-center justify-between gap-4 rounded-xl border border-rose-400/25 bg-rose-400/10 px-4 py-3 text-xs text-rose-200">
              <span>Não foi possível carregar os dados de métricas ({error}).</span>
              <button type="button" className="font-semibold underline" onClick={() => { setLoading(true); fetchOverview(); }}>Tentar novamente</button>
            </div>
          ) : null}

          <section className="grid gap-4 xl:grid-cols-[1.08fr_2fr]" aria-label="Resumo de velocidade e tokens">
            <div className="relative overflow-hidden rounded-2xl border border-nexus-accent/35 bg-gradient-to-br from-[#211d4d] via-[#171a39] to-[#111827] p-5 shadow-[0_18px_45px_rgba(35,29,91,0.28)]">
              <div className="pointer-events-none absolute -right-14 -top-16 h-48 w-48 rounded-full bg-nexus-accent/20 blur-3xl" />
              <div className="relative flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-200/75"><Gauge className="h-3.5 w-3.5" /> Ritmo de geração</div>
                  <div className="mt-5 flex items-end gap-2">
                    <span className="font-mono text-5xl font-bold tabular-nums tracking-tight text-white">{currentTps.toFixed(1)}</span>
                    <span className="mb-2 text-sm text-indigo-200/70">tokens/s</span>
                  </div>
                  <p className="mt-2 text-xs text-indigo-100/60">média de {selectedStats?.avg_tokens_per_second?.toFixed(1) ?? "0.0"} t/s em {PERIODS.find((period) => period.key === activePeriod)?.short}</p>
                </div>
                <div className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-300">LIVE</div>
              </div>
              <div className="relative mt-7 grid grid-cols-2 gap-3 border-t border-white/10 pt-4">
                <div><p className="text-[10px] uppercase tracking-wider text-indigo-100/45">Modelo ativo</p><p className="mt-1 truncate font-mono text-xs font-semibold text-indigo-100">{data?.current?.active_model || "Automático"}</p></div>
                <div><p className="text-[10px] uppercase tracking-wider text-indigo-100/45">Pedidos no período</p><p className="mt-1 font-mono text-xs font-semibold text-indigo-100">{exact(selectedStats?.requests)}</p></div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {PERIODS.map((period) => (
                <button key={period.key} type="button" className="text-left" onClick={() => setActivePeriod(period.key)} aria-pressed={activePeriod === period.key}>
                  <MetricCard period={period} stats={data?.periods[period.key] ?? { total_tokens: 0, tokens_in: 0, tokens_out: 0, requests: 0, sessions: 0, cost: 0, avg_tokens_per_second: 0 }} active={activePeriod === period.key} />
                </button>
              ))}
            </div>
          </section>

          <section className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
            <Panel title="Consumo ao longo do tempo" subtitle="Entrada e saída de tokens por dia" icon={<Activity className="h-4 w-4" />} action={<div className="flex rounded-lg border border-nexus-border bg-nexus-card/60 p-0.5" role="tablist" aria-label="Janela do gráfico"><span className="sr-only">Janela:</span>{(["7d", "30d", "all"] as ChartRange[]).map((range) => <button key={range} type="button" role="tab" aria-selected={chartRange === range} onClick={() => setChartRange(range)} className={`rounded-md px-2.5 py-1 text-[10px] font-semibold transition ${chartRange === range ? "bg-nexus-accent/20 text-nexus-accent-bright" : "text-nexus-faint hover:text-nexus-text"}`}>{range === "7d" ? "7 dias" : range === "30d" ? "30 dias" : "Tudo"}</button>)}</div>}>
              {hasTimeline ? <div className="h-[278px] w-full"><ResponsiveContainer width="100%" height="100%"><AreaChart data={timeline} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}><defs><linearGradient id="tokensInGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#31d6d1" stopOpacity={0.34} /><stop offset="100%" stopColor="#31d6d1" stopOpacity={0.02} /></linearGradient><linearGradient id="tokensOutGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#8b7bff" stopOpacity={0.44} /><stop offset="100%" stopColor="#8b7bff" stopOpacity={0.04} /></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--nx-line)" strokeDasharray="4 6" /><XAxis dataKey="day" tickFormatter={dateLabel} tick={{ fill: "var(--nx-muted)", fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={28} /><YAxis tickFormatter={(value) => compact(value)} tick={{ fill: "var(--nx-muted)", fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip kind="tokens" />} /><Area type="monotone" dataKey="tokens_in" name="tokens_in" stackId="1" stroke="#31d6d1" strokeWidth={2} fill="url(#tokensInGradient)" /><Area type="monotone" dataKey="tokens_out" name="tokens_out" stackId="1" stroke="#8b7bff" strokeWidth={2} fill="url(#tokensOutGradient)" /></AreaChart></ResponsiveContainer></div> : <EmptyChart label="o período selecionado" />}
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-nexus-border/60 pt-3 text-[10px] text-nexus-muted"><div className="flex items-center gap-4"><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-cyan-300" />Entrada</span><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-nexus-accent" />Saída</span></div><span>O total geral permanece visível no resumo acima</span></div>
            </Panel>

            <Panel title="Velocidade média" subtitle="Tokens gerados por segundo" icon={<Zap className="h-4 w-4" />} action={<span className="rounded-full bg-emerald-400/10 px-2 py-1 text-[10px] font-semibold text-emerald-300">{selectedStats?.avg_tokens_per_second ? `${selectedStats.avg_tokens_per_second.toFixed(1)} t/s` : "Sem dados"}</span>}>
              {hasTimeline ? <div className="h-[278px] w-full"><ResponsiveContainer width="100%" height="100%"><LineChart data={timeline} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}><CartesianGrid vertical={false} stroke="var(--nx-line)" strokeDasharray="4 6" /><XAxis dataKey="day" tickFormatter={dateLabel} tick={{ fill: "var(--nx-muted)", fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={28} /><YAxis tickFormatter={(value) => `${value}`} tick={{ fill: "var(--nx-muted)", fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip content={<ChartTooltip kind="speed" />} /><Line type="monotone" dataKey="avg_tokens_per_second" name="avg_tokens_per_second" stroke="#ffb454" strokeWidth={2.5} dot={false} activeDot={{ r: 4, fill: "#ffb454", stroke: "#171a39", strokeWidth: 2 }} /></LineChart></ResponsiveContainer></div> : <EmptyChart label="a velocidade" />}
              <div className="mt-4 flex items-center justify-between border-t border-nexus-border/60 pt-3 text-[10px] text-nexus-muted"><span>Baseado em tokens de saída + latência</span><span className="flex items-center gap-1 text-amber-300"><ArrowUpRight className="h-3 w-3" /> picos destacam-se</span></div>
            </Panel>
          </section>

          <section className="grid gap-5 xl:grid-cols-[1.4fr_0.9fr]">
            <Panel title="Modelos mais usados" subtitle="Ranking por tokens consumidos desde sempre" icon={<Bot className="h-4 w-4" />} action={hasModels ? <span className="text-[10px] text-nexus-muted">{models.length} modelos identificados</span> : null}>
              {hasModels ? <div className="space-y-4">{models.slice(0, 6).map((model, index) => <div key={model.name} className="group"><div className="flex items-center justify-between gap-4"><div className="flex min-w-0 items-center gap-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-nexus-card font-mono text-[10px] font-bold text-nexus-muted">{String(index + 1).padStart(2, "0")}</span><div className="min-w-0"><p className="truncate text-xs font-semibold text-nexus-text" title={model.name}>{model.name}</p><p className="mt-0.5 text-[10px] text-nexus-muted">{exact(model.requests)} pedidos · {model.avg_tokens_per_second > 0 ? `${model.avg_tokens_per_second.toFixed(1)} t/s méd.` : "velocidade —"}</p></div></div><div className="shrink-0 text-right"><p className="font-mono text-xs font-semibold tabular-nums text-nexus-text">{compact(model.total_tokens)}</p><p className="mt-0.5 text-[10px] tabular-nums text-nexus-muted">{percent(model.share)}</p></div></div><div className="ml-9 mt-2 h-1.5 overflow-hidden rounded-full bg-nexus-card"><div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(2, model.share)}%`, background: `linear-gradient(90deg, ${model.color}, ${model.color}99)` }} /></div></div>)}</div> : <div className="flex min-h-[245px] flex-col items-center justify-center text-center"><Layers3 className="h-7 w-7 text-nexus-faint" /><p className="mt-3 text-xs font-medium text-nexus-muted">Nenhum modelo identificado</p><p className="mt-1 max-w-xs text-[10px] leading-relaxed text-nexus-faint">Os modelos aparecem aqui depois da primeira execução com uso de tokens persistido.</p></div>}
            </Panel>

            <Panel title="Composição do período" subtitle={`Entrada vs. saída · ${PERIODS.find((period) => period.key === activePeriod)?.label}`} icon={<BarChart3 className="h-4 w-4" />} action={<div className="flex gap-1">{PERIODS.slice(0, 3).map((period) => <button key={period.key} type="button" onClick={() => setActivePeriod(period.key)} className={`rounded-md px-2 py-1 text-[10px] ${activePeriod === period.key ? "bg-nexus-accent/20 text-nexus-accent-bright" : "text-nexus-faint hover:text-nexus-text"}`}>{period.key === "today" ? "Hoje" : period.key === "week" ? "7d" : "30d"}</button>)}</div>}>
              <div className="h-[205px]"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={tokenMix} dataKey="value" nameKey="name" innerRadius={58} outerRadius={82} paddingAngle={4} stroke="none">{tokenMix.map((entry) => <Cell key={entry.name} fill={entry.color} />)}</Pie><Tooltip formatter={(value: number) => `${compact(value)} tokens`} contentStyle={{ background: "var(--nx-elevated)", border: "1px solid var(--nx-line)", borderRadius: 10, fontSize: 11 }} /></PieChart></ResponsiveContainer></div>
              <div className="mt-1 grid grid-cols-2 gap-3">{tokenMix.map((entry) => { const total = (selectedStats?.total_tokens ?? 0) || 1; return <div key={entry.name} className="rounded-lg border border-nexus-border/60 bg-nexus-card/40 p-2.5"><div className="flex items-center gap-1.5 text-[10px] text-nexus-muted"><span className="h-2 w-2 rounded-full" style={{ background: entry.color }} />{entry.name}</div><p className="mt-1 font-mono text-sm font-semibold tabular-nums text-nexus-text">{compact(entry.value)}</p><p className="mt-0.5 text-[10px] text-nexus-faint">{percent((entry.value / total) * 100)}</p></div>; })}</div>
            </Panel>
          </section>

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Indicadores auxiliares">
            <div className="rounded-xl border border-nexus-border/70 bg-nexus-card/50 p-4"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-nexus-muted"><ArrowDownRight className="h-3.5 w-3.5 text-cyan-300" />Tokens de entrada</div><p className="mt-2 font-mono text-xl font-semibold tabular-nums text-nexus-text">{compact(selectedStats?.tokens_in)}</p><p className="mt-1 text-[10px] text-nexus-faint">{PERIODS.find((period) => period.key === activePeriod)?.short}</p></div>
            <div className="rounded-xl border border-nexus-border/70 bg-nexus-card/50 p-4"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-nexus-muted"><ArrowUpRight className="h-3.5 w-3.5 text-nexus-accent-bright" />Tokens de saída</div><p className="mt-2 font-mono text-xl font-semibold tabular-nums text-nexus-text">{compact(selectedStats?.tokens_out)}</p><p className="mt-1 text-[10px] text-nexus-faint">{PERIODS.find((period) => period.key === activePeriod)?.short}</p></div>
            <div className="rounded-xl border border-nexus-border/70 bg-nexus-card/50 p-4"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-nexus-muted"><Clock3 className="h-3.5 w-3.5 text-amber-300" />Pedidos processados</div><p className="mt-2 font-mono text-xl font-semibold tabular-nums text-nexus-text">{exact(selectedStats?.requests)}</p><p className="mt-1 text-[10px] text-nexus-faint">{exact(selectedStats?.sessions)} sessões no período</p></div>
            <div className="rounded-xl border border-nexus-border/70 bg-nexus-card/50 p-4"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-nexus-muted"><Sparkles className="h-3.5 w-3.5 text-emerald-300" />Custo estimado</div><p className="mt-2 font-mono text-xl font-semibold tabular-nums text-nexus-text">{selectedStats?.cost ? `$${selectedStats.cost.toFixed(4)}` : "$0.0000"}</p><p className="mt-1 text-[10px] text-nexus-faint">Estimativa · USD</p></div>
          </section>

          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-nexus-border/60 pt-4 text-[10px] text-nexus-faint"><span>As médias usam apenas respostas com latência registada.</span><span>Retenção visual: 30 dias · total acumulado: desde sempre</span></footer>
        </main>
      </div>
    </AppShell>
  );
}
