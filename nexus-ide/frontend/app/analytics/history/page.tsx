"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  MessageSquare, Search, SlidersHorizontal, ChevronLeft,
  ChevronRight, Filter, ArrowUpDown, CheckCircle2, XCircle,
  Clock, Bot, TrendingUp, TrendingDown, Download, X,
} from "lucide-react";
import { apiUrl } from "../../../lib/api";

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

const PAGE_SIZE = 25;

function SentimentPill({ label }: { label: string }) {
  const colors: Record<string, string> = { positive: "emerald", negative: "red", neutral: "amber" };
  const color = colors[label] || "slate";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-${color}-500/10 border-${color}-500/30 text-${color}-300`}>
      {label}
    </span>
  );
}

export default function HistoryPage() {
  const [conversations, setConversations] = useState<Conv[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filterAgent, setFilterAgent] = useState("");
  const [filterSentiment, setFilterSentiment] = useState("");
  const [filterSuccess, setFilterSuccess] = useState("");
  const [sortBy, setSortBy] = useState<"timestamp" | "response_time_ms" | "tokens_generated">("timestamp");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<Conv | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(t);
  }, [search]);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
        ...(filterAgent ? { agent: filterAgent } : {}),
        ...(filterSentiment ? { sentiment: filterSentiment } : {}),
      });
      const res = await fetch(apiUrl(`/api/analytics/conversations?${params}`));
      const data = await res.json();
      let convs: Conv[] = data.conversations || [];
      if (debouncedSearch) {
        const q = debouncedSearch.toLowerCase();
        convs = convs.filter(c =>
          c.user_message.toLowerCase().includes(q) ||
          c.agent_response.toLowerCase().includes(q) ||
          c.agent.toLowerCase().includes(q)
        );
      }
      if (filterSuccess !== "") {
        const ok = filterSuccess === "true";
        convs = convs.filter(c => c.success === ok);
      }
      convs.sort((a, b) => {
        let va = a[sortBy]; let vb = b[sortBy];
        if (typeof va === "string") va = new Date(va).getTime();
        if (typeof vb === "string") vb = new Date(vb).getTime();
        return sortDir === "desc" ? Number(vb) - Number(va) : Number(va) - Number(vb);
      });
      setConversations(convs);
      setTotal(data.total || 0);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch, filterAgent, filterSentiment, filterSuccess, sortBy, sortDir]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  function toggleSort(col: typeof sortBy) {
    if (sortBy === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortBy(col); setSortDir("desc"); }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[#06061a]">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-[#07071a] flex flex-col">
        <div className="p-5 border-b border-slate-800">
          <p className="text-[10px] uppercase tracking-[0.25em] text-cyan-400 font-bold">Nexus Omega</p>
          <h2 className="text-base font-bold text-slate-100 mt-1">History</h2>
          <p className="text-[11px] text-slate-500 mt-0.5">{total} total interactions</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {[
            { label: "Overview", href: "/analytics", icon: MessageSquare },
            { label: "History", href: "/analytics/history", icon: Clock, active: true },
          ].map(({ label, href, icon: Icon, active }) => (
            <a key={label} href={href} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${active ? "bg-violet-500/20 text-violet-300 border border-violet-500/30" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"}`}>
              <Icon size={16} />{label}
            </a>
          ))}
        </nav>
        <div className="p-4 border-t border-slate-800">
          <div className="text-[11px] text-slate-500">Showing {conversations.length} of {total}</div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="shrink-0 flex flex-col gap-3 px-6 py-4 border-b border-slate-800 bg-[#07071a]/90 backdrop-blur">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-bold text-slate-100">Interaction History</h1>
            <div className="flex items-center gap-2">
              <button onClick={() => setShowFilters(f => !f)} className="ana-btn flex items-center gap-1.5 px-3 py-1.5 text-xs">
                <Filter size={12} /> Filters
              </button>
            </div>
          </div>

          {/* Search */}
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              placeholder="Search messages, agents..."
              className="w-full bg-slate-900/80 border border-slate-700/60 rounded-lg pl-9 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500/50 transition-colors"
            />
          </div>

          {/* Filters row */}
          {showFilters && (
            <div className="flex flex-wrap gap-3 p-3 rounded-lg bg-slate-800/40 border border-slate-700/40">
              <select value={filterAgent} onChange={e => { setFilterAgent(e.target.value); setPage(1); }} className="ana-select text-xs">
                <option value="">All agents</option>
                {["ROUTER","ARCHITECT","RESEARCHER","CODER","ANALYZER","DEBUGGER","DOCUMENTER","OPTIMIZER"].map(a => <option key={a} value={a}>{a}</option>)}
              </select>
              <select value={filterSentiment} onChange={e => { setFilterSentiment(e.target.value); setPage(1); }} className="ana-select text-xs">
                <option value="">All sentiments</option>
                <option value="positive">Positive</option>
                <option value="neutral">Neutral</option>
                <option value="negative">Negative</option>
              </select>
              <select value={filterSuccess} onChange={e => { setFilterSuccess(e.target.value); setPage(1); }} className="ana-select text-xs">
                <option value="">All statuses</option>
                <option value="true">Successful</option>
                <option value="false">Failed</option>
              </select>
              {(filterAgent || filterSentiment || filterSuccess) && (
                <button onClick={() => { setFilterAgent(""); setFilterSentiment(""); setFilterSuccess(""); setPage(1); }} className="ana-btn flex items-center gap-1 text-xs px-2 py-1 text-red-400">
                  <X size={11} /> Clear
                </button>
              )}
            </div>
          )}
        </header>

        {/* Table */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-[#07071a] border-b border-slate-800 z-10">
              <tr>
                  {[
                  { label: "Timestamp", col: "timestamp" as const },
                  { label: "Agent", col: "timestamp" as const },
                  { label: "Preview", col: "timestamp" as const },
                  { label: "Sentiment", col: "timestamp" as const },
                  { label: "Response Time", col: "response_time_ms" as const },
                  { label: "Tokens", col: "tokens_generated" as const },
                  { label: "Status", col: "timestamp" as const },
                ].map(({ label, col }) => (
                  <th
                    key={label}
                    onClick={() => col === "response_time_ms" || col === "tokens_generated" ? toggleSort(col) : undefined}
                    className={`px-4 py-3 text-left text-[11px] uppercase tracking-wider font-semibold text-slate-400 ${["Response Time","Tokens"].includes(label) ? "cursor-pointer hover:text-slate-200" : ""}`}
                  >
                    <span className="flex items-center gap-1">
                      {label}
                      {sortBy === "tokens_generated" && (sortDir === "desc" ? <TrendingDown size={11} /> : <TrendingUp size={11} />)}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-16 text-center text-slate-500">
                  <span className="flex items-center justify-center gap-2"><span className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" /> Loading...</span>
                </td></tr>
              ) : conversations.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-16 text-center text-slate-500">No conversations found</td></tr>
              ) : conversations.map(conv => (
                <tr
                  key={conv.id}
                  onClick={() => setSelected(conv)}
                  className="hover:bg-slate-800/30 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">
                    {new Date(conv.timestamp).toLocaleString("pt-PT")}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded border border-violet-500/30 bg-violet-500/10 text-violet-300">{conv.agent}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-300 max-w-xs truncate">{conv.user_message}</td>
                  <td className="px-4 py-3"><SentimentPill label={conv.sentiment.label} /></td>
                  <td className="px-4 py-3 text-xs font-mono text-slate-400">{conv.response_time_ms} ms</td>
                  <td className="px-4 py-3 text-xs font-mono text-slate-400">{conv.tokens_generated}</td>
                  <td className="px-4 py-3">
                    {conv.success
                      ? <CheckCircle2 size={15} className="text-emerald-400" />
                      : <XCircle size={15} className="text-red-400" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="shrink-0 flex items-center justify-between px-6 py-3 border-t border-slate-800 bg-[#07071a]">
          <span className="text-xs text-slate-500">
            Page {page} of {totalPages || 1} — {total} total
          </span>
          <div className="flex items-center gap-2">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="ana-btn px-3 py-1.5 text-xs disabled:opacity-30">
              <ChevronLeft size={14} /> Previous
            </button>
            <span className="text-xs text-slate-400 px-2">{page} / {totalPages || 1}</span>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="ana-btn px-3 py-1.5 text-xs disabled:opacity-30">
              Next <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </main>

      {/* Detail drawer */}
      {selected && (
        <div className="w-[480px] shrink-0 border-l border-slate-800 bg-[#07071a] flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
            <h3 className="font-semibold text-slate-100">Conversation Detail</h3>
            <button onClick={() => setSelected(null)} className="ana-btn p-1.5"><X size={14} /></button>
          </div>
          <div className="flex-1 overflow-y-auto p-5 space-y-5">
            <div className="space-y-2 text-xs">
              <div className="flex justify-between"><span className="text-slate-500">ID</span><span className="text-slate-300 font-mono">{selected.id}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Agent</span><span className="text-violet-300 font-semibold">{selected.agent}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Timestamp</span><span className="text-slate-300">{new Date(selected.timestamp).toLocaleString("pt-PT")}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Response time</span><span className="text-slate-300 font-mono">{selected.response_time_ms} ms</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Tokens</span><span className="text-slate-300 font-mono">{selected.tokens_generated}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Sentiment</span><SentimentPill label={selected.sentiment.label} /></div>
              <div className="flex justify-between"><span className="text-slate-500">Status</span>
                {selected.success ? <CheckCircle2 size={14} className="text-emerald-400" /> : <XCircle size={14} className="text-red-400" />}
              </div>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-2">User Message</p>
              <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs text-slate-200 leading-relaxed">{selected.user_message}</div>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Agent Response</p>
              <div className="p-3 rounded-lg bg-violet-900/20 border border-violet-500/20 text-xs text-slate-200 leading-relaxed">{selected.agent_response}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
