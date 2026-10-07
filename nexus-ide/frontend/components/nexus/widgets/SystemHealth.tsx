"use client";

import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Clock3, HardDrive, Layers, Zap } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useSystemStore, type SystemMetricField } from "../../../stores/useSystemStore";

interface ChartPoint {
  t: number;
  cpu: number | null;
  memory: number | null;
}

function GaugeRing({
  value,
  color,
  label,
}: {
  value: number | null;
  color: string;
  label: string;
}) {
  const size = 60;
  const r = (size / 2) - 6;
  const circumference = 2 * Math.PI * r;
  const percent = value === null ? 0 : Math.min(100, Math.max(0, value));
  const dash = (percent / 100) * circumference;

  return (
    <div className="flex min-w-0 flex-col items-center gap-1.5">
      <div className="relative h-[60px] w-[60px]" aria-label={`${label}: ${value === null ? "sem dados" : `${percent.toFixed(0)}%`}`}>
        <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full -rotate-90" aria-hidden="true">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1e293b" strokeWidth="5" />
          {value !== null && (
            <motion.circle
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={color}
              strokeWidth="5"
              strokeDasharray={`${dash} ${circumference}`}
              strokeLinecap="round"
              initial={{ strokeDasharray: `0 ${circumference}` }}
              animate={{ strokeDasharray: `${dash} ${circumference}` }}
              transition={{ duration: 0.7, ease: "easeOut" }}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xs font-semibold tabular-nums text-slate-100">
            {value === null ? "—" : `${percent.toFixed(0)}%`}
          </span>
        </div>
      </div>
      <span className="truncate text-[10px] font-medium text-slate-400">{label}</span>
    </div>
  );
}

function MetricRow({
  icon: Icon,
  label,
  value,
  unit,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 border-b border-slate-800/60 py-2 last:border-0">
      <span className="flex min-w-0 items-center gap-2 text-[11px] text-slate-400">
        <Icon size={13} className="shrink-0 text-slate-500" />
        <span className="truncate">{label}</span>
      </span>
      <span className="shrink-0 font-mono text-[11px] font-medium tabular-nums text-slate-200">
        {value}{unit ? <span className="ml-1 text-slate-500">{unit}</span> : null}
      </span>
    </div>
  );
}

function formatMetric(
  value: number,
  isMeasured: (field: SystemMetricField) => boolean,
  field: SystemMetricField,
  digits = 0,
): string {
  return isMeasured(field) ? value.toFixed(digits) : "—";
}

export default function SystemHealth() {
  const metrics = useSystemStore((state) => state.metrics);
  const measuredMetrics = useSystemStore((state) => state.measuredMetrics);
  const hasTelemetry = useSystemStore((state) => state.hasTelemetry);
  const isLive = useSystemStore((state) => state.isLive);
  const isLoading = useSystemStore((state) => state.isLoading);
  const error = useSystemStore((state) => state.error);
  const [chartHistory, setChartHistory] = useState<ChartPoint[]>([]);

  const isMeasured = (field: SystemMetricField) => measuredMetrics[field] === true;
  const cpu = isMeasured("cpuUsage") ? metrics.cpuUsage : null;
  const memory = isMeasured("memoryUsage") ? metrics.memoryUsage : null;
  const disk = isMeasured("diskUsage") ? metrics.diskUsage : null;

  useEffect(() => {
    if (!isLive || !hasTelemetry || (cpu === null && memory === null)) return;
    const point: ChartPoint = {
      t: metrics.timestamp ?? Date.now(),
      cpu,
      memory,
    };
    setChartHistory((previous) => {
      if (previous.at(-1)?.t === point.t) return previous;
      return [...previous, point].slice(-20);
    });
  }, [cpu, hasTelemetry, isLive, memory, metrics.timestamp]);

  const chartData = chartHistory.map((point, index) => ({ ...point, t: index }));
  const chartReady = chartData.length >= 2;
  const stateLabel = isLoading
    ? "A atualizar"
    : isLive
      ? hasTelemetry ? "API ligada · telemetria disponível" : "API ligada · sem telemetria"
      : hasTelemetry ? "Sem ligação · dados antigos" : "Sem ligação";
  const stateClass = isLoading
    ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
    : isLive && hasTelemetry
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
      : isLive
        ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
        : "border-slate-700 bg-slate-800/60 text-slate-400";

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Saúde do sistema">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/70 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Activity size={15} className="shrink-0 text-emerald-400" />
          <h2 className="truncate text-xs font-semibold text-slate-100">Recursos do sistema</h2>
        </div>
        <span className={`max-w-full truncate rounded-full border px-2 py-1 text-[9px] font-medium ${stateClass}`}>
          {stateLabel}
        </span>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 sm:p-4">
        {error && (
          <p role="status" className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[10px] leading-relaxed text-amber-200">
            {hasTelemetry
              ? "A atualização falhou; a última medição continua disponível."
              : isLive
                ? "A API respondeu, mas ainda não enviou métricas reconhecidas."
                : "Não foi possível obter métricas neste momento."}
          </p>
        )}

        {!error && isLive && !hasTelemetry && (
          <p className="rounded-lg border border-slate-700/70 bg-slate-900/60 px-3 py-2 text-[10px] leading-relaxed text-slate-400">
            A ligação à API está ativa. Os valores aparecem quando a resposta incluir medições.
          </p>
        )}
        {!isLive && hasTelemetry && !isLoading && (
          <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[10px] leading-relaxed text-amber-200">
            A mostrar a última medição recebida; a API não está ligada agora.
          </p>
        )}

        <div className="grid grid-cols-3 gap-2 rounded-xl border border-slate-800/70 bg-slate-900/45 px-2 py-3">
          <GaugeRing value={cpu} color="#fb923c" label="CPU" />
          <GaugeRing value={memory} color="#22d3ee" label="RAM" />
          <GaugeRing value={disk} color="#a78bfa" label="Disco" />
        </div>

        <div className="rounded-xl border border-slate-800/70 bg-slate-900/45 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Histórico de recursos</h3>
            <span className="text-[9px] text-slate-500">Últimas {chartHistory.length} amostras</span>
          </div>
          {chartReady ? (
            <>
              <ResponsiveContainer width="100%" height={94}>
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="nexusCpuGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#fb923c" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#fb923c" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="nexusMemoryGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#22d3ee" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="t" hide />
                  <YAxis domain={[0, 100]} hide />
                  <Tooltip
                    formatter={(value: number | string, name: string) => [`${Number(value).toFixed(1)}%`, name === "cpu" ? "CPU" : "RAM"]}
                    contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, fontSize: 10 }}
                    labelFormatter={() => ""}
                  />
                  <Area type="monotone" dataKey="cpu" connectNulls={false} stroke="#fb923c" fill="url(#nexusCpuGradient)" strokeWidth={1.5} />
                  <Area type="monotone" dataKey="memory" connectNulls={false} stroke="#22d3ee" fill="url(#nexusMemoryGradient)" strokeWidth={1.5} />
                </AreaChart>
              </ResponsiveContainer>
              <div className="mt-1 flex justify-center gap-4 text-[9px] text-slate-500">
                <span className="flex items-center gap-1"><span className="h-0.5 w-3 rounded bg-orange-400" />CPU</span>
                <span className="flex items-center gap-1"><span className="h-0.5 w-3 rounded bg-cyan-400" />RAM</span>
              </div>
            </>
          ) : (
            <p className="flex h-[94px] items-center justify-center px-4 text-center text-[10px] leading-relaxed text-slate-500">
              {hasTelemetry ? "O gráfico aparece depois de receber mais amostras." : "O gráfico aparece quando houver medições disponíveis."}
            </p>
          )}
        </div>

        <div className="rounded-xl border border-slate-800/70 bg-slate-900/45 px-3">
          <h3 className="pt-3 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Medições recebidas</h3>
          <MetricRow
            icon={Clock3}
            label="Latência média"
            value={formatMetric(metrics.avgResponseTime, isMeasured, "avgResponseTime")}
            unit={isMeasured("avgResponseTime") ? "ms" : undefined}
          />
          <MetricRow
            icon={Layers}
            label="Fila"
            value={formatMetric(metrics.queueSize, isMeasured, "queueSize")}
            unit={isMeasured("queueSize") ? "tarefas" : undefined}
          />
          <MetricRow
            icon={Zap}
            label="Tokens por segundo"
            value={isMeasured("tokensPerSecond") && typeof metrics.tokensPerSecond === "number"
              ? metrics.tokensPerSecond.toFixed(1)
              : "—"}
            unit={isMeasured("tokensPerSecond") ? "tok/s" : undefined}
          />
          <MetricRow
            icon={HardDrive}
            label="Disco usado"
            value={formatMetric(metrics.diskUsage, isMeasured, "diskUsage")}
            unit={isMeasured("diskUsage") ? "%" : undefined}
          />
        </div>
      </div>
    </section>
  );
}
