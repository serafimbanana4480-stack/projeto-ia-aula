"use client";
import { useEffect } from "react";
import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import { Cpu, Loader2, AlertCircle, CheckCircle2, Zap } from "lucide-react";
import { useModelStore } from "../../stores/modelStore";

export default function ModelsPage() {
  const models = useModelStore((s) => s.models);
  const activeModel = useModelStore((s) => s.activeModel);
  const setActiveModel = useModelStore((s) => s.setActiveModel);
  const modelsLoaded = useModelStore((s) => s.modelsLoaded);
  const modelsLoading = useModelStore((s) => s.modelsLoading);
  const modelsError = useModelStore((s) => s.modelsError);
  const loadModels = useModelStore((s) => s.loadModels);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  return (
    <AppShell title="Modelos IA">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-4xl mx-auto"
      >
        <div className="mb-6 flex items-center gap-3">
          <Cpu className="h-6 w-6 text-nexus-accent" />
          <h1 className="text-2xl font-bold">Modelos IA</h1>
        </div>

        {modelsLoading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-nexus-accent" />
          </div>
        )}

        {modelsError && (
          <div className="flex items-center gap-2 text-sm text-red-400">
            <AlertCircle className="h-4 w-4" />
            {modelsError}
          </div>
        )}

        {modelsLoaded && !modelsError && models.length === 0 && (
          <div className="flex items-center gap-2 text-sm text-nexus-muted">
            <AlertCircle className="h-4 w-4" />
            Nenhum modelo disponível. Verifique se o backend está a
            funcionar.
          </div>
        )}

        {!modelsLoading && models.length > 0 && (
          <div className="space-y-3">
            <div className="text-sm text-nexus-muted">
              {models.length} modelos disponíveis
            </div>
            {models.map((model, index) => {
              const isActive = model.id === activeModel;
              return (
                <motion.button
                  key={model.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03 }}
                  onClick={() => setActiveModel(model.id, model.provider)}
                  className={`card w-full text-left transition-colors ${
                    isActive
                      ? "border-nexus-accent"
                      : "hover:border-nexus-border/80"
                  }`}
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex items-center gap-2">
                        <span className="font-medium">
                          {model.name || model.id}
                        </span>
                        {isActive && (
                          <CheckCircle2 className="h-4 w-4 text-nexus-accent" />
                        )}
                      </div>
                      <p className="font-mono text-xs text-nexus-muted">
                        {model.id}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-nexus-muted">
                        {model.provider && (
                          <span className="rounded-full border border-nexus-border px-2 py-0.5">
                            {model.provider}
                          </span>
                        )}
                        {model.pricing && (
                          <span className="rounded-full border border-nexus-border px-2 py-0.5">
                            {model.pricing}
                          </span>
                        )}
                        {model.estimated_tokens_per_sec != null && (
                          <span className="flex items-center gap-1">
                            <Zap className="h-3 w-3" />
                            {model.estimated_tokens_per_sec} tok/s
                          </span>
                        )}
                      </div>
                    </div>
                    <span
                      className={`shrink-0 rounded-lg border px-3 py-1.5 text-xs ${
                        isActive
                          ? "border-nexus-accent text-nexus-accent"
                          : "border-nexus-border text-nexus-muted"
                      }`}
                    >
                      {isActive ? "Ativo" : "Selecionar"}
                    </span>
                  </div>
                </motion.button>
              );
            })}
          </div>
        )}
      </motion.div>
    </AppShell>
  );
}
