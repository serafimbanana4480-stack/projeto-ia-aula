"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CircleHelp } from "lucide-react";

import { apiUrl } from "../../lib/api";

type ReadinessState = {
  status: "ready" | "not_ready" | "unavailable";
  dependencies: string[];
  diskStatus: string | null;
  writeBlocked: boolean;
  freePercent: number | null;
  freeBytes: number | null;
};

const UNAVAILABLE: ReadinessState = {
  status: "unavailable",
  dependencies: [],
  diskStatus: null,
  writeBlocked: false,
  freePercent: null,
  freeBytes: null,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function parseReadiness(value: unknown): ReadinessState | null {
  if (!isRecord(value) || (value.status !== "ready" && value.status !== "not_ready")) {
    return null;
  }

  const dependencyData = isRecord(value.dependencies) ? value.dependencies : {};
  const dependencies = Object.entries(dependencyData)
    .filter(([, status]) => status !== "ready")
    .map(([name]) => name);
  const disk = isRecord(value.disk_pressure) ? value.disk_pressure : {};
  const snapshot = isRecord(disk.snapshot) ? disk.snapshot : {};
  const freePercent = typeof snapshot.free_percent === "number" && Number.isFinite(snapshot.free_percent)
    ? Math.max(0, Math.min(100, snapshot.free_percent))
    : null;
  const freeSource = typeof snapshot.free_bytes === "number" ? snapshot.free_bytes : disk.free_bytes;
  const freeBytes = typeof freeSource === "number" && Number.isFinite(freeSource) && freeSource >= 0 ? freeSource : null;

  return {
    status: value.status,
    dependencies,
    diskStatus: typeof disk.status === "string" ? disk.status : null,
    writeBlocked: disk.write_blocked === true,
    freePercent,
    freeBytes,
  };
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 1 }).format(value);
}

function formatFree(state: ReadinessState): string {
  const parts: string[] = [];
  if (state.freeBytes !== null) {
    parts.push(`${new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 1 }).format(state.freeBytes / 1024 ** 3)} GB livres`);
  }
  if (state.freePercent !== null) parts.push(`${formatPercent(state.freePercent)}%`);
  if (parts.length === 0) return "";
  return parts.length === 2 ? ` — ${parts[0]} (${parts[1]})` : ` — ${parts[0]}${state.freeBytes === null ? " livre" : ""}`;
}

export default function RuntimeReadinessBanner() {
  const [readiness, setReadiness] = useState<ReadinessState | null>(null);

  useEffect(() => {
    let activeController: AbortController | null = null;
    let mounted = true;

    const refresh = async () => {
      if (activeController && !activeController.signal.aborted) return;
      const controller = new AbortController();
      activeController = controller;
      let timedOut = false;
      const timeout = window.setTimeout(() => {
        timedOut = true;
        controller.abort();
        if (mounted) setReadiness(UNAVAILABLE);
      }, 8_000);

      try {
        const response = await fetch(apiUrl("/api/ready"), {
          method: "GET",
          cache: "no-store",
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (!response.ok) throw new Error("Readiness probe failed");
        const payload: unknown = await response.json();
        if (controller.signal.aborted) return;
        const parsed = parseReadiness(payload);
        if (mounted && parsed) setReadiness(parsed);
        else if (mounted) setReadiness(UNAVAILABLE);
      } catch {
        if (mounted && (!controller.signal.aborted || timedOut)) setReadiness(UNAVAILABLE);
      } finally {
        window.clearTimeout(timeout);
        if (activeController === controller) activeController = null;
      }
    };

    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
      activeController?.abort();
    };
  }, []);

  if (!readiness) return null;

  const critical = readiness.writeBlocked || readiness.diskStatus === "critical";
  const warning = readiness.diskStatus === "warning";
  const failedDependencies = readiness.dependencies.join(", ");

  if (readiness.status === "ready" && !critical && !warning) return null;

  if (readiness.status === "unavailable") {
    return (
      <div
        role="status"
        className="flex items-start gap-2.5 rounded-xl border border-amber-300/20 bg-amber-300/[0.05] px-3.5 py-2.5 text-xs text-amber-100/80"
      >
        <CircleHelp className="mt-0.5 h-4 w-4 shrink-0 text-nexus-accent3" aria-hidden="true" />
        <span>Não foi possível confirmar a prontidão do runtime.</span>
      </div>
    );
  }

  const message = critical
    ? `Armazenamento crítico${formatFree(readiness)}. O runtime está não pronto e o guard de escrita está ativo.`
    : warning
      ? `Pouco espaço no disco${formatFree(readiness)}.`
      : `Runtime não pronto${failedDependencies ? ` — dependências: ${failedDependencies}` : "."}`;

  return (
    <div
      role={critical ? "alert" : "status"}
      className={`flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-xs leading-relaxed ${
        critical
          ? "border-rose-300/25 bg-rose-300/[0.07] text-rose-100/90"
          : "border-amber-300/25 bg-amber-300/[0.07] text-amber-100/90"
      }`}
    >
      <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${critical ? "text-nexus-accent4" : "text-nexus-accent3"}`} aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}
