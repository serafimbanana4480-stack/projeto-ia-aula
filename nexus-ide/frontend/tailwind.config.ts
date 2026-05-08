import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        nexus: {
          bg: "#0a0a0f",
          panel: "#12121a",
          border: "#1a1a2e",
          accent: "#a78bfa", // Purple neon
          accent2: "#5eead4", // Cyan neon
          accent3: "#fbbf24", // Amber neon
          accent4: "#f87171", // Red neon
        },
      },
      backdropBlur: {
        xs: "2px",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "glow": "glow 2s ease-in-out infinite alternate",
      },
      keyframes: {
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
