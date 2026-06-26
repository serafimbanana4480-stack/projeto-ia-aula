"use client";

import React, { useEffect } from "react";
import NexusSidebar from "./NexusSidebar";
import NexusTopBar from "./NexusTopBar";
import { useEventBus } from "../../stores/useEventBus";
import { useAgentStore } from "../../stores/useAgentStore";
import { useSystemStore } from "../../stores/useSystemStore";

export default function NexusLayout({ children }: { children: React.ReactNode }) {
  const { startBus, stopBus } = useEventBus();
  const fetchAgents = useAgentStore((s) => s.fetchAgents);
  const fetchMetrics = useSystemStore((s) => s.fetchMetrics);

  useEffect(() => {
    startBus();
    return () => stopBus();
  }, [startBus, stopBus]);

  // Fetch real data periodically
  useEffect(() => {
    fetchAgents();
    const agentInterval = setInterval(() => fetchAgents(), 10000);
    return () => clearInterval(agentInterval);
  }, [fetchAgents]);

  useEffect(() => {
    fetchMetrics();
    const metricsInterval = setInterval(() => fetchMetrics(), 5000);
    return () => clearInterval(metricsInterval);
  }, [fetchMetrics]);

  return (
    <div className="flex h-screen overflow-hidden bg-transparent">
      <NexusSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <NexusTopBar />
        <main className="flex-1 overflow-y-auto bg-slate-900/20 backdrop-blur-sm">
          {children}
        </main>
      </div>
    </div>
  );
}
