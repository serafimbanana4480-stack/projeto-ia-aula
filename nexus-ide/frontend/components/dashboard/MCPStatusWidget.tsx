"use client";
import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { Plug, RefreshCw, ArrowRight } from "lucide-react";
import { getMCPConnectors, type MCPConnector, type MCPConnectorsSummary } from "../../lib/api";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { StatusDot, AnimatedNumber, EmptyState } from "../ui/Primitives";

const TONE_TEXT = {
  neutral: "text-nexus-text",
  success: "text-emerald-400",
  warning: "text-amber-400",
  danger: "text-rose-400",
} as const;

const TEST_STATUS_TONE: Record<MCPConnector["last_test_status"], "success" | "warning" | "danger" | "neutral"> = {
  ok: "success",
  warning: "warning",
  error: "danger",
  untested: "neutral",
};

const TEST_STATUS_LABEL: Record<MCPConnector["last_test_status"], string> = {
  ok: "OK",
  warning: "Aviso",
  error: "Erro",
  untested: "Por testar",
};

export default function MCPStatusWidget() {
  const [connectors, setConnectors] = useState<MCPConnector[]>([]);
  const [summary, setSummary] = useState<MCPConnectorsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await getMCPConnectors();
      setConnectors(resp.connectors);
      setSummary(resp.summary);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchStatus();
    const interval = setInterval(fetchStatus, 60000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  return (
    <motion.div className="h-full" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <Surface elevation={1} padding="md" className="nx-dashboard-widget h-full">
        <SurfaceHeader
          icon={<Plug className="h-4 w-4" />}
          title="Conectores MCP"
          subtitle="Configuração e último teste — não é uma ligação em tempo real"
          action={
            <button
              type="button"
              onClick={() => {
                setLoading(true);
                fetchStatus();
              }}
              aria-label="Atualizar conectores MCP"
              title="Atualizar"
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-nexus-border/60 text-nexus-muted transition-colors hover:bg-nexus-card hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
          }
        />

        <div className="mt-4">
          {loading && !summary ? (
            <div className="space-y-2">
              <div className="nx-shimmer h-14 rounded-lg" />
              <div className="nx-shimmer h-8 rounded-lg" />
              <div className="nx-shimmer h-8 rounded-lg" />
            </div>
          ) : error ? (
            <EmptyState
              icon={<Plug className="h-6 w-6" />}
              title="Falha ao carregar conectores"
              hint={error}
            />
          ) : !summary || summary.total === 0 ? (
            <EmptyState
              icon={<Plug className="h-6 w-6" />}
              title="Nenhum conector MCP configurado"
              hint="Liga um servidor MCP para dares aos agentes acesso a ferramentas externas."
              action={
                <a
                  href="/mcp"
                  className="inline-flex items-center gap-1 text-xs font-medium text-[var(--nx-accent-bright)] hover:underline"
                >
                  Ligar o primeiro servidor <ArrowRight className="h-3 w-3" />
                </a>
              }
            />
          ) : (
            <>
              <div className="nx-inset grid grid-cols-2 gap-x-3 gap-y-4 rounded-xl p-4 text-center">
                <div>
                  <div className={`font-mono text-lg font-bold tabular-nums ${TONE_TEXT.neutral}`}>
                    <AnimatedNumber value={summary.total} />
                  </div>
                  <div className="mt-1 text-[11px] text-nexus-muted">Configurados</div>
                </div>
                <div>
                  <div className={`font-mono text-lg font-bold tabular-nums ${TONE_TEXT.success}`}>
                    <AnimatedNumber value={summary.healthy} />
                  </div>
                  <div className="mt-1 text-[11px] text-nexus-muted">Último teste OK</div>
                </div>
                <div>
                  <div className={`font-mono text-lg font-bold tabular-nums ${TONE_TEXT.warning}`}>
                    <AnimatedNumber value={summary.warning} />
                  </div>
                  <div className="mt-1 text-[11px] text-nexus-muted">Avisos</div>
                </div>
                <div>
                  <div className={`font-mono text-lg font-bold tabular-nums ${TONE_TEXT.danger}`}>
                    <AnimatedNumber value={summary.error} />
                  </div>
                  <div className="mt-1 text-[11px] text-nexus-muted">Erros</div>
                </div>
              </div>

              <div className="mt-3 space-y-1">
                {connectors.slice(0, 3).map((c) => (
                  <div
                    key={c.id}
                    className="flex min-h-14 flex-wrap items-center justify-between gap-2 rounded-xl border border-nexus-border/50 bg-nexus-card/30 px-3 py-2.5 text-xs"
                  >
                    <span className="truncate text-nexus-text" title={c.name}>
                      {c.name}
                    </span>
                    <div className="flex shrink-0 flex-col items-end gap-1 text-right text-[10px] text-nexus-muted">
                      <span>{c.enabled ? "Ativo na config." : "Inativo na config."}</span>
                      <span className="flex items-center gap-1">
                        <StatusDot
                          tone={TEST_STATUS_TONE[c.last_test_status]}
                          label={`Último teste: ${TEST_STATUS_LABEL[c.last_test_status]}`}
                        />
                        Último teste: {TEST_STATUS_LABEL[c.last_test_status]}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
              <a
                href="/mcp"
                className="mt-4 flex min-h-10 items-center justify-center gap-2 rounded-lg border border-nexus-border/60 text-xs font-medium text-[var(--nx-accent-bright)] transition-colors hover:bg-nexus-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
              >
                Gerir conectores <ArrowRight className="h-3 w-3" />
              </a>
            </>
          )}
        </div>
      </Surface>
    </motion.div>
  );
}
