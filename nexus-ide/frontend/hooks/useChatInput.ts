"use client";
import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "nexus.chat.draft";

/**
 * A tiny store for the chat input draft so a SWARM run can push text
 * back into the chat composer. Used by ``SwarmPanel``'s "Send to chat"
 * action.
 */
export function useChatInput() {
  const [draft, setDraft] = useState<string>("");

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setDraft(stored);
    } catch {}
  }, []);

  const setValue = useCallback((value: string) => {
    setDraft(value);
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {}
    // Notify any open ChatPanel via a custom event
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("nexus:chat-input", { detail: value }));
    }
  }, []);

  const clear = useCallback(() => {
    setDraft("");
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {}
  }, []);

  return { draft, setValue, clear };
}
