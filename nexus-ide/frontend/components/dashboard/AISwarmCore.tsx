'use client';

import React, { useRef, useState, useEffect } from 'react';
import { useSSE } from '@/hooks/useSSE';
import { apiUrl } from '@/lib/api';
import { motion } from 'framer-motion';
import { StatusDot } from '../ui/Primitives';

interface AgentNode {
  id: string;
  agentId: string;
  agentType: string;
  status: 'active' | 'busy' | 'error' | 'idle';
  model: string;
  task: string;
  cpu: number;
  memory: number;
  tokensPerSecond: number;
  reasoningDepth: number;
  confidence: number;
  retries: number;
  workflow: string;
  x?: number;
  y?: number;
}

interface AgentConnection {
  source: string;
  target: string;
  type: 'debate' | 'coordination' | 'error' | 'planning';
  frequency: number;
  messageRate: number;
}

const STATUS_LABEL_PT: Record<AgentNode['status'], string> = {
  active: 'Ativo',
  busy: 'Ocupado',
  error: 'Erro',
  idle: 'Inativo',
};

/**
 * A topology endpoint reports relationships, not chart coordinates. Keep the
 * layout deterministic so the same real agent never appears to be a new one
 * on every render.
 */
function getNodePosition(id: string, index: number, width: number, height: number) {
  let seed = index + 1;
  for (let i = 0; i < id.length; i += 1) seed = (seed * 31 + id.charCodeAt(i)) >>> 0;
  const xRatio = 0.12 + ((seed & 0xffff) / 0xffff) * 0.76;
  const yRatio = 0.18 + (((seed >>> 16) & 0xffff) / 0xffff) * 0.64;
  return { x: width * xRatio, y: height * yRatio };
}

