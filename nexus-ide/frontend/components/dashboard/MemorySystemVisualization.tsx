'use client';

import React, { useRef, useEffect, useState } from 'react';
import { useSSE } from '@/hooks/useSSE';
import { apiUrl } from '@/lib/api';
import { StatusDot } from '../ui/Primitives';

interface MemoryNode {
  id: string;
  type: 'graph' | 'episodic' | 'semantic';
  content: string;
  importance: number;
  accessCount: number;
  lastAccessed: number;
  position: { x: number; y: number };
  connections: string[];
}

const TYPE_LABEL_PT: Record<MemoryNode['type'], string> = {
  graph: 'Grafo',
  episodic: 'Episódica',
  semantic: 'Semântica',
};

const VIEW_MODE_LABEL_PT: Record<'graph' | 'episodic' | 'semantic', string> = {
  graph: 'Tudo',
  episodic: 'Episódica',
  semantic: 'Semântica',
};

export function MemorySystemVisualization() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [selectedMemory, setSelectedMemory] = useState<MemoryNode | null>(null);
  const [viewMode, setViewMode] = useState<'graph' | 'episodic' | 'semantic'>('graph');
  const { data: memories, isConnected } = useSSE<MemoryNode[]>(apiUrl('/api/memory/visualization/stream'));

  useEffect(() => {
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const nodes = memories || [];

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Draw connections
      nodes.forEach(node => {
        node.connections.forEach(targetId => {
          const target = nodes.find(n => n.id === targetId);
          if (target) {
            ctx.beginPath();
            ctx.moveTo(node.position.x, node.position.y);
            ctx.lineTo(target.position.x, target.position.y);
            ctx.strokeStyle = 'rgba(0, 255, 255, 0.2)';
            ctx.lineWidth = 1;
            ctx.stroke();
          }
        });
      });

      // Draw nodes
      nodes.forEach(node => {
        const size = node.importance / 5;

        // Glow effect
        ctx.beginPath();
        ctx.arc(node.position.x, node.position.y, size * 1.5, 0, Math.PI * 2);
        ctx.fillStyle = getMemoryColor(node.type);
        ctx.globalAlpha = 0.3;
        ctx.fill();

        // Main circle
        ctx.beginPath();
        ctx.arc(node.position.x, node.position.y, size, 0, Math.PI * 2);
        ctx.fillStyle = getMemoryColor(node.type);
        ctx.globalAlpha = 0.8;
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
        node.position.x += pulse;
        node.position.y += pulse;
      });
      draw();
    }, 50);

    return () => {
      window.removeEventListener('resize', handleResize);
      clearInterval(animationId);
    };
  }, [memories, viewMode]);

  const filteredMemories = memories?.filter(m => {
    if (viewMode === 'graph') return true;
    return m.type === viewMode;
  }) || [];

  return (
    <div className={`memory-system-visualization nx-elev-2 nx-surface relative w-full h-full !border !border-cyan-500/25 rounded-lg overflow-hidden ${isConnected ? 'nx-live-rim' : ''}`}>
      <div className="absolute top-0 left-0 right-0 z-10 bg-gradient-to-b from-black/80 to-transparent p-4">
        <h2 className="flex items-center gap-2 text-cyan-400 text-xl font-bold">
          VISUALIZAÇÃO DO SISTEMA DE MEMÓRIA
          <StatusDot tone={isConnected ? 'success' : 'neutral'} pulse={isConnected} label={isConnected ? 'Ligado' : 'Desligado'} />
        </h2>
        <p className="text-gray-400 text-xs">Cérebro digital em tempo real · {filteredMemories.length} nós</p>
      </div>

      <div className="absolute top-4 right-4 z-10 flex gap-2">
        <button
          onClick={() => setViewMode('graph')}
          className={`px-3 py-1 rounded text-sm transition-colors ${
            viewMode === 'graph' ? 'bg-cyan-500/30 text-cyan-400' : 'bg-black/30 text-gray-400 hover:text-gray-300'
          }`}
        >
          {VIEW_MODE_LABEL_PT.graph}
        </button>
        <button
          onClick={() => setViewMode('episodic')}
          className={`px-3 py-1 rounded text-sm transition-colors ${
            viewMode === 'episodic' ? 'bg-cyan-500/30 text-cyan-400' : 'bg-black/30 text-gray-400 hover:text-gray-300'
          }`}
        >
          {VIEW_MODE_LABEL_PT.episodic}
        </button>
        <button
          onClick={() => setViewMode('semantic')}
          className={`px-3 py-1 rounded text-sm transition-colors ${
            viewMode === 'semantic' ? 'bg-cyan-500/30 text-cyan-400' : 'bg-black/30 text-gray-400 hover:text-gray-300'
          }`}
        >
          {VIEW_MODE_LABEL_PT.semantic}
        </button>
      </div>

      <canvas ref={canvasRef} className="w-full h-full" />

      {!memories?.length && (
        <div className="absolute inset-0 flex items-center justify-center px-6 text-center">
          <div>
            <p className="text-sm text-gray-400">Sem memórias para visualizar</p>
            <p className="mt-1 text-xs text-gray-600">
              {isConnected ? 'Ligado — os nós aparecem assim que forem criados.' : 'Sem ligação ao stream de memória.'}
            </p>
          </div>
        </div>
      )}

      <div className="absolute bottom-4 left-4 z-10 nx-elev-2 nx-glass p-4 rounded-lg !border !border-cyan-500/25">
        <div className="text-xs text-gray-400 space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-cyan-400" />
            <span>Memória de Grafo</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-purple-400" />
            <span>Memória Episódica</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-green-400" />
            <span>Memória Semântica</span>
          </div>
        </div>
      </div>

      {selectedMemory && (
        <MemoryDetailsPanel
          memory={selectedMemory}
          onClose={() => setSelectedMemory(null)}
        />
      )}
    </div>
  );
}

function getMemoryColor(type: string): string {
  switch (type) {
    case 'graph': return '#00f0ff';
    case 'episodic': return '#b000ff';
    case 'semantic': return '#00ff88';
    default: return '#00f0ff';
  }
}

function MemoryDetailsPanel({ memory, onClose }: { memory: MemoryNode, onClose: () => void }) {
  return (
    <div className="absolute bottom-4 right-4 z-20 nx-elev-3 nx-surface nx-glass p-6 rounded-lg !border !border-cyan-500/40 w-80">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-cyan-400 font-bold">Nó de Memória</h3>
        <button onClick={onClose} aria-label="Fechar detalhes" className="text-gray-400 hover:text-white">✕</button>
      </div>

      <div className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-400">Tipo:</span>
          <span className="text-white">{TYPE_LABEL_PT[memory.type]}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Importância:</span>
          <span className="text-white tabular-nums">{memory.importance}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Nº de acessos:</span>
          <span className="text-white tabular-nums">{memory.accessCount}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Último acesso:</span>
          <span className="text-white">{new Date(memory.lastAccessed).toLocaleString('pt-PT')}</span>
        </div>
        <div className="mt-4">
          <span className="text-gray-400 block mb-2">Conteúdo:</span>
          <p className="nx-inset text-white text-xs p-3 rounded">
            {memory.content}
          </p>
        </div>
      </div>
    </div>
  );
}
