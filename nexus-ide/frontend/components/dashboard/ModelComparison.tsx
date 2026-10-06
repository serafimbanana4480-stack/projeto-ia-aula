"use client";
import { useEffect, useState, useMemo, useCallback, KeyboardEvent } from "react";
import { apiUrl } from "../../lib/api";
import { authHeaders } from "../../lib/auth";
import { Brain, HardDrive, Clock, Layers } from "lucide-react";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, AnimatedNumber, EmptyState } from "../ui/Primitives";

interface ModelInfo {
  id: string;
  size_bytes: number | null;
  size_gb?: number;
  modified_at: string | null;
  details: Record<string, unknown>;
  provider?: string;
  status: "available" | "loading" | "error";
}

type SortField = "size_bytes" | "status" | "id";

const STR = {
  title: "Comparação de Modelos",
  subtitle: "Modelos disponíveis no provider local selecionado",
  model: "Modelo",
  status: "Estado",
  size: "Tamanho",
  params: "Parâmetros",
  updated: "Atualizado",
  available: "disponível",
  loading: "a carregar",
  unavailable: "indisponível",
  loadingList: "A carregar modelos…",
  empty: "Sem modelos disponíveis",
  error: "Falha ao carregar modelos",
  sortPrefix: "Ordenar por",
  count: "modelos",
  total: "total",
  checkProvider: "Seleciona Ollama ou LM Studio nas definições e confirma que o serviço está ativo",
} as const;

const COLUMN_LABELS: Record<SortField, string> = {
  status: STR.status,
  id: STR.model,
  size_bytes: STR.size,
};

const STATUS_TONE: Record<ModelInfo["status"], "success" | "warning" | "danger"> = {
  available: "success",
  loading: "warning",
  error: "danger",
};

const STATUS_LABEL: Record<ModelInfo["status"], string> = {
  available: STR.available,
  loading: STR.loading,
  error: STR.unavailable,
};

