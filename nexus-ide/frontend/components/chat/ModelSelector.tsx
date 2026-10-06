"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  Code2,
  Eye,
  Gauge,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Wand2,
  Zap,
} from "lucide-react";
import { useModelStore, type Model } from "../../stores/modelStore";
import { formatContext, formatPricePer1M } from "../../lib/format";

/**
 * Model picker for the chat header.
 *
 * Replaces a flat list of six hardcoded entries. The catalog is now discovered
 * live from every configured provider, which means hundreds of options — so
 * search, provider grouping, price/context columns and keyboard navigation are
 * requirements, not polish.
 *
 * The selected value is a concrete model id sent verbatim to `/api/chat`.
 * It used to be mapped down to a router tier, which silently ran a different
 * model than the one displayed.
 */

const CAPABILITY_ICONS: Record<string, { icon: typeof Code2; label: string }> = {
  code: { icon: Code2, label: "Código" },
  reasoning: { icon: Wand2, label: "Raciocínio" },
  vision: { icon: Eye, label: "Visão" },
};

/** Empty string = let the smart router choose. */
const AUTO_OPTION = "";

function providerLabel(provider: string | undefined): string {
  if (!provider) return "Outros";
  const labels: Record<string, string> = {
    openrouter: "OpenRouter",
    openai: "OpenAI",
    anthropic: "Anthropic",
    gemini: "Google Gemini",
    deepseek: "DeepSeek",
    groq: "Groq",
    kimi: "Kimi",
    opencode_go: "OpenCode Go",
    kilo: "Kilo AI Gateway",
    ollama: "Ollama (local)",
    lmstudio: "LM Studio (local)",
  };
  return labels[provider] ?? provider;
}

function matches(model: Model, query: string): boolean {
  if (!query) return true;
  const needle = query.toLowerCase();
  return (
    model.id.toLowerCase().includes(needle) ||
    (model.name ?? "").toLowerCase().includes(needle) ||
    (model.provider ?? "").toLowerCase().includes(needle) ||
    (model.capabilities ?? []).some((c) => c.includes(needle))
  );
}

type Filter = "all" | "free" | "code" | "reasoning" | "long";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "free", label: "Grátis" },
  { id: "code", label: "Código" },
  { id: "reasoning", label: "Raciocínio" },
  { id: "long", label: "Contexto longo" },
];

function passesFilter(model: Model, filter: Filter): boolean {
  switch (filter) {
    case "free":
      return Boolean(model.free);
    case "code":
      return (model.capabilities ?? []).includes("code");
    case "reasoning":
      return (model.capabilities ?? []).includes("reasoning");
    case "long":
      return (model.contextWindow ?? 0) >= 200_000;
    default:
      return true;
  }
}

