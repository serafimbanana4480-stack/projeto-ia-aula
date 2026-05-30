"use client";
import { useEffect, useState } from "react";
import { useModelStore } from "../../stores/modelStore";
import { getModelStatus } from "../../lib/api";
import { motion } from "framer-motion";
import { Cpu, Check, Loader2 } from "lucide-react";
import { log } from "../../lib/log";

interface DynamicModel {
  id: string;
  name: string;
  tier: string;
  size: string;
  color: string;
  status: "available" | "loading" | "error";
}

// Fallback models when API is unavailable
const FALLBACK_MODELS: DynamicModel[] = [
  {
    id: "coder",
    name: "Qwen Coder 7B",
    tier: "CODER",
    size: "4.7GB",
    color: "bg-yellow-500/20 border-yellow-500/30",
    status: "loading",
  },
  {
    id: "reasoning",
    name: "DeepSeek R1 14B",
    tier: "REASONING",
    size: "9GB",
    color: "bg-purple-500/20 border-purple-500/30",
    status: "loading",
  },
  {
    id: "deep",
    name: "Qwen 32B",
    tier: "DEEP",
    size: "20GB",
    color: "bg-blue-500/20 border-blue-500/30",
    status: "loading",
  },
  {
    id: "fast",
    name: "Qwen 3B",
    tier: "FAST",
    size: "2GB",
    color: "bg-green-500/20 border-green-500/30",
    status: "loading",
  },
  {
    id: "micro",
    name: "Qwen 0.5B",
    tier: "MICRO",
    size: "400MB",
    color: "bg-gray-500/20 border-gray-500/30",
    status: "loading",
  },
];

function formatSize(bytes: number): string {
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(0)} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

// Map model IDs to display colors
const MODEL_COLORS: Record<string, string> = {
  coder: "bg-yellow-500/20 border-yellow-500/30",
  reasoning: "bg-purple-500/20 border-purple-500/30",
  deep: "bg-blue-500/20 border-blue-500/30",
  fast: "bg-green-500/20 border-green-500/30",
  micro: "bg-gray-500/20 border-gray-500/30",
  default: "bg-gray-500/20 border-gray-500/30",
};

// Map model IDs to tier names
const MODEL_TIERS: Record<string, string> = {
  coder: "CODER",
  reasoning: "REASONING",
  deep: "DEEP",
  fast: "FAST",
  micro: "MICRO",
};

export default function ModelPanel() {
  const { activeModel, setActiveModel } = useModelStore();
  const [models, setModels] = useState<DynamicModel[]>(FALLBACK_MODELS);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchModels = async () => {
      try {
        const apiModels = await getModelStatus();

        if (apiModels && apiModels.length > 0) {
          // Map API models to our display format
          const dynamicModels: DynamicModel[] = apiModels.map((m: any) => {
            const modelId = m.id.split(":")[0]; // e.g. "qwen2.5-coder:7b" -> "qwen2.5-coder"
            return {
              id: modelId,
              name: m.id, // Use full Ollama model name
              tier:
                m.details?.parameter_size
                  ? `${m.details.parameter_size}B`
                  : MODEL_TIERS[modelId] || "MODEL",
              size: m.size_bytes ? formatSize(m.size_bytes) : "—",
              color:
                MODEL_COLORS[modelId] || MODEL_COLORS["default"],
              status: m.status || "available",
            };
          });
          setModels(dynamicModels);
        }
      } catch (error) {
        // Keep fallback models
        log.error("Failed to fetch models:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchModels();
    const interval = setInterval(fetchModels, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      initial={{ x: 20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="rounded border border-nexus-border bg-nexus-panel/50 p-2"
    >
      <div className="mb-2 flex items-center gap-1.5">
        <Cpu className="h-3.5 w-3.5 text-nexus-accent" />
        <span className="text-[11px] font-semibold">Model</span>
        {loading && (
          <Loader2 className="h-3 w-3 animate-spin text-nexus-accent" />
        )}
      </div>

      <div className="space-y-1.5">
        {models.map((model) => (
          <motion.button
            key={model.id}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => setActiveModel(model.id)}
            className={`w-full rounded border p-1.5 text-left transition-colors ${
              activeModel === model.id
                ? model.color
                : "border-nexus-border/50 bg-transparent hover:bg-nexus-border/30"
            }`}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] font-medium">{model.name}</div>
                <div className="text-[10px] text-gray-500">
                  {model.tier} • {model.size}
                </div>
              </div>
              {activeModel === model.id ? (
                <Check className="h-3.5 w-3.5 text-nexus-accent" />
              ) : model.status === "loading" ? (
                <Loader2 className="h-3 w-3 animate-spin text-gray-500" />
              ) : null}
            </div>
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}
