"use client";

import { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import { Radio, Filter, Clock } from "lucide-react";
import { useMissionStore } from "../../stores/missionStore";

const topicColors: Record<string, string> = {
  "code.changes": "text-blue-400",
  "test.results": "text-green-400",
  "errors.found": "text-red-400",
  "architecture.proposals": "text-purple-400",
  "review.completed": "text-nexus-accent2",
  "agent.status": "text-gray-400",
  "mission.update": "text-nexus-accent",
};

function getTopicColor(topic: string): string {
  return topicColors[topic] || "text-nexus-muted";
}

export default function BusVisualizer() {
  const messages = useMissionStore((s) => s.busMessages);
  const [filterTopic, setFilterTopic] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const filtered = filterTopic
    ? messages.filter((m) => m.topic.toLowerCase().includes(filterTopic.toLowerCase()))
    : messages;

  const topics = Array.from(new Set(messages.map((m) => m.topic))).slice(0, 12);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [filtered, autoScroll]);

  return (
    <div className="rounded-lg border border-nexus-border bg-nexus-panel p-4 flex flex-col">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-nexus-accent3" />
          <span className="text-sm font-semibold">Agent Bus</span>
          <span className="rounded bg-nexus-accent3/10 px-1.5 py-0.5 text-[10px] text-nexus-accent3">
            {filtered.length} msgs
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`rounded px-2 py-0.5 text-[10px] transition-colors ${
              autoScroll ? "bg-nexus-accent/10 text-nexus-accent" : "text-nexus-muted hover:text-nexus-text"
            }`}
          >
            Auto-scroll
          </button>
        </div>
      </div>

      {/* Topic filters */}
      <div className="mb-2 flex flex-wrap gap-1">
        <button
          onClick={() => setFilterTopic("")}
          className={`rounded px-2 py-0.5 text-[10px] transition-colors ${
            filterTopic === "" ? "bg-nexus-accent/15 text-nexus-accent" : "bg-nexus-card text-nexus-muted hover:text-nexus-text"
          }`}
        >
          Todos
        </button>
        {topics.map((t) => (
          <button
            key={t}
            onClick={() => setFilterTopic(t)}
            className={`rounded px-2 py-0.5 text-[10px] transition-colors ${
              filterTopic === t ? "bg-nexus-accent/15 text-nexus-accent" : "bg-nexus-card text-nexus-muted hover:text-nexus-text"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Terminal-like message stream */}
      <div
        ref={containerRef}
        className="relative flex-1 min-h-[200px] max-h-[300px] overflow-y-auto overflow-x-hidden thin-scrollbar rounded border border-nexus-border/50 bg-nexus-bg/50 p-2 font-mono text-[11px]"
      >
        {filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center text-nexus-muted">
            <Filter className="h-3 w-3 mr-1" />
            Sem mensagens
          </div>
        ) : (
          <div className="space-y-1">
            {filtered.map((msg, idx) => (
              <motion.div
                key={`${msg.message_id}-${idx}`}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                className="flex flex-wrap items-start gap-x-2 gap-y-0.5 py-0.5"
              >
                <span className="shrink-0 text-nexus-muted">
                  <Clock className="h-3 w-3 inline mr-1" />
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </span>
                <span className={`shrink-0 ${getTopicColor(msg.topic)}`}>[{msg.topic}]</span>
                <span className="shrink-0 text-nexus-accent2">{msg.source_agent}</span>
                <span className="min-w-0 break-all text-nexus-muted">
                  {JSON.stringify(msg.payload).slice(0, 120)}
                  {JSON.stringify(msg.payload).length > 120 ? "…" : ""}
                </span>
              </motion.div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
