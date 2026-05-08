"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { getModelStatus } from "../../lib/api";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import { Cpu, Download, CheckCircle, XCircle, Loader2 } from "lucide-react";

interface Model {
  id: string;
  size_bytes: number;
  size_gb?: number;
  status: "available" | "loading" | "error";
}

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [installing, setInstalling] = useState<string | null>(null);

  useEffect(() => {
    const fetchModels = async () => {
      try {
        const data = await getModelStatus();
        setModels(data || []);
      } catch (error) {
        console.error("Failed to fetch models:", error);
      }
    };
    fetchModels();
  }, []);

  const formatSize = (bytes: number) => {
    if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
    return `${(bytes / 1e9).toFixed(1)} GB`;
  };

  const handleInstall = async (modelId: string) => {
    setInstalling(modelId);
    // TODO: Implement real Ollama install API
    // For now, simulate installation
    setTimeout(() => {
      setInstalling(null);
      alert(`Installation of ${modelId} would require Ollama API integration.`);
    }, 3000);
  };

  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        
        <main className="flex-1 overflow-auto p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="mb-6 flex items-center gap-3">
              <Cpu className="h-6 w-6 text-nexus-accent" />
              <h1 className="text-2xl font-bold">Models</h1>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {models.map((model, index) => (
                <motion.div
                  key={model.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.1 }}
                  className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
                >
                  <div className="mb-3 flex items-start justify-between">
                    <div>
                      <h3 className="text-sm font-semibold">{model.id}</h3>
                      <p className="text-xs text-gray-500">{formatSize(model.size_bytes)}</p>
                    </div>
                    {model.status === "available" && (
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    )}
                    {model.status === "loading" && (
                      <Loader2 className="h-4 w-4 animate-spin text-nexus-accent" />
                    )}
                    {model.status === "error" && (
                      <XCircle className="h-4 w-4 text-red-500" />
                    )}
                  </div>
                  
                  <div className="flex items-center justify-between">
                    <div className="rounded bg-nexus-border px-2 py-0.5 text-xs">
                      {model.status}
                    </div>
                    {model.status !== "available" && (
                      <button
                        onClick={() => handleInstall(model.id)}
                        disabled={installing === model.id}
                        className="flex items-center gap-1 rounded bg-nexus-accent px-3 py-1 text-xs text-black hover:bg-nexus-accent/80 disabled:opacity-50"
                      >
                        {installing === model.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Download className="h-3 w-3" />
                        )}
                        Install
                      </button>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>

            {models.length === 0 && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex h-64 items-center justify-center text-gray-500"
              >
                <div className="text-center">
                  <Cpu className="mx-auto mb-3 h-12 w-12 text-nexus-border" />
                  <p className="text-sm">No models available</p>
                  <p className="text-xs">Install models to get started</p>
                </div>
              </motion.div>
            )}
          </motion.div>
        </main>
      </div>
      
      <BottomHUD />
    </div>
  );
}
