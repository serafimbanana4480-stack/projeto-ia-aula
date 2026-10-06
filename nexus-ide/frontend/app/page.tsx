"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Maximize2, Minimize2, ScanSearch } from "lucide-react";
import Sidebar from "../components/layout/Sidebar";
import ChatPanel from "../components/chat/ChatPanel";
import RightPanel, { ContextMiniRail } from "../components/layout/RightPanel";

const FOCUS_KEY = "nexus:focus-mode";
const INSPECT_KEY = "nexus:inspect-mode";
const RIGHT_KEY = "nexus:right-open";

/**
 * Chat route — conversation-first layout (Claude Code / ChatGPT / Grok).
 *
 * - The conversation is centred: `width: min(100% - 64px, 1080px)`,
 *   `margin-inline: auto`, so ultrawide never pins content to the left.
 * - Left sidebar collapses to a 68px icon-rail (owned by Sidebar).
 * - Right side is a Context Rail: open = 320px of collapsible modules,
 *   closed = 56px mini-rail ([AI][◉n][%][$]) that re-opens on click.
 * - Focus mode (`nexus-focus`) hides both rails + the utility bar and shows
 *   a minimal floating pill. Toggle via button or Ctrl+Shift+F.
 * - Inspect mode (`nexus-inspect`) is the deep view: widens the rail and
 *   forces every Context Rail module open.
 * - Mobile hides both rails; the rail reappears at xl.
 */
export default function HomePage() {
  const [rightOpen, setRightOpen] = useState(true);
  const [focusMode, setFocusMode] = useState(false);
  const [inspectMode, setInspectMode] = useState(false);
  const hydratedRef = useRef(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(FOCUS_KEY) === "true") setFocusMode(true);
      if (window.localStorage.getItem(INSPECT_KEY) === "true") setInspectMode(true);
      if (window.localStorage.getItem(RIGHT_KEY) === "false") setRightOpen(false);
    } catch {
      // Storage blocked — defaults still give a working layout.
    }
    hydratedRef.current = true;
  }, []);

  useEffect(() => {
    if (!hydratedRef.current) return;
    try {
      window.localStorage.setItem(FOCUS_KEY, String(focusMode));
    } catch {
      /* ignore */
    }
  }, [focusMode]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    try {
      window.localStorage.setItem(INSPECT_KEY, String(inspectMode));
    } catch {
      /* ignore */
    }
  }, [inspectMode]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    try {
      window.localStorage.setItem(RIGHT_KEY, String(rightOpen));
    } catch {
      /* ignore */
    }
  }, [rightOpen]);

  const toggleFocus = useCallback(() => setFocusMode((v) => !v), []);
  const toggleInspect = useCallback(() => setInspectMode((v) => !v), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && (e.key === "F" || e.key === "f")) {
        e.preventDefault();
        toggleFocus();
      } else if (e.key === "Escape" && focusMode) {
        setFocusMode(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleFocus, focusMode]);

  return (
    <div
      className={`nx-ambient nx-chat-workspace flex h-dvh overflow-hidden bg-nexus-bg text-nexus-text ${
        focusMode ? "nexus-focus" : ""
      } ${inspectMode ? "nexus-inspect" : ""}`}
    >
      {!focusMode && <Sidebar />}

      {/* Centre column — owns the conversation width */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {!focusMode ? (
          <div className="flex h-11 shrink-0 items-center justify-between border-b border-nexus-border/60 bg-nexus-panel/40 px-3 sm:px-5">
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={toggleFocus}
                aria-pressed={focusMode}
                title="Focus mode (Ctrl+Shift+F)"
                className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-medium text-nexus-muted transition-[transform,opacity,background-color,color] duration-[180ms] hover:bg-white/[0.05] hover:text-nexus-text"
              >
                <Maximize2 className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Foco</span>
              </button>
              <button
                type="button"
                onClick={toggleInspect}
                aria-pressed={inspectMode}
                title="Inspect — modo profundo do Context Rail"
                className={`flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-medium transition-[transform,opacity,background-color,color] duration-[180ms] hover:bg-white/[0.05] hover:text-nexus-text ${
                  inspectMode ? "text-nexus-accent-bright" : "text-nexus-muted"
                }`}
              >
                <ScanSearch className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Detalhes</span>
              </button>
            </div>
            <div className="hidden items-center gap-2 text-[10px] text-nexus-faint md:flex">
              <kbd className="rounded-md border border-nexus-border bg-white/[0.03] px-1.5 py-0.5 font-mono">
                Ctrl+Shift+F
              </kbd>
              <span>para focar</span>
            </div>
          </div>
        ) : null}

        <div className="flex min-h-0 min-w-0 flex-1 justify-center overflow-hidden">
          <div
            className="mx-auto flex min-h-0 w-full min-w-0 max-w-[1280px] flex-1 flex-col"
          >
            <ChatPanel rightOpen={rightOpen} setRightOpen={setRightOpen} />
          </div>
        </div>
      </div>

      {/* Right rail — hidden on mobile, mini-rail when closed, gone in focus */}
      {!focusMode && rightOpen ? (
        <aside
          className={`hidden shrink-0 overflow-hidden border-l border-nexus-border bg-nexus-panel transition-[width,transform,opacity] duration-[180ms] ease-out xl:block ${
            inspectMode ? "w-[360px]" : "w-[320px]"
          }`}
          aria-label="Context Rail"
        >
          <RightPanel deep={inspectMode} onClose={() => setRightOpen(false)} />
        </aside>
      ) : null}
      {!focusMode && !rightOpen ? <ContextMiniRail onOpen={() => setRightOpen(true)} /> : null}

      {/* Focus mode — minimal floating pill */}
      {focusMode ? (
        <div className="fixed left-1/2 top-3 z-50 -translate-x-1/2">
          <div className="nx-elev-2 flex items-center gap-1 rounded-full px-2 py-1 opacity-90 transition-opacity duration-[180ms] hover:opacity-100">
            <button
              type="button"
              onClick={toggleFocus}
              title="Sair do foco (Esc)"
              className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[11px] font-medium text-nexus-text transition-[transform,opacity,background-color] duration-[180ms] hover:bg-white/[0.06]"
            >
              <Minimize2 className="h-3.5 w-3.5" />
              Sair do foco
            </button>
            <button
              type="button"
              onClick={toggleInspect}
              aria-pressed={inspectMode}
              title="Inspect — modo profundo"
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[11px] font-medium transition-[transform,opacity,background-color] duration-[180ms] hover:bg-white/[0.06] ${
                inspectMode ? "text-nexus-accent-bright" : "text-nexus-muted"
              }`}
            >
              <ScanSearch className="h-3.5 w-3.5" />
              Inspect
            </button>
          </div>
        </div>
      ) : null}

      <style>{`
        .nexus-focus { --nx-focus: 1; }
        .nexus-inspect { --nx-inspect: 1; }
      `}</style>
    </div>
  );
}
