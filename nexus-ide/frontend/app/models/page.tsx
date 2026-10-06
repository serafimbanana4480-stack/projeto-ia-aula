"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight, BrainCircuit, Code2, Eye, RefreshCw, Search, Sparkles } from "lucide-react";

import AppShell from "../../components/layout/AppShell";
import { useModelStore, type Model } from "../../stores/modelStore";
import { formatContext, formatPricePer1M } from "../../lib/format";

const PAGE_SIZE = 36;

function matches(model: Model, query: string): boolean {
  if (!query) return true;
  const value = query.toLocaleLowerCase("pt-PT");
  return [model.id, model.name ?? "", model.provider ?? "", model.description ?? ""]
    .some((part) => part.toLocaleLowerCase("pt-PT").includes(value));
}

export default function ModelsPage() {
  const router = useRouter();
  const models = useModelStore((state) => state.models);
  const providerStatus = useModelStore((state) => state.providerStatus);
  const activeModel = useModelStore((state) => state.activeModel);
  const modelsLoaded = useModelStore((state) => state.modelsLoaded);
  const modelsLoading = useModelStore((state) => state.modelsLoading);
  const modelsError = useModelStore((state) => state.modelsError);
  const loadModels = useModelStore((state) => state.loadModels);
  const setActiveModel = useModelStore((state) => state.setActiveModel);
  const [query, setQuery] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  const chatModels = useMemo(
    () => models.filter((model) => !(model.capabilities ?? []).includes("embedding")),
    [models],
  );
  const providers = useMemo(
    () => [...new Set(chatModels.map((model) => model.provider ?? "unknown"))].sort(),
    [chatModels],
  );
  const filteredModels = useMemo(
    () => chatModels.filter((model) =>
      matches(model, query)
      && (providerFilter === "all" || (model.provider ?? "unknown") === providerFilter),
    ),
    [chatModels, providerFilter, query],
  );
  const visibleModels = filteredModels.slice(0, visibleCount);

  const selectModel = (modelId: string, provider = "") => {
    setActiveModel(modelId, provider);
    router.push("/");
  };

  return (
    <AppShell title="Modelos IA" noPadding>
      <div className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-nexus-accent-bright">
              Catálogo do NEXUS
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-nexus-text sm:text-3xl">
              Modelos IA
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-nexus-muted">
              Pesquisa os modelos disponíveis e escolhe qual usar na próxima conversa.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-nexus-border px-3 py-1.5 text-xs text-nexus-muted">
              {chatModels.length} {chatModels.length === 1 ? "modelo" : "modelos"}
            </span>
            <button
              type="button"
              onClick={() => void loadModels(true)}
              disabled={modelsLoading}
              aria-label="Atualizar catálogo de modelos"
              className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-nexus-border bg-nexus-card px-3 text-sm text-nexus-text transition hover:border-nexus-accent/50 disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw className={`h-4 w-4 ${modelsLoading ? "animate-spin" : ""}`} aria-hidden="true" />
              Atualizar
            </button>
          </div>
        </header>

        {providerStatus.length > 0 ? (
          <section aria-label="Estado dos fornecedores" className="flex flex-wrap gap-2">
            {providerStatus.map((provider) => (
              <span
                key={provider.provider}
                className={`inline-flex max-w-full items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                  provider.error
                    ? "border-amber-400/25 bg-amber-400/[0.06] text-amber-200"
                    : "border-nexus-border bg-nexus-card/60 text-nexus-muted"
                }`}
                title={provider.error ?? undefined}
              >
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${provider.error ? "bg-amber-400" : "bg-emerald-400"}`} />
                <span className="truncate">{provider.label}</span>
                <span className="tabular-nums">{provider.count}</span>
              </span>
            ))}
          </section>
        ) : null}

        <section aria-label="Filtrar modelos" className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
          <label className="flex min-h-11 items-center gap-2 rounded-xl border border-nexus-border bg-nexus-panel/70 px-3 text-nexus-muted focus-within:border-nexus-accent/60">
            <Search className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="sr-only">Pesquisar modelos</span>
            <input
              type="search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setVisibleCount(PAGE_SIZE);
              }}
              placeholder="Pesquisar por modelo, provider ou descrição"
              className="min-w-0 flex-1 bg-transparent text-sm text-nexus-text outline-none placeholder:text-nexus-faint"
            />
          </label>
          <label className="flex min-h-11 items-center gap-2 rounded-xl border border-nexus-border bg-nexus-panel/70 px-3 text-xs text-nexus-muted">
            <span>Provider</span>
            <select
              aria-label="Filtrar por provider"
              value={providerFilter}
              onChange={(event) => {
                setProviderFilter(event.target.value);
                setVisibleCount(PAGE_SIZE);
              }}
              className="min-w-0 flex-1 bg-transparent text-sm text-nexus-text outline-none"
            >
              <option value="all">Todos</option>
              {providers.map((provider) => <option key={provider} value={provider}>{provider}</option>)}
            </select>
          </label>
        </section>

        {modelsError ? (
          <div role="alert" className="flex flex-col gap-3 rounded-xl border border-amber-400/25 bg-amber-400/[0.06] p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-amber-100">O catálogo não ficou completo</h2>
              <p className="mt-1 break-words text-xs leading-relaxed text-amber-100/75">{modelsError}</p>
            </div>
            <Link href="/settings" className="shrink-0 text-xs font-medium text-nexus-accent-bright hover:underline">
              Rever configuração
            </Link>
          </div>
        ) : null}

        <section aria-label="Catálogo de modelos" aria-busy={modelsLoading || !modelsLoaded}>
          {(modelsLoading || !modelsLoaded) && chatModels.length === 0 ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }, (_, index) => (
                <div key={index} className="nx-shimmer h-36 rounded-2xl border border-nexus-border/70" aria-hidden="true" />
              ))}
              <span className="sr-only">A carregar modelos…</span>
            </div>
          ) : chatModels.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-nexus-border p-8 text-center sm:p-12">
              <BrainCircuit className="mx-auto h-8 w-8 text-nexus-faint" aria-hidden="true" />
              <h2 className="mt-3 text-base font-semibold text-nexus-text">Ainda não há modelos disponíveis</h2>
              <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-nexus-muted">
                Configura um provider ou confirma que o serviço local está ativo para carregar o catálogo.
              </p>
              <Link href="/settings" className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-xl bg-nx-accent px-4 text-sm font-semibold text-white">
                Abrir definições <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
          ) : filteredModels.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-nexus-border p-8 text-center text-sm text-nexus-muted">
              Não encontrei modelos com estes filtros.
            </div>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-nexus-muted">
                <span>{filteredModels.length} resultados</span>
                <button
                  type="button"
                  onClick={() => selectModel("")}
                  className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-nexus-border px-3 transition hover:border-nexus-accent/50 hover:text-nexus-text"
                >
                  <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                  Usar seleção automática
                </button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {visibleModels.map((model) => {
                  const selected = activeModel === model.id;
                  const capabilities = (model.capabilities ?? []).filter((capability) => capability !== "chat").slice(0, 3);
                  return (
                    <article key={`${model.provider}:${model.id}`} className={`flex min-w-0 flex-col rounded-2xl border bg-nexus-panel/70 p-4 transition-colors ${selected ? "border-nexus-accent/70 shadow-rim" : "border-nexus-border/80 hover:border-nexus-accent/40"}`}>
                      <div className="flex min-w-0 items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-nexus-text" title={model.name ?? model.id}>{model.name || model.id}</p>
                          <p className="mt-1 truncate font-mono text-[11px] text-nexus-faint" title={model.id}>{model.id}</p>
                        </div>
                        <span className="shrink-0 rounded-full border border-nexus-border px-2 py-1 text-[10px] text-nexus-muted">
                          {model.provider || "Provider desconhecido"}
                        </span>
                      </div>
                      {model.description ? <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-nexus-muted">{model.description}</p> : null}
                      <div className="mt-4 grid grid-cols-2 gap-2 text-[11px]">
                        <div className="rounded-lg bg-nexus-bg/65 p-2">
                          <span className="block text-nexus-faint">Contexto</span>
                          <span className="mt-1 block font-medium text-nexus-text">{formatContext(model.contextWindow)}</span>
                        </div>
                        <div className="rounded-lg bg-nexus-bg/65 p-2">
                          <span className="block text-nexus-faint">Entrada / saída · 1M</span>
                          <span className="mt-1 block font-medium text-nexus-text">
                            {formatPricePer1M(model.inputPricePer1M)} / {formatPricePer1M(model.outputPricePer1M)}
                          </span>
                        </div>
                      </div>
                      <div className="mt-3 flex min-h-6 flex-wrap gap-1.5">
                        {capabilities.map((capability) => {
                          const Icon = capability === "code" ? Code2 : capability === "vision" ? Eye : BrainCircuit;
                          const label = capability === "code" ? "Código" : capability === "vision" ? "Visão" : "Raciocínio";
                          return <span key={capability} className="inline-flex items-center gap-1 rounded-md bg-nexus-bg/70 px-2 py-1 text-[10px] text-nexus-muted"><Icon className="h-3 w-3" aria-hidden="true" />{label}</span>;
                        })}
                        {model.free ? <span className="rounded-md bg-emerald-400/10 px-2 py-1 text-[10px] text-emerald-300">Grátis</span> : null}
                      </div>
                      <button
                        type="button"
                        onClick={() => selectModel(model.id, model.provider)}
                        aria-pressed={selected}
                        aria-label={`${selected ? "Abrir chat com" : "Usar"} ${model.name || model.id}`}
                        className="mt-4 inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-nexus-border px-3 text-xs font-semibold text-nexus-text transition hover:border-nexus-accent/60 hover:bg-nexus-accent/10"
                      >
                        {selected ? "Selecionado · abrir chat" : "Usar no chat"}
                        <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    </article>
                  );
                })}
              </div>
              {visibleCount < filteredModels.length ? (
                <button
                  type="button"
                  onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
                  className="mx-auto mt-5 flex min-h-10 items-center rounded-xl border border-nexus-border px-4 text-sm text-nexus-muted transition hover:border-nexus-accent/50 hover:text-nexus-text"
                >
                  Mostrar mais modelos
                </button>
              ) : null}
            </>
          )}
        </section>
      </div>
    </AppShell>
  );
}
