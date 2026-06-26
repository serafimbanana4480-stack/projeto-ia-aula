"use client";

import React, { useEffect, useState } from "react";
import {
  Download, FileText, Table2, BarChart2,
  Clock, CheckCircle2, Loader2, RefreshCw,
  Calendar, Filter, File,
} from "lucide-react";
import { apiUrl } from "../../../lib/api";

type Report = {
  id: string;
  name: string;
  description: string;
  format: string[];
  period: string;
  size_kb: number;
};

type GenerationState = {
  [id: string]: { status: "idle" | "generating" | "ready" | "error"; downloadUrl?: string };
};

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [genState, setGenState] = useState<GenerationState>({});
  const [selectedFormat, setSelectedFormat] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(apiUrl("/api/analytics/reports/available"));
        const data = await res.json();
        setReports(data);
        const fmt: Record<string, string> = {};
        data.forEach((r: Report) => { fmt[r.id] = r.format[0] || "pdf"; });
        setSelectedFormat(fmt);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function generateReport(reportId: string, format: string) {
    setGenState(s => ({ ...s, [reportId]: { status: "generating" } }));
    try {
      const res = await fetch(apiUrl("/api/analytics/reports/generate"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_id: reportId, format }),
      });
      const data = await res.json();
      setGenState(s => ({ ...s, [reportId]: { status: "ready", downloadUrl: data.download_url } }));
    } catch {
      setGenState(s => ({ ...s, [reportId]: { status: "error" } }));
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[#06061a]">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-[#07071a] flex flex-col">
        <div className="p-5 border-b border-slate-800">
          <p className="text-[10px] uppercase tracking-[0.25em] text-cyan-400 font-bold">Nexus Omega</p>
          <h2 className="text-base font-bold text-slate-100 mt-1">Reports</h2>
          <p className="text-[11px] text-slate-500 mt-0.5">Export & Analytics</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {[
            { label: "Overview", href: "/analytics", icon: BarChart2 },
            { label: "History", href: "/analytics/history", icon: Clock },
            { label: "Reports", href: "/analytics/reports", icon: Download, active: true },
          ].map(({ label, href, icon: Icon, active }) => (
            <a key={label} href={href} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${active ? "bg-violet-500/20 text-violet-300 border border-violet-500/30" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"}`}>
              <Icon size={16} />{label}
            </a>
          ))}
        </nav>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-[#07071a]/90 backdrop-blur">
          <div>
            <h1 className="text-lg font-bold text-slate-100">Export Reports</h1>
            <p className="text-xs text-slate-500 mt-0.5">Generate and download detailed analytics reports in PDF or Excel format</p>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <CheckCircle2 size={13} className="text-emerald-400" />
            <span className="text-xs text-emerald-400 font-medium">All systems operational</span>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <span className="flex items-center gap-2 text-slate-400 text-sm"><span className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" /> Loading reports...</span>
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-2">
              {reports.map(report => {
                const state = genState[report.id] || { status: "idle" };
                const fmt = selectedFormat[report.id] || report.format[0];

                return (
                  <div key={report.id} className="ana-card flex flex-col p-5">
                    {/* Icon + title */}
                    <div className="flex items-start gap-4 mb-4">
                      <div className="w-12 h-12 rounded-xl border flex items-center justify-center shrink-0"
                        style={{ background: "rgba(124,58,237,0.12)", borderColor: "rgba(124,58,237,0.3)" }}>
                        {fmt === "xlsx" ? <Table2 size={22} className="text-violet-400" /> : <FileText size={22} className="text-violet-400" />}
                      </div>
                      <div className="min-w-0">
                        <h3 className="text-base font-bold text-slate-100 leading-tight">{report.name}</h3>
                        <p className="text-xs text-slate-400 mt-1 leading-relaxed">{report.description}</p>
                      </div>
                    </div>

                    {/* Meta */}
                    <div className="flex items-center gap-4 mb-5 text-[11px] text-slate-500">
                      <span className="flex items-center gap-1"><Calendar size={11} />{report.period}</span>
                      <span className="flex items-center gap-1"><File size={11} />{report.size_kb} KB</span>
                      <div className="flex items-center gap-1">
                        {report.format.map(f => (
                          <span key={f} className="px-1.5 py-0.5 rounded border border-slate-600 text-slate-400 font-mono text-[10px] uppercase">{f}</span>
                        ))}
                      </div>
                    </div>

                    {/* Format selector + action */}
                    <div className="mt-auto flex items-center gap-3">
                      <select
                        value={fmt}
                        onChange={e => setSelectedFormat(s => ({ ...s, [report.id]: e.target.value }))}
                        className="ana-select text-xs flex-1"
                      >
                        {report.format.map(f => (
                          <option key={f} value={f}>{f.toUpperCase()}</option>
                        ))}
                      </select>
                      {state.status === "idle" && (
                        <button
                          onClick={() => generateReport(report.id, fmt)}
                          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold transition-colors"
                        >
                          <Download size={13} /> Generate
                        </button>
                      )}
                      {state.status === "generating" && (
                        <button disabled className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-700 text-slate-400 text-xs font-semibold cursor-not-allowed">
                          <Loader2 size={13} className="animate-spin" /> Generating...
                        </button>
                      )}
                      {state.status === "ready" && (
                        <a
                          href={state.downloadUrl}
                          download
                          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition-colors"
                        >
                          <Download size={13} /> Download
                        </a>
                      )}
                      {state.status === "error" && (
                        <button
                          onClick={() => generateReport(report.id, fmt)}
                          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-semibold transition-colors"
                        >
                          <RefreshCw size={13} /> Retry
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