export default function ModelComparison() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [sortField, setSortField] = useState<SortField>("size_bytes");
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    let mounted = true;

    const fetchModels = async () => {
      try {
        setLoading(true);
        setHasError(false);
        const response = await fetch(apiUrl("/api/models/status"), {
          headers: authHeaders(),
          signal: AbortSignal.timeout(10000),
        });
        if (response.ok) {
          const data = (await response.json()) as ModelInfo[];
          if (mounted && Array.isArray(data) && data.length > 0) {
            setModels(data);
          }
        } else if (mounted) {
          setHasError(true);
        }
      } catch {
        if (mounted) setHasError(true);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchModels();
    const interval = setInterval(fetchModels, 120000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const sortedModels = useMemo(() => {
    return [...models].sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }
      if (typeof aVal !== "number") return typeof bVal === "number" ? 1 : 0;
      if (typeof bVal !== "number") return -1;
      return sortAsc ? aVal - bVal : bVal - aVal;
    });
  }, [models, sortField, sortAsc]);

  const handleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) {
        setSortAsc((prev) => !prev);
      } else {
        setSortField(field);
        setSortAsc(true);
      }
    },
    [sortField]
  );

  const onHeaderKeyDown = useCallback(
    (field: SortField) => (e: KeyboardEvent<HTMLTableCellElement>) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        handleSort(field);
      }
    },
    [handleSort]
  );

  const ariaSortValue = (field: SortField): "ascending" | "descending" | "none" => {
    if (sortField !== field) return "none";
    return sortAsc ? "ascending" : "descending";
  };

  const totalSize = useMemo(
    () =>
      models.every((model) => typeof model.size_bytes === "number")
        ? models.reduce((total, model) => total + (model.size_bytes ?? 0), 0)
        : null,
    [models]
  );

  const formatSize = useCallback((bytes: number | null) => {
    if (bytes === null) return "—";
    if (bytes < 1e9) return `${(bytes / 1e6).toFixed(0)} MB`;
    return `${(bytes / 1e9).toFixed(1)} GB`;
  }, []);

  const formatDate = useCallback((dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString("pt-PT");
    } catch {
      return dateStr;
    }
  }, []);

  const getFamilyIcon = useCallback((family: string) => {
    const icons: Record<string, string> = {
      qwen2: "🔷",
      qwen35: "🔶",
      llama: "🦙",
      mistral: "⚡",
      deepseek: "🔍",
    };
    return icons[family] || "🤖";
  }, []);

  const sortIndicator = (field: SortField) =>
    sortField === field ? (sortAsc ? "↑" : "↓") : "";

  return (
    <section aria-label={STR.title}>
      <Surface elevation={1} padding="sm">
        <SurfaceHeader
          icon={<Brain className="h-4 w-4" />}
          title={STR.title}
          subtitle={STR.subtitle}
          action={
            <div className="text-right text-[10px] text-nexus-faint">
              <AnimatedNumber value={models.length} /> {STR.count} · {totalSize === null ? "—" : formatSize(totalSize)} {STR.total}
            </div>
          }
        />

        <div className="mt-3">
          {loading && models.length === 0 ? (
            <div className="space-y-1.5" role="status" aria-live="polite" aria-label={STR.loadingList}>
              <div className="nx-shimmer h-6 rounded-lg" />
              <div className="nx-shimmer h-8 rounded-lg" />
              <div className="nx-shimmer h-8 rounded-lg" />
              <div className="nx-shimmer h-8 rounded-lg" />
            </div>
          ) : hasError && models.length === 0 ? (
            <EmptyState icon={<Brain className="h-6 w-6" />} title={STR.error} hint={STR.checkProvider} />
          ) : models.length === 0 ? (
            <EmptyState icon={<Brain className="h-6 w-6" />} title={STR.empty} hint={STR.checkProvider} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-xs sm:text-sm">
                <caption className="sr-only">{STR.title}</caption>
                <thead className="text-nexus-faint">
                  <tr className="border-b border-[var(--nx-line)]">
                    <th
                      scope="col"
                      aria-sort={ariaSortValue("status")}
                      tabIndex={0}
                      aria-label={`${STR.sortPrefix} ${COLUMN_LABELS.status}`}
                      className="cursor-pointer pb-2 text-left hover:text-nexus-text"
                      onClick={() => handleSort("status")}
                      onKeyDown={onHeaderKeyDown("status")}
                    >
                      {STR.status} {sortIndicator("status")}
                    </th>
                    <th
                      scope="col"
                      aria-sort={ariaSortValue("id")}
                      tabIndex={0}
                      aria-label={`${STR.sortPrefix} ${COLUMN_LABELS.id}`}
                      className="cursor-pointer pb-2 text-left hover:text-nexus-text"
                      onClick={() => handleSort("id")}
                      onKeyDown={onHeaderKeyDown("id")}
                    >
                      {STR.model} {sortIndicator("id")}
                    </th>
                    <th
                      scope="col"
                      aria-sort={ariaSortValue("size_bytes")}
                      tabIndex={0}
                      aria-label={`${STR.sortPrefix} ${COLUMN_LABELS.size_bytes}`}
                      className="cursor-pointer pb-2 text-right hover:text-nexus-text"
                      onClick={() => handleSort("size_bytes")}
                      onKeyDown={onHeaderKeyDown("size_bytes")}
                    >
                      <div className="flex items-center justify-end gap-1">
                        <HardDrive className="h-3 w-3" />
                        {STR.size} {sortIndicator("size_bytes")}
                      </div>
                    </th>
                    <th scope="col" className="hidden pb-2 text-right sm:table-cell">
                      <div className="flex items-center justify-end gap-1">
                        <Layers className="h-3 w-3" />
                        {STR.params}
                      </div>
                    </th>
                    <th scope="col" className="hidden pb-2 text-right sm:table-cell">
                      <div className="flex items-center justify-end gap-1">
                        <Clock className="h-3 w-3" />
                        {STR.updated}
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--nx-line)]">
                  {sortedModels.map((model) => (
                    <tr key={model.id} className="transition-colors hover:bg-white/[0.03]">
                      <td className="py-2">
                        <Badge tone={STATUS_TONE[model.status]}>{STATUS_LABEL[model.status]}</Badge>
                      </td>
                      <td className="py-2">
                        <div className="flex min-w-0 items-center gap-1.5">
                          <span className="text-sm" aria-hidden="true">
                            {getFamilyIcon((model.details?.family as string) || "")}
                          </span>
                          <span className="truncate font-mono text-xs" title={model.id}>
                            {model.id}
                          </span>
                        </div>
                      </td>
                      <td className="py-2 text-right font-mono tabular-nums">{formatSize(model.size_bytes)}</td>
                      <td className="hidden py-2 text-right text-nexus-muted sm:table-cell">
                        {model.details?.parameter_size ? `${model.details.parameter_size}` : "—"}
                      </td>
                      <td className="hidden py-2 text-right text-nexus-faint sm:table-cell">
                        {model.modified_at ? formatDate(model.modified_at) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Surface>
    </section>
  );
}
