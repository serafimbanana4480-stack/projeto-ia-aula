"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import {
  AlertCircle,
  ArrowUpRight,
  ExternalLink,
  Globe2,
  Image as ImageIcon,
  Loader2,
  Search,
} from "lucide-react";
import {
  ApiError,
  webImageSearch,
  webSearch,
  type WebImageHit,
  type WebSearchHit,
} from "../../lib/api";
import { log } from "../../lib/log";

type SearchTab = "web" | "images";
const MAX_SEARCH_QUERY_LENGTH = 400;
const WEB_RESULTS_PER_PAGE = 10;
const MAX_WEB_SEARCH_RESULTS = 50;
const IMAGE_RESULTS_PER_PAGE = 25;

function isWebSearchDisabled(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 503 || !error.responseText) return false;
  try {
    const payload = JSON.parse(error.responseText) as { detail?: { code?: unknown } };
    return payload.detail?.code === "web_search_disabled";
  } catch {
    return false;
  }
}

function safeExternalUrl(value?: string): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

function safeBraveThumbnailUrl(value?: string): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.hostname !== "imgs.search.brave.com" ||
      url.port !== "" ||
      url.username ||
      url.password
    ) return null;
    return url.href;
  } catch {
    return null;
  }
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [activeTab, setActiveTab] = useState<SearchTab>("web");
  const [webHits, setWebHits] = useState<WebSearchHit[]>([]);
  const [imageHits, setImageHits] = useState<WebImageHit[]>([]);
  const [webCount, setWebCount] = useState<number | null>(null);
  const [webPage, setWebPage] = useState(1);
  const [imageConfigured, setImageConfigured] = useState<boolean | null>(null);
  const [imageErrorCode, setImageErrorCode] = useState<string | undefined>();
  const [imagePage, setImagePage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState("");
  const [brokenImages, setBrokenImages] = useState<Record<string, boolean>>({});
  const requestId = useRef(0);
  const activeController = useRef<AbortController | null>(null);

  const handleSearch = async (override?: string, target: SearchTab = activeTab) => {
    const q = (override ?? query).trim();
    if (!q) return;
    if (Array.from(q).length > MAX_SEARCH_QUERY_LENGTH) {
      setSearched(q);
      setError(`A pesquisa aceita até ${MAX_SEARCH_QUERY_LENGTH} caracteres. Encurta a expressão e tenta novamente.`);
      return;
    }
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    const currentRequest = ++requestId.current;
    setActiveTab(target);
    setLoading(true);
    setError("");
    setSearched(q);
    if (target === "web") setWebPage(1);
    if (target === "images") {
      setBrokenImages({});
      setImageErrorCode(undefined);
      setImagePage(1);
    }
    try {
      if (target === "images") {
        const result = await webImageSearch({ query: q, limit: 50 }, controller.signal);
        if (currentRequest !== requestId.current) return;
        setImageHits(result.hits ?? []);
        setImageConfigured(result.configured);
        setImageErrorCode(result.error_code);
        if (result.error) setError(result.error);
      } else {
        const result = await webSearch(
          { query: q, limit: MAX_WEB_SEARCH_RESULTS },
          controller.signal,
        );
        if (currentRequest !== requestId.current) return;
        setWebHits(result.hits ?? []);
        setWebCount(result.count ?? result.hits?.length ?? 0);
      }
    } catch (err) {
      if (controller.signal.aborted || currentRequest !== requestId.current) return;
      log.error("Search failed:", err);
      const authFailure = err instanceof ApiError && err.status === 401;
      setError(isWebSearchDisabled(err)
        ? "A pesquisa Web/Imagens está desativada na configuração deste ambiente."
        : authFailure
          ? "A sessão expirou. Inicia sessão novamente para pesquisar."
          : target === "images"
            ? "A pesquisa de imagens falhou. Confirma a ligação ao backend e a configuração do fornecedor."
            : "A pesquisa falhou. Confirma a ligação ao backend e o motor de busca configurado.");
      if (target === "images") {
        setImageHits([]);
        setImageConfigured(null);
        setImageErrorCode(undefined);
      } else {
        setWebHits([]);
        setWebCount(null);
      }
    } finally {
      if (currentRequest === requestId.current) {
        setLoading(false);
        activeController.current = null;
      }
    }
  };

  const selectTab = (tab: SearchTab) => {
    setActiveTab(tab);
    const nextQuery = query.trim() || searched;
    if (nextQuery) void handleSearch(nextQuery, tab);
  };

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) {
      setQuery(q);
      void handleSearch(q, "web");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => {
    requestId.current += 1;
    activeController.current?.abort();
  }, []);

  const usableImageHits = imageHits.filter((hit) => safeExternalUrl(hit.url));
  const hasNoSearchResults = activeTab === "images" ? imageHits.length === 0 : webHits.length === 0;
  const allImageResultsFiltered = imageHits.length > 0 && usableImageHits.length === 0;
  const imagePageCount = Math.max(1, Math.ceil(usableImageHits.length / IMAGE_RESULTS_PER_PAGE));
  const webPageCount = Math.max(1, Math.ceil(webHits.length / WEB_RESULTS_PER_PAGE));
  const visibleWebHits = webHits.slice(
    (webPage - 1) * WEB_RESULTS_PER_PAGE,
    webPage * WEB_RESULTS_PER_PAGE,
  );
  const visibleImageHits = usableImageHits.slice(
    (imagePage - 1) * IMAGE_RESULTS_PER_PAGE,
    imagePage * IMAGE_RESULTS_PER_PAGE,
  );
  const canOpenImageSettings = imageErrorCode === "not_configured" || imageErrorCode === "invalid_credentials";

  return (
    <AppShell title="Pesquisa">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        className="mx-auto max-w-6xl"
      >
        <div className="mb-6 flex items-center gap-3">
          <Search className="h-6 w-6 text-nexus-accent" />
          <div>
            <h1 className="text-2xl font-bold text-nexus-text">Pesquisa</h1>
            <p className="mt-0.5 text-xs text-nexus-muted">
              Resultados da web e imagens num só sítio.
            </p>
          </div>
        </div>

        <div className="mb-6 rounded-2xl border border-nexus-border bg-nexus-panel/70 p-3 shadow-lg shadow-black/5 sm:p-4">
          <form
            className="flex flex-col gap-3 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              void handleSearch();
            }}
          >
            <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-nexus-border bg-nexus-card px-3.5 py-3 focus-within:border-nexus-accent/60 focus-within:ring-2 focus-within:ring-nexus-accent/10">
              <Search className="h-4 w-4 shrink-0 text-nexus-muted" />
              <span className="sr-only">Termos de pesquisa</span>
              <input
                type="search"
                maxLength={MAX_SEARCH_QUERY_LENGTH}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="O que queres encontrar?"
                className="min-w-0 flex-1 bg-transparent text-sm text-nexus-text outline-none placeholder:text-nexus-muted"
              />
            </label>
            <button
              type="submit"
              disabled={!query.trim()}
              className="flex shrink-0 items-center justify-center gap-2 rounded-xl bg-nexus-accent px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-nexus-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {loading ? "Nova pesquisa" : "Pesquisar"}
            </button>
          </form>

          <div className="mt-3 flex gap-1 rounded-xl bg-nexus-bg/70 p-1" role="group" aria-label="Tipo de pesquisa">
            <button
              type="button"
              aria-pressed={activeTab === "web"}
              onClick={() => selectTab("web")}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
                activeTab === "web"
                  ? "bg-nexus-card text-nexus-text shadow-sm"
                  : "text-nexus-muted hover:text-nexus-text"
              }`}
            >
              <Globe2 className="h-3.5 w-3.5" /> Web
            </button>
            <button
              type="button"
              aria-pressed={activeTab === "images"}
              onClick={() => selectTab("images")}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
                activeTab === "images"
                  ? "bg-nexus-card text-nexus-text shadow-sm"
                  : "text-nexus-muted hover:text-nexus-text"
              }`}
            >
              <ImageIcon className="h-3.5 w-3.5" /> Imagens
            </button>
          </div>
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-nexus-muted" role="status">
            <Loader2 className="h-5 w-5 animate-spin text-nexus-accent" />
            A pesquisar {activeTab === "images" ? "imagens" : "na web"}…
          </div>
        )}

        {error && !loading && (
          <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-300" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p>{error}</p>
              {activeTab === "images" && (imageConfigured === false || canOpenImageSettings) && (
                <Link href="/settings" className="mt-2 inline-flex items-center gap-1 font-medium text-nexus-accent hover:underline">
                  Abrir definições <ArrowUpRight className="h-3 w-3" />
                </Link>
              )}
            </div>
          </div>
        )}

        {!loading && !error && searched && hasNoSearchResults && (
          <div role="status" aria-live="polite" aria-atomic="true" className="rounded-xl border border-nexus-border bg-nexus-panel/40 px-4 py-8 text-center text-sm text-nexus-muted">
            Sem resultados para <span className="font-medium text-nexus-text">“{searched}”</span>.
          </div>
        )}

        {!loading && !error && activeTab === "images" && searched && allImageResultsFiltered && (
          <div role="status" aria-live="polite" aria-atomic="true" className="rounded-xl border border-nexus-border bg-nexus-panel/40 px-4 py-8 text-center text-sm text-nexus-muted">
            A pesquisa devolveu imagens, mas nenhuma tinha uma página de origem segura para abrir.
          </div>
        )}

        {!loading && !error && activeTab === "web" && webHits.length > 0 && (
          <section aria-label="Resultados da web" className="space-y-3">
            <div role="status" aria-live="polite" aria-atomic="true" className="text-xs text-nexus-muted">
              {webCount ?? webHits.length} resultado{(webCount ?? webHits.length) === 1 ? "" : "s"}
              {searched && <span> para “{searched}”</span>}
            </div>
            {visibleWebHits.map((hit, index) => (
              (() => {
                const resultUrl = safeExternalUrl(hit.url);
                return (
                  <motion.article
                    key={`${resultUrl ?? index}-${(webPage - 1) * WEB_RESULTS_PER_PAGE + index}`}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: Math.min(index * 0.025, 0.2) }}
                    className="rounded-xl border border-nexus-border bg-nexus-panel/50 p-4 transition-colors hover:border-nexus-accent/30"
                  >
                    <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                      {resultUrl ? (
                        <a href={resultUrl} target="_blank" rel="noopener noreferrer" className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-nexus-accent hover:underline">
                          <span className="truncate">{hit.title || resultUrl}</span>
                          <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                        </a>
                      ) : (
                        <span className="text-sm font-medium text-nexus-text">{hit.title || "Sem título"}</span>
                      )}
                      {hit.source_engine && (
                        <span className="rounded-full border border-nexus-border bg-nexus-card px-2 py-0.5 text-[10px] text-nexus-muted">
                          {hit.source_engine}
                        </span>
                      )}
                    </div>
                    {resultUrl && <div className="mb-1 truncate text-xs text-emerald-400/80">{resultUrl}</div>}
                    {hit.snippet && <p className="text-xs leading-relaxed text-nexus-muted">{hit.snippet}</p>}
                    {hit.age_hint && <div className="mt-2 text-[10px] text-nexus-faint">{hit.age_hint}</div>}
                  </motion.article>
                );
              })()
            ))}
            {webPageCount > 1 && (
              <nav aria-label="Paginação de resultados Web" className="mt-4 flex items-center justify-center gap-3">
                <button
                  type="button"
                  onClick={() => setWebPage((page) => Math.max(1, page - 1))}
                  disabled={webPage <= 1}
                  className="rounded-lg border border-nexus-border px-3 py-2 text-xs text-nexus-text transition-colors hover:border-nexus-accent/50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
                >
                  Anterior
                </button>
                <span aria-live="polite" className="text-xs text-nexus-muted">
                  Página {webPage} de {webPageCount}
                </span>
                <button
                  type="button"
                  onClick={() => setWebPage((page) => Math.min(webPageCount, page + 1))}
                  disabled={webPage >= webPageCount}
                  className="rounded-lg border border-nexus-border px-3 py-2 text-xs text-nexus-text transition-colors hover:border-nexus-accent/50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
                >
                  Seguinte
                </button>
              </nav>
            )}
          </section>
        )}

        {!loading && !error && activeTab === "images" && usableImageHits.length > 0 && (
          <section aria-label="Resultados de imagens">
            <div role="status" aria-live="polite" aria-atomic="true" className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-nexus-muted">
              <span>{usableImageHits.length} imagem{usableImageHits.length === 1 ? "" : "s"} para “{searched}”</span>
              <span>Pesquisa visual · resultados externos</span>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {visibleImageHits.map((hit, index) => {
                const key = `${hit.thumbnail_url}-${index}`;
                const sourceUrl = safeExternalUrl(hit.url);
                const thumbnailUrl = safeBraveThumbnailUrl(hit.thumbnail_url);
                if (!sourceUrl) return null;
                return (
                  <motion.a
                    key={key}
                    href={sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: Math.min(index * 0.02, 0.2) }}
                    className="group overflow-hidden rounded-xl border border-nexus-border bg-nexus-panel/60 transition-all hover:-translate-y-0.5 hover:border-nexus-accent/40 hover:shadow-lg hover:shadow-black/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
                    title={`Abrir ${hit.source || "página de origem"}`}
                  >
                    <div className="relative aspect-[4/3] overflow-hidden bg-nexus-bg/70">
                      {brokenImages[key] || !thumbnailUrl ? (
                        <div className="flex h-full flex-col items-center justify-center gap-2 text-nexus-muted">
                          <ImageIcon className="h-6 w-6" />
                          <span className="text-[10px]">Pré-visualização indisponível</span>
                        </div>
                      ) : (
                        // Brave serves proxied HTTPS thumbnails; keep loading lazy and use a local fallback on failure.
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={thumbnailUrl}
                          alt={hit.title || "Imagem de resultado de pesquisa"}
                          loading="lazy"
                          decoding="async"
                          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                          onError={() => setBrokenImages((current) => ({ ...current, [key]: true }))}
                        />
                      )}
                      <span className="absolute bottom-2 right-2 rounded-md bg-black/65 px-1.5 py-1 text-[9px] text-white opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                        Abrir origem <ExternalLink className="ml-0.5 inline h-2.5 w-2.5" />
                      </span>
                    </div>
                    <div className="p-2.5">
                      <p className="line-clamp-2 text-xs font-medium leading-snug text-nexus-text">{hit.title || "Imagem"}</p>
                      <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-nexus-muted">
                        <span className="truncate">{hit.source || "Página de origem"}</span>
                        {hit.width && hit.height && <span className="shrink-0">{hit.width} × {hit.height}</span>}
                      </div>
                    </div>
                  </motion.a>
                );
              })}
            </div>
            {imagePageCount > 1 && (
              <nav aria-label="Paginação de imagens" className="mt-4 flex items-center justify-center gap-3">
                <button
                  type="button"
                  onClick={() => setImagePage((page) => Math.max(1, page - 1))}
                  disabled={imagePage <= 1}
                  className="rounded-lg border border-nexus-border px-3 py-2 text-xs text-nexus-text transition-colors hover:border-nexus-accent/50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
                >
                  Anterior
                </button>
                <span aria-live="polite" className="text-xs text-nexus-muted">
                  Página {imagePage} de {imagePageCount}
                </span>
                <button
                  type="button"
                  onClick={() => setImagePage((page) => Math.min(imagePageCount, page + 1))}
                  disabled={imagePage >= imagePageCount}
                  className="rounded-lg border border-nexus-border px-3 py-2 text-xs text-nexus-text transition-colors hover:border-nexus-accent/50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
                >
                  Seguinte
                </button>
              </nav>
            )}
            <p className="mt-4 rounded-lg border border-nexus-border/70 bg-nexus-panel/30 px-3 py-2 text-[11px] leading-relaxed text-nexus-muted">
              As miniaturas ligam à página onde a imagem foi encontrada. Confirma a licença nessa página antes de reutilizar a imagem.
            </p>
          </section>
        )}
      </motion.div>
    </AppShell>
  );
}
