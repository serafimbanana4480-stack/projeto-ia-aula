"use client";

import { useCallback, useEffect, useState } from "react";
import { getRoomMemory, updateRoomMemory } from "../../../lib/bots";

const PIN_KEY = "nexus:bots:pins";
const SEEN_KEY = "nexus:bots:seen";

function readList(key: string): string[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(key) || "[]") as unknown;
    return Array.isArray(raw) ? raw.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function readMap(key: string): Record<string, string> {
  try {
    const raw = JSON.parse(window.localStorage.getItem(key) || "{}") as unknown;
    if (!raw || typeof raw !== "object") return {};
    const entries = Object.entries(raw).filter((entry): entry is [string, string] => typeof entry[1] === "string");
    return Object.fromEntries(entries);
  } catch {
    return {};
  }
}

export function useRoomMemory() {
  const [pins, setPins] = useState<string[]>([]);
  const [seen, setSeen] = useState<Record<string, string>>({});
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const localPins = readList(PIN_KEY);
    const localSeen = readMap(SEEN_KEY);
    setPins(localPins);
    setSeen(localSeen);
    setReady(true);
    void getRoomMemory()
      .then((remote) => {
        const mergedPins = Array.from(new Set([...localPins, ...(remote.pins ?? [])]));
        const mergedSeen = { ...(remote.seen ?? {}), ...localSeen };
        setPins(mergedPins);
        setSeen(mergedSeen);
        window.localStorage.setItem(PIN_KEY, JSON.stringify(mergedPins));
        window.localStorage.setItem(SEEN_KEY, JSON.stringify(mergedSeen));
        if (
          mergedPins.length !== (remote.pins ?? []).length ||
          Object.keys(mergedSeen).length !== Object.keys(remote.seen ?? {}).length
        ) {
          void updateRoomMemory({ pins: mergedPins, seen: mergedSeen }).catch(() => {});
        }
      })
      .catch(() => {});
  }, []);

  const togglePin = useCallback((id: string) => {
    setPins((current) => {
      const next = current.includes(id) ? current.filter((item) => item !== id) : [id, ...current];
      window.localStorage.setItem(PIN_KEY, JSON.stringify(next));
      void updateRoomMemory({ pins: next }).catch(() => {});
      return next;
    });
  }, []);

  const markSeen = useCallback((id: string, signature: string) => {
    setSeen((current) => {
      if (current[id] === signature) return current;
      const next = { ...current, [id]: signature };
      window.localStorage.setItem(SEEN_KEY, JSON.stringify(next));
      void updateRoomMemory({ seen: { [id]: signature } }).catch(() => {});
      return next;
    });
  }, []);

  const unread = useCallback((id: string, signature: string) => {
    if (!ready) return false;
    const previous = seen[id];
    return typeof previous === "string" && previous !== signature;
  }, [ready, seen]);

  return { pins, togglePin, markSeen, unread };
}
