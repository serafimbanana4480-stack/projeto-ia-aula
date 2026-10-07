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

const widgetCard = "min-w-0 overflow-hidden rounded-2xl border border-slate-700/50 bg-slate-900/70 shadow-lg shadow-black/10";

export default function NexusDashboard() {
  return (
    <NexusLayout>
      <div className="mx-auto w-full max-w-[1600px] space-y-4 p-3 sm:p-5">
        <header className="flex flex-col gap-1 px-1 pb-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-violet-300">Nexus · Centro de controlo</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-100 sm:text-2xl">Visão geral</h2>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-400 sm:text-sm">
              Agentes, tarefas, fluxos e recursos num só ecrã.
            </p>
          </div>
        </header>

        <div className="grid grid-cols-1 gap-3 xl:grid-cols-12 xl:gap-4">
          <section aria-label="Agentes" className={`${widgetCard} min-h-[300px] xl:col-span-8`}>
            <Suspense fallback={<WidgetSkeleton />}>
              <AgentActivityMap />
            </Suspense>
          </section>
          <section aria-label="Saúde do sistema" className={`${widgetCard} min-h-[300px] xl:col-span-4`}>
            <Suspense fallback={<WidgetSkeleton />}>
              <SystemHealth />
            </Suspense>
          </section>

          <section aria-label="Tarefas" className={`${widgetCard} min-h-[320px] xl:col-span-7`}>
            <Suspense fallback={<WidgetSkeleton />}>
              <TaskOrchestration />
            </Suspense>
          </section>
          <section aria-label="Fluxos" className={`${widgetCard} min-h-[320px] xl:col-span-5`}>
            <Suspense fallback={<WidgetSkeleton />}>
              <WorkflowTimeline />
            </Suspense>
          </section>

          <section aria-label="Mensagens entre agentes" className={`${widgetCard} min-h-[280px] xl:col-span-6`}>
            <Suspense fallback={<WidgetSkeleton />}>
              <MultiAgentChat />
            </Suspense>
          </section>
          <section aria-label="Eventos dos agentes" className={`${widgetCard} min-h-[280px] xl:col-span-6`}>
            <Suspense fallback={<WidgetSkeleton />}>
              <LiveReasoningStream />
            </Suspense>
          </section>

          <section aria-label="Memória" className={`${widgetCard} min-h-[360px] xl:col-span-12`}>
            <Suspense fallback={<WidgetSkeleton />}>
              <MemoryRAG />
            </Suspense>
          </section>
        </div>
      </div>
    </NexusLayout>
  );
}
