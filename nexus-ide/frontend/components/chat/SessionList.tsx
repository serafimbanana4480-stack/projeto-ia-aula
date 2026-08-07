"use client";
import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Plus,
  MessageSquare,
  Trash2,
  Edit3,
  X,
  Loader2,
  Search,
  AlertCircle,
} from "lucide-react";
import { useChatSessions, type ChatSession } from "../../hooks/useChatSessions";

interface SessionListProps {
  collapsed?: boolean;
  onToggle?: () => void;
}

/**
 * Sidebar with the list of chat sessions. Supports:
 * - new session button
 * - search / filter
 * - rename inline
 * - delete
 * - selection
 */
export default function SessionList({ collapsed = false, onToggle }: SessionListProps) {
  const { sessions, currentId, setCurrentId, create, rename, remove, loading, error, refresh } =
    useChatSessions();

  const [filter, setFilter] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const visible = sessions.filter(
    (s) =>
      !filter.trim() ||
      s.title.toLowerCase().includes(filter.toLowerCase()) ||
      (s.mode || "").toLowerCase().includes(filter.toLowerCase()),
  );

  const startEdit = useCallback((s: ChatSession) => {
    setEditingId(s.id);
    setEditValue(s.title);
  }, []);

  const commitEdit = useCallback(async () => {
    if (!editingId) return;
    const next = editValue.trim() || "Sem título";
    await rename(editingId, next);
    setEditingId(null);
    setEditValue("");
  }, [editingId, editValue, rename]);

  const handleNew = useCallback(async () => {
    await create(`Sessão ${new Date().toLocaleString("pt-PT")}`, "auto");
  }, [create]);

  if (collapsed) {
    return null;
  }

  return (
    <aside
      className="absolute inset-y-0 left-0 z-50 flex w-[min(18rem,calc(100%-1rem))] flex-col border-r border-nexus-border bg-nexus-panel shadow-2xl shadow-black/30"
      aria-label="Sessões de chat"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-nexus-border px-3 py-2.5">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-3.5 w-3.5 text-nexus-accent" />
          <span className="text-xs font-semibold uppercase tracking-wider text-nexus-text">
            Sessões
          </span>
          <span className="rounded-full bg-nexus-bg/60 px-1.5 py-0.5 font-mono text-[10px] text-nexus-muted">
            {sessions.length}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleNew}
            title="Nova sessão"
            className="rounded-md p-1 text-nexus-muted hover:bg-nexus-bg/60 hover:text-nexus-text"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          {onToggle && (
            <button
              onClick={onToggle}
              title="Recolher"
              className="rounded-md p-1 text-nexus-muted hover:bg-nexus-bg/60 hover:text-nexus-text"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Search */}
      <div className="border-b border-nexus-border px-2 py-1.5">
        <div className="flex items-center gap-1.5 rounded-md border border-nexus-border bg-nexus-bg/40 px-2 py-1">
          <Search className="h-3 w-3 text-nexus-muted" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filtrar..."
            className="flex-1 bg-transparent text-[11px] text-nexus-text outline-none placeholder:text-nexus-muted"
          />
        </div>
      </div>

      {/* List */}
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
        {loading && sessions.length === 0 ? (
          <div className="flex items-center justify-center py-6 text-nexus-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          </div>
        ) : visible.length === 0 ? (
          <div className="px-3 py-6 text-center text-[11px] text-nexus-muted">
            {filter ? "Sem resultados" : "Sem sessões — clique + para criar"}
          </div>
        ) : (
          <ul className="divide-y divide-nexus-border/40">
            <AnimatePresence initial={false}>
              {visible.map((s) => {
                const active = s.id === currentId;
                const isEditing = editingId === s.id;
                return (
                  <motion.li
                    key={s.id}
                    layout
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    className={`group relative flex flex-col gap-0.5 px-3 py-2 transition-colors ${
                      active
                        ? "bg-nexus-accent/10 border-l-2 border-l-nexus-accent"
                        : "hover:bg-nexus-bg/40"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void commitEdit();
                            if (e.key === "Escape") setEditingId(null);
                          }}
                          onBlur={() => void commitEdit()}
                          className="flex-1 rounded border border-nexus-accent/40 bg-nexus-bg/60 px-1.5 py-0.5 text-[12px] text-nexus-text outline-none"
                        />
                      ) : (
                        <button
                          onClick={() => setCurrentId(s.id)}
                          onDoubleClick={() => startEdit(s)}
                          className="flex-1 truncate text-left text-[12px] font-medium text-nexus-text"
                          title={`${s.title}\n${s.mode} · ${s.message_count ?? 0} mensagens`}
                        >
                          {s.title}
                        </button>
                      )}
                      {!isEditing && (
                        <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                          <button
                            onClick={() => startEdit(s)}
                            title="Renomear"
                            className="rounded p-0.5 text-nexus-muted hover:bg-nexus-bg/60 hover:text-nexus-text"
                          >
                            <Edit3 className="h-3 w-3" />
                          </button>
                          <button
                            onClick={() => {
                              if (confirm(`Apagar "${s.title}"?`)) void remove(s.id);
                            }}
                            title="Apagar"
                            className="rounded p-0.5 text-nexus-muted hover:bg-rose-500/15 hover:text-rose-400"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 text-[10px] text-nexus-muted">
                      <span className="rounded bg-nexus-bg/60 px-1 font-mono uppercase">
                        {s.mode || "auto"}
                      </span>
                      <span>·</span>
                      <span>{s.message_count ?? 0} msg</span>
                      <span className="ml-auto">{formatRelative(s.last_active_at)}</span>
                    </div>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        )}
      </div>

      {/* Footer / error banner */}
      {error && (
        <div className="flex items-center gap-1.5 border-t border-rose-500/30 bg-rose-500/10 px-2.5 py-1.5 text-[10px] text-rose-400">
          <AlertCircle className="h-3 w-3 shrink-0" />
          <span className="truncate" title={error}>
            {error}
          </span>
          <button
            onClick={refresh}
            className="ml-auto rounded p-0.5 hover:bg-rose-500/20"
            title="Tentar novamente"
          >
            <Loader2 className="h-3 w-3" />
          </button>
        </div>
      )}
    </aside>
  );
}

function formatRelative(iso: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const dt = Date.now() - t;
  if (dt < 0) return "agora";
  const s = Math.floor(dt / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}
