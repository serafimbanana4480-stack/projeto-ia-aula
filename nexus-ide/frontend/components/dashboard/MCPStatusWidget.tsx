"use client";
import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
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
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <Surface elevation={2} padding="md">
        <SurfaceHeader
          icon={<Plug className="h-4 w-4" />}
          title="Conectores MCP"
          subtitle="Servidores externos ligados ao NEXUS"
          action={
            <button
              type="button"
              onClick={() => {
                setLoading(true);
                fetchStatus();
              }}
              aria-label="Atualizar conectores MCP"
              title="Atualizar"
              className="flex h-7 w-7 items-center justify-center rounded-lg text-nexus-faint transition-colors hover:bg-white/[0.06] hover:text-[var(--nx-accent-bright)]"
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
              <div className="nx-inset grid grid-cols-4 gap-1 rounded-lg p-2 text-center">
                <div>
                  <div className={`font-mono text-lg font-bold tabular-nums ${TONE_TEXT.neutral}`}>
                    <AnimatedNumber value={summary.total} />
                  </div>
                  <div className="text-[9px] uppercase tracking-wide text-nexus-faint">Total</div>
                </div>
                <div>
                  <div className={`font-mono text-lg font-bold tabular-nums ${TONE_TEXT.success}`}>
                    <AnimatedNumber value={summary.healthy} />
                  </div>
                  <div className="text-[9px] uppercase tracking-wide text-nexus-faint">Saudáveis</div>
                </div>
                <div>
                  <div className={`font-mono text-lg font-bold tabular-nums ${TONE_TEXT.warning}`}>
                    <AnimatedNumber value={summary.warning} />
                  </div>
                  <div className="text-[9px] uppercase tracking-wide text-nexus-faint">Avisos</div>
                </div>
                <div>
                  <div className={`font-mono text-lg font-bold tabular-nums ${TONE_TEXT.danger}`}>
                    <AnimatedNumber value={summary.error} />
                  </div>
                  <div className="text-[9px] uppercase tracking-wide text-nexus-faint">Erros</div>
                </div>
              </div>

              <div className="mt-3 space-y-1">
                {connectors.slice(0, 3).map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center justify-between gap-2 rounded-lg px-1.5 py-1 text-[11px]"
                  >
                    <span className="truncate text-nexus-text" title={c.name}>
                      {c.name}
                    </span>
                    <StatusDot
                      tone={TEST_STATUS_TONE[c.last_test_status]}
                      label={TEST_STATUS_LABEL[c.last_test_status]}
                    />
                  </div>
                ))}
              </div>
              <a
                href="/mcp"
                className="mt-3 flex items-center gap-1 text-[11px] font-medium text-[var(--nx-accent-bright)] hover:underline"
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
