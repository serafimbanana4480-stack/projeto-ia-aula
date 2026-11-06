"use client";

import { useEffect, useState } from "react";
import { useThemeStore } from "../stores/themeStore";

/**
 * Resolved chart colours.
 *
 * Recharts writes these values straight into SVG presentation attributes
 * (`stroke`, `fill`, `<stop stopColor>`). A `var(--nx-*)` reference is not
 * resolved in a presentation attribute, so passing a CSS variable would leave
 * every series at its initial black. Reading the tokens from the document once
 * the theme is applied keeps charts in sync with `globals.css` without
 * hardcoding a second palette that silently drifts out of date.
 */
export interface ChartTokens {
  accent: string;
  accentBright: string;
  cyan: string;
  emerald: string;
  amber: string;
  rose: string;
  surface2: string;
  border: string;
  textFaint: string;
  text: string;
}

const FALLBACK: ChartTokens = {
  accent: "#7c6afb",
  accentBright: "#9b8cff",
  cyan: "#22d3ee",
  emerald: "#34d399",
  amber: "#fbbf24",
  rose: "#fb7185",
  surface2: "#1b1c25",
  border: "rgba(255,255,255,0.07)",
  textFaint: "#9294a8",
  text: "#f0f0f5",
};

const TOKEN_KEYS: Record<keyof ChartTokens, string> = {
  accent: "--nx-accent",
  accentBright: "--nx-accent-bright",
  cyan: "--nx-cyan",
  emerald: "--nx-emerald",
  amber: "--nx-amber",
  rose: "--nx-rose",
  surface2: "--nx-surface-2",
  border: "--nx-line",
  textFaint: "--nx-text-faint",
  text: "--nx-text",
};

function read(): ChartTokens {
  if (typeof window === "undefined") return FALLBACK;
  const style = getComputedStyle(document.documentElement);
  const next = { ...FALLBACK };
  for (const key of Object.keys(TOKEN_KEYS) as (keyof ChartTokens)[]) {
    const value = style.getPropertyValue(TOKEN_KEYS[key]).trim();
    if (value) next[key] = value;
  }
  return next;
}

/**
 * Colour palette for charts, re-read whenever the theme class on `<html>`
 * changes so a light theme does not keep drawing dark-theme series.
 */
export function useChartTokens(): ChartTokens {
  const theme = useThemeStore((s) => s.theme);
  const [tokens, setTokens] = useState<ChartTokens>(FALLBACK);

  useEffect(() => {
    // The class lands on <html> in an effect too, so wait a frame before
    // reading or the previous theme's colours are captured.
    const id = requestAnimationFrame(() => setTokens(read()));
    return () => cancelAnimationFrame(id);
  }, [theme]);

  return tokens;
}

/** Categorical series ramp, derived from the resolved tokens. */
export function chartPalette(t: ChartTokens): string[] {
  return [
    t.accent,
    t.cyan,
    t.emerald,
    t.amber,
    t.accentBright,
    t.rose,
    `color-mix(in srgb, ${t.accent} 55%, ${t.cyan})`,
    `color-mix(in srgb, ${t.rose} 45%, ${t.amber})`,
  ];
}
