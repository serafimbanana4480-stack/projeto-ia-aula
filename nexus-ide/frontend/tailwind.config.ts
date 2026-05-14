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
        },
      },
      backdropBlur: {
        xs: "2px",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        glow: "glow 2s ease-in-out infinite alternate",
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
