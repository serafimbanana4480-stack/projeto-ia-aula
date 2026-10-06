'use client';

import React, { useState, useRef } from 'react';
import { useSSE } from '@/hooks/useSSE';
import { apiUrl } from '@/lib/api';
import { motion } from 'framer-motion';
import { StatusDot } from '../ui/Primitives';

interface TimelineEvent {
  id: string;
  type: 'task' | 'subtask' | 'retry' | 'failure' | 'fix' | 'deployment' | 'commit' | 'test' | 'workflow';
  timestamp: number;
  duration?: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  title: string;
  description?: string;
  metadata?: any;
  parentId?: string;
  children?: TimelineEvent[];
}

const TYPE_LABEL_PT: Record<TimelineEvent['type'], string> = {
  task: 'tarefa',
  subtask: 'subtarefa',
  retry: 'nova tentativa',
  failure: 'falha',
  fix: 'correção',
  deployment: 'implementação',
  commit: 'commit',
  test: 'teste',
  workflow: 'fluxo de trabalho',
};

const STATUS_LABEL_PT: Record<TimelineEvent['status'], string> = {
  pending: 'pendente',
  running: 'a executar',
  completed: 'concluído',
  failed: 'falhou',
};

export function ExecutionTimeline() {
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);
  const [zoom, setZoom] = useState(1);
  const containerRef = useRef<HTMLDivElement>(null);
  const { data: events, isConnected } = useSSE<TimelineEvent[]>(apiUrl('/api/timeline/stream'));

  return (
    <div className={`execution-timeline nx-elev-2 nx-surface relative h-full w-full overflow-hidden rounded-lg !border !border-cyan-500/25 ${isConnected ? 'nx-live-rim' : ''}`}>
      <div className="absolute top-0 left-0 right-0 z-10 bg-gradient-to-b from-black/80 to-transparent p-4 flex justify-between items-center">
        <div>
          <h2 className="flex items-center gap-2 text-cyan-400 text-xl font-bold">
            LINHA TEMPORAL DE EXECUÇÃO
            <StatusDot tone={isConnected ? 'success' : 'neutral'} pulse={isConnected} label={isConnected ? 'Ligado' : 'Desligado'} />
          </h2>
          <p className="text-gray-400 text-xs">Visualização cinematográfica da execução autónoma</p>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setZoom(Math.min(zoom * 1.2, 3))}
            aria-label="Aproximar"
            className="px-3 py-1 bg-cyan-500/20 text-cyan-400 rounded hover:bg-cyan-500/30 transition-colors text-sm"
          >
            Aproximar
          </button>
          <button
            onClick={() => setZoom(Math.max(zoom / 1.2, 0.5))}
            aria-label="Afastar"
            className="px-3 py-1 bg-cyan-500/20 text-cyan-400 rounded hover:bg-cyan-500/30 transition-colors text-sm"
          >
            Afastar
          </button>
          <button
            onClick={() => setZoom(1)}
            aria-label="Repor zoom"
            className="px-3 py-1 bg-cyan-500/20 text-cyan-400 rounded hover:bg-cyan-500/30 transition-colors text-sm"
          >
            Repor
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="h-full overflow-x-auto pt-20 pb-4 px-4"
      >
        <div
          className="relative h-full"
          style={{
            minWidth: `${(events?.length || 0) * 200 * zoom}px`,
            transform: `scaleX(${zoom})`,
            transformOrigin: 'left'
          }}
        >
          {/* Timeline base line */}
          <div className="absolute top-1/2 left-0 right-0 h-0.5 bg-gradient-to-r from-cyan-500/50 to-purple-500/50" />

          {!events?.length && (
            <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
              <span className="text-sm text-gray-400">Sem eventos de execução ainda</span>
              <span className="text-xs text-gray-600">
                {isConnected ? 'A aguardar o próximo evento do stream.' : 'Sem ligação ao stream de eventos.'}
              </span>
            </div>
          )}

          {/* Events */}
          {events?.map((event, index) => (
            <TimelineEventItem
              key={event.id}
              event={event}
              index={index}
              onClick={() => setSelectedEvent(event)}
              selected={selectedEvent?.id === event.id}
            />
          ))}
        </div>
      </div>

      {selectedEvent && (
        <EventDetailsPanel
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
        />
      )}
    </div>
  );
}

