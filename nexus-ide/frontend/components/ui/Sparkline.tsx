"use client";

import { useId } from "react";

/**
 * Inline trend line for KPI cards.
 *
 * Hand-rolled SVG rather than a chart library: these render a dozen at a time
 * and need no axes, tooltips or layout pass. A number without a trend does not
 * tell you whether things are getting better or worse, which was the main gap
 * in the old dashboard cards.
 */

export interface SparklineProps {
  /** Oldest value first. Fewer than 2 points renders nothing. */
  data: number[];
  color?: string;
  width?: number;
  height?: number;
  /** Fill the area under the line with a fading gradient. */
  filled?: boolean;
  className?: string;
}

export function Sparkline({
  data,
  color = "#7c6afb",
  width = 120,
  height = 32,
  filled = true,
  className = "",
}: SparklineProps) {
  const gradientId = useId();

  const clean = data.filter((n) => typeof n === "number" && Number.isFinite(n));
  if (clean.length < 2) {
    // Reserve the space so cards do not jump once data arrives.
    return <div style={{ width, height }} className={className} aria-hidden />;
  }

  const min = Math.min(...clean);
  const max = Math.max(...clean);
  // A flat series would divide by zero; draw it through the middle instead.
  const span = max - min || 1;
  const padding = 2;
  const usableHeight = height - padding * 2;

  const points = clean.map((value, index) => {
    const x = (index / (clean.length - 1)) * width;
    const y = padding + usableHeight - ((value - min) / span) * usableHeight;
    return [x, y] as const;
  });

  const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  const [lastX, lastY] = points[points.length - 1];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      role="img"
      aria-label={`Tendência: ${clean.length} pontos, de ${min} a ${max}`}
      preserveAspectRatio="none"
    >
      {filled ? (
        <>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${gradientId})`} />
        </>
      ) : null}
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={lastX} cy={lastY} r={2} fill={color} />
    </svg>
  );
}
