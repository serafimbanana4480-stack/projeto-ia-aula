"use client";

import { motion } from "framer-motion";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  Shield,
  Bug,
  Lock,
  Zap,
  Gauge,
  Palette,
  BookOpen,
} from "lucide-react";
import { useMissionStore, type QualityGate } from "../../stores/missionStore";

const gateMeta: Record<
  string,
  { icon: React.ReactNode; label: string; description: string }
> = {
  tests: {
    icon: <Bug className="h-5 w-5" />,
    label: "Testes",
    description: "≥90% coverage, 0 falhas",
  },
  security: {
    icon: <Lock className="h-5 w-5" />,
    label: "Segurança",
    description: "0 críticas/altas",
  },
  performance: {
    icon: <Zap className="h-5 w-5" />,
    label: "Performance",
    description: "Dentro da baseline",
  },
  complexity: {
    icon: <Gauge className="h-5 w-5" />,
    label: "Complexidade",
    description: "<15 por função",
  },
  style: {
    icon: <Palette className="h-5 w-5" />,
    label: "Estilo",
    description: "0 erros de lint",
  },
  documentation: {
    icon: <BookOpen className="h-5 w-5" />,
    label: "Documentação",
    description: "Completa",
  },
};

function GateCard({ gate, index }: { gate: QualityGate; index: number }) {
  const meta = gateMeta[gate.name] || {
    icon: <Shield className="h-5 w-5" />,
    label: gate.label,
    description: "",
  };

  const statusColors = {
    pass: "border-green-500/30 bg-green-500/5 text-green-400",
    fail: "border-red-500/30 bg-red-500/5 text-red-400",
    warn: "border-yellow-500/30 bg-yellow-500/5 text-yellow-400",
    unknown: "border-gray-500/30 bg-gray-500/5 text-gray-400",
  };

  const StatusIcon =
    gate.status === "pass" ? (
      <ShieldCheck className="h-5 w-5 text-green-400" />
    ) : gate.status === "fail" ? (
      <ShieldX className="h-5 w-5 text-red-400" />
    ) : gate.status === "warn" ? (
      <ShieldAlert className="h-5 w-5 text-yellow-400" />
    ) : (
      <Shield className="h-5 w-5 text-gray-400" />
    );

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: index * 0.05 }}
      className={`flex flex-col items-center justify-center rounded-lg border p-4 text-center ${statusColors[gate.status]}`}
    >
      <div className="mb-2">{StatusIcon}</div>
      <div className="text-sm font-semibold">{meta.label}</div>
      <div className="mt-1 text-lg font-bold">{gate.value}</div>
      {meta.description && (
        <div className="mt-1 text-[10px] opacity-80">{meta.description}</div>
      )}
    </motion.div>
  );
}

export default function QualityGateStatus() {
  const gates = useMissionStore((s) => s.qualityGates);
  const loading = useMissionStore((s) => s.loading);

  return (
    <div className="rounded-lg border border-nexus-border bg-nexus-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-green-400" />
          <span className="text-sm font-semibold">Quality Gates</span>
        </div>
      </div>

      {loading && gates.length === 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-lg bg-nexus-border/20" />
          ))}
        </div>
      ) : gates.length === 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
          {Object.entries(gateMeta).map(([key, meta], idx) => (
            <motion.div
              key={key}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: idx * 0.05 }}
              className="flex flex-col items-center justify-center rounded-lg border border-nexus-border bg-nexus-card p-4 text-center text-gray-400"
            >
              <div className="mb-2">{meta.icon}</div>
              <div className="text-sm font-semibold text-nexus-text">{meta.label}</div>
              <div className="mt-1 text-[10px] text-nexus-muted">{meta.description}</div>
            </motion.div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
          {gates.map((gate, idx) => (
            <GateCard key={gate.name} gate={gate} index={idx} />
          ))}
        </div>
      )}
    </div>
  );
}
