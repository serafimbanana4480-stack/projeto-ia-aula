"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  BarChart2, Bot, Brain, Clock, Filter, Globe,
  MessageSquare, RefreshCw, Search,
  SlidersHorizontal, ThumbsDown, ThumbsUp, TrendingUp,
  TrendingDown, Users, Zap, Download, ChevronDown,
  Activity, CheckCircle2, XCircle, AlertCircle, FileSearch,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, AreaChart, Area,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { apiUrl } from "../../lib/api";

type Conv = {
  id: string;
  agent: string;
  user_message: string;
  agent_response: string;
  timestamp: string;
  response_time_ms: number;
  tokens_generated: number;
  sentiment: { score: number; label: string; positive_pct: number; neutral_pct: number; negative_pct: number };
  success: boolean;
};

type TimeSeriesPoint = { timestamp: number; value: number };
type AgentMetric = { agent: string; calls: number; avg_latency_ms: number; success_rate: number; total_tokens: number };
type UsageSummary = {
  total_conversations: number; total_messages: number; total_tokens: number;
  unique_sessions: number; peak_concurrent_sessions: number;
  avg_messages_per_conversation: number; uptime_seconds: number;
};
type SentimentOverview = {
  overall: { score: number; label: string; positive_pct: number; neutral_pct: number; negative_pct: number };
  trend: Array<{ timestamp: number; score: number; label: string }>;
  by_agent: Record<string, { score: number; label: string; positive_pct: number }>;
  insights: string[];
};
type Report = { id: string; name: string; description: string; format: string[]; size_kb: number };

const SENTIMENT_COLORS = { positive: "#10b981", neutral: "#f59e0b", negative: "#ef4444" };
const AGENT_COLORS = ["#7c3aed", "#06b6d4", "#f59e0b", "#10b981", "#ec4899", "#f97316", "#3b82f6", "#8b5cf6"];

function fmtTs(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
}
function fmtDate(ts: number) {
  return new Date(ts * 1000).toLocaleDateString("pt-PT", { day: "2-digit", month: "short" });
}
function fmtMs(ms: number) { return `${ms.toLocaleString()} ms`; }
function fmtNum(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}
function fmtUptime(s: number) {
  const d = Math.floor(s / 86400); s %= 86400;
  const h = Math.floor(s / 3600); s %= 3600;
  return d > 0 ? `${d}d ${h}h` : `${h}h ${Math.floor(s / 60)}m`;
}

function StatCard({ label, value, sub, icon: Icon, color }: { label: string; value: string; sub?: string; icon: React.ElementType; color: string }) {
  return (
    <div className="ana-card flex items-center gap-4 p-4">
      <div className={`shrink-0 w-12 h-12 rounded-xl flex items-center justify-center border`} style={{ background: `${color}18`, borderColor: `${color}40` }}>
        <Icon size={22} style={{ color }} />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-widest text-slate-400 font-semibold">{label}</p>
        <p className="text-2xl font-bold text-slate-100 mt-0.5 truncate">{value}</p>
        {sub && <p className="text-[11px] text-slate-500 mt-0.5 truncate">{sub}</p>}
      </div>
    </div>
  );
}

function ChartPanel({ title, children, actions }: { title: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="ana-card flex flex-col">
      <div className="ana-panel-header">
        <span className="ana-panel-title">{title}</span>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      <div className="flex-1 p-4">{children}</div>
    </div>
  );
}

function SentimentBadge({ score, label }: { score: number; label: string }) {
  const color = label === "positive" ? "#10b981" : label === "negative" ? "#ef4444" : "#f59e0b";
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border" style={{ color, borderColor: `${color}50`, background: `${color}15` }}>
      {label === "positive" ? <ThumbsUp size={10} /> : label === "negative" ? <ThumbsDown size={10} /> : <AlertCircle size={10} />}
      {label}
    </span>
  );
}

