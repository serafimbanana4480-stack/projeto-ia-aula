"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { apiUrl } from "../../lib/api";

interface ModelInfo {
  id: string;
  size_bytes: number;
  size_gb: number;
  modified_at: string;
  details: Record<string, unknown>;
  status: "available" | "loading" | "error";
}

export default function ModelComparison() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sortField, setSortField] = useState<"size_gb" | "status">("size_gb");
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    const fetchModels = async () => {
      try {
        setLoading(true);
        setErrorMessage(null);
        const response = await fetch(apiUrl("/api/models/status"));
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        setModels(data);
      } catch (error) {
        console.error("Failed to fetch models:", error);
        setModels([]);
        setErrorMessage(
          "Ollama model inventory is unavailable. No fallback model data is shown.",
        );
      } finally {
        setLoading(false);
      }
    };

    fetchModels();

    // Refresh every 60 seconds
    const interval = setInterval(fetchModels, 60000);

    return () => clearInterval(interval);
  }, []);

  const sortedModels = [...models].sort((a, b) => {
    const aVal = a[sortField];
    const bVal = b[sortField];
    if (typeof aVal === "string" && typeof bVal === "string") {
      return sortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    }
    return sortAsc
      ? (aVal as number) - (bVal as number)
      : (bVal as number) - (aVal as number);
  });

  const handleSort = (field: "size_gb" | "status") => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  const getStatusBadge = (status: string) => {
    const colors = {
      available: "bg-green-500/20 text-green-400",
      loading: "bg-yellow-500/20 text-yellow-400",
      error: "bg-red-500/20 text-red-400",
    };
    return (
      <span
        className={`rounded px-2 py-0.5 text-xs ${colors[status as keyof typeof colors] || colors.available}`}
      >
        {status}
      </span>
    );
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
    return `${(bytes / 1e9).toFixed(1)} GB`;
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
      className="rounded border border-nexus-border bg-nexus-panel p-3"
    >
      <div className="mb-2 text-sm font-semibold">Modelos Disponíveis</div>
      {loading ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-40 items-center justify-center text-xs text-gray-500"
        >
          Carregando...
        </motion.div>
      ) : errorMessage ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-40 flex-col items-center justify-center gap-2 text-center text-xs text-gray-500"
        >
          <div>Model telemetry unavailable</div>
          <div className="max-w-sm text-gray-600">{errorMessage}</div>
        </motion.div>
      ) : models.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th
                  className="cursor-pointer text-left hover:text-gray-300"
                  onClick={() => handleSort("status")}
                >
                  Status {sortField === "status" && (sortAsc ? "↑" : "↓")}
                </th>
                <th className="text-left">Model</th>
                <th
                  className="cursor-pointer text-right hover:text-gray-300"
                  onClick={() => handleSort("size_gb")}
                >
                  Tamanho {sortField === "size_gb" && (sortAsc ? "↑" : "↓")}
                </th>
                <th className="text-right">Param</th>
              </tr>
            </thead>
            <tbody>
              {sortedModels.map((model, index) => (
                <motion.tr
                  key={model.id}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className="border-t border-nexus-border/50 hover:bg-nexus-border/20"
                >
                  <td className="py-2">{getStatusBadge(model.status)}</td>
                  <td className="py-2 font-mono text-xs">{model.id}</td>
                  <td className="py-2 text-right">
                    {formatSize(model.size_bytes)}
                  </td>
                  <td className="py-2 text-right text-gray-400">
                    {model.details?.parameter_size
                      ? `${model.details.parameter_size}B`
                      : "—"}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-40 items-center justify-center text-xs text-gray-500"
        >
          Nenhum modelo encontrado
        </motion.div>
      )}
    </motion.div>
  );
}
