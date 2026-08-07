import type { Config } from "tailwindcss";

/**
 * NEXUS theme.
 *
 * The `nexus-*` scale is kept verbatim — around a hundred files reference it —
 * but each colour is now wired to the CSS custom properties defined in
 * globals.css. That means theme switching happens by swapping variables on
 * :root rather than by re-rendering every component, and the new `nx-*`
 * primitives and the old classes can never drift apart.
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        nexus: {
          bg: "var(--nx-bg)",
          panel: "var(--nx-surface-1)",
          card: "var(--nx-surface-2)",
          elevated: "var(--nx-surface-3)",
          border: "var(--nx-line)",
          "border-strong": "var(--nx-line-strong)",
          accent: "var(--nx-accent)",
          "accent-bright": "var(--nx-accent-bright)",
          "accent-deep": "var(--nx-accent-deep)",
          accent2: "var(--nx-emerald)",
          accent3: "var(--nx-amber)",
          accent4: "var(--nx-rose)",
          cyan: "var(--nx-cyan)",
          muted: "var(--nx-text-dim)",
          faint: "var(--nx-text-faint)",
          text: "var(--nx-text)",
          deep: "var(--nx-void)",
          surface: "var(--nx-surface-2)",
        },
      },
      borderRadius: {
        nx: "var(--nx-radius)",
        "nx-lg": "var(--nx-radius-lg)",
      },
      boxShadow: {
        "nx-1": "var(--nx-shadow-1)",
        "nx-2": "var(--nx-shadow-2)",
        "nx-3": "var(--nx-shadow-3)",
        "nx-accent": "var(--nx-shadow-accent)",
        rim: "inset 0 1px 0 0 var(--nx-rim)",
        "rim-strong": "inset 0 1px 0 0 var(--nx-rim-strong)",
        well: "inset 0 2px 6px rgba(0,0,0,0.55), inset 0 1px 0 rgba(0,0,0,0.6)",
      },
      backdropBlur: {
        xs: "2px",
      },
      transitionTimingFunction: {
        nx: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
      backgroundImage: {
        "nx-sheen":
          "linear-gradient(145deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.012) 34%, transparent 62%)",
        "nx-accent": "linear-gradient(100deg, var(--nx-accent), var(--nx-accent-bright))",
        "nx-mesh":
          "radial-gradient(38rem 30rem at 12% -8%, rgba(124,106,251,0.16), transparent 68%), radial-gradient(34rem 26rem at 92% 4%, rgba(34,211,238,0.09), transparent 66%)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "pulse-subtle": "pulse-subtle 2.2s ease-in-out infinite",
        float: "float 4s ease-in-out infinite",
        shimmer: "shimmer 1.8s linear infinite",
        "slide-up": "slide-up 0.35s ease-out both",
        "glow-pulse": "glow-pulse 2s ease-in-out infinite",
        glow: "glow 2s ease-in-out infinite alternate",
        "aurora-drift": "aurora-drift 34s cubic-bezier(0.65,0,0.35,1) infinite",
        "rim-sweep": "rim-sweep 2.8s cubic-bezier(0.65,0,0.35,1) infinite",
        "radar-ping": "radar-ping 2.4s cubic-bezier(0.65,0,0.35,1) infinite",
        "spin-slow": "spin-slow 8s linear infinite",
        "ticker-in": "ticker-in 0.3s cubic-bezier(0.22,1,0.36,1) both",
      },
      keyframes: {
        "pulse-subtle": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.5" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "glow-pulse": {
          "0%, 100%": { boxShadow: "0 0 5px rgba(124, 106, 251, 0.4)" },
          "50%": { boxShadow: "0 0 20px rgba(124, 106, 251, 0.6)" },
        },
        glow: {
          "0%": { boxShadow: "0 0 5px rgba(167, 139, 250, 0.2)" },
          "100%": { boxShadow: "0 0 20px rgba(167, 139, 250, 0.6)" },
        },
        "aurora-drift": {
          "0%, 100%": { transform: "translate3d(0,0,0) scale(1)" },
          "33%": { transform: "translate3d(3%,-4%,0) scale(1.08)" },
          "66%": { transform: "translate3d(-3%,3%,0) scale(0.95)" },
        },
        "rim-sweep": {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(200%)" },
        },
        "radar-ping": {
          "0%": { transform: "scale(0.7)", opacity: "0.6" },
          "80%, 100%": { transform: "scale(2.2)", opacity: "0" },
        },
        "spin-slow": {
          to: { transform: "rotate(360deg)" },
        },
        "ticker-in": {
          from: { opacity: "0", transform: "translateY(6px) scale(0.98)" },
          to: { opacity: "1", transform: "translateY(0) scale(1)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
