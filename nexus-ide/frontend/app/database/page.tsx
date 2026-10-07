"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import {
  Database,
  Table2,
  MessageSquare,
  GitBranch,
  Wrench,
  Route,
  Clock,
  AlertCircle,
} from "lucide-react";
import { getDbStats } from "../../lib/api";

interface TableCounts {
  // users and projects carry no owner column, so the backend cannot scope them
  // per tenant and returns null rather than another user's total.
  users: number | null;
  projects: number | null;
  sessions: number;
  messages: number;
  tool_executions: number;
  routing_decisions: number;
  proposed_changes: number;
}

interface MessageStats {
  total_messages: number;
  sessions_with_messages: number;
  user_messages: number;
  assistant_messages: number;
  tokens_in_total: number;
  tokens_out_total: number;
  avg_latency_ms: number;
  last_message_at: string;
}

interface Session {
  id: string;
  title: string;
  mode: string;
  started_at: string;
  last_active_at: string;
}

interface ToolExecution {
  tool_name: string;
  success: number;
  duration_ms: number;
  created_at: string;
}

interface RoutingDecision {
  tier_chosen: string;
  reason: string;
  confidence: number;
  decision_ms: number;
  created_at: string;
}

interface DbStats {
  table_counts: TableCounts;
  message_stats: MessageStats;
  recent_sessions: Session[];
  pending_changes: number;
  recent_tool_executions: ToolExecution[];
  recent_routing_decisions: RoutingDecision[];
}

