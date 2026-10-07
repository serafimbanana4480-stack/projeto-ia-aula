"use client";
import { useState, useRef, useCallback, useEffect } from "react";
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
import {
  searchChatSessions,
  useChatSessions,
  type ChatSession,
  type SessionSearchMatch,
} from "../../hooks/useChatSessions";

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
  const {
    sessions,
    currentId,
    setCurrentId,
    create,
    rename,
    remove,
    loading,
    loadingMore,
    hasMore,
    total,
    error,
    refresh,
    loadMore,
  } = useChatSessions();

  const [filter, setFilter] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [remoteMatches, setRemoteMatches] = useState<SessionSearchMatch[]>([]);
  const [remoteTotal, setRemoteTotal] = useState(0);
  const [remoteNextOffset, setRemoteNextOffset] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const searchSequenceRef = useRef(0);
  // Enter and onBlur both fired `commitEdit`, and `editingId` is only cleared
  // after the await — so every rename was sent twice (two PATCH requests
  // racing to write the same title). This latch makes the commit single-shot.
  const commitInFlightRef = useRef(false);

  const visible = sessions.filter(
    (s) =>
      !filter.trim() ||
      s.title.toLowerCase().includes(filter.toLowerCase()) ||
      (s.mode || "").toLowerCase().includes(filter.toLowerCase()),
  );

  useEffect(() => {
    const query = filter.trim();
    const sequence = ++searchSequenceRef.current;
    if (query.length < 2) {
      setRemoteMatches([]);
      setRemoteTotal(0);
      setRemoteNextOffset(0);
      setSearchError(null);
      setSearching(false);
      return;
    }
    setRemoteMatches([]);
    setRemoteTotal(0);
    setRemoteNextOffset(0);
    setSearchError(null);
    setSearching(true);
    const timeout = setTimeout(() => {
      void searchChatSessions(query, 50, 0)
        .then((result) => {
          if (searchSequenceRef.current !== sequence) return;
          setRemoteMatches(result.sessions);
          setRemoteTotal(result.total);
          setRemoteNextOffset(result.offset + result.sessions.length);
        })
        .catch((reason: unknown) => {
          if (searchSequenceRef.current !== sequence) return;
          setSearchError(reason instanceof Error ? reason.message : String(reason));
          setRemoteMatches([]);
          setRemoteTotal(0);
        })
        .finally(() => {
          if (searchSequenceRef.current === sequence) setSearching(false);
        });
    }, 220);
    return () => clearTimeout(timeout);
  }, [filter]);

  const localVisibleIds = new Set(visible.map((session) => session.id));
  const remoteVisible = remoteMatches.filter((match) => !localVisibleIds.has(match.id));
  const localMessageMatches = new Map(
    remoteMatches
      .filter((match) => match.match_type === "message")
      .map((match) => [match.id, match]),
  );

  const startEdit = useCallback((s: ChatSession) => {
    commitInFlightRef.current = false;
    setEditingId(s.id);
    setEditValue(s.title);
  }, []);

  const commitEdit = useCallback(async () => {
    if (!editingId || commitInFlightRef.current) return;
    commitInFlightRef.current = true;
    const next = editValue.trim() || "Sem título";
    setEditingId(null);
    setEditValue("");
    try {
      await rename(editingId, next);
    } finally {
      commitInFlightRef.current = false;
    }
  }, [editingId, editValue, rename]);

  const loadMoreSearchResults = useCallback(async () => {
    const query = filter.trim();
    if (!query || remoteNextOffset >= remoteTotal || searching) return;
    const sequence = searchSequenceRef.current;
    setSearching(true);
    setSearchError(null);
    try {
      const result = await searchChatSessions(query, 50, remoteNextOffset);
      if (searchSequenceRef.current !== sequence) return;
      setRemoteMatches((current) => {
        const byId = new Map(current.map((match) => [match.id, match]));
        for (const match of result.sessions) {
          const previous = byId.get(match.id);
          if (!previous || match.match_type === "message") byId.set(match.id, match);
        }
        return [...byId.values()];
      });
      setRemoteTotal(result.total);
      setRemoteNextOffset(result.offset + result.sessions.length);
    } catch (reason: unknown) {
      if (searchSequenceRef.current !== sequence) return;
      setSearchError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (searchSequenceRef.current === sequence) setSearching(false);
    }
  }, [filter, remoteNextOffset, remoteTotal, searching]);

  const cancelEdit = useCallback(() => {
    commitInFlightRef.current = false;
    setEditingId(null);
    setEditValue("");
  }, []);

  const handleNew = useCallback(async () => {
    await create(`Sessão ${new Date().toLocaleString("pt-PT")}`, "auto");
  }, [create]);

  if (collapsed) {
    return null;
  }

  return (
    <aside
      className="absolute inset-y-0 left-0 z-50 flex w-[min(19rem,calc(100%-1rem))] flex-col border-r border-nexus-border/80 bg-nexus-panel shadow-2xl shadow-black/30"
      aria-label="Sessões de chat"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-nexus-border/60 px-4 py-3.5">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-3.5 w-3.5 text-nexus-accent" />
          <span className="text-xs font-semibold uppercase tracking-wider text-nexus-text">
            Sessões
          </span>
          <span className="rounded-full bg-nexus-bg/60 px-1.5 py-0.5 font-mono text-[10px] text-nexus-muted">
            {filter.trim() ? visible.length + remoteVisible.length : total || sessions.length}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleNew}
            title="Nova sessão"
            className="rounded-lg border border-nexus-accent/15 bg-nexus-accent/10 p-2 text-nexus-accent transition-colors hover:bg-nexus-accent/20"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          {onToggle && (
            <button
              onClick={onToggle}
              title="Recolher"
              className="rounded-lg p-2 text-nexus-muted transition-colors hover:bg-nexus-card hover:text-nexus-text"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Search */}
      <div className="px-3 py-3">
        <div className="flex items-center gap-2 rounded-xl border border-nexus-border/80 bg-nexus-bg/50 px-3 py-2.5 focus-within:border-nexus-accent/40">
          <Search className="h-3 w-3 text-nexus-muted" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filtrar..."
            className="min-w-0 flex-1 bg-transparent text-xs text-nexus-text outline-none placeholder:text-nexus-faint"
          />
        </div>
      </div>

      {/* List */}
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
        {loading && sessions.length === 0 ? (
          <div className="flex items-center justify-center py-6 text-nexus-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          </div>
        ) : visible.length === 0 && remoteVisible.length === 0 && !searching ? (
          <div className="px-3 py-6 text-center text-[11px] text-nexus-muted">
            {filter ? "Sem resultados" : "Sem sessões — clique + para criar"}
          </div>
        ) : (
          <>
          {filter.trim() && visible.length > 0 && (
            <div className="px-3 pt-2 text-[10px] font-semibold uppercase tracking-wide text-nexus-faint">
              Nesta lista · {visible.length}
            </div>
          )}
          {visible.length > 0 && <ul className="space-y-1 px-2 pb-2">
            <AnimatePresence initial={false}>
              {visible.map((s) => {
                const active = s.id === currentId;
                const isEditing = editingId === s.id;
                const messageMatch = localMessageMatches.get(s.id);
                return (
                  <motion.li
                    key={s.id}
                    layout
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    className={`group relative flex flex-col gap-1 rounded-xl border px-3 py-3 transition-colors ${
                      active
                        ? "border-nexus-accent/20 bg-nexus-accent/10"
                        : "border-transparent hover:border-nexus-border/60 hover:bg-nexus-card/50"
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
                            if (e.key === "Escape") cancelEdit();
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
                    {messageMatch?.snippet && (
                      <div className="flex min-w-0 items-start gap-1.5 pt-0.5 text-[10px] text-nexus-muted">
                        <span className="shrink-0 rounded bg-nexus-accent/10 px-1 text-nexus-accent/80">
                          mensagem
                        </span>
                        <span className="line-clamp-2 min-w-0 leading-relaxed">
                          {messageMatch.snippet}
                        </span>
                      </div>
                    )}
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>}
          {filter.trim() && (
            remoteVisible.length > 0 ||
            searching ||
            searchError ||
            remoteTotal === 0 ||
            remoteNextOffset < remoteTotal
          ) && (
            <>
              <div className="flex items-center gap-2 px-3 pt-3 text-[10px] font-semibold uppercase tracking-wide text-nexus-faint">
                <span className="flex-1">Todas as conversas</span>
                {searching && <Loader2 className="h-3 w-3 animate-spin" aria-label="A pesquisar" />}
                {!searching && remoteTotal > 0 && <span>{remoteVisible.length} visíveis · {remoteTotal} resultados</span>}
              </div>
              {searchError ? (
                <div className="px-3 py-2 text-[10px] text-rose-400" role="status">
                  Pesquisa indisponível: {searchError}
                </div>
              ) : remoteVisible.length > 0 ? (
                <ul className="divide-y divide-nexus-border/40">
                  {remoteVisible.map((match) => (
                    <li key={`${match.id}-${match.match_type}-${match.match_message_id ?? ""}`}>
                      <button
                        type="button"
                        onClick={() => setCurrentId(match.id)}
                        className={`flex w-full flex-col gap-1 px-3 py-2 text-left transition-colors ${
                          match.id === currentId ? "bg-nexus-accent/10" : "hover:bg-nexus-bg/40"
                        }`}
                        title={match.title}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <MessageSquare className="h-3 w-3 shrink-0 text-nexus-accent/70" />
                          <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-nexus-text">
                            {match.title || "Sem título"}
                          </span>
                          <span className="shrink-0 rounded bg-nexus-bg/70 px-1 py-0.5 text-[9px] uppercase text-nexus-muted">
                            {match.match_type === "message" ? "mensagem" : match.match_type === "title" ? "título" : "modo"}
                          </span>
                        </span>
                        {match.snippet && (
                          <span className="line-clamp-2 pl-5 text-[10px] leading-relaxed text-nexus-muted">
                            {match.snippet}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : !searching && remoteTotal === 0 && visible.length === 0 ? (
                <div className="px-3 py-2 text-[10px] text-nexus-muted">Sem resultados</div>
              ) : null}
              {!searching && remoteNextOffset < remoteTotal && (
                <button
                  type="button"
                  onClick={() => void loadMoreSearchResults()}
                  className="flex w-full items-center justify-center border-t border-nexus-border/40 px-3 py-2 text-[10px] text-nexus-muted hover:text-nexus-text"
                >
                  Mais resultados de pesquisa
                </button>
              )}
            </>
          )}
          {!filter.trim() && hasMore && (
            <button
              type="button"
              onClick={() => void loadMore()}
              disabled={loadingMore}
              className="flex w-full items-center justify-center gap-2 border-t border-nexus-border/50 px-3 py-2 text-[11px] text-nexus-muted hover:text-nexus-text disabled:opacity-60"
            >
              {loadingMore && <Loader2 className="h-3 w-3 animate-spin" />}
              Carregar mais conversas
            </button>
          )}
          </>
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
            <Loader2 className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
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
