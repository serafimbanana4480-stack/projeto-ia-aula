"use client";
import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import MetricsGrid from "../../components/dashboard/MetricsGrid";
import ModelComparison from "../../components/dashboard/ModelComparison";
import TokenTimeline from "../../components/dashboard/TokenTimeline";
import AlertFeed from "../../components/dashboard/AlertFeed";
import SystemHealth from "../../components/dashboard/SystemHealth";
import AgentActivity from "../../components/dashboard/AgentActivity";
import RequestFlow from "../../components/dashboard/RequestFlow";

// Dedicated dashboard route. See ARCHITECTURE.md §9.
export default function DashboardPage() {
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    overview: true,
    throughput: true,
    performance: true,
    flow: true,
    health: true,
    activity: true,
    alerts: true,
  });

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };
  return (
    <div className="h-screen overflow-auto bg-gradient-to-b from-nexus-bg to-black/95 p-4 text-gray-100">
      <div className="mb-4 flex items-center justify-between rounded-2xl border border-nexus-border bg-nexus-panel/70 px-4 py-3 backdrop-blur">
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">Observability</div>
          <h1 className="text-xl font-bold text-white">NEXUS Dashboard</h1>
        </div>
        <div className="text-right text-xs text-gray-500">
          <div>Live system view</div>
          <div>Última atualização: {new Date().toLocaleTimeString()}</div>
        </div>
      </div>

      <section className="rounded-2xl border border-nexus-border bg-nexus-panel/30 overflow-hidden">
        <button
          onClick={() => toggleSection('overview')}
          className="w-full flex items-center justify-between p-4 hover:bg-nexus-border/20 transition-colors"
        >
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-500">System overview</div>
            <div className="text-sm text-gray-300">Core metrics with drill-down and live state</div>
          </div>
          {expandedSections.overview ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
        </button>
        {expandedSections.overview && (
          <div className="p-4 pt-0">
            <MetricsGrid />
          </div>
        )}
      </section>
      
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="rounded-2xl border border-nexus-border bg-nexus-panel/30 overflow-hidden">
          <button
            onClick={() => toggleSection('throughput')}
            className="w-full flex items-center justify-between p-4 hover:bg-nexus-border/20 transition-colors"
          >
            <div className="text-xs uppercase tracking-wide text-gray-500">Throughput</div>
            {expandedSections.throughput ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
          </button>
          {expandedSections.throughput && (
            <div className="p-4 pt-0">
              <TokenTimeline />
            </div>
          )}
        </section>
        <section className="rounded-2xl border border-nexus-border bg-nexus-panel/30 overflow-hidden">
          <button
            onClick={() => toggleSection('performance')}
            className="w-full flex items-center justify-between p-4 hover:bg-nexus-border/20 transition-colors"
          >
            <div className="text-xs uppercase tracking-wide text-gray-500">Model performance</div>
            {expandedSections.performance ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
          </button>
          {expandedSections.performance && (
            <div className="p-4 pt-0">
              <ModelComparison />
            </div>
          )}
        </section>
      </div>
      
      <section className="rounded-2xl border border-nexus-border bg-nexus-panel/30 overflow-hidden">
        <button
          onClick={() => toggleSection('flow')}
          className="w-full flex items-center justify-between p-4 hover:bg-nexus-border/20 transition-colors"
        >
          <div className="text-xs uppercase tracking-wide text-gray-500">Request flow</div>
          {expandedSections.flow ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
        </button>
        {expandedSections.flow && (
          <div className="p-4 pt-0">
            <RequestFlow />
          </div>
        )}
      </section>
      
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="rounded-2xl border border-nexus-border bg-nexus-panel/30 overflow-hidden">
          <button
            onClick={() => toggleSection('health')}
            className="w-full flex items-center justify-between p-4 hover:bg-nexus-border/20 transition-colors"
          >
            <div className="text-xs uppercase tracking-wide text-gray-500">System health</div>
            {expandedSections.health ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
          </button>
          {expandedSections.health && (
            <div className="p-4 pt-0">
              <SystemHealth />
            </div>
          )}
        </section>
        <section className="rounded-2xl border border-nexus-border bg-nexus-panel/30 overflow-hidden">
          <button
            onClick={() => toggleSection('activity')}
            className="w-full flex items-center justify-between p-4 hover:bg-nexus-border/20 transition-colors"
          >
            <div className="text-xs uppercase tracking-wide text-gray-500">Agent activity</div>
            {expandedSections.activity ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
          </button>
          {expandedSections.activity && (
            <div className="p-4 pt-0">
              <AgentActivity />
            </div>
          )}
        </section>
      </div>
      
      <section className="rounded-2xl border border-nexus-border bg-nexus-panel/30 overflow-hidden">
        <button
          onClick={() => toggleSection('alerts')}
          className="w-full flex items-center justify-between p-4 hover:bg-nexus-border/20 transition-colors"
        >
          <div className="text-xs uppercase tracking-wide text-gray-500">Alerts</div>
          {expandedSections.alerts ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
        </button>
        {expandedSections.alerts && (
          <div className="p-4 pt-0">
            <AlertFeed />
          </div>
        )}
      </section>
    </div>
  );
}
