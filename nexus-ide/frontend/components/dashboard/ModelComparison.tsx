"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
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

export default function ModelComparison() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortField, setSortField] = useState<"size_bytes" | "status" | "id">("size_bytes");
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    let mounted = true;

    const fetchModels = async () => {
      try {
        setLoading(true);
        const response = await fetch(apiUrl("/api/models/status"), { headers: authHeaders(), signal: AbortSignal.timeout(10000) });
        if (response.ok) {
          const data = (await response.json()) as ModelInfo[];
          if (mounted && Array.isArray(data) && data.length > 0) {
            setModels(data);
          }
        }
      } catch {
        /* Ollama unavailable */
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
    (field: "size_bytes" | "status" | "id") => {
      if (sortField === field) {
        setSortAsc((prev) => !prev);
      } else {
        setSortField(field);
        setSortAsc(true);
      }
    },
    [sortField]
  );

  const totalSize = useMemo(() => models.reduce((acc, m) => acc + m.size_bytes, 0), [models]);

  const getStatusBadge = useCallback((status: string) => {
    const colors: Record<string, string> = {
      available: "bg-green-500/15 text-green-400 border-green-500/30",
      loading: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
      error: "bg-red-500/15 text-red-400 border-red-500/30",
    };
    return (
      <span
        className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${colors[status] || colors.available}`}
      >
        {status}
      </span>
    );
  }, []);

  const formatSize = useCallback((bytes: number) => {
    if (bytes < 1e9) return `${(bytes / 1e6).toFixed(0)} MB`;
    return `${(bytes / 1e9).toFixed(1)} GB`;
  }, []);

  const formatDate = useCallback((dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString();
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

  return (
    <div className="rounded border border-nexus-border bg-nexus-panel p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-nexus-accent" />
          <div className="text-sm font-semibold">Modelos Disponíveis</div>
        </div>
        <div className="text-[10px] text-gray-500">
          {models.length} models · {formatSize(totalSize)} total
        </div>
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center text-xs text-gray-500">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
            Carregando...
          </div>
        </div>
      ) : models.length === 0 ? (
        <div className="flex h-32 flex-col items-center justify-center text-xs text-gray-500">
          <Brain className="h-8 w-8 text-gray-600 mb-2" />
          <span>Nenhum modelo disponível</span>
          <span className="text-gray-600 mt-1">Verifique se o Ollama está em execução</span>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500">
              <tr className="border-b border-nexus-border/50">
                <th
                  className="cursor-pointer pb-2 text-left hover:text-gray-300"
                  onClick={() => handleSort("status")}
                >
                  Status {sortField === "status" && (sortAsc ? "↑" : "↓")}
                </th>
                <th
                  className="cursor-pointer pb-2 text-left hover:text-gray-300"
                  onClick={() => handleSort("id")}
                >
                  Model {sortField === "id" && (sortAsc ? "↑" : "↓")}
                </th>
                <th
                  className="cursor-pointer pb-2 text-right hover:text-gray-300"
                  onClick={() => handleSort("size_bytes")}
                >
                  <div className="flex items-center justify-end gap-1">
                    <HardDrive className="h-3 w-3" />
                    Size {sortField === "size_bytes" && (sortAsc ? "↑" : "↓")}
                  </div>
                </th>
                <th className="pb-2 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <Layers className="h-3 w-3" />
                    Params
                  </div>
                </th>
                <th className="pb-2 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <Clock className="h-3 w-3" />
                    Updated
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedModels.map((model) => (
                <tr
                  key={model.id}
                  className="border-t border-nexus-border/30 hover:bg-nexus-border/10 transition-colors"
                >
                  <td className="py-2">{getStatusBadge(model.status)}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm">{getFamilyIcon((model.details?.family as string) || "")}</span>
                      <span className="font-mono text-xs">{model.id}</span>
                    </div>
                  </td>
                  <td className="py-2 text-right font-mono">{formatSize(model.size_bytes)}</td>
                  <td className="py-2 text-right text-gray-400">
                    {model.details?.parameter_size ? `${model.details.parameter_size}` : "—"}
                  </td>
                  <td className="py-2 text-right text-gray-500">
                    {model.modified_at ? formatDate(model.modified_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