export default function ModelSelector() {
  const {
    activeModel,
    models,
    modelsLoaded,
    modelsLoading,
    modelsError,
    providerStatus,
    setActiveModel,
    loadModels,
  } = useModelStore();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [highlight, setHighlight] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  // Close on outside click — the old dropdown stayed open until re-clicked.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (open) searchRef.current?.focus();
    else {
      setQuery("");
      setHighlight(0);
    }
  }, [open]);

  // Embeddings are not chat models; they would only clutter the list.
  const chatModels = useMemo(
    () => models.filter((m) => !(m.capabilities ?? []).includes("embedding")),
    [models],
  );

  const visible = useMemo(
    () => chatModels.filter((m) => matches(m, query) && passesFilter(m, filter)),
    [chatModels, query, filter],
  );

  /** Flat list mirroring render order, so arrow keys and Enter agree. */
  const grouped = useMemo(() => {
    const byProvider = new Map<string, Model[]>();
    for (const model of visible) {
      const key = model.provider ?? "outros";
      const bucket = byProvider.get(key);
      if (bucket) bucket.push(model);
      else byProvider.set(key, [model]);
    }
    return [...byProvider.entries()].sort((a, b) =>
      providerLabel(a[0]).localeCompare(providerLabel(b[0])),
    );
  }, [visible]);

  const flat = useMemo(() => grouped.flatMap(([, list]) => list), [grouped]);

  useEffect(() => {
    setHighlight(0);
  }, [query, filter]);

  const selected = chatModels.find((m) => m.id === activeModel);
  const buttonLabel = activeModel
    ? (selected?.name ?? activeModel)
    : "Automático";

  function choose(id: string) {
    setActiveModel(id, models.find((model) => model.id === id)?.provider);
    setOpen(false);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (flat.length === 0) return;
      const next =
        event.key === "ArrowDown"
          ? (highlight + 1) % flat.length
          : (highlight - 1 + flat.length) % flat.length;
      setHighlight(next);
      listRef.current
        ?.querySelector(`[data-index="${next}"]`)
        ?.scrollIntoView({ block: "nearest" });
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const model = flat[highlight];
      if (model) choose(model.id);
    }
  }

  const failedProviders = providerStatus.filter(
    (p) => p.error && p.configured && !p.error.includes("Sem chave API configurada"),
  );
  const unconfiguredProviders = providerStatus.filter(
    (p) => p.error && p.configured && p.error.includes("Sem chave API configurada"),
  );

  return (
    <div className="relative" ref={containerRef}>
        <button
          type="button"
          onClick={() => {
            const nextOpen = !open;
            setOpen(nextOpen);
            // A backend restart must not leave the selector stuck on the
            // first transient connection error until the whole page reloads.
            if (nextOpen && modelsError) void loadModels(true);
          }}
        className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-2.5 py-1.5 text-[11px] font-medium text-nexus-muted transition-colors hover:border-nexus-accent/30 hover:text-nexus-text"
        title={activeModel || "Automático — o router escolhe o modelo"}
      >
        {activeModel ? (
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: selected?.color ?? "#7c6afb" }}
          />
        ) : (
          <Sparkles className="h-3.5 w-3.5 text-nexus-accent/70" />
        )}
        <span className="hidden max-w-[140px] truncate sm:inline">{buttonLabel}</span>
        <ChevronDown className="h-3 w-3" />
      </button>

      {open ? (
        <div
          className="absolute right-0 top-full z-50 mt-1.5 w-[400px] overflow-hidden rounded-xl border border-nexus-border bg-nexus-card shadow-2xl shadow-black/40"
          onKeyDown={onKeyDown}
        >
          {/* Search */}
          <div className="flex items-center gap-2 border-b border-nexus-border px-3 py-2.5">
            <Search className="h-3.5 w-3.5 shrink-0 text-nexus-muted" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Procurar modelo ou provider…"
              className="min-w-0 flex-1 bg-transparent text-xs text-nexus-text outline-none placeholder:text-nexus-muted"
            />
            <button
              type="button"
              onClick={() => void loadModels(true)}
              title="Recarregar catálogo dos providers"
              className="shrink-0 rounded p-1 text-nexus-muted transition-colors hover:text-nexus-text"
            >
              <RefreshCw className={`h-3 w-3 ${modelsLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-1 overflow-x-auto border-b border-nexus-border px-2.5 py-2 thin-scrollbar">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilter(f.id)}
                className={`shrink-0 rounded-md px-2 py-1 text-[10px] font-medium transition-colors ${
                  filter === f.id
                    ? "bg-nexus-accent/15 text-nexus-accent"
                    : "text-nexus-muted hover:bg-nexus-bg hover:text-nexus-text"
                }`}
              >
                {f.label}
              </button>
            ))}
            <span className="ml-auto shrink-0 pl-2 text-[10px] text-nexus-muted">
              {visible.length} de {chatModels.length}
            </span>
          </div>

          <div ref={listRef} className="max-h-[340px] overflow-y-auto thin-scrollbar">
            {/* Auto option — always first, always available. */}
            <button
              type="button"
              onClick={() => choose(AUTO_OPTION)}
              className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors ${
                activeModel === AUTO_OPTION
                  ? "bg-nexus-accent/10"
                  : "hover:bg-nexus-bg/70"
              }`}
            >
              <Sparkles className="h-4 w-4 shrink-0 text-nexus-accent" />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium text-nexus-text">Automático</span>
                <span className="block text-[10px] text-nexus-muted">
                  O router escolhe conforme a tarefa
                </span>
              </span>
              {activeModel === AUTO_OPTION ? (
                <Check className="h-3.5 w-3.5 shrink-0 text-nexus-accent" />
              ) : null}
            </button>

            {modelsLoading && chatModels.length === 0 ? (
              <div className="flex items-center justify-center gap-2 px-3 py-8 text-[11px] text-nexus-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                A consultar os providers…
              </div>
            ) : null}

            {modelsError ? (
              <div className="mx-2.5 my-2 flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-2.5 py-2 text-[10px] text-amber-300">
                <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                <span className="min-w-0">{modelsError}</span>
              </div>
            ) : null}

            {modelsLoaded && !modelsLoading && chatModels.length === 0 && !modelsError ? (
              <div className="px-3 py-6 text-center text-[11px] text-nexus-muted">
                Nenhum modelo encontrado.
                <br />
                Adiciona uma chave API em Definições.
              </div>
            ) : null}

            {visible.length === 0 && chatModels.length > 0 ? (
              <div className="px-3 py-6 text-center text-[11px] text-nexus-muted">
                Nada corresponde a “{query || FILTERS.find((f) => f.id === filter)?.label}”.
              </div>
            ) : null}

            {grouped.map(([provider, list]) => (
              <div key={provider}>
                <div className="sticky top-0 z-10 flex items-center justify-between bg-nexus-card/95 px-3 py-1.5 backdrop-blur-sm">
                  <span className="text-[9px] font-semibold uppercase tracking-wider text-nexus-muted">
                    {providerLabel(provider)}
                  </span>
                  <span className="text-[9px] text-nexus-muted">{list.length}</span>
                </div>
                {list.map((model) => {
                  const index = flat.indexOf(model);
                  const isActive = model.id === activeModel;
                  const isHighlighted = index === highlight;
                  return (
                    <button
                      key={model.id}
                      data-index={index}
                      type="button"
                      onMouseEnter={() => setHighlight(index)}
                      onClick={() => choose(model.id)}
                      className={`flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors ${
                        isActive
                          ? "bg-nexus-accent/10"
                          : isHighlighted
                            ? "bg-nexus-bg/70"
                            : ""
                      }`}
                    >
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: model.color ?? "#64748b" }}
                      />

                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className="truncate text-xs font-medium text-nexus-text">
                            {model.name || model.id}
                          </span>
                          {model.free ? (
                            <span className="shrink-0 rounded bg-emerald-500/15 px-1 py-px text-[9px] font-semibold text-emerald-400">
                              GRÁTIS
                            </span>
                          ) : null}
                        </span>
                        <span className="mt-0.5 flex items-center gap-2 text-[10px] text-nexus-muted">
                          {model.contextWindow ? (
                            <span title="Janela de contexto">
                              {formatContext(model.contextWindow)} ctx
                            </span>
                          ) : null}
                          {!model.free && model.inputPricePer1M != null ? (
                            <span title="Preço por 1M tokens de entrada / saída">
                              {formatPricePer1M(model.inputPricePer1M)}
                              {model.outputPricePer1M != null
                                ? ` / ${formatPricePer1M(model.outputPricePer1M)}`
                                : ""}
                            </span>
                          ) : null}
                          {model.estimated_tokens_per_sec ? (
                            <span className="flex items-center gap-0.5" title="Velocidade estimada">
                              <Zap className="h-2.5 w-2.5" />
                              {model.estimated_tokens_per_sec}
                            </span>
                          ) : null}
                        </span>
                      </span>

                      <span className="flex shrink-0 items-center gap-1">
                        {(model.capabilities ?? [])
                          .filter((c) => c in CAPABILITY_ICONS)
                          .map((cap) => {
                            const { icon: Icon, label } = CAPABILITY_ICONS[cap];
                            // lucide icons take no `title` prop; the tooltip
                            // has to live on a wrapping element.
                            return (
                              <span key={cap} title={label} className="flex">
                                <Icon className="h-3 w-3 text-nexus-muted" />
                              </span>
                            );
                          })}
                        {isActive ? (
                          <Check className="h-3.5 w-3.5 text-nexus-accent" />
                        ) : null}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>

          {failedProviders.length > 0 ? (
            <div className="border-t border-nexus-border px-3 py-2 text-[10px] text-nexus-muted">
              <span className="flex items-center gap-1.5">
                <Gauge className="h-3 w-3" />
                {failedProviders.length} provider
                {failedProviders.length > 1 ? "s" : ""} sem responder:{" "}
                {failedProviders.map((p) => p.label).join(", ")}
              </span>
            </div>
          ) : null}
          {unconfiguredProviders.length > 0 ? (
            <div className="border-t border-nexus-border px-3 py-2 text-[10px] text-nexus-muted">
              <span className="flex items-center gap-1.5">
                <AlertCircle className="h-3 w-3" />
                {unconfiguredProviders.length} provider
                {unconfiguredProviders.length > 1 ? "s" : ""} não configurado
                {unconfiguredProviders.length > 1 ? "s" : ""}:{" "}
                {unconfiguredProviders.map((p) => p.label).join(", ")}
              </span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
