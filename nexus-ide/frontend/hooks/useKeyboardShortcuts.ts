"use client";
import { useEffect } from "react";

interface KeyboardShortcut {
  key: string;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  metaKey?: boolean;
  callback: () => void;
  description: string;
}

export function useKeyboardShortcuts(shortcuts: KeyboardShortcut[]) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      for (const shortcut of shortcuts) {
        const matchesKey = shortcut.key.toLowerCase() === event.key.toLowerCase();
        const matchesCtrl = shortcut.ctrlKey === undefined || shortcut.ctrlKey === event.ctrlKey;
        const matchesShift = shortcut.shiftKey === undefined || shortcut.shiftKey === event.shiftKey;
        const matchesAlt = shortcut.altKey === undefined || shortcut.altKey === event.altKey;
        const matchesMeta = shortcut.metaKey === undefined || shortcut.metaKey === event.metaKey;

        if (matchesKey && matchesCtrl && matchesShift && matchesAlt && matchesMeta) {
          event.preventDefault();
          shortcut.callback();
          return;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [shortcuts]);
}
