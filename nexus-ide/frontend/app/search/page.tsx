"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import { Search, Loader2, AlertCircle, ExternalLink } from "lucide-react";
import { webSearch } from "../../lib/api";
import { log } from "../../lib/log";

interface SearchHit {
  title?: string;
  url?: string;
  snippet?: string;
  score?: number;
  source_engine?: string;
  age_hint?: string;
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState("");

  const handleSearch = async (override?: string) => {
    const q = (override ?? query).trim();
    if (!q) return;
    setLoading(true);
    setError("");
    setSearched(q);
    try {
      const result = (await webSearch({ query: q, limit: 10 })) as {
        hits?: SearchHit[];
        count?: number;
      };
      setHits(result.hits ?? []);
      setCount(result.count ?? result.hits?.length ?? 0);
    } catch (err) {
      log.error("Web search failed:", err);
      setError(
        "Falha na pesquisa (o backend pode não ter um motor de busca configurado).",
      );
      setHits([]);
      setCount(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) {
      setQuery(q);
      void handleSearch(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AppShell title="Web Search">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mx-auto max-w-4xl"
      >
        <div className="mb-6 flex items-center gap-3">
          <Search className="h-6 w-6 text-nexus-accent" />
          <h1 className="text-2xl font-bold">Web Search</h1>
        </div>

        <div className="card mb-6 p-4">
          <div className="flex items-center gap-2">
            <div className="flex flex-1 items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card px-3 py-2">
              <Search className="h-4 w-4 text-nexus-muted" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="Pesquisar na web..."
                className="flex-1 bg-transparent text-sm text-nexus-text outline-none placeholder:text-nexus-muted"
              />
            </div>
            <button
              onClick={() => void handleSearch()}
              disabled={loading || !query.trim()}
              className="flex items-center gap-2 rounded-lg bg-nexus-accent px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-nexus-accent/90 disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Pesquisar
            </button>
          </div>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-nexus-accent" />
          </div>
        )}

        {error && !loading && (
          <div className="flex items-center gap-2 text-sm text-red-400">
            <AlertCircle className="h-4 w-4" />
            {error}
          </div>
        )}

        {!loading && !error && count === 0 && searched && (
          <div className="text-sm text-nexus-muted">
            Sem resultados para &quot;{searched}&quot;.
          </div>
        )}

        {!loading && !error && hits.length > 0 && (
          <div className="space-y-3">
            {count != null && (
              <div className="text-sm text-nexus-muted">
                {count} resultado{count === 1 ? "" : "s"}
              </div>
            )}
            {hits.map((hit, index) => (
              <motion.div
                key={`${hit.url ?? index}-${index}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="rounded-lg border border-nexus-border bg-nexus-panel/50 p-4"
              >
                <div className="mb-1 flex items-start justify-between gap-3">
                  {hit.url ? (
                    <a
                      href={hit.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 text-sm font-medium text-nexus-accent hover:underline"
                    >
                      {hit.title || hit.url}
                      <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                    </a>
                  ) : (
                    <span className="text-sm font-medium text-nexus-text">
                      {hit.title || "(sem título)"}
                    </span>
                  )}
                  {hit.source_engine && (
                    <span className="shrink-0 rounded-full border border-nexus-border bg-nexus-card px-2 py-0.5 text-[10px] text-nexus-muted">
                      {hit.source_engine}
                    </span>
                  )}
                </div>
                {hit.url && (
                  <div className="mb-1 truncate text-xs text-green-500/80">
                    {hit.url}
                  </div>
                )}
                {hit.snippet && (
                  <p className="text-xs text-nexus-muted">{hit.snippet}</p>
                )}
                {hit.age_hint && (
                  <div className="mt-1 text-[10px] text-nexus-muted">
                    {hit.age_hint}
                  </div>
                )}
              </motion.div>
            ))}
          </div>
        )}
      </motion.div>
    </AppShell>
  );
}
