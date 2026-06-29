import type { Config } from "tailwindcss";

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
          bg: "#0b0b14",
          panel: "#13131f",
          card: "#161622",
          border: "#1e1e2d",
          accent: "#7c6afb",
          accent2: "#5eead4",
          accent3: "#fbbf24",
          accent4: "#f87171",
          muted: "#8a8a9a",
          text: "#e8e8ed",
          deep: "#08080f",
          surface: "#12121e",
        },
      },
      backdropBlur: {
        xs: "2px",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "pulse-subtle": "pulse-subtle 2.2s ease-in-out infinite",
        float: "float 4s ease-in-out infinite",
        shimmer: "shimmer 1.8s linear infinite",
        "slide-up": "slide-up 0.35s ease-out both",
        "glow-pulse": "glow-pulse 2s ease-in-out infinite",
        glow: "glow 2s ease-in-out infinite alternate",
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
      },
    },
  },
  plugins: [],
};

export default config;
