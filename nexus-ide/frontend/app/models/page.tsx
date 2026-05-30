"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { getModelStatus } from "../../lib/api";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import { Cpu, Download, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { log } from "../../lib/log";

interface Model {
  id: string;
  size_bytes: number;
  size_gb?: number;
  status: "available" | "loading" | "error";
  details?: Record<string, unknown>;
}

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [installing, setInstalling] = useState<string | null>(null);
  const [installProgress, setInstallProgress] = useState<string>("");

  useEffect(() => {
    const fetchModels = async () => {
      try {
        const data = await getModelStatus();
        setModels(data || []);
      } catch (error) {
        log.error("Failed to fetch models:", error);
      }
    };
    fetchModels();
    const interval = setInterval(fetchModels, 10000);
    return () => clearInterval(interval);
  }, []);

  const formatSize = (bytes: number) => {
    if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
    return `${(bytes / 1e9).toFixed(1)} GB`;
  };

  const handleInstall = async (modelId: string) => {
    setInstalling(modelId);
    setInstallProgress("Starting download...");

    try {
      // Use Ollama's pull API to download the model
      const OLLAMA_HOST = process.env.NEXT_PUBLIC_OLLAMA_HOST ?? "http://localhost:11434";
      const response = await fetch(`${OLLAMA_HOST}/api/pull`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: modelId, stream: true }),
      });

      if (!response.ok) {
        throw new Error(`Failed to start download: ${response.statusText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            if (data.status) {
              setInstallProgress(data.status);
            }
            if (data.completed && data.total) {
              const pct = ((data.completed / data.total) * 100).toFixed(0);
              setInstallProgress(`Downloading: ${pct}%`);
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }

      setInstallProgress("Installation complete!");
      // Refresh model list
      const data = await getModelStatus();
      setModels(data || []);
    } catch (error) {
      log.error("Failed to install model:", error);
      setInstallProgress(
        `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    } finally {
      setTimeout(() => {
        setInstalling(null);
        setInstallProgress("");
      }, 2000);
    }
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

            {installing && installProgress && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-4 rounded border border-nexus-accent/30 bg-nexus-accent/10 p-3 text-sm"
              >
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin text-nexus-accent" />
                  <span>
                    Installing <strong>{installing}</strong>: {installProgress}
                  </span>
                </div>
              </motion.div>
            )}

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
                      <p className="text-xs text-gray-500">
                        {formatSize(model.size_bytes)}
                      </p>
                      {model.details?.parameter_size ? (
                        <p className="text-xs text-gray-500">
                          {String(model.details.parameter_size)}B parameters
                        </p>
                      ) : null}
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
                  <p className="text-xs">
                    Make sure Ollama is running to see and install models
                  </p>
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
