"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** A native modal keeps keyboard focus inside the context panel on small screens. */
export default function ChatContextDrawer({ children, onClose, label = "Contexto da conversa", wide = false }: {
  children: ReactNode;
  onClose: () => void;
  label?: string;
  wide?: boolean;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      aria-label={label}
      className={`nx-chat-context-drawer fixed inset-y-0 left-auto right-0 m-0 h-dvh max-h-none ${wide ? "w-[min(850px,calc(100%-24px))]" : "w-[min(360px,calc(100%-24px))]"} max-w-none border-l border-nexus-border bg-nexus-panel p-0 text-nexus-text shadow-2xl`}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
      }}
    >
      {children}
    </dialog>
  );
}
