/**
 * Turning the rolling metrics buffer into trends.
 *
 * `metricsStore.history` keeps the last ~100 `SystemMetrics` snapshots, but
 * every consumer was reading only `metrics` — the newest single sample. A bare
 * instantaneous number cannot answer the one question a dashboard exists to
 * answer ("is this getting better or worse?"), so the buffer sat unused while
 * the UI showed static digits.
 *
 * These helpers are pure and cheap: they walk an array of at most 100 items,
 * so they are safe to call on every render behind a `useMemo`.
 */

import type { SystemMetrics } from "../stores/metricsStore";

/** Fraction of the window treated as "recent" when computing a delta. */
const DELTA_SPLIT = 0.5;

/** Below this many samples a delta is noise dressed up as a trend. */
const MIN_SAMPLES_FOR_DELTA = 6;

/**
 * Extract one numeric series from the snapshot buffer.
 *
 * `select` may return `null`/`undefined` for snapshots where the field was not
 * reported; those points are dropped rather than coerced to 0, because a
 * missing sample and a genuine zero mean very different things and plotting
 * them identically produces phantom cliffs in the sparkline.
 */
export function seriesOf(
  history: readonly SystemMetrics[],
  select: (m: SystemMetrics) => number | null | undefined,
  limit = 40,
): number[] {
  const out: number[] = [];
  for (const snapshot of history) {
    const value = select(snapshot);
    if (typeof value === "number" && Number.isFinite(value)) out.push(value);
  }
  return out.length > limit ? out.slice(out.length - limit) : out;
}

/**
 * Fractional change between the older and newer halves of a series.
 *
 * Comparing means of two halves rather than first-vs-last point, because the
 * endpoints of a noisy 1 Hz telemetry stream swing wildly and would report a
 * dramatic "trend" that is really just the last sample being unlucky.
 *
 * Returns `null` when there is not enough data, or when the baseline is zero
 * (any move away from zero is an infinite percentage, which is not useful).
 */
export function deltaOf(series: readonly number[]): number | null {
  if (series.length < MIN_SAMPLES_FOR_DELTA) return null;

  const split = Math.floor(series.length * DELTA_SPLIT);
  const older = series.slice(0, split);
  const newer = series.slice(split);
  if (!older.length || !newer.length) return null;

  const mean = (xs: readonly number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const base = mean(older);
  if (base === 0) return null;

  const change = (mean(newer) - base) / Math.abs(base);
  return Number.isFinite(change) ? change : null;
}

/**
 * Approximate p95 from a sample window.
 *
 * The backend reports only `avg_latency_ms`, and an average hides exactly the
 * tail that users actually feel. Estimating the 95th percentile from the
 * rolling window of averages is not a true p95 — it is the 95th percentile of
 * recent averages — but it surfaces sustained slow periods that the mean
 * flattens away. Labelled "p95 (aprox.)" in the UI so the approximation is not
 * mistaken for an exact figure.
 */
export function approxP95(series: readonly number[]): number | null {
  const clean = series.filter((n) => Number.isFinite(n) && n > 0);
  if (clean.length < 3) return null;
  const sorted = [...clean].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1);
  return sorted[index];
}

/**
 * Share of requests that succeeded, as a 0–1 fraction.
 *
 * Returns `null` rather than 1.0 when nothing has been requested yet: a fresh
 * process showing "100% de sucesso" is a claim about zero events, and reading
 * it as a healthy system is precisely the wrong conclusion.
 */
export function successRate(metrics: SystemMetrics | null): number | null {
  if (!metrics) return null;
  const total = metrics.requests_total ?? 0;
  if (total <= 0) return null;
  return (metrics.requests_successful ?? 0) / total;
}

/** Total tokens moved through the system, in + out. `null` when unreported. */
export function totalTokens(metrics: SystemMetrics | null): number | null {
  const stats = metrics?.message_stats;
  if (!stats) return null;
  const out = stats.tokens_out_total;
  const inbound = stats.tokens_in_total;
  if (out == null && inbound == null) return null;
  return (out ?? 0) + (inbound ?? 0);
}