export function AISwarmCore() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [selectedAgent, setSelectedAgent] = useState<AgentNode | null>(null);
  const { data: agents, isConnected } = useSSE<AgentNode[]>(apiUrl('/api/agents/topology/stream'));
  const { data: connections } = useSSE<AgentConnection[]>(apiUrl('/api/agents/connections/stream'));

  useEffect(() => {
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.parentElement?.clientWidth || canvas.width;
    const height = canvas.parentElement?.clientHeight || canvas.height;
    const nodes = agents?.map((agent, index) => ({
      id: agent.agentId,
      ...(agent.x != null && agent.y != null ? { x: agent.x, y: agent.y } : getNodePosition(agent.agentId, index, width, height)),
      agentType: agent.agentType,
      status: agent.status,
      model: agent.model,
      task: agent.task,
      cpu: agent.cpu,
      memory: agent.memory,
      tokensPerSecond: agent.tokensPerSecond,
      reasoningDepth: agent.reasoningDepth,
      confidence: agent.confidence,
      retries: agent.retries,
      workflow: agent.workflow,
      color: getNodeColor(agent.status),
      size: getNodeSize(agent.cpu, agent.memory),
    })) || [];

    const links = connections?.map(conn => ({
      source: conn.source,
      target: conn.target,
      color: getConnectionColor(conn.type),
      width: Math.min(conn.frequency / 10, 5),
    })) || [];

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Draw connections
      links.forEach(link => {
        const sourceNode = nodes.find(n => n.id === link.source);
        const targetNode = nodes.find(n => n.id === link.target);
        if (sourceNode && targetNode) {
          ctx.beginPath();
          ctx.moveTo(sourceNode.x, sourceNode.y);
          ctx.lineTo(targetNode.x, targetNode.y);
          ctx.strokeStyle = link.color;
          ctx.globalAlpha = 0.6;
          ctx.lineWidth = link.width;
          ctx.stroke();
        }
      });

      // Draw nodes
      nodes.forEach(node => {
        const size = node.size / 10;

        // Glow effect
        ctx.beginPath();
        ctx.arc(node.x, node.y, size * 1.5, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.globalAlpha = 0.3;
        ctx.fill();

        // Main circle
        ctx.beginPath();
        ctx.arc(node.x, node.y, size, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.globalAlpha = 0.8;
        ctx.fill();

        // Inner highlight
        ctx.beginPath();
        ctx.arc(node.x - size * 0.3, node.y - size * 0.3, size * 0.3, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.globalAlpha = 0.4;
        ctx.fill();

        ctx.globalAlpha = 1;
      });
    };

    // Handle resize
    const handleResize = () => {
      const parent = canvas.parentElement;
      if (parent) {
        canvas.width = parent.clientWidth;
        canvas.height = parent.clientHeight;
        draw();
      }
    };

    handleResize();
    window.addEventListener('resize', handleResize);

    // Animation loop
    const animationId = setInterval(() => {
      const time = Date.now() * 0.001;
      nodes.forEach((node, i) => {
        const pulse = Math.sin(time + i * 0.5) * 2;
        node.x = Math.max(12, Math.min(canvas.width - 12, node.x + pulse * 0.1));
        node.y = Math.max(12, Math.min(canvas.height - 12, node.y + pulse * 0.1));
      });
      draw();
    }, 50);

    return () => {
      window.removeEventListener('resize', handleResize);
      clearInterval(animationId);
    };
  }, [agents, connections]);

  return (
    <div className="ai-swarm-core relative w-full h-full bg-[#0a0a0f]">
      <div className="absolute top-4 left-4 z-10 nx-elev-2 nx-glass p-4 rounded-lg !border !border-cyan-500/25">
        <h2 className="flex items-center gap-2 text-cyan-400 text-xl font-bold mb-2">
          NÚCLEO DO SWARM DE IA
          <StatusDot tone={isConnected ? 'success' : 'neutral'} pulse={isConnected} label={isConnected ? 'Ligado' : 'Desligado'} />
        </h2>
        <div className="text-xs text-gray-400 space-y-0.5">
          <div>Agentes: <span className="tabular-nums text-gray-200">{agents?.length || 0}</span></div>
          <div>Ligações: <span className="tabular-nums text-gray-200">{connections?.length || 0}</span></div>
          <div>Ativos: <span className="tabular-nums text-emerald-400">{agents?.filter(a => a.status === 'active').length || 0}</span></div>
        </div>
      </div>

      {selectedAgent && (
        <AgentDetailsPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
      )}

      <canvas ref={canvasRef} className="w-full h-full" />
    </div>
  );
}

function getNodeColor(status: string): string {
  switch (status) {
    case 'active': return '#00f0ff';
    case 'busy': return '#ff8800';
    case 'error': return '#ff0044';
    case 'idle': return '#00ff88';
    default: return '#00f0ff';
  }
}

function getConnectionColor(type: string): string {
  switch (type) {
    case 'debate': return '#b000ff';
    case 'coordination': return '#00f0ff';
    case 'error': return '#ff0044';
    case 'planning': return '#00ff88';
    default: return '#00f0ff';
  }
}

function getNodeSize(cpu: number, memory: number): number {
  return Math.max(20, Math.min(100, (cpu + memory) / 2));
}

function AgentDetailsPanel({ agent, onClose }: { agent: AgentNode, onClose: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.8 }}
      className="absolute top-4 right-4 z-20 nx-elev-3 nx-surface nx-glass p-6 rounded-lg !border !border-cyan-500/40 w-80"
    >
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-cyan-400 font-bold">{agent.agentId}</h3>
        <button onClick={onClose} aria-label="Fechar detalhes" className="text-gray-400 hover:text-white">✕</button>
      </div>

      <div className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-400">Tipo:</span>
          <span className="text-white">{agent.agentType}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Estado:</span>
          <span className={agent.status === 'active' ? 'text-emerald-400' : 'text-amber-400'}>
            {STATUS_LABEL_PT[agent.status]}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Modelo:</span>
          <span className="text-white truncate max-w-[60%]" title={agent.model}>{agent.model}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Tarefa:</span>
          <span className="text-white truncate max-w-[60%]" title={agent.task}>{agent.task}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">CPU:</span>
          <span className="text-white tabular-nums">{agent.cpu}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Memória:</span>
          <span className="text-white tabular-nums">{agent.memory}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Tokens/s:</span>
          <span className="text-white tabular-nums">{agent.tokensPerSecond}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Profundidade de raciocínio:</span>
          <span className="text-white tabular-nums">{agent.reasoningDepth}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Confiança:</span>
          <span className="text-white tabular-nums">{Math.round(agent.confidence * 100)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Novas tentativas:</span>
          <span className="text-white tabular-nums">{agent.retries}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Fluxo de trabalho:</span>
          <span className="text-white truncate max-w-[60%]" title={agent.workflow}>{agent.workflow}</span>
        </div>
      </div>
    </motion.div>
  );
}
