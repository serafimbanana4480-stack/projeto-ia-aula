"use client";

import React, { useState, useEffect } from "react";
import { useRealTimeStream } from "../../hooks/useRealTimeStream";
import { apiUrl } from "../../lib/api";

type Message = {
  id: string;
  agent: string;
  content: string;
  timestamp: string;
  type: "thinking" | "speaking" | "action" | "result";
};

type Agent = {
  name: string;
  color: string;
  avatar: string;
  status?: string;
};

const AGENTS: Agent[] = [
  { name: "Architect", color: "#8b5cf6", avatar: "🏗️" },
  { name: "Researcher", color: "#06b6d4", avatar: "🔬" },
  { name: "Coder", color: "#10b981", avatar: "💻" },
  { name: "Debugger", color: "#f59e0b", avatar: "🐛" },
  { name: "Documenter", color: "#ec4899", avatar: "📝" },
  { name: "Optimizer", color: "#f97316", avatar: "⚡" },
];

export default function SimpleDashboard() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agents, setAgents] = useState<Record<string, any>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { connectionStatus, isConnected } = useRealTimeStream(
    "http://localhost:8000/api/autonomous-tasks/stream",
    { enabled: true }
  );

  // Fetch real agent data on mount
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [agentsRes, eventsRes] = await Promise.all([
          fetch(apiUrl("/api/agents/status")),
          fetch(apiUrl("/api/autonomous-tasks/stream")).catch(() => null),
        ]);

        if (agentsRes.ok) {
          const data = await agentsRes.json();
          const agentMap: Record<string, any> = {};
          (data.agents ?? []).forEach((a: any) => {
            agentMap[a.name] = a;
          });
          setAgents(agentMap);
        }
      } catch (e) {
        setError("Failed to load agent data");
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  // Subscribe to SSE events for real messages
  useEffect(() => {
    if (!isConnected) return;

    const eventSource = new EventSource(apiUrl("/api/autonomous-tasks/stream"));
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        // Accept both canonical StreamEvent format and legacy formats
        // Canonical: type="task_scheduled", type="agent_started", type="goal", etc.
        // Legacy:    type="task" (with .task sub-object), type="agent_instance"
        // Simple-dashboard is message-focused, so show goal/task/agent events as messages
        if (data.type && data.type !== "heartbeat") {
          const agentName = data.agent
            || (data.task?.agent)
            || (data.goal?.agent)
            || (data.agent_instance?.agent_id)
            || "System";
          const messageContent = data.content
            || data.goal?.content
            || data.task?.goal
            || JSON.stringify(data.data || data.agent_instance || data.task || data.goal || "");
          const newMessage: Message = {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            agent: agentName,
            content: messageContent,
            timestamp: new Date().toISOString(),
            type: data.type === "task" || data.type === "agent_instance" ? "result" :
                   data.type === "goal" ? "action" :
                   data.type === "agent_started" || data.type === "task_scheduled" ? "action" :
                   data.type === "task_completed" || data.type === "agent_finished" ? "result" :
                   (data.payload?.type) || "result",
          };
          setMessages((prev) => [...prev.slice(-49), newMessage]);
        }
      } catch {
        // Ignore malformed events
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => eventSource.close();
  }, [isConnected]);

  const filteredMessages = selectedAgent
    ? messages.filter((m) => m.agent === selectedAgent)
    : messages;

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center">
        <div className="text-slate-500">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-slate-800">NEXUS AI Dashboard</h1>
              <p className="text-sm text-slate-500">Real-time AI Agent Activity</p>
            </div>
            <div className="flex items-center gap-3">
              <div
                className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm ${
                  isConnected ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                }`}
              >
                <div
                  className={`w-2 h-2 rounded-full ${
                    isConnected ? "bg-green-500 animate-pulse" : "bg-red-500"
                  }`}
                />
                {isConnected ? "Live" : "Offline"}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
            {error}
          </div>
        )}

        {/* Agent Filter */}
        <div className="mb-6">
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setSelectedAgent(null)}
              className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
                selectedAgent === null
                  ? "bg-slate-800 text-white shadow-md"
                  : "bg-white text-slate-600 hover:bg-slate-50 border border-slate-200"
              }`}
            >
              All Agents
            </button>
            {AGENTS.map((agent) => (
              <button
                key={agent.name}
                onClick={() => setSelectedAgent(agent.name)}
                className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${
                  selectedAgent === agent.name
                    ? "bg-white text-slate-800 shadow-md border-2"
                    : "bg-white text-slate-600 hover:bg-slate-50 border border-slate-200"
                }`}
                style={selectedAgent === agent.name ? { borderColor: agent.color } : {}}
              >
                <span>{agent.avatar}</span>
                {agent.name}
                {agents[agent.name] && (
                  <span
                    className={`w-2 h-2 rounded-full ${
                      agents[agent.name].status === "idle" ? "bg-gray-300" : "bg-green-400"
                    }`}
                  />
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Messages */}
        <div className="bg-white rounded-2xl shadow-lg border border-slate-200 overflow-hidden">
          <div className="bg-slate-50 border-b border-slate-200 px-6 py-4 flex items-center justify-between">
            <h2 className="font-semibold text-slate-700">Conversation Stream</h2>
            <span className="text-xs text-slate-400">{messages.length} events</span>
          </div>

          <div className="p-6 space-y-4 max-h-[600px] overflow-y-auto">
            {filteredMessages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-slate-500">
                <span className="text-2xl mb-3 opacity-25">💬</span>
                <p className="text-sm font-medium">No messages yet</p>
                <p className="text-[11px] mt-1 text-slate-600">
                  Agent conversations will appear here when the system is active
                </p>
              </div>
            ) : (
              filteredMessages.map((message, index) => {
                const agent = AGENTS.find((a) => a.name === message.agent);
                return (
                  <div
                    key={message.id}
                    className="flex gap-4 p-4 rounded-xl bg-slate-50 hover:bg-slate-100 transition-colors"
                    style={{ animationDelay: `${index * 100}ms` }}
                  >
                    <div
                      className="w-12 h-12 rounded-full flex items-center justify-center text-2xl flex-shrink-0"
                      style={{ backgroundColor: `${agent?.color ?? "#64748b"}15` }}
                    >
                      {agent?.avatar ?? "🤖"}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-slate-800">{message.agent}</span>
                        <span className="text-xs text-slate-400">
                          {new Date(message.timestamp).toLocaleTimeString()}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                            message.type === "thinking"
                              ? "bg-purple-100 text-purple-700"
                              : message.type === "speaking"
                              ? "bg-blue-100 text-blue-700"
                              : message.type === "action"
                              ? "bg-green-100 text-green-700"
                              : "bg-orange-100 text-orange-700"
                          }`}
                        >
                          {message.type}
                        </span>
                      </div>
                      <p className="text-slate-600 leading-relaxed">{message.content}</p>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Agent Status */}
        <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4">
          {AGENTS.map((agent) => {
            const realAgent = agents[agent.name];
            return (
              <div
                key={agent.name}
                className="bg-white rounded-xl p-4 shadow-sm border border-slate-200 hover:shadow-md transition-shadow"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full flex items-center justify-center text-xl">
                    {agent.avatar}
                  </div>
                  <div className="flex-1">
                    <h3 className="font-semibold text-slate-800">{agent.name}</h3>
                    <p className="text-xs text-slate-500">
                      {realAgent ? `Status: ${realAgent.status || "idle"}` : "No data"}
                    </p>
                  </div>
                  <div
                    className={`w-2.5 h-2.5 rounded-full ${
                      realAgent?.status === "active" || realAgent?.status === "thinking"
                        ? "bg-green-400 animate-pulse"
                        : "bg-gray-300"
                    }`}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