export default function DatabasePage() {
  const [stats, setStats] = useState<DbStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<
    "overview" | "sessions" | "tools" | "routing"
  >("overview");

  useEffect(() => {
    const loadStats = async () => {
      try {
        const data = await getDbStats();
        setStats(data as unknown as DbStats);
      } catch {
        setError("Não foi possível conectar ao backend");
      } finally {
        setLoading(false);
      }
    };
    loadStats();
  }, []);

  const formatDate = (iso: string) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("pt-PT", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  const tableCards = stats
    ? [
        {
          name: "Users",
          icon: Database,
          count: stats.table_counts.users,
          color: "text-blue-400",
        },
        {
          name: "Projects",
          icon: Table2,
          count: stats.table_counts.projects,
          color: "text-green-400",
        },
        {
          name: "Sessions",
          icon: MessageSquare,
          count: stats.table_counts.sessions,
          color: "text-purple-400",
        },
        {
          name: "Messages",
          icon: MessageSquare,
          count: stats.table_counts.messages,
          color: "text-cyan-400",
        },
        {
          name: "Tool Executions",
          icon: Wrench,
          count: stats.table_counts.tool_executions,
          color: "text-orange-400",
        },
        {
          name: "Routing Decisions",
          icon: Route,
          count: stats.table_counts.routing_decisions,
          color: "text-yellow-400",
        },
        {
          name: "Proposed Changes",
          icon: GitBranch,
          count: stats.table_counts.proposed_changes,
          color: "text-pink-400",
        },
      ]
    : [];

  return (
    <AppShell title="Base de Dados">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="mb-6 flex items-center gap-3">
          <Database className="h-6 w-6 text-nexus-accent" />
          <h1 className="text-2xl font-bold">Database</h1>
        </div>

        {loading && (
          <div className="flex h-64 items-center justify-center text-gray-500">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
            <span className="ml-3">A carregar estatísticas...</span>
          </div>
        )}

        {error && (
          <div className="flex h-64 flex-col items-center justify-center text-gray-500">
            <AlertCircle className="mb-3 h-10 w-10 text-red-400" />
            <p className="text-red-400">{error}</p>
            <p className="mt-1 text-sm text-gray-600">
              Certifique-se que o backend está a correr em localhost:8000
            </p>
          </div>
        )}

        {stats && !loading && (
          <>
            {/* Table overview cards */}
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7">
              {tableCards.map((card) => (
                <motion.div
                  key={card.name}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded border border-nexus-border bg-nexus-panel/50 p-3"
                >
                  <div className="flex items-center gap-2">
                    <card.icon className={`h-4 w-4 ${card.color}`} />
                    <span className="text-xs text-gray-400">
                      {card.name}
                    </span>
                  </div>
                  <div className="mt-2 text-2xl font-bold">
                    {/* Tables with no owner column cannot be scoped per tenant,
                        so the API reports them as null. A dash is honest; 0
                        would be a claim about other people's data. */}
                    {typeof card.count === "number" ? card.count.toLocaleString() : "—"}
                  </div>
                </motion.div>
              ))}
            </div>

            {/* Message stats */}
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="mb-6 rounded border border-nexus-border bg-nexus-panel/50 p-4"
            >
              <h3 className="mb-3 text-sm font-semibold text-gray-300">
                Estatísticas de Mensagens
              </h3>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <div>
                  <div className="text-xs text-gray-500">Total</div>
                  <div className="text-lg font-bold">
                    {stats.message_stats.total_messages.toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">Utilizador</div>
                  <div className="text-lg font-bold text-blue-400">
                    {stats.message_stats.user_messages.toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">Assistente</div>
                  <div className="text-lg font-bold text-green-400">
                    {stats.message_stats.assistant_messages.toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">
                    Latência Média
                  </div>
                  <div className="text-lg font-bold text-yellow-400">
                    {stats.message_stats.avg_latency_ms > 0
                      ? `${Math.round(stats.message_stats.avg_latency_ms)}ms`
                      : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">Tokens In</div>
                  <div className="text-lg font-bold text-cyan-400">
                    {stats.message_stats.tokens_in_total.toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">Tokens Out</div>
                  <div className="text-lg font-bold text-purple-400">
                    {stats.message_stats.tokens_out_total.toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">
                    Sessões c/ Msgs
                  </div>
                  <div className="text-lg font-bold">
                    {
                      stats.message_stats.sessions_with_messages.toLocaleString()
                    }
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">
                    Alterações Pendentes
                  </div>
                  <div className="text-lg font-bold text-orange-400">
                    {stats.pending_changes}
                  </div>
                </div>
              </div>
            </motion.div>

            {/* Tabs */}
            <div className="mb-4 flex gap-1 rounded-lg border border-nexus-border bg-nexus-panel/30 p-1">
              {(
                [
                  { key: "overview", label: "Sessões Recentes" },
                  { key: "tools", label: "Ferramentas" },
                  { key: "routing", label: "Roteamento" },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                    activeTab === tab.key
                      ? "bg-nexus-accent text-black"
                      : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            {activeTab === "overview" && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded border border-nexus-border bg-nexus-panel/50"
              >
                <div className="border-b border-nexus-border px-4 py-2">
                  <h3 className="text-sm font-semibold text-gray-300">
                    Sessões Recentes
                  </h3>
                </div>
                {stats.recent_sessions.length === 0 ? (
                  <div className="p-6 text-center text-sm text-gray-500">
                    Nenhuma sessão encontrada
                  </div>
                ) : (
                  <div className="divide-y divide-nexus-border">
                    {stats.recent_sessions.map((s) => (
                      <div
                        key={s.id}
                        className="flex items-center justify-between px-4 py-2.5"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium">
                            {s.title || "Sem título"}
                          </div>
                          <div className="flex items-center gap-3 text-xs text-gray-500">
                            <span className="rounded bg-nexus-border px-1.5 py-0.5">
                              {s.mode}
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {formatDate(s.last_active_at)}
                            </span>
                          </div>
                        </div>
                        <div className="ml-3 text-xs text-gray-600">
                          {s.id.slice(0, 8)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            )}

            {activeTab === "tools" && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded border border-nexus-border bg-nexus-panel/50"
              >
                <div className="border-b border-nexus-border px-4 py-2">
                  <h3 className="text-sm font-semibold text-gray-300">
                    Execuções de Ferramentas
                  </h3>
                </div>
                {stats.recent_tool_executions.length === 0 ? (
                  <div className="p-6 text-center text-sm text-gray-500">
                    Nenhuma execução registada
                  </div>
                ) : (
                  <div className="divide-y divide-nexus-border">
                    {stats.recent_tool_executions.map((t, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between px-4 py-2.5"
                      >
                        <div className="flex items-center gap-3">
                          <Wrench className="h-3.5 w-3.5 text-orange-400" />
                          <span className="text-sm">{t.tool_name}</span>
                          <span
                            className={`rounded px-1.5 py-0.5 text-xs ${
                              t.success
                                ? "bg-green-500/20 text-green-400"
                                : "bg-red-500/20 text-red-400"
                            }`}
                          >
                            {t.success ? "OK" : "Erro"}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-gray-500">
                          <span>{t.duration_ms}ms</span>
                          <span>{formatDate(t.created_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            )}

            {activeTab === "routing" && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded border border-nexus-border bg-nexus-panel/50"
              >
                <div className="border-b border-nexus-border px-4 py-2">
                  <h3 className="text-sm font-semibold text-gray-300">
                    Decisões de Roteamento
                  </h3>
                </div>
                {stats.recent_routing_decisions.length === 0 ? (
                  <div className="p-6 text-center text-sm text-gray-500">
                    Nenhuma decisão registada
                  </div>
                ) : (
                  <div className="divide-y divide-nexus-border">
                    {stats.recent_routing_decisions.map((r, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between px-4 py-2.5"
                      >
                        <div className="flex items-center gap-3">
                          <Route className="h-3.5 w-3.5 text-yellow-400" />
                          <span className="rounded bg-nexus-border px-1.5 py-0.5 text-xs font-medium">
                            {r.tier_chosen}
                          </span>
                          <span className="max-w-xs truncate text-sm text-gray-400">
                            {r.reason}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-gray-500">
                          <span>
                            {(r.confidence * 100).toFixed(0)}%
                          </span>
                          <span>{r.decision_ms}ms</span>
                          <span>{formatDate(r.created_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            )}
          </>
        )}
      </motion.div>
    </AppShell>
  );
}
