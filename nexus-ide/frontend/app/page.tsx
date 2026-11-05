"use client";

import { useEffect, useState } from "react";
import Sidebar from "../components/layout/Sidebar";
import ChatPanel from "../components/chat/ChatPanel";
import RightPanel from "../components/layout/RightPanel";
import AgentTree from "../components/chat/AgentTree";
import ExecutionPanel from "../components/chat/ExecutionPanel";

const RAIL_KEY = "nexus.railWidth";

export default function HomePage() {
  const [rightOpen, setRightOpen] = useState(true);
  const [railWidth, setRailWidth] = useState(340);

  useEffect(() => {
    const stored = Number(window.localStorage.getItem(RAIL_KEY));
    if (Number.isFinite(stored) && stored >= 280 && stored <= 560) setRailWidth(stored);
  }, []);

  function startResize(event: React.MouseEvent) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = railWidth;
    const onMove = (move: MouseEvent) => {
      const next = Math.min(560, Math.max(280, startWidth - (move.clientX - startX)));
      setRailWidth(next);
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      setRailWidth((width) => {
        window.localStorage.setItem(RAIL_KEY, String(width));
        return width;
      });
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  return (
    <div className="flex h-screen overflow-hidden bg-nexus-bg text-nexus-text">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <ChatPanel rightOpen={rightOpen} setRightOpen={setRightOpen} />
      </div>
      {rightOpen && (
        <aside
          style={{ width: railWidth }}
          className="relative hidden shrink-0 border-l border-nexus-border bg-nexus-panel xl:block"
        >
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Redimensionar painel"
            tabIndex={0}
            onMouseDown={startResize}
            onKeyDown={(event) => {
              if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
              event.preventDefault();
              setRailWidth((width) => {
                const next = Math.min(560, Math.max(280, width + (event.key === "ArrowLeft" ? 24 : -24)));
                window.localStorage.setItem(RAIL_KEY, String(next));
                return next;
              });
            }}
            className="absolute inset-y-0 left-0 z-10 w-1.5 cursor-col-resize hover:bg-white/10 focus-visible:bg-white/20"
          />
          <div className="h-full space-y-3 overflow-y-auto p-3">
            <ExecutionPanel />
            <AgentTree />
            <RightPanel />
          </div>
        </aside>
      )}
    </div>
  );
}
