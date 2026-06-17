"use client";
import { useEffect, useState, useMemo, useCallback, KeyboardEvent } from "react";
import { apiUrl } from "../../lib/api";
import { authHeaders } from "../../lib/auth";
import { Brain, HardDrive, Clock, Layers } from "lucide-react";

interface ModelInfo {
  id: string;
  size_bytes: number;
  size_gb?: number;
  modified_at: string;
  details: Record<string, unknown>;
  status: "available" | "loading" | "error";
}

type SortField = "size_bytes" | "status" | "id";

const STR = {
  title: "Comparação de Modelos",
  model: "Modelo",
  status: "Estado",
  size: "Tamanho",
  params: "Parâmetros",
  updated: "Atualizado",
  available: "disponível",
  unavailable: "indisponível",
  loading: "A carregar modelos…",
  empty: "Sem modelos disponíveis",
  error: "Falha ao carregar modelos",
  sortPrefix: "Ordenar por",
  count: "modelos",
  total: "total",
  checkOllama: "Verifique se o Ollama está em execução",
} as const;

const COLUMN_LABELS: Record<SortField, string> = {
  status: STR.status,
  id: STR.model,
  size_bytes: STR.size,
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
      return sortAsc ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number);
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

  const totalSize = useMemo(() => models.reduce((acc, m) => acc + m.size_bytes, 0), [models]);

  const getStatusBadge = useCallback((status: string) => {
    const colors: Record<string, string> = {
      available: "bg-green-500/15 text-green-400 border-green-500/30",
      loading: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
      error: "bg-red-500/15 text-red-400 border-red-500/30",
    };
    const label = status === "available" ? STR.available : STR.unavailable;
    return (
      <span
        role="img"
        aria-label={label}
        className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${colors[status] || colors.available}`}
      >
        {label}
      </span>
    );
  }, []);

  const formatSize = useCallback((bytes: number) => {
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
    <section
      aria-label={STR.title}
      className="rounded border border-nexus-border bg-nexus-panel p-3"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <Brain className="h-4 w-4 shrink-0 text-nexus-accent" />
          <div className="truncate text-sm font-semibold">{STR.title}</div>
        </div>
        <div className="shrink-0 text-[10px] text-gray-500">
          {models.length} {STR.count} · {formatSize(totalSize)} {STR.total}
        </div>
      </div>

      {loading ? (
        <div
          role="status"
          aria-live="polite"
          className="flex h-32 items-center justify-center text-xs text-gray-500"
        >
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
            {STR.loading}
          </div>
        </div>
      ) : hasError && models.length === 0 ? (
        <div className="flex h-32 flex-col items-center justify-center text-xs text-gray-500">
          <Brain className="mb-2 h-8 w-8 text-gray-600" />
          <span>{STR.error}</span>
          <span className="mt-1 text-gray-600">{STR.checkOllama}</span>
        </div>
      ) : models.length === 0 ? (
        <div className="flex h-32 flex-col items-center justify-center text-xs text-gray-500">
          <Brain className="mb-2 h-8 w-8 text-gray-600" />
          <span>{STR.empty}</span>
          <span className="mt-1 text-gray-600">{STR.checkOllama}</span>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-xs sm:text-sm">
            <caption className="sr-only">{STR.title}</caption>
            <thead className="text-gray-500">
              <tr className="border-b border-nexus-border/50">
                <th
                  scope="col"
                  aria-sort={ariaSortValue("status")}
                  role="button"
                  tabIndex={0}
                  aria-label={`${STR.sortPrefix} ${COLUMN_LABELS.status}`}
                  className="cursor-pointer pb-2 text-left hover:text-gray-300"
                  onClick={() => handleSort("status")}
                  onKeyDown={onHeaderKeyDown("status")}
                >
                  {STR.status} {sortIndicator("status")}
                </th>
                <th
                  scope="col"
                  aria-sort={ariaSortValue("id")}
                  role="button"
                  tabIndex={0}
                  aria-label={`${STR.sortPrefix} ${COLUMN_LABELS.id}`}
                  className="cursor-pointer pb-2 text-left hover:text-gray-300"
                  onClick={() => handleSort("id")}
                  onKeyDown={onHeaderKeyDown("id")}
                >
                  {STR.model} {sortIndicator("id")}
                </th>
                <th
                  scope="col"
                  aria-sort={ariaSortValue("size_bytes")}
                  role="button"
                  tabIndex={0}
                  aria-label={`${STR.sortPrefix} ${COLUMN_LABELS.size_bytes}`}
                  className="cursor-pointer pb-2 text-right hover:text-gray-300"
                  onClick={() => handleSort("size_bytes")}
                  onKeyDown={onHeaderKeyDown("size_bytes")}
                >
                  <div className="flex items-center justify-end gap-1">
                    <HardDrive className="h-3 w-3" />
                    {STR.size} {sortIndicator("size_bytes")}
                  </div>
                </th>
                <th
                  scope="col"
                  className="hidden pb-2 text-right sm:table-cell"
                >
                  <div className="flex items-center justify-end gap-1">
                    <Layers className="h-3 w-3" />
                    {STR.params}
                  </div>
                </th>
                <th
                  scope="col"
                  className="hidden pb-2 text-right sm:table-cell"
                >
                  <div className="flex items-center justify-end gap-1">
                    <Clock className="h-3 w-3" />
                    {STR.updated}
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedModels.map((model) => (
                <tr
                  key={model.id}
                  className="border-t border-nexus-border/30 transition-colors hover:bg-nexus-border/10"
                >
                  <td className="py-2">{getStatusBadge(model.status)}</td>
                  <td className="py-2">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="text-sm" aria-hidden="true">
                        {getFamilyIcon((model.details?.family as string) || "")}
                      </span>
                      <span className="truncate font-mono text-xs">{model.id}</span>
                    </div>
                  </td>
                  <td className="py-2 text-right font-mono">{formatSize(model.size_bytes)}</td>
                  <td className="hidden py-2 text-right text-gray-400 sm:table-cell">
                    {model.details?.parameter_size ? `${model.details.parameter_size}` : "—"}
                  </td>
                  <td className="hidden py-2 text-right text-gray-500 sm:table-cell">
                    {model.modified_at ? formatDate(model.modified_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
