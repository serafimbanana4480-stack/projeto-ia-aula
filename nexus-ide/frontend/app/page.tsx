"use client";

import { useState } from "react";
import Sidebar from "../components/layout/Sidebar";
import ChatPanel from "../components/chat/ChatPanel";
import RightPanel from "../components/layout/RightPanel";
import AgentActivity from "../components/dashboard/AgentActivity";

export default function HomePage() {
  const [rightOpen, setRightOpen] = useState(true);

  return (
    <div className="flex h-screen overflow-hidden bg-nexus-bg text-nexus-text">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <ChatPanel rightOpen={rightOpen} setRightOpen={setRightOpen} />
      </div>
      {rightOpen && (
        <aside className="hidden w-[320px] shrink-0 overflow-y-auto border-l border-nexus-border bg-nexus-panel xl:block">
          <div className="space-y-3 p-3">
            <AgentActivity />
            <RightPanel />
          </div>
        </aside>
      )}
    </div>
  );
}
