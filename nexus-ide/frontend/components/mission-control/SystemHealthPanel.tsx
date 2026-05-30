"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  Server,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
} from "lucide-react";
import { useMissionStore } from "../../stores/missionStore";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

function WorkerStatus({
  worker,
}: {
  worker: { name: string; status: string; last_run?: string; queue_size?: number };
}) {
  const cfg =
    worker.status === "healthy"
      ? { icon: <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />, color: "text-green-400" }
      : worker.status === "degraded"
      ? { icon: <AlertTriangle className="h-3.5 w-3.5 text-yellow-400" />, color: "text-yellow-400" }
      : worker.status === "unhealthy"
      ? { icon: <AlertTriangle className="h-3.5 w-3.5 text-red-400" />, color: "text-red-400" }
      : { icon: <HelpCircle className="h-3.5 w-3.5 text-gray-400" />, color: "text-gray-400" };

  return (
    <div className="flex items-center justify-between rounded border border-nexus-border/50 bg-nexus-card px-3 py-2">
      <div className="flex items-center gap-2">
        {cfg.icon}
        <span className="text-xs font-medium">{worker.name}</span>
      </div>
      <div className="flex items-center gap-3 text-[10px] text-nexus-muted">
        {worker.queue_size !== undefined && <span>Queue: {worker.queue_size}</span>}
        <span className={cfg.color}>{worker.status}</span>
      </div>
    </div>
  );
}

function MiniChart({
  data,
  dataKey,
  color,
  label,
}: {
  data: Array<{ [key: string]: string | number }>;
  dataKey: string;
  color: string;
  label: string;
}) {
  return (
    <div className="rounded border border-nexus-border/50 bg-nexus-card p-2">
      <div className="mb-1 text-[10px] text-nexus-muted">{label}</div>
      <div className="h-24">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id={`grad-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                <stop offset="100%" stopColor={color} stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2d" />
            <XAxis dataKey="label" hide />
            <YAxis hide />
            <Tooltip
              contentStyle={{
                background: "#161622",
                border: "1px solid #1e1e2d",
                borderRadius: 6,
                fontSize: 11,
              }}
              itemStyle={{ color: "#e8e8ed" }}
            />
            <Area
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              fill={`url(#grad-${dataKey})`}
              strokeWidth={1.5}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function SystemHealthPanel() {
  const health = useMissionStore((s) => s.systemHealth);

  const hourlyData = useMemo(() => {
    if (!health?.token_usage_hourly) return [];
    return health.token_usage_hourly.map((d) => ({
      label: d.hour,
      tokens: d.tokens,
    }));
  }, [health]);

  const successRate = health?.mission_success_rate ?? 0;
  const failureRate = health?.agent_failure_rate ?? 0;

  return (
    <div className="rounded-lg border border-nexus-border bg-nexus-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-nexus-accent4" />
          <span className="text-sm font-semibold">Saúde do Sistema</span>
        </div>
      </div>

      {!health ? (
        <div className="flex h-32 items-center justify-center text-xs text-nexus-muted">
          Sem dados de saúde do sistema
        </div>
      ) : (
        <div className="space-y-4">
          {/* Workers */}
          <div>
            <div className="mb-2 text-xs font-medium text-nexus-muted">Background Workers</div>
            <div className="space-y-1.5 max-h-[160px] overflow-y-auto thin-scrollbar pr-1">
              {health.workers.map((w) => (
                <WorkerStatus key={w.name} worker={w} />
              ))}
            </div>
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {hourlyData.length > 0 && (
              <MiniChart data={hourlyData} dataKey="tokens" color="#7c6afb" label="Tokens / hora" />
            )}
            <div className="grid grid-cols-2 gap-2">
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col items-center justify-center rounded border border-nexus-border/50 bg-nexus-card p-2"
              >
                <TrendingUp className="h-4 w-4 text-green-400 mb-1" />
                <div className="text-lg font-bold text-green-400">{(successRate * 100).toFixed(1)}%</div>
                <div className="text-[10px] text-nexus-muted">Sucesso missões</div>
              </motion.div>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col items-center justify-center rounded border border-nexus-border/50 bg-nexus-card p-2"
              >
                <TrendingDown className="h-4 w-4 text-red-400 mb-1" />
                <div className="text-lg font-bold text-red-400">{(failureRate * 100).toFixed(1)}%</div>
                <div className="text-[10px] text-nexus-muted">Falhas agentes</div>
              </motion.div>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col items-center justify-center rounded border border-nexus-border/50 bg-nexus-card p-2"
              >
                <Server className="h-4 w-4 text-nexus-accent mb-1" />
                <div className="text-lg font-bold">{health.total_missions}</div>
                <div className="text-[10px] text-nexus-muted">Missões</div>
              </motion.div>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col items-center justify-center rounded border border-nexus-border/50 bg-nexus-card p-2"
              >
                <Activity className="h-4 w-4 text-nexus-accent2 mb-1" />
                <div className="text-lg font-bold">{health.total_agents}</div>
                <div className="text-[10px] text-nexus-muted">Agentes</div>
              </motion.div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
