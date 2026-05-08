"use client";
import { useState } from "react";
import dynamic from "next/dynamic";
import TopBar from "../components/layout/TopBar";
import Sidebar from "../components/layout/Sidebar";
import BottomHUD from "../components/layout/BottomHUD";
import ChatPanel from "../components/chat/ChatPanel";
import ModeSelector from "../components/chat/ModeSelector";
import ModelPanel from "../components/chat/ModelPanel";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

// Monaco touches `window` on import → must be client-only.
const MonacoEditor = dynamic(() => import("../components/editor/MonacoEditor"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-black/40" />,
});

// Main IDE view - Windsurf-style layout with right sidebar chat
export default function HomePage() {
  const [chatOpen, setChatOpen] = useState(true);

  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        
        <main className="flex flex-1 overflow-hidden">
          <div className="flex-1 h-full">
            <MonacoEditor />
          </div>
          
          {/* Right sidebar chat panel - Windsurf style */}
          {chatOpen && (
            <div className="flex w-[760px] flex-col border-l border-nexus-border bg-nexus-panel/50 backdrop-blur-md">
              {/* Chat header with mode and model selectors */}
              <div className="grid grid-cols-[auto_1fr_auto] items-center gap-1.5 border-b border-nexus-border px-2 py-0.5">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-nexus-accent animate-pulse" />
                  <span className="text-[10px] font-semibold text-gray-200">Chat</span>
                </div>
                <div className="flex items-center justify-center gap-1.5">
                  <ModeSelector />
                  <div className="h-2.5 w-px bg-nexus-border" />
                  <ModelPanel />
                </div>
                <button
                  onClick={() => setChatOpen(false)}
                  className="justify-self-end rounded p-0.5 hover:bg-nexus-border"
                  title="Close chat"
                >
                  <PanelRightClose className="h-3 w-3 text-gray-400" />
                </button>
              </div>

              {/* Chat panel - maximized space */}
              <div className="min-h-0 flex-1 overflow-hidden">
                <ChatPanel />
              </div>
            </div>
          )}
        </main>
      </div>
      
      {/* Floating chat toggle button when closed */}
      {!chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          className="fixed bottom-16 right-4 z-50 flex items-center gap-2 rounded-full bg-nexus-accent px-4 py-2 text-sm font-medium text-black shadow-lg hover:bg-nexus-accent/80"
        >
          <PanelRightOpen className="h-4 w-4" />
          Chat
        </button>
      )}
      
      <BottomHUD />
    </div>
  );
}