function TimelineEventItem({ event, index, onClick, selected }: {
  event: TimelineEvent,
  index: number,
  onClick: () => void,
  selected: boolean
}) {
  const width = event.duration ? Math.max(event.duration * 10, 50) : 50;
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'bg-[var(--nx-accent)]';
      case 'completed': return 'bg-emerald-500';
      case 'failed': return 'bg-rose-500';
      case 'pending': return 'bg-slate-500';
      default: return 'bg-slate-500';
    }
  };

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'task': return '📋';
      case 'subtask': return '📝';
      case 'retry': return '🔄';
      case 'failure': return '❌';
      case 'fix': return '✅';
      case 'deployment': return '🚀';
      case 'commit': return '💾';
      case 'test': return '🧪';
      case 'workflow': return '⚙️';
      default: return '📌';
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      className={`timeline-event absolute cursor-pointer transition-all hover:scale-105 ${
        selected ? 'ring-2 ring-cyan-400 z-10' : ''
      }`}
      style={{
        left: `${index * 200}px`,
        top: '50%',
        transform: 'translateY(-50%)',
      }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      aria-label={`${event.title}: ${STATUS_LABEL_PT[event.status]}`}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {/* Event marker */}
      <div
        className={`w-4 h-4 rounded-full ${getStatusColor(event.status)} ${
          event.status === 'running' ? 'animate-pulse' : ''
        }`}
      />

      {/* Event bar */}
      <div
        className={`absolute top-1/2 left-4 h-2 rounded ${getStatusColor(event.status)} ${
          event.status === 'running' ? 'animate-pulse' : ''
        }`}
        style={{ width: `${width}px` }}
      >
        {event.status === 'running' && (
          <motion.div
            className="absolute top-0 left-0 h-full bg-white/30"
            initial={{ width: 0 }}
            animate={{ width: '100%' }}
            transition={{ duration: event.duration || 5, ease: 'linear' }}
          />
        )}
      </div>

      {/* Event label */}
      <div className="absolute top-full left-0 mt-2 nx-elev-2 nx-surface p-2 rounded border !border-cyan-500/25 min-w-[150px]">
        <div className="flex items-center gap-2 mb-1">
          <span aria-hidden="true">{getTypeIcon(event.type)}</span>
          <span className="text-cyan-400 text-xs font-semibold uppercase">
            {TYPE_LABEL_PT[event.type]}
          </span>
        </div>
        <div className="text-white text-sm font-medium truncate">
          {event.title}
        </div>
        <div className="text-gray-400 text-xs">
          {new Date(event.timestamp).toLocaleTimeString('pt-PT')}
        </div>
      </div>
    </motion.div>
  );
}

function EventDetailsPanel({ event, onClose }: { event: TimelineEvent, onClose: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.8 }}
      className="absolute bottom-4 right-4 z-20 nx-elev-3 nx-surface nx-glass p-6 rounded-lg !border !border-cyan-500/40 w-96 max-h-[80vh] overflow-y-auto"
    >
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-cyan-400 font-bold">{event.title}</h3>
        <button onClick={onClose} aria-label="Fechar detalhes" className="text-gray-400 hover:text-white">✕</button>
      </div>

      <div className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-400">Tipo:</span>
          <span className="text-white">{TYPE_LABEL_PT[event.type]}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Estado:</span>
          <span className={`${
            event.status === 'completed' ? 'text-emerald-400' :
            event.status === 'failed' ? 'text-rose-400' :
            event.status === 'running' ? 'text-[var(--nx-accent-bright)]' :
            'text-gray-400'
          }`}>
            {STATUS_LABEL_PT[event.status]}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Duração:</span>
          <span className="text-white tabular-nums">{event.duration != null ? `${event.duration}s` : '—'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Data/hora:</span>
          <span className="text-white">
            {new Date(event.timestamp).toLocaleString('pt-PT')}
          </span>
        </div>

        {event.description && (
          <div className="pt-3 border-t border-gray-800">
            <span className="text-gray-400 block mb-1">Descrição:</span>
            <span className="text-white">{event.description}</span>
          </div>
        )}

        {event.metadata && (
          <div className="pt-3 border-t border-gray-800">
            <span className="text-gray-400 block mb-2">Metadados:</span>
            <pre className="nx-inset text-xs text-gray-300 p-2 rounded overflow-x-auto">
              {JSON.stringify(event.metadata, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </motion.div>
  );
}
