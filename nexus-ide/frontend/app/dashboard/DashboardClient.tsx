"use client";
import { useEffect, useMemo, useState } from "react";
import { useMetricsStore, initMetricsStream } from "../../stores/metricsStore";
import { useModeStore } from "../../stores/modeStore";
import { 
  Sparkles, 
  Activity, 
  Cpu, 
  HardDrive, 
  Users, 
  Command, 
  CheckCircle2, 
  Play, 
  Clock,
  ExternalLink
} from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";

const MODE_COLORS: Record<string, string> = {
  auto: "from-violet-500/10 via-fuchsia-500/5 to-transparent border-violet-500/20",
  agent: "from-blue-500/10 via-cyan-500/5 to-transparent border-blue-500/20",
  swarm: "from-fuchsia-500/10 via-pink-500/5 to-transparent border-fuchsia-500/20",
};

export default function DashboardClient() {
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const connectionStatus = useMetricsStore((s) => s.connectionStatus);
  const lastUpdate = useMetricsStore((s) => s.lastUpdate);
  
  const { currentMode, setMode, modes, loadModes } = useModeStore();
  const [promptInput, setPromptInput] = useState("");

  useEffect(() => {
    initMetricsStream();
    loadModes();
  }, [loadModes]);

  const formatUptime = useMemo(() => {
    return (seconds: number): string => {
      if (seconds < 60) return `${Math.floor(seconds)}s`;
      if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
      if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
      return `${(seconds / 86400).toFixed(1)}d`;
    };
  }, []);

  const m = metrics;
  const statusLabel =
    connectionStatus === "degraded"
      ? "Degradado"
      : backendOnline
        ? "Ligado"
        : connectionStatus === "connecting"
          ? "A Ligar"
          : "Offline";

  const statusDotClass =
    connectionStatus === "degraded"
      ? "bg-yellow-500 animate-pulse"
      : backendOnline
        ? "bg-emerald-500"
        : connectionStatus === "connecting"
          ? "bg-yellow-500 animate-pulse"
          : "bg-red-500 animate-pulse";

  // Filter modes to match the prominent ones (auto, agent/coder, swarm)
  const mainModes = useMemo(() => {
    return modes.filter(mode => ["auto", "coder", "swarm"].includes(mode.id));
  }, [modes]);

  return (
    <main className="flex-1 overflow-auto bg-[#08080f] text-[#e8e8ed] font-sans selection:bg-nexus-accent/30">
      
      {/* HEADER / TOP HERO */}
      <div className="relative overflow-hidden border-b border-nexus-border/60 bg-gradient-to-b from-[#12121e]/80 to-transparent px-8 py-10">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(124,106,251,0.08),transparent_50%)]" />
        
        <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="flex h-2 w-2 rounded-full bg-nexus-accent animate-pulse" />
              <span className="text-xs font-semibold uppercase tracking-wider text-nexus-accent">Antigravity Suite</span>
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-white via-[#e8e8ed] to-nexus-muted bg-clip-text text-transparent">
              Agentic Hub
            </h1>
            <p className="text-sm text-nexus-muted max-w-xl">
              Monitore a saúde do sistema, orchestre múltiplos agentes em Swarm e execute prompts de forma inteligente em tempo real.
            </p>
          </div>

          {/* Quick Stats Panel */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-xl border border-nexus-border bg-[#13131f]/60 px-4 py-2.5 backdrop-blur-md">
              <div className="text-[10px] uppercase tracking-wider text-nexus-muted">Estado do Sistema</div>
              <div className="flex items-center gap-2 mt-1">
                <span className={`h-2 w-2 rounded-full ${statusDotClass}`} />
                <span className="text-sm font-semibold">{statusLabel}</span>
              </div>
            </div>
            <div className="rounded-xl border border-nexus-border bg-[#13131f]/60 px-4 py-2.5 backdrop-blur-md">
              <div className="text-[10px] uppercase tracking-wider text-nexus-muted">Modelo Ativo</div>
              <div className="text-sm font-mono font-semibold text-nexus-accent mt-1">{m?.active_model || "Nenhum"}</div>
            </div>
            <div className="rounded-xl border border-nexus-border bg-[#13131f]/60 px-4 py-2.5 backdrop-blur-md">
              <div className="text-[10px] uppercase tracking-wider text-nexus-muted">Velocidade</div>
              <div className="text-sm font-semibold mt-1 font-mono">{m?.tokens_per_second?.toFixed(1) ?? "0.0"} T/s</div>
            </div>
          </div>
        </div>
      </div>

      <div className="p-8 space-y-8 max-w-7xl mx-auto">
        
        {/* COMPOSER / PROMPT BAR (Style Cursor 3) */}
        <motion.div 
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl border border-nexus-accent/20 bg-gradient-to-r from-[#12121e] to-[#161622] p-6 shadow-2xl shadow-nexus-accent/5"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-nexus-accent/15 text-nexus-accent">
                <Command className="h-4 w-4" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Comando de Ideias do Agente</h3>
                <p className="text-[10px] text-nexus-muted">Envie objetivos diretamente para os agentes ativos ou Swarm</p>
              </div>
            </div>
            <span className="rounded-full bg-nexus-accent/10 px-2.5 py-0.5 text-[10px] font-semibold text-nexus-accent uppercase tracking-wider">
              Modo {currentMode}
            </span>
          </div>

          <div className="relative">
            <input
              type="text"
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              placeholder="Digite uma ideia, ex: 'Criar um scraper de imobiliário...' ou '/swarm Criar análise de mercado'"
              className="w-full rounded-xl border border-nexus-border bg-[#0b0b14]/80 px-4 py-3.5 pr-24 text-sm text-white placeholder-nexus-muted outline-none transition-all focus:border-nexus-accent/50 focus:ring-1 focus:ring-nexus-accent/30"
            />
            <div className="absolute right-2 top-2 flex items-center gap-1.5">
              <Link 
                href={currentMode === "swarm" ? "/swarm" : "/"}
                className="flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-nexus-accent/90 transition-all shadow-md shadow-nexus-accent/20"
              >
                <span>Executar</span>
                <Play className="h-3 w-3" />
              </Link>
            </div>
          </div>

          <div className="mt-3 flex items-center gap-2 text-xs text-nexus-muted">
            <span className="font-semibold text-nexus-accent">Sugestões:</span>
            <span className="hover:text-white cursor-pointer transition-colors" onClick={() => setPromptInput("Análise profunda do repositório")}>Análise profunda</span>
            <span>•</span>
            <span className="hover:text-white cursor-pointer transition-colors" onClick={() => setPromptInput("Validar segurança dos endpoints")}>Validar segurança</span>
            <span>•</span>
            <span className="hover:text-white cursor-pointer transition-colors" onClick={() => setPromptInput("Configurar Swarm automático")}>Configurar Swarm</span>
          </div>
        </motion.div>

        {/* METRICS & RUNTIME STATUS GRID */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          
          {/* CPU Card */}
          <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5 hover:border-nexus-accent/30 transition-all">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-nexus-muted">Processador</span>
              <Cpu className="h-4 w-4 text-[#60a5fa]" />
            </div>
            <div className="text-2xl font-bold">{m?.cpu_percent != null ? `${m.cpu_percent.toFixed(1)}%` : "—"}</div>
            <div className="mt-3 h-1.5 w-full rounded-full bg-nexus-border/50 overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-blue-500 to-cyan-400 rounded-full transition-all duration-500" 
                style={{ width: m?.cpu_percent != null ? `${m.cpu_percent}%` : "0%" }}
              />
            </div>
          </div>

          {/* RAM Card */}
          <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5 hover:border-nexus-accent/30 transition-all">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-nexus-muted">Memória RAM</span>
              <Activity className="h-4 w-4 text-[#a78bfa]" />
            </div>
            <div className="text-2xl font-bold">{m?.ram_percent != null ? `${m.ram_percent.toFixed(1)}%` : "—"}</div>
            <div className="mt-3 h-1.5 w-full rounded-full bg-nexus-border/50 overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-violet-500 to-purple-400 rounded-full transition-all duration-500" 
                style={{ width: m?.ram_percent != null ? `${m.ram_percent}%` : "0%" }}
              />
            </div>
          </div>

          {/* Disk Card */}
          <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-5 hover:border-nexus-accent/30 transition-all">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-nexus-muted">Armazenamento</span>
              <HardDrive className="h-4 w-4 text-[#5eead4]" />
            </div>
            <div className="text-2xl font-bold">{m?.disk_percent != null ? `${m.disk_percent.toFixed(1)}%` : "—"}</div>
            <div className="mt-3 h-1.5 w-full rounded-full bg-nexus-border/50 overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-emerald-400 to-teal-300 rounded-full transition-all duration-500" 
                style={{ width: m?.disk_percent != null ? `${m.disk_percent}%` : "0%" }}
              />
            </div>
          </div>

        </div>

        {/* SWARM & MODES ORCHESTRATION */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Swarm State / Activity */}
          <div className="lg:col-span-2 rounded-xl border border-nexus-border bg-[#13131f]/40 p-6 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-fuchsia-500/10 text-fuchsia-400">
                    <Users className="h-4 w-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white">Status do SWARM Auto</h3>
                    <p className="text-[10px] text-nexus-muted">Orquestração Multi-Agente inteligente</p>
                  </div>
                </div>
                <Link href="/swarm" className="flex items-center gap-1 text-xs text-nexus-accent hover:underline">
                  Ver Painel Swarm
                  <ExternalLink className="h-3 w-3" />
                </Link>
              </div>

              <div className="grid grid-cols-3 gap-4 mb-6">
                <div className="bg-[#0b0b14]/50 border border-nexus-border/40 p-3 rounded-lg">
                  <div className="text-[10px] text-nexus-muted">Agentes Conectados</div>
                  <div className="text-lg font-mono font-bold text-white mt-1">8 Agentes</div>
                </div>
                <div className="bg-[#0b0b14]/50 border border-nexus-border/40 p-3 rounded-lg">
                  <div className="text-[10px] text-nexus-muted">Memória de Curto Prazo</div>
                  <div className="text-lg font-mono font-bold text-white mt-1">RAG FAISS</div>
                </div>
                <div className="bg-[#0b0b14]/50 border border-nexus-border/40 p-3 rounded-lg">
                  <div className="text-[10px] text-nexus-muted">Status do Pipeline</div>
                  <div className="text-lg font-mono font-bold text-emerald-400 mt-1">Pronto</div>
                </div>
              </div>

              {/* Mini timeline / activity of Swarm */}
              <div className="space-y-2">
                <div className="text-[10px] uppercase tracking-wider text-nexus-muted mb-2 font-semibold">Mensagens Recentes do Swarm</div>
                <div className="flex items-start gap-2.5 text-xs text-nexus-muted bg-[#0b0b14]/20 border border-nexus-border/40 p-2.5 rounded-lg">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 mt-1 shrink-0" />
                  <div>
                    <span className="font-semibold text-white">CODER</span> compilou a proposta com sucesso e executou os testes locais.
                  </div>
                </div>
                <div className="flex items-start gap-2.5 text-xs text-nexus-muted bg-[#0b0b14]/20 border border-nexus-border/40 p-2.5 rounded-lg">
                  <span className="h-2 w-2 rounded-full bg-violet-400 mt-1 shrink-0" />
                  <div>
                    <span className="font-semibold text-white">ARCHITECT</span> refinou os requisitos técnicos e as dependências da aplicação.
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-nexus-border/40 flex items-center justify-between text-xs text-nexus-muted">
              <span className="flex items-center gap-1">
                <Clock className="h-3.5 w-3.5 text-nexus-accent" />
                Uptime: {m ? formatUptime(m.uptime_seconds) : "—"}
              </span>
              <span>Updated {lastUpdate || "recently"}</span>
            </div>
          </div>

          {/* Mode Selector Panel */}
          <div className="rounded-xl border border-nexus-border bg-[#13131f]/40 p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/10 text-violet-400">
                <Sparkles className="h-4 w-4" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Modos Rápidos</h3>
                <p className="text-[10px] text-nexus-muted">Escolha a estratégia do seu agente</p>
              </div>
            </div>

            <div className="space-y-3">
              {mainModes.map((mode) => {
                const isActive = mode.id === currentMode;
                const gradient = MODE_COLORS[mode.id] || "from-nexus-accent/10 to-transparent border-nexus-border";
                return (
                  <button
                    key={mode.id}
                    onClick={() => setMode(mode.id)}
                    className={`relative w-full rounded-xl border bg-gradient-to-br p-3.5 text-left transition-all duration-300 hover:border-nexus-accent/50 ${
                      isActive
                        ? `${gradient} border-nexus-accent ring-1 ring-nexus-accent/40`
                        : "border-nexus-border bg-[#0b0b14]/20 hover:bg-[#13131f]/50"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold uppercase tracking-wider text-white font-mono">
                        {mode.id}
                      </span>
                      {isActive && (
                        <CheckCircle2 className="h-4 w-4 text-nexus-accent" />
                      )}
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-nexus-muted">
                      {mode.description}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>

        </div>

      </div>

    </main>
  );
}
