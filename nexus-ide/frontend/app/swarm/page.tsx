"use client";
import { Suspense, useState, useCallback, useEffect } from "react";
import SwarmPanel from "../../components/swarm/SwarmPanel";
import ThinkingBlock from "../../components/chat/ThinkingBlock";

function SwarmClient() {
  const [insertText, setInsertText] = useState<string>("");
  const [thinking] = useState<string>("");
  const insertIntoChat = useCallback((text: string) => setInsertText(text), []);

  // Listen for cross-component events from the SWARM panel
  useEffect(() => {
    if (typeof window === "undefined") return;
    const handler = (e: Event) => {
      const ce = e as CustomEvent<string>;
      setInsertText(ce.detail);
    };
    window.addEventListener("nexus:chat-input", handler as EventListener);
    return () => window.removeEventListener("nexus:chat-input", handler as EventListener);
  }, []);

  return (
    <main className="flex h-full flex-col">
      <div className="grid h-full grid-cols-1 lg:grid-cols-[1fr_400px]">
        <div className="border-r border-nexus-border">
          <SwarmPanel sessionId="default" onInsertIntoChat={insertIntoChat} />
        </div>
        <aside className="bg-nexus-bg/30 p-4">
          <div className="rounded-xl border border-fuchsia-500/20 bg-gradient-to-br from-fuchsia-500/5 to-violet-500/5 p-4">
            <h3 className="mb-2 text-sm font-semibold text-nexus-text">Send to chat</h3>
            <p className="mb-3 text-[11px] text-nexus-muted">
              When you launch a SWARM run, the final answer is automatically inserted here so you can refine or follow up.
            </p>
            <ThinkingBlock content={thinking} defaultOpen />
            <div className="min-h-32 whitespace-pre-wrap rounded-lg border border-nexus-border bg-nexus-bg/40 p-3 text-[11px] leading-relaxed text-nexus-text">
              {insertText || "_(nothing sent yet - launch a run to see the answer here)_"}
            </div>
          </div>
          <div className="mt-4 rounded-xl border border-nexus-border bg-nexus-card/30 p-4 text-[11px] leading-relaxed text-nexus-muted">
            <h4 className="mb-1.5 text-xs font-semibold text-nexus-text">How SWARM works</h4>
            <ol className="list-decimal space-y-1 pl-4">
              <li>The <strong>Coordinator</strong> picks the operational mode from your objective.</li>
              <li>It pulls RAG evidence from the indexed codebase.</li>
              <li>External research is gathered if the mode requires it.</li>
              <li>The right agents collaborate via the message bus.</li>
              <li>The Reviewer scores the output across 4 axes.</li>
              <li>Only proposals that pass the quality gate are approved.</li>
            </ol>
          </div>
        </aside>
      </div>
    </main>
  );
}

export default function SwarmPage() {
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center text-nexus-muted">A carregar SWARM...</div>}>
      <SwarmClient />
    </Suspense>
  );
}
