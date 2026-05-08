"use client";
import { useEffect, useRef } from "react";

// xterm.js terminal. Phase 5 will wire PTY via WebSocket + `nexus` CLI.
export default function Terminal() {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    // TODO: instantiate xterm Terminal + FitAddon, wire WS to backend PTY.
  }, []);

  return <div ref={ref} className="h-full w-full bg-black/60 p-2 font-mono text-xs" />;
}
