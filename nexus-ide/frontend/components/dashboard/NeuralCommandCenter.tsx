'use client';

import React from 'react';
import { AISwarmCore } from './AISwarmCore';
import { LiveReasoningStream } from './LiveReasoningStream';
import { ExecutionTimeline } from './ExecutionTimeline';
import { MemorySystemVisualization } from './MemorySystemVisualization';

export default function NeuralCommandCenter() {
  return (
    <div className="w-full h-screen bg-[#0a0a0f] overflow-hidden">
      {/* Header */}
      <div className="absolute top-0 left-0 right-0 z-50 bg-black/80 backdrop-blur-xl border-b border-cyan-500/30 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-purple-400 bg-clip-text text-transparent">
              NEXUS OMEGA
            </h1>
            <p className="text-gray-400 text-sm">Neural Command Center</p>
          </div>
          
          <div className="flex items-center gap-6">
            <div className="text-right">
              <div className="text-cyan-400 text-2xl font-bold">23</div>
              <div className="text-gray-500 text-xs">Active Agents</div>
            </div>
            <div className="text-right">
              <div className="text-green-400 text-2xl font-bold">99.9%</div>
              <div className="text-gray-500 text-xs">System Health</div>
            </div>
            <div className="text-right">
              <div className="text-purple-400 text-2xl font-bold">1.2K</div>
              <div className="text-gray-500 text-xs">Tokens/s</div>
            </div>
            <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          </div>
        </div>
      </div>

      {/* Main Grid Layout */}
      <div className="h-full pt-20 grid grid-cols-12 grid-rows-6 gap-4 p-4">
        
        {/* AI SWARM CORE - Center (Largest) */}
        <div className="col-span-8 row-span-4 bg-black/40 backdrop-blur-sm border border-cyan-500/30 rounded-lg overflow-hidden">
          <AISwarmCore />
        </div>

        {/* LIVE REASONING STREAM - Right Side */}
        <div className="col-span-4 row-span-4 bg-black/40 backdrop-blur-sm border border-cyan-500/30 rounded-lg overflow-hidden">
          <LiveReasoningStream />
        </div>

        {/* EXECUTION TIMELINE - Bottom Left */}
        <div className="col-span-6 row-span-2 bg-black/40 backdrop-blur-sm border border-cyan-500/30 rounded-lg overflow-hidden">
          <ExecutionTimeline />
        </div>

        {/* MEMORY SYSTEM VISUALIZATION - Bottom Right */}
        <div className="col-span-6 row-span-2 bg-black/40 backdrop-blur-sm border border-cyan-500/30 rounded-lg overflow-hidden">
          <MemorySystemVisualization />
        </div>

      </div>
    </div>
  );
}
