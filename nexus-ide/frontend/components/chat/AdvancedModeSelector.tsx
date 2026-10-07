"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Infinity, X } from "lucide-react";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";
import { InfinitySuiteWorkspace } from "../infinity/InfinitySuiteWorkspace";

export default function AdvancedModePanel() {
  const { activeModeIds, loadModes } = useAdvancedModeStore();
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => { void loadModes(); }, [loadModes]);

  useEffect(() => {
    if (!isOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    const trigger = triggerRef.current;
    document.body.style.overflow = "hidden";
    dialogRef.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsOpen(false);
      }
      if (event.key !== "Tab") return;
      const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), summary, a[href], [tabindex="0"]',
      ) ?? []).filter((item) => item.getClientRects().length > 0);
      const first = items[0];
      const last = items[items.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialogRef.current)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
      else trigger?.focus();
    };
  }, [isOpen]);

  return (
    <>
      <button ref={triggerRef} data-advanced-mode-toggle type="button"
        onClick={() => setIsOpen((value) => !value)}
        aria-expanded={isOpen} aria-haspopup="dialog" aria-label="Abrir Infinity Suite"
        className="inline-flex min-h-10 items-center gap-2 rounded-full border border-purple-400/25 bg-nexus-panel px-4 text-xs font-semibold text-nexus-text shadow-lg hover:border-purple-400/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
        <Infinity aria-hidden="true" className="h-4 w-4 text-purple-300" />
        Infinity
        {activeModeIds.length > 0 && <span className="rounded-full bg-purple-400/15 px-2 py-0.5 text-[10px] text-purple-300">{activeModeIds.length}</span>}
      </button>
      {isOpen && createPortal(
        <div className="fixed inset-0 z-[60]">
          <div aria-hidden="true" className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setIsOpen(false)} />
          <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
            className="fixed inset-y-3 left-3 right-3 z-[70] flex max-w-full flex-col overflow-hidden rounded-3xl border border-nexus-border bg-nexus-panel shadow-2xl outline-none sm:left-auto sm:w-[640px] sm:max-w-[calc(100vw-24px)]">
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-nexus-border px-5 py-5 sm:px-6">
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-purple-400/20 bg-purple-400/10"><Infinity aria-hidden="true" className="h-6 w-6 text-purple-300" /></span>
                <div><h2 id={titleId} className="text-lg font-semibold text-nexus-text">Infinity Suite</h2><p className="mt-0.5 text-xs text-nexus-muted">Estratégias, executores e provas à vista.</p></div>
              </div>
              <button type="button" aria-label="Fechar Infinity Suite" onClick={() => setIsOpen(false)} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-nexus-border text-nexus-muted hover:bg-nexus-border/40 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"><X aria-hidden="true" className="h-4 w-4" /></button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 sm:p-6">
              <InfinitySuiteWorkspace onCommandPrepared={() => setIsOpen(false)} />
            </div>
          </div>
        </div>, document.body,
      )}
    </>
  );
}
