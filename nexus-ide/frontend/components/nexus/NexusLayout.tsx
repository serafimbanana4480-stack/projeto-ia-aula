"use client";

import React, { useEffect } from "react";
import { useEventBus } from "../../stores/useEventBus";
import { useAgentStore } from "../../stores/useAgentStore";
import { useSystemStore } from "../../stores/useSystemStore";
import { useTaskStore } from "../../stores/useTaskStore";

export default function NexusLayout({ children }: { children: React.ReactNode }) {
  const { startBus, stopBus } = useEventBus();
  const fetchAgents = useAgentStore((s) => s.fetchAgents);
  const fetchMetrics = useSystemStore((s) => s.fetchMetrics);
  const fetchTasks = useTaskStore((s) => s.fetchTasks);
  const fetchWorkflows = useTaskStore((s) => s.fetchWorkflows);

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

  // Keep the task and workflow widgets backed by the same APIs they display.
  // Guard the timer against overlapping requests when the backend is slow.
  useEffect(() => {
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        await Promise.all([fetchTasks(), fetchWorkflows()]);
      } finally {
        refreshing = false;
      }
    };

    void refresh();
    const refreshInterval = setInterval(() => void refresh(), 10_000);
    return () => clearInterval(refreshInterval);
  }, [fetchTasks, fetchWorkflows]);

  return <div className="min-h-full">{children}</div>;
}