function AgentBadge({ agent }: { agent: string }) {
  const colorMap: Record<string, string> = {
    ROUTER: "#7c3aed", ARCHITECT: "#06b6d4", RESEARCHER: "#f59e0b",
    CODER: "#10b981", ANALYZER: "#3b82f6", DEBUGGER: "#ef4444",
    DOCUMENTER: "#ec4899", OPTIMIZER: "#f97316",
  };
  const color = colorMap[agent] || "#8b5cf6";
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border" style={{ color, borderColor: `${color}50`, background: `${color}15` }}>
      {agent}
    </span>
  );
}

export default function AnalyticsPage() {
  const [conversations, setConversations] = useState<Conv[]>([]);
  const [convsLoading, setConvsLoading] = useState(true);
  const [totalConvs, setTotalConvs] = useState(0);
  const [convOffset, setConvOffset] = useState(0);
  const [filterAgent, setFilterAgent] = useState("");
  const [filterSentiment, setFilterSentiment] = useState("");
  const [responseTime, setResponseTime] = useState<{ data: TimeSeriesPoint[]; summary: Record<string, number> }>({ data: [], summary: {} });
  const [throughput, setThroughput] = useState<{ data: TimeSeriesPoint[]; summary: Record<string, number> }>({ data: [], summary: {} });
  const [accuracy, setAccuracy] = useState<{ data: TimeSeriesPoint[]; summary: Record<string, number> }>({ data: [], summary: {} });
  const [agentMetrics, setAgentMetrics] = useState<AgentMetric[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [sentimentOverview, setSentimentOverview] = useState<SentimentOverview | null>(null);
  const [reports, setReports] = useState<Report[]>([]);
  const [activeReport, setActiveReport] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState(24);
  const [lastRefresh, setLastRefresh] = useState(new Date());

  const fetchAll = useCallback(async () => {
    setConvsLoading(true);
    try {
      const [rt, tp, acc, ag, us, so, rep, cv] = await Promise.all([
        fetch(apiUrl(`/api/analytics/performance/response-time?hours=${timeRange}`)).then(r => r.json()),
        fetch(apiUrl(`/api/analytics/performance/throughput?hours=${timeRange}`)).then(r => r.json()),
        fetch(apiUrl(`/api/analytics/performance/accuracy?days=${Math.ceil(timeRange / 24)}`)).then(r => r.json()),
        fetch(apiUrl("/api/analytics/agents/metrics")).then(r => r.json()),
        fetch(apiUrl("/api/analytics/usage/summary")).then(r => r.json()),
        fetch(apiUrl("/api/analytics/sentiment/overview")).then(r => r.json()),
        fetch(apiUrl("/api/analytics/reports/available")).then(r => r.json()),
        fetch(apiUrl(`/api/analytics/conversations?limit=20&offset=${convOffset}&agent=${filterAgent}&sentiment=${filterSentiment}`)).then(r => r.json()),
      ]);
      setResponseTime(rt);
      setThroughput(tp);
      setAccuracy(acc);
      setAgentMetrics(ag);
      setUsage(us);
      setSentimentOverview(so);
      setReports(rep);
      setConversations(cv.conversations || []);
      setTotalConvs(cv.total || 0);
    } finally {
      setConvsLoading(false);
      setLastRefresh(new Date());
    }
  }, [timeRange, convOffset, filterAgent, filterSentiment]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  useEffect(() => {
    const t = setInterval(fetchAll, 15000);
    return () => clearInterval(t);
  }, [fetchAll]);

  const pieData = sentimentOverview ? [
    { name: "Positivo", value: sentimentOverview.overall.positive_pct, color: "#10b981" },
    { name: "Neutro", value: sentimentOverview.overall.neutral_pct, color: "#f59e0b" },
    { name: "Negativo", value: sentimentOverview.overall.negative_pct, color: "#ef4444" },
  ] : [];

  return (
    <div className="flex h-screen overflow-hidden bg-[#06061a]">
      {/* ─── SIDEBAR ─── */}
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-[#07071a] flex flex-col">
        <div className="p-5 border-b border-slate-800">
          <p className="text-[10px] uppercase tracking-[0.25em] text-cyan-400 font-bold">Nexus Omega</p>
          <h2 className="text-base font-bold text-slate-100 mt-1">Analytics</h2>
          <p className="text-[11px] text-slate-500 mt-0.5">Conversation Intelligence</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {[
            { label: "Overview", icon: BarChart2, active: true },
            { label: "Conversations", icon: MessageSquare, active: false },
            { label: "Reports", icon: Download, active: false },
          ].map(({ label, icon: Icon, active }) => (
            <button key={label} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${active ? "bg-violet-500/20 text-violet-300 border border-violet-500/30" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"}`}>
              <Icon size={16} />{label}
            </button>
          ))}
        </nav>
        <div className="p-4 border-t border-slate-800 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-500">Auto-refresh</span>
            <span className="flex items-center gap-1 text-[11px] text-emerald-400"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> 15s</span>
          </div>
          <div className="text-[10px] text-slate-600">
            Last: {lastRefresh.toLocaleTimeString("pt-PT")}
          </div>
          <button onClick={fetchAll} className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-violet-500/20 border border-violet-500/30 text-violet-300 text-xs font-semibold hover:bg-violet-500/30 transition-all">
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </aside>

      {/* ─── MAIN ─── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-[#07071a]/90 backdrop-blur">
          <div>
            <h1 className="text-lg font-bold text-slate-100">Conversation Analytics</h1>
            <p className="text-xs text-slate-500 mt-0.5">Real-time performance, sentiment and usage insights</p>
          </div>
          <div className="flex items-center gap-3">
            <select value={timeRange} onChange={e => setTimeRange(Number(e.target.value))} className="ana-select text-xs">
              <option value={6}>Last 6 hours</option>
              <option value={24}>Last 24 hours</option>
              <option value={72}>Last 3 days</option>
              <option value={168}>Last 7 days</option>
            </select>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs text-emerald-400 font-medium">Live</span>
            </div>
          </div>
        </header>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">

          {/* ── KPI ROW ── */}
          <div className="grid gap-4 grid-cols-2 xl:grid-cols-4">
            <StatCard label="Total Conversations" value={usage ? fmtNum(usage.total_conversations) : "—"} sub={`${usage?.unique_sessions || 0} unique sessions`} icon={MessageSquare} color="#7c3aed" />
            <StatCard label="Messages Processed" value={usage ? fmtNum(usage.total_messages) : "—"} sub={`avg ${usage?.avg_messages_per_conversation.toFixed(1) || 0} per session`} icon={Brain} color="#06b6d4" />
            <StatCard label="Tokens Generated" value={usage ? fmtNum(usage.total_tokens) : "—"} sub={`peak ${throughput.summary?.peak_tokens_per_second?.toFixed(0) || 0} t/s`} icon={Zap} color="#f59e0b" />
            <StatCard label="System Uptime" value={usage ? fmtUptime(usage.uptime_seconds) : "—"} sub={`${usage?.peak_concurrent_sessions || 0} peak sessions`} icon={Clock} color="#10b981" />
          </div>

          {/* ── PERFORMANCE CHARTS ROW ── */}
          <div className="grid gap-4 xl:grid-cols-3">
            <ChartPanel title="Response Time Distribution" actions={<span className="text-[11px] text-slate-500">p95: {fmtMs(responseTime.summary?.p95_ms || 0)}</span>}>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={[...responseTime.data].reverse()}>
                  <defs>
                    <linearGradient id="rtGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#7c3aed" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#7c3aed" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="timestamp" tickFormatter={t => fmtTs(t)} tick={{ fontSize: 10, fill: "#64748b" }} />
                  <YAxis tickFormatter={v => `${v}ms`} tick={{ fontSize: 10, fill: "#64748b" }} />
                  <Tooltip formatter={(v: number) => [`${v} ms`]} labelFormatter={t => fmtTs(t as number)} contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 }} />
                  <Area type="monotone" dataKey="value" stroke="#7c3aed" fill="url(#rtGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel title="Token Throughput" actions={<span className="text-[11px] text-slate-500">peak: {throughput.summary?.peak_tokens_per_second?.toFixed(0) || 0} t/s</span>}>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={[...throughput.data].reverse()}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="timestamp" tickFormatter={t => fmtTs(t)} tick={{ fontSize: 10, fill: "#64748b" }} />
                  <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
                  <Tooltip formatter={(v: number) => [`${v} t/s`]} labelFormatter={t => fmtTs(t as number)} contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 }} />
                  <Line type="monotone" dataKey="value" stroke="#06b6d4" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel title="Success Rate" actions={<span className="text-[11px] text-emerald-400 font-semibold">{accuracy.summary?.avg_success_rate?.toFixed(1) || 0}%</span>}>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={[...accuracy.data].reverse()}>
                  <defs>
                    <linearGradient id="accGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="timestamp" tickFormatter={t => fmtDate(t)} tick={{ fontSize: 10, fill: "#64748b" }} />
                  <YAxis domain={[80, 100]} tick={{ fontSize: 10, fill: "#64748b" }} />
                  <Tooltip formatter={(v: number) => [`${v}%`]} labelFormatter={t => fmtDate(t as number)} contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 }} />
                  <Area type="monotone" dataKey="value" stroke="#10b981" fill="url(#accGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </ChartPanel>
          </div>

          {/* ── SENTIMENT + AGENTS ROW ── */}
          <div className="grid gap-4 xl:grid-cols-3">
            <ChartPanel title="Sentiment Analysis">
              {sentimentOverview && (
                <div className="flex flex-col gap-4">
                  <div className="flex items-center justify-center">
                    <PieChart width={160} height={160}>
                      <Pie data={pieData} cx={80} cy={80} innerRadius={45} outerRadius={70} paddingAngle={3} dataKey="value">
                        {pieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                      </Pie>
                    </PieChart>
                  </div>
                  <div className="space-y-2">
                    {pieData.map(d => (
                      <div key={d.name} className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-full" style={{ background: d.color }} />
                          <span className="text-slate-300">{d.name}</span>
                        </div>
                        <span className="text-slate-400 font-mono">{d.value}%</span>
                      </div>
                    ))}
                  </div>
                  {sentimentOverview.insights?.length > 0 && (
                    <div className="border-t border-slate-700/60 pt-3 space-y-1.5">
                      {sentimentOverview.insights.slice(0, 2).map((ins, i) => (
                        <p key={i} className="text-[11px] text-slate-400 leading-relaxed">• {ins}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </ChartPanel>

            <ChartPanel title="Agent Performance">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={agentMetrics} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                  <XAxis type="number" domain={[0, 1]} tickFormatter={v => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10, fill: "#64748b" }} />
                  <YAxis type="category" dataKey="agent" tick={{ fontSize: 10, fill: "#94a3b8" }} width={70} />
                  <Tooltip formatter={(v: number) => [`${(v * 100).toFixed(1)}%`]} contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="success_rate" fill="#7c3aed" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel title="Latency by Agent">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={agentMetrics} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                  <XAxis type="number" tickFormatter={v => `${v}ms`} tick={{ fontSize: 10, fill: "#64748b" }} />
                  <YAxis type="category" dataKey="agent" tick={{ fontSize: 10, fill: "#94a3b8" }} width={70} />
                  <Tooltip formatter={(v: number) => [`${v} ms`]} contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="avg_latency_ms" fill="#06b6d4" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartPanel>
          </div>

          {/* ── CONVERSATION FEED ── */}
          <div className="ana-card">
            <div className="ana-panel-header">
              <span className="ana-panel-title flex items-center gap-2"><MessageSquare size={14} /> Recent Conversations</span>
              <div className="flex items-center gap-2">
                <select value={filterAgent} onChange={e => { setFilterAgent(e.target.value); setConvOffset(0); }} className="ana-select text-[11px]">
                  <option value="">All agents</option>
                  {agentMetrics.map(a => <option key={a.agent} value={a.agent}>{a.agent}</option>)}
                </select>
                <select value={filterSentiment} onChange={e => { setFilterSentiment(e.target.value); setConvOffset(0); }} className="ana-select text-[11px]">
                  <option value="">All sentiments</option>
                  <option value="positive">Positive</option>
                  <option value="neutral">Neutral</option>
                  <option value="negative">Negative</option>
                </select>
                <span className="text-[11px] text-slate-500">{totalConvs} total</span>
              </div>
            </div>
            <div className="divide-y divide-slate-800/60">
              {convsLoading && conversations.length === 0 ? (
                <div className="flex items-center justify-center h-40">
                  <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex items-center justify-center h-32 text-sm text-slate-500">No conversations found</div>
              ) : conversations.map(conv => (
                <div key={conv.id} className="p-4 hover:bg-slate-800/20 transition-colors">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                        <AgentBadge agent={conv.agent} />
                        <SentimentBadge score={conv.sentiment.score} label={conv.sentiment.label} />
                        <span className="text-[11px] text-slate-500">{new Date(conv.timestamp).toLocaleString("pt-PT")}</span>
                        {conv.success
                          ? <CheckCircle2 size={12} className="text-emerald-400" />
                          : <XCircle size={12} className="text-red-400" />}
                      </div>
                      <p className="text-xs text-slate-300 mb-1.5 leading-relaxed">
                        <span className="text-slate-500 font-semibold">Q: </span>{conv.user_message.slice(0, 120)}{conv.user_message.length > 120 ? "…" : ""}
                      </p>
                      <p className="text-xs text-slate-400 leading-relaxed">
                        <span className="text-violet-400 font-semibold">A: </span>{conv.agent_response.slice(0, 160)}{conv.agent_response.length > 160 ? "…" : ""}
                      </p>
                    </div>
                    <div className="shrink-0 text-right space-y-1">
                      <p className="text-[11px] text-slate-500">{fmtMs(conv.response_time_ms)}</p>
                      <p className="text-[11px] text-slate-500">{conv.tokens_generated} tok</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-800/60">
              <span className="text-[11px] text-slate-500">Showing {convOffset + 1}–{convOffset + conversations.length} of {totalConvs}</span>
              <div className="flex items-center gap-2">
                <button disabled={convOffset === 0} onClick={() => setConvOffset(Math.max(0, convOffset - 20))} className="ana-btn text-xs px-3 py-1.5 disabled:opacity-30">Previous</button>
                <button disabled={convOffset + 20 >= totalConvs} onClick={() => setConvOffset(convOffset + 20)} className="ana-btn text-xs px-3 py-1.5 disabled:opacity-30">Next</button>
              </div>
            </div>
          </div>

          {/* ── REPORTS ── */}
          <div className="ana-card">
            <div className="ana-panel-header">
              <span className="ana-panel-title flex items-center gap-2"><Download size={14} /> Export Reports</span>
            </div>
            <div className="p-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {reports.map(report => (
                <div key={report.id} className="flex flex-col gap-2 p-3 rounded-xl border border-slate-700/60 bg-slate-800/30 hover:border-violet-500/40 transition-all">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-sm font-semibold text-slate-200">{report.name}</p>
                      <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">{report.description}</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <div className="flex gap-1.5">
                      {report.format.map(f => (
                        <span key={f} className="text-[10px] px-1.5 py-0.5 rounded border border-slate-600 text-slate-400 font-mono uppercase">{f}</span>
                      ))}
                      <span className="text-[10px] text-slate-600">{report.size_kb} KB</span>
                    </div>
                    <button
                      onClick={() => setActiveReport(report.id)}
                      className="flex items-center gap-1 text-[11px] text-violet-400 hover:text-violet-300 font-medium"
                    >
                      <Download size={11} /> Export
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}
