'use client';

import React, { useRef, useEffect, useState } from 'react';
import { useSSE } from '@/hooks/useSSE';
import { apiUrl } from '@/lib/api';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain } from 'lucide-react';
import { Badge, Meter, AnimatedNumber, EmptyState, StatusDot } from '../ui/Primitives';

interface ReasoningMessage {
  id: string;
  type: 'reasoning' | 'planning' | 'debate' | 'reflection' | 'architecture' | 'critique';
  agentId: string;
  agentType: string;
  timestamp: number;
  content: string;
  metadata?: {
    confidence?: number;
    priority?: string;
    severity?: string;
    decision?: string;
  };
}

const TYPE_LABEL_PT: Record<ReasoningMessage['type'], string> = {
  reasoning: 'raciocínio',
  planning: 'planeamento',
  debate: 'debate',
  reflection: 'reflexão',
  architecture: 'arquitetura',
  critique: 'crítica',
};

const LEVEL_TONE: Record<string, 'danger' | 'warning' | 'success'> = {
  CRITICAL: 'danger',
  HIGH: 'danger',
  MEDIUM: 'warning',
  LOW: 'success',
};

const LEVEL_LABEL_PT: Record<string, string> = {
  CRITICAL: 'Crítico',
  HIGH: 'Alta',
  MEDIUM: 'Média',
  LOW: 'Baixa',
};

export function LiveReasoningStream() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<ReasoningMessage[]>([]);
  const { data: newMessages, isConnected } = useSSE<ReasoningMessage[]>(apiUrl('/api/reasoning/stream'));

  useEffect(() => {
    if (newMessages) {
      setMessages(prev => [...prev, ...newMessages].slice(-50)); // Keep last 50
    }
  }, [newMessages]);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className={`live-reasoning-stream nx-elev-2 nx-surface relative w-full h-full !border !border-cyan-500/25 rounded-lg overflow-hidden ${isConnected ? 'nx-live-rim' : ''}`}>
      <div className="absolute top-0 left-0 right-0 z-10 bg-gradient-to-b from-black/80 to-transparent p-4">
        <h2 className="flex items-center gap-2 text-cyan-400 text-xl font-bold">
          RACIOCÍNIO EM DIRETO
          <StatusDot tone={isConnected ? 'success' : 'neutral'} pulse={isConnected} label={isConnected ? 'Ligado' : 'Desligado'} />
        </h2>
        <p className="text-gray-400 text-xs">Cognição da IA em tempo real</p>
      </div>

      <div
        ref={containerRef}
        className="h-full overflow-y-auto pt-20 pb-4 px-4 space-y-2"
      >
        <AnimatePresence mode="popLayout">
          {messages.map((message, index) => (
            <ReasoningMessageItem key={message.id} message={message} index={index} />
          ))}
        </AnimatePresence>
      </div>

      {messages.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center">
          <EmptyState
            icon={<Brain className="h-6 w-6" />}
            title="A aguardar o stream de cognição da IA"
            hint={isConnected ? "Ligado — os pensamentos dos agentes aparecem aqui assim que forem gerados." : "Sem ligação ao stream de raciocínio."}
          />
        </div>
      )}
    </div>
  );
}

function ReasoningMessageItem({ message, index }: { message: ReasoningMessage, index: number }) {
  const getTypeColor = (type: string) => {
    switch (type) {
      case 'reasoning': return 'text-blue-400';
      case 'planning': return 'text-emerald-400';
      case 'debate': return 'text-purple-400';
      case 'reflection': return 'text-amber-400';
      case 'architecture': return 'text-cyan-400';
      case 'critique': return 'text-rose-400';
      default: return 'text-gray-400';
    }
  };

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'reasoning': return '🧠';
      case 'planning': return '📋';
      case 'debate': return '⚔️';
      case 'reflection': return '🪞';
      case 'architecture': return '🏗️';
      case 'critique': return '🔍';
      default: return '💭';
    }
  };

  const confidencePct = message.metadata?.confidence != null ? message.metadata.confidence * 100 : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, x: -20 }}
      animate={{ opacity: 1, y: 0, x: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      className="reasoning-message nx-elev-1 nx-surface !border !border-cyan-500/20 rounded-lg p-4 transition-colors hover:!border-cyan-500/50"
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg" aria-hidden="true">{getTypeIcon(message.type)}</span>
        <span className={`text-xs font-bold uppercase ${getTypeColor(message.type)}`}>
          [{TYPE_LABEL_PT[message.type] ?? message.type}]
        </span>
        <span className="text-cyan-400 font-semibold text-sm truncate" title={message.agentId}>
          {message.agentId}
        </span>
        <span className="text-gray-500 text-xs">
          ({message.agentType})
        </span>
        <span className="ml-auto text-gray-600 text-xs shrink-0">
          {new Date(message.timestamp).toLocaleTimeString('pt-PT')}
        </span>
      </div>

      <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
        {message.content}
      </div>

      {message.metadata && (
        <div className="mt-3 pt-3 border-t border-gray-800 flex flex-wrap items-center gap-3">
          {confidencePct !== null && (
            <div className="flex items-center gap-2">
              <span className="text-gray-500 text-xs">Confiança:</span>
              <Meter value={confidencePct} tone="info" height={6} showThresholds={false} className="w-20" />
              <span className="text-xs text-cyan-400 tabular-nums">
                <AnimatedNumber value={confidencePct} decimals={0} />%
              </span>
            </div>
          )}

          {message.metadata.priority && (
            <Badge tone={LEVEL_TONE[message.metadata.priority] ?? 'neutral'}>
              {LEVEL_LABEL_PT[message.metadata.priority] ?? message.metadata.priority}
            </Badge>
          )}

          {message.metadata.severity && (
            <Badge tone={LEVEL_TONE[message.metadata.severity] ?? 'neutral'}>
              {LEVEL_LABEL_PT[message.metadata.severity] ?? message.metadata.severity}
            </Badge>
          )}

          {message.metadata.decision && (
            <span className="text-xs text-emerald-400">
              ✓ {message.metadata.decision}
            </span>
          )}
        </div>
      )}
    </motion.div>
  );
}
