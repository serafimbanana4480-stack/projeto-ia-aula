"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { apiUrl } from "../../lib/api";
import { MOCK_MODELS, type ModelInfo } from "../../lib/mock-data";

export default function ModelComparison() {
  const [models, setModels] = useState<ModelInfo[]>(MOCK_MODELS);
  const [loading, setLoading] = useState(true);
  const [isMock, setIsMock] = useState(true);
  const [sortField, setSortField] = useState<"size_gb" | "status">("size_gb");
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    const fetchModels = async () => {
      try {
        setLoading(true);
        const response = await fetch(apiUrl("/api/models/status"));
        if (response.ok) {
          const data = await response.json();
          if (Array.isArray(data) && data.length > 0) {
            setModels(data);
            setIsMock(false);
          }
          // If empty, keep mock data
        }
      } catch {
        // Ollama unavailable — keep mock data
      } finally {
        setLoading(false);
      }
    };

    fetchModels();
    const interval = setInterval(fetchModels, 60000);
    return () => clearInterval(interval);
  }, []);

  const sortedModels = [...models].sort((a, b) => {
    const aVal = a[sortField];
    const bVal = b[sortField];
    if (typeof aVal === "string" && typeof bVal === "string") {
      return sortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    }
    return sortAsc ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number);
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
    const colors: Record<string, string> = {
      available: "bg-green-500/20 text-green-400",
      loading: "bg-yellow-500/20 text-yellow-400",
      error: "bg-red-500/20 text-red-400",
    };
    return (
      <span className={`rounded px-1.5 py-0.5 text-xs ${colors[status] || colors.available}`}>
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
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold">Modelos Disponíveis</div>
        {isMock && !loading && (
          <span className="text-xs text-gray-600">demo</span>
        )}
      </div>
      {loading ? (
        <div className="flex h-32 items-center justify-center text-xs text-gray-500">
          Carregando...
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500">
              <tr>
                <th className="cursor-pointer text-left hover:text-gray-300" onClick={() => handleSort("status")}>
                  Status {sortField === "status" && (sortAsc ? "↑" : "↓")}
                </th>
                <th className="text-left">Model</th>
                <th className="cursor-pointer text-right hover:text-gray-300" onClick={() => handleSort("size_gb")}>
                  Size {sortField === "size_gb" && (sortAsc ? "↑" : "↓")}
                </th>
                <th className="text-right">Param</th>
              </tr>
            </thead>
            <tbody>
              {sortedModels.map((model, index) => (
                <motion.tr
                  key={model.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.03 }}
                  className="border-t border-nexus-border/50 hover:bg-nexus-border/20"
                >
                  <td className="py-1.5">{getStatusBadge(model.status)}</td>
                  <td className="py-1.5 font-mono">{model.id}</td>
                  <td className="py-1.5 text-right">{formatSize(model.size_bytes)}</td>
                  <td className="py-1.5 text-right text-gray-400">
                    {model.details?.parameter_size ? `${model.details.parameter_size}` : "—"}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </motion.div>
  );
}
