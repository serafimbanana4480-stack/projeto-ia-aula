/**
 * Shared display formatters.
 *
 * These lived inline in RightPanel, DashboardClient and several widgets, each
 * with its own idea of what an unknown value looks like ("—", "não reportado",
 * "Não reportado", "0.0"). One implementation keeps empty states consistent.
 */

/** Rendered whenever a value is genuinely unknown. Never invent a zero. */
export const EMPTY = "—";

/** 1234 → "1.2K", 1_500_000 → "1.5M". */
export function formatCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return EMPTY;
  if (Math.abs(value) >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString("pt-PT");
}

/** Context windows read better in K/M than as raw digits. */
export function formatContext(tokens: number | null | undefined): string {
  if (!tokens) return EMPTY;
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000;
    return `${millions % 1 === 0 ? millions : millions.toFixed(1)}M`;
  }
  return `${Math.round(tokens / 1_000)}K`;
}

/** Milliseconds → "820 ms" / "2.4 s". */
export function formatLatency(ms: number | null | undefined): string {
  if (ms == null || ms <= 0 || Number.isNaN(ms)) return EMPTY;
  if (ms < 1_000) return `${Math.round(ms)} ms`;
  return `${(ms / 1_000).toFixed(2)} s`;
}

/** USD with enough precision to stay honest about sub-cent amounts. */
export function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return EMPTY;
  if (value === 0) return "$0";
  if (Math.abs(value) < 0.01) return `$${value.toFixed(4)}`;
  if (Math.abs(value) < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

/** Per-1M-token price as shown in the model selector. */
export function formatPricePer1M(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return EMPTY;
  if (value === 0) return "grátis";
  if (value < 1) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(2)}`;
}

/** Seconds → "45s" / "12m 30s" / "3.4h" / "2.1d". */
export function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0 || Number.isNaN(seconds)) return EMPTY;
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3_600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  if (seconds < 86_400) return `${(seconds / 3_600).toFixed(1)}h`;
  return `${(seconds / 86_400).toFixed(1)}d`;
}

/** 0.87 → "87%". Pass `alreadyPercent` for values already on a 0–100 scale. */
export function formatPercent(
  value: number | null | undefined,
  { alreadyPercent = false, digits = 1 } = {},
): string {
  if (value == null || Number.isNaN(value)) return EMPTY;
  const percent = alreadyPercent ? value : value * 100;
  return `${percent.toFixed(digits)}%`;
}

/** Relative time for "updated 2m ago" labels. */
export function formatRelativeTime(timestamp: number | null | undefined): string {
  if (!timestamp) return EMPTY;
  // Accept both seconds and milliseconds since the epoch.
  const ms = timestamp < 1e12 ? timestamp * 1_000 : timestamp;
  const delta = Date.now() - ms;
  if (delta < 0 || Number.isNaN(delta)) return EMPTY;
  if (delta < 10_000) return "agora";
  if (delta < 60_000) return `${Math.floor(delta / 1_000)}s atrás`;
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m atrás`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h atrás`;
  return `${Math.floor(delta / 86_400_000)}d atrás`;
}

/** Bytes → "4.4 GB". */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || bytes <= 0 || Number.isNaN(bytes)) return EMPTY;
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const scaled = bytes / 1024 ** exponent;
  return `${scaled.toFixed(scaled < 10 && exponent > 0 ? 1 : 0)} ${units[exponent]}`;
}
