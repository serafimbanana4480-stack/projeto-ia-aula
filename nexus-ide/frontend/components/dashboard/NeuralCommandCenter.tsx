'use client';

import React from 'react';
import { AISwarmCore } from './AISwarmCore';
import { LiveReasoningStream } from './LiveReasoningStream';
import { ExecutionTimeline } from './ExecutionTimeline';
import { MemorySystemVisualization } from './MemorySystemVisualization';
import { useSystemStore } from '../../stores/useSystemStore';
import { useMetricsStore } from '../../stores/metricsStore';
import { AnimatedNumber } from '../ui/Primitives';

const STATUS_STYLES: Record<string, string> = {
  operational: 'text-emerald-400',
  degraded: 'text-amber-400',
  incident: 'text-rose-400',
  maintenance: 'text-amber-400',
};

const STATUS_LABEL_PT: Record<string, string> = {
  operational: 'Operacional',
  degraded: 'Degradado',
  incident: 'Incidente',
  maintenance: 'Manutenção',
};

export default function NeuralCommandCenter() {
  const runningAgents = useSystemStore((s) => s.metrics.runningAgents) ?? 0;
  const globalStatus = useSystemStore((s) => s.globalStatus);
  const tokensPerSecond = useMetricsStore((s) => s.metrics?.tokens_per_second) ?? 0;
  const tpsParts = tokensPerSecond >= 1000 ? { num: tokensPerSecond / 1000, decimals: 1, suffix: 'K' } : { num: tokensPerSecond, decimals: 1, suffix: '' };

  return (
    <div className="w-full h-screen bg-[#0a0a0f] overflow-hidden">
      {/* Header */}
      <div className="absolute top-0 left-0 right-0 z-50 nx-elev-3 nx-glass border-b !border-cyan-500/25 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-purple-400 bg-clip-text text-transparent">
              NEXUS OMEGA
            </h1>
            <p className="text-gray-400 text-sm">Centro de Comando Neural</p>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-right">
              <div className="text-cyan-400 text-2xl font-bold tabular-nums">
                <AnimatedNumber value={runningAgents} />
              </div>
              <div className="text-gray-500 text-xs">Agentes Ativos</div>
            </div>
            <div className="text-right">
              <div className={`text-2xl font-bold ${STATUS_STYLES[globalStatus] ?? 'text-emerald-400'}`}>
                {STATUS_LABEL_PT[globalStatus] ?? globalStatus}
              </div>
              <div className="text-gray-500 text-xs">Saúde do Sistema</div>
            </div>
            <div className="text-right">
              <div className="text-purple-400 text-2xl font-bold tabular-nums">
                <AnimatedNumber value={tpsParts.num} decimals={tpsParts.decimals} />
                {tpsParts.suffix}
              </div>
              <div className="text-gray-500 text-xs">Tokens/s</div>
            </div>
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" title="Ligado" />
          </div>
        </div>
      </div>

      {/* Main Grid Layout */}
      <div className="h-full pt-20 grid grid-cols-12 grid-rows-6 gap-4 p-4">

        {/* AI SWARM CORE - Center (Largest). Its own root has no chrome by
            design, so this cell supplies the elevation/border. */}
        <div className="col-span-8 row-span-4 nx-elev-2 !border !border-cyan-500/25 rounded-lg overflow-hidden">
          <AISwarmCore />
        </div>

        {/* The other three widgets already carry their own nx-elev/border
            treatment on their root element — the cell here only sizes them,
            so the frame is not drawn twice. */}
        <div className="col-span-4 row-span-4 overflow-hidden rounded-lg">
          <LiveReasoningStream />
        </div>

        <div className="col-span-6 row-span-2 overflow-hidden rounded-lg">
          <ExecutionTimeline />
        </div>

        <div className="col-span-6 row-span-2 overflow-hidden rounded-lg">
          <MemorySystemVisualization />
        </div>

      </div>
    </div>
  );
}
