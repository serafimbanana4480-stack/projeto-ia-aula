"use client";

import React, { Suspense } from "react";
import dynamic from "next/dynamic";
import NexusLayout from "../../components/nexus/NexusLayout";
import { WidgetSkeleton } from "../../components/ui/Skeleton";

// ─── Lazy‑loaded widgets with skeleton fallbacks ────────────────────────────

const AgentActivityMap = dynamic(
  () => import("../../components/nexus/widgets/AgentActivityMap"),
  { loading: () => <WidgetSkeleton />, ssr: false }
);

const LiveReasoningStream = dynamic(
  () => import("../../components/nexus/widgets/LiveReasoningStream"),
  { loading: () => <WidgetSkeleton />, ssr: false }
);

const MultiAgentChat = dynamic(
  () => import("../../components/nexus/widgets/MultiAgentChat"),
  { loading: () => <WidgetSkeleton />, ssr: false }
);

const WorkflowTimeline = dynamic(
  () => import("../../components/nexus/widgets/WorkflowTimeline"),
  { loading: () => <WidgetSkeleton />, ssr: false }
);

const SystemHealth = dynamic(
  () => import("../../components/nexus/widgets/SystemHealth"),
  { loading: () => <WidgetSkeleton />, ssr: false }
);

const TaskOrchestration = dynamic(
  () => import("../../components/nexus/widgets/TaskOrchestration"),
  { loading: () => <WidgetSkeleton />, ssr: false }
);

const MemoryRAG = dynamic(
  () => import("../../components/nexus/widgets/MemoryRAG"),
  { loading: () => <WidgetSkeleton />, ssr: false }
);

// ─── Dashboard ──────────────────────────────────────────────────────────────

export default function NexusDashboard() {
  return (
    <NexusLayout>
      <div className="p-4 space-y-4">
        {/* Top row: Agent map + Reasoning stream */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 nexus-widget">
            <Suspense fallback={<WidgetSkeleton />}>
              <AgentActivityMap />
            </Suspense>
          </div>
          <div className="nexus-widget">
            <Suspense fallback={<WidgetSkeleton />}>
              <LiveReasoningStream />
            </Suspense>
          </div>
        </div>

        {/* Middle row: Agent Chat + Workflow + System */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="nexus-widget">
            <Suspense fallback={<WidgetSkeleton />}>
              <MultiAgentChat />
            </Suspense>
          </div>
          <div className="nexus-widget">
            <Suspense fallback={<WidgetSkeleton />}>
              <WorkflowTimeline />
            </Suspense>
          </div>
          <div className="nexus-widget">
            <Suspense fallback={<WidgetSkeleton />}>
              <SystemHealth />
            </Suspense>
          </div>
        </div>

        {/* Bottom row: Tasks + Memory */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="nexus-widget">
            <Suspense fallback={<WidgetSkeleton />}>
              <TaskOrchestration />
            </Suspense>
          </div>
          <div className="nexus-widget">
            <Suspense fallback={<WidgetSkeleton />}>
              <MemoryRAG />
            </Suspense>
          </div>
        </div>
      </div>
    </NexusLayout>
  );
}
