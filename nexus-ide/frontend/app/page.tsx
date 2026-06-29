"use client";
import { useState, lazy, Suspense } from "react";
import TopBar from "../components/layout/TopBar";
import Sidebar from "../components/layout/Sidebar";
import ChatPanel from "../components/chat/ChatPanel";
import { PanelRightOpen } from "lucide-react";

// Lazy load non-critical components for better initial load performance
const RightPanel = lazy(() => import("../components/layout/RightPanel"));
const BottomHUD = lazy(() => import("../components/layout/BottomHUD"));

// Loading fallback component
function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
    </div>
  );
}

// NEXUS IDE style layout: sidebar + central chat + right panel
export default function HomePage() {
  const [rightOpen, setRightOpen] = useState(true);

  return (
    <div className="flex h-screen flex-col bg-nexus-bg text-nexus-text">
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        <main className="flex flex-1 overflow-hidden min-w-0 h-full">
          {/* Central chat panel */}
          <div className="flex flex-1 flex-col min-w-0 overflow-hidden h-full">
            <ChatPanel rightOpen={rightOpen} setRightOpen={setRightOpen} />
          </div>

          {/* Right sidebar - model, performance, tools */}
          {rightOpen && (
            <div className="hidden lg:flex w-[380px] flex-col border-l border-nexus-border bg-nexus-panel overflow-hidden shrink-0">
              <Suspense fallback={<LoadingFallback />}>
                <RightPanel />
              </Suspense>
            </div>
          )}
        </main>
      </div>

      {/* Floating toggle button when right panel closed */}
      {!rightOpen && (
        <button
          onClick={() => setRightOpen(true)}
          className="fixed bottom-14 right-4 z-50 flex items-center gap-2 rounded-full bg-nexus-accent px-4 py-2 text-sm font-medium text-white shadow-lg hover:bg-nexus-accent/90"
        >
          <PanelRightOpen className="h-4 w-4" />
          Painel
        </button>
      )}

      <Suspense fallback={<LoadingFallback />}>
        <BottomHUD />
      </Suspense>
    </div>
  );
}
