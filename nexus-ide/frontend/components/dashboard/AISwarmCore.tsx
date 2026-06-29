'use client';

import React, { useRef, useState, useEffect } from 'react';
import { useSSE } from '@/hooks/useSSE';
import { motion } from 'framer-motion';

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

export function AISwarmCore() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [selectedAgent, setSelectedAgent] = useState<AgentNode | null>(null);
  const { data: agents } = useSSE<AgentNode[]>('http://localhost:8000/api/agents/topology/stream');
  const { data: connections } = useSSE<AgentConnection[]>('http://localhost:8000/api/agents/connections/stream');

  useEffect(() => {
    if (!canvasRef.current) return;
    
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const nodes = agents?.map(agent => ({
      id: agent.agentId,
      x: agent.x || Math.random() * canvas.width,
      y: agent.y || Math.random() * canvas.height,
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
        node.x += pulse * 0.1;
        node.y += pulse * 0.1;
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
      <div className="absolute top-4 left-4 z-10 bg-black/50 backdrop-blur-md p-4 rounded-lg border border-cyan-500/30">
        <h2 className="text-cyan-400 text-xl font-bold mb-2">AI SWARM CORE</h2>
        <div className="text-xs text-gray-400">
          <div>Agents: {agents?.length || 0}</div>
          <div>Connections: {connections?.length || 0}</div>
          <div>Active: {agents?.filter(a => a.status === 'active').length || 0}</div>
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
      className="absolute top-4 right-4 z-20 bg-black/80 backdrop-blur-xl p-6 rounded-lg border border-cyan-500/50 w-80"
    >
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-cyan-400 font-bold">{agent.agentId}</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-white">✕</button>
      </div>
      
      <div className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-400">Type:</span>
          <span className="text-white">{agent.agentType}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Status:</span>
          <span className={agent.status === 'active' ? 'text-green-400' : 'text-orange-400'}>
            {agent.status.toUpperCase()}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Model:</span>
          <span className="text-white">{agent.model}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Task:</span>
          <span className="text-white">{agent.task}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">CPU:</span>
          <span className="text-white">{agent.cpu}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Memory:</span>
          <span className="text-white">{agent.memory}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Tokens/s:</span>
          <span className="text-white">{agent.tokensPerSecond}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Reasoning Depth:</span>
          <span className="text-white">{agent.reasoningDepth}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Confidence:</span>
          <span className="text-white">{Math.round(agent.confidence * 100)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Retries:</span>
          <span className="text-white">{agent.retries}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Workflow:</span>
          <span className="text-white">{agent.workflow}</span>
        </div>
      </div>
    </motion.div>
  );
}
