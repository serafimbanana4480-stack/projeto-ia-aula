'use client';

import React, { useRef, useEffect, useState } from 'react';
import { useSSE } from '@/hooks/useSSE';
import { motion, AnimatePresence } from 'framer-motion';

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

export function LiveReasoningStream() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<ReasoningMessage[]>([]);
  const { data: newMessages } = useSSE<ReasoningMessage[]>('http://localhost:8000/api/reasoning/stream');
  
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
    <div className="live-reasoning-stream relative w-full h-full bg-[#0a0a0f] border border-cyan-500/30 rounded-lg overflow-hidden">
      <div className="absolute top-0 left-0 right-0 z-10 bg-gradient-to-b from-black/80 to-transparent p-4">
        <h2 className="text-cyan-400 text-xl font-bold">LIVE REASONING STREAM</h2>
        <p className="text-gray-400 text-xs">AI cognition in real-time</p>
      </div>

      <div 
        ref={containerRef}
        className="h-full overflow-y-auto pt-20 pb-4 px-4 space-y-2"
      >
        <AnimatePresence mode="popLayout">
          {messages.map((message, index) => (
            <ReasoningMessage key={message.id} message={message} index={index} />
          ))}
        </AnimatePresence>
      </div>

      {messages.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-gray-500">Waiting for AI cognition stream...</div>
        </div>
      )}
    </div>
  );
}

function ReasoningMessage({ message, index }: { message: ReasoningMessage, index: number }) {
  const getTypeColor = (type: string) => {
    switch (type) {
      case 'reasoning': return 'text-blue-400';
      case 'planning': return 'text-green-400';
      case 'debate': return 'text-purple-400';
      case 'reflection': return 'text-yellow-400';
      case 'architecture': return 'text-cyan-400';
      case 'critique': return 'text-red-400';
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

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, x: -20 }}
      animate={{ opacity: 1, y: 0, x: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      className={`reasoning-message bg-black/40 backdrop-blur-sm border border-cyan-500/20 rounded-lg p-4 hover:border-cyan-500/50 transition-colors`}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{getTypeIcon(message.type)}</span>
        <span className={`text-xs font-bold uppercase ${getTypeColor(message.type)}`}>
          [{message.type}]
        </span>
        <span className="text-cyan-400 font-semibold text-sm">
          {message.agentId}
        </span>
        <span className="text-gray-500 text-xs">
          ({message.agentType})
        </span>
        <span className="ml-auto text-gray-600 text-xs">
          {new Date(message.timestamp).toLocaleTimeString()}
        </span>
      </div>
      
      <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
        {message.content}
      </div>
      
      {message.metadata && (
        <div className="mt-3 pt-3 border-t border-gray-800 flex flex-wrap gap-3">
          {message.metadata.confidence !== undefined && (
            <div className="flex items-center gap-2">
              <span className="text-gray-500 text-xs">Confidence:</span>
              <div className="w-20 h-2 bg-gray-800 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${message.metadata.confidence * 100}%` }}
                  className="h-full bg-gradient-to-r from-cyan-500 to-purple-500"
                />
              </div>
              <span className="text-xs text-cyan-400">
                {Math.round(message.metadata.confidence * 100)}%
              </span>
            </div>
          )}
          
          {message.metadata.priority && (
            <span className={`text-xs px-2 py-1 rounded ${
              message.metadata.priority === 'HIGH' ? 'bg-red-500/20 text-red-400' :
              message.metadata.priority === 'MEDIUM' ? 'bg-yellow-500/20 text-yellow-400' :
              'bg-green-500/20 text-green-400'
            }`}>
              {message.metadata.priority}
            </span>
          )}
          
          {message.metadata.severity && (
            <span className={`text-xs px-2 py-1 rounded ${
              message.metadata.severity === 'CRITICAL' ? 'bg-red-500/20 text-red-400' :
              message.metadata.severity === 'HIGH' ? 'bg-orange-500/20 text-orange-400' :
              'bg-yellow-500/20 text-yellow-400'
            }`}>
              {message.metadata.severity}
            </span>
          )}
          
          {message.metadata.decision && (
            <span className="text-xs text-green-400">
              ✓ {message.metadata.decision}
            </span>
          )}
        </div>
      )}
    </motion.div>
  );
}
