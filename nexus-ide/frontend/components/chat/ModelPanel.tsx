"use client";
import { useModelStore } from "../../stores/modelStore";
import { motion } from "framer-motion";
import { Cpu, Check } from "lucide-react";

const MODELS = [
  { id: "coder", name: "Qwen Coder 7B", tier: "CODER", size: "4.7GB", color: "bg-yellow-500/20 border-yellow-500/30" },
  { id: "reasoning", name: "DeepSeek R1 14B", tier: "REASONING", size: "9GB", color: "bg-purple-500/20 border-purple-500/30" },
  { id: "deep", name: "Qwen 32B", tier: "DEEP", size: "20GB", color: "bg-blue-500/20 border-blue-500/30" },
  { id: "fast", name: "Qwen 3B", tier: "FAST", size: "2GB", color: "bg-green-500/20 border-green-500/30" },
  { id: "micro", name: "Qwen 0.5B", tier: "MICRO", size: "400MB", color: "bg-gray-500/20 border-gray-500/30" },
];

export default function ModelPanel() {
  const { activeModel, setActiveModel } = useModelStore();

  return (
    <motion.div
      initial={{ x: 20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="rounded border border-nexus-border bg-nexus-panel/50 p-2"
    >
      <div className="mb-2 flex items-center gap-1.5">
        <Cpu className="h-3.5 w-3.5 text-nexus-accent" />
        <span className="text-[11px] font-semibold">Model</span>
      </div>
      
      <div className="space-y-1.5">
        {MODELS.map((model) => (
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
              {activeModel === model.id && (
                <Check className="h-3.5 w-3.5 text-nexus-accent" />
              )}
            </div>
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}
