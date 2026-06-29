"use client";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, X, Copy, Check } from "lucide-react";

export type ToastKind = "error" | "warning" | "info" | "success";

export interface Toast {
  id: string;
  kind: ToastKind;
  title: string;
  message?: string;
  details?: string;
  /** Whether the user must dismiss manually (otherwise auto-dismiss). */
  sticky?: boolean;
  /** Optional callback exposed in the toast. */
  action?: { label: string; onClick: () => void };
  created_at: number;
}

const COLORS: Record<ToastKind, { bg: string; border: string; text: string; icon: string }> = {
  error: {
    bg: "bg-rose-500/10",
    border: "border-rose-500/40",
    text: "text-rose-300",
    icon: "text-rose-400",
  },
  warning: {
    bg: "bg-amber-500/10",
    border: "border-amber-500/40",
    text: "text-amber-300",
    icon: "text-amber-400",
  },
  info: {
    bg: "bg-sky-500/10",
    border: "border-sky-500/40",
    text: "text-sky-300",
    icon: "text-sky-400",
  },
  success: {
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/40",
    text: "text-emerald-300",
    icon: "text-emerald-400",
  },
};

const DEFAULT_TIMEOUT_MS: Record<ToastKind, number> = {
  error: 8000,
  warning: 6000,
  info: 4000,
  success: 3000,
};

let _next_id = 0;
const gen_id = () => `t-${++_next_id}-${Date.now()}`;

// ---------------------------------------------------------------------------
// Singleton store (no React state, so we can call from anywhere)
// ---------------------------------------------------------------------------

type Listener = (toasts: Toast[]) => void;
const _toasts: Toast[] = [];
const _listeners = new Set<Listener>();

function _emit() {
  for (const l of _listeners) l([..._toasts]);
}

export function pushToast(input: Omit<Toast, "id" | "created_at"> & { id?: string }) {
  const t: Toast = { id: input.id ?? gen_id(), created_at: Date.now(), ...input };
  _toasts.push(t);
  _emit();
  if (!t.sticky) {
    const ttl = DEFAULT_TIMEOUT_MS[t.kind] ?? 5000;
    setTimeout(() => dismissToast(t.id), ttl);
  }
  return t.id;
}

export function dismissToast(id: string) {
  const idx = _toasts.findIndex((t) => t.id === id);
  if (idx >= 0) {
    _toasts.splice(idx, 1);
    _emit();
  }
}

export function clearToasts() {
  _toasts.splice(0, _toasts.length);
  _emit();
}

function useToasts(): Toast[] {
  const [items, setItems] = useState<Toast[]>(_toasts);
  useEffect(() => {
    const l: Listener = (next) => setItems(next);
    _listeners.add(l);
    // Initial sync
    setItems([..._toasts]);
    return () => {
      _listeners.delete(l);
    };
  }, []);
  return items;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ToastHost() {
  const items = useToasts();
  const [copiedId, setCopiedId] = useState<string | null>(null);

  return (
    <div
      role="region"
      aria-label="Notifications"
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2"
    >
      <AnimatePresence initial={false}>
        {items.map((t) => {
          const c = COLORS[t.kind];
          return (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 40, scale: 0.95 }}
              transition={{ duration: 0.2 }}
              className={`pointer-events-auto flex gap-2 rounded-lg border ${c.border} ${c.bg} p-3 shadow-lg backdrop-blur-md`}
            >
              <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${c.icon}`} />
              <div className="min-w-0 flex-1">
                <div className={`text-[12px] font-semibold ${c.text}`}>{t.title}</div>
                {t.message && (
                  <div className="mt-0.5 text-[11px] leading-relaxed text-nexus-text/90">{t.message}</div>
                )}
                {t.details && (
                  <pre className="mt-1.5 max-h-24 overflow-y-auto rounded bg-black/30 px-2 py-1 font-mono text-[10px] leading-relaxed text-nexus-muted thin-scrollbar">
                    {t.details}
                  </pre>
                )}
                <div className="mt-1.5 flex items-center gap-2">
                  {t.action && (
                    <button
                      onClick={() => {
                        t.action?.onClick();
                        dismissToast(t.id);
                      }}
                      className={`rounded border ${c.border} px-2 py-0.5 text-[11px] font-medium ${c.text} hover:bg-white/5`}
                    >
                      {t.action.label}
                    </button>
                  )}
                  {t.details && (
                    <button
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(t.details || "");
                          setCopiedId(t.id);
                          setTimeout(() => setCopiedId((c) => (c === t.id ? null : c)), 1200);
                        } catch {}
                      }}
                      className="rounded p-0.5 text-nexus-muted hover:bg-white/5 hover:text-nexus-text"
                      title="Copiar detalhes"
                    >
                      {copiedId === t.id ? (
                        <Check className="h-3 w-3" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </button>
                  )}
                </div>
              </div>
              <button
                onClick={() => dismissToast(t.id)}
                className="rounded p-0.5 text-nexus-muted hover:bg-white/5 hover:text-nexus-text"
                title="Fechar"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// Convenience hooks
export function useToast() {
  return {
    push: pushToast,
    dismiss: dismissToast,
    clear: clearToasts,
    error: (title: string, message?: string, details?: string) =>
      pushToast({ kind: "error", title, message, details, sticky: true }),
    warning: (title: string, message?: string) => pushToast({ kind: "warning", title, message }),
    info: (title: string, message?: string) => pushToast({ kind: "info", title, message }),
    success: (title: string, message?: string) => pushToast({ kind: "success", title, message }),
  };
}
