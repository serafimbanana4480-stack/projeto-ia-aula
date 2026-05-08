"use client";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Brain, Settings, Github, User, Moon, Sun } from "lucide-react";
import { useThemeStore } from "../../stores/themeStore";

export default function TopBar() {
  const router = useRouter();
  const { theme, toggleTheme } = useThemeStore();

  return (
    <motion.div
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="flex items-center justify-between border-b border-nexus-border bg-nexus-panel/50 px-4 py-2 backdrop-blur-md"
    >
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <Brain className="h-6 w-6 text-nexus-accent" />
          <span className="text-lg font-bold">NEXUS</span>
          <span className="text-xs text-gray-500">LUSO AI</span>
        </div>
      </div>
      
      <div className="flex items-center gap-4">
        <button 
          onClick={() => router.push("/projects")}
          className="rounded bg-nexus-border px-3 py-1 text-xs hover:bg-nexus-border/50"
        >
          Projects
        </button>
        <button className="rounded bg-nexus-border px-3 py-1 text-xs hover:bg-nexus-border/50">
          Docs
        </button>
        <div className="h-4 w-px bg-nexus-border" />
        <button
          onClick={toggleTheme}
          className="cursor-pointer hover:text-gray-300"
          title="Toggle theme"
        >
          {theme === "dark" ? <Sun className="h-4 w-4 text-gray-400" /> : <Moon className="h-4 w-4 text-gray-400" />}
        </button>
        <a 
          href="https://github.com" 
          target="_blank" 
          rel="noopener noreferrer"
          className="cursor-pointer hover:text-gray-300"
        >
          <Github className="h-4 w-4 text-gray-400" />
        </a>
        <button 
          onClick={() => router.push("/settings")}
          className="cursor-pointer hover:text-gray-300"
        >
          <Settings className="h-4 w-4 text-gray-400" />
        </button>
        <User className="h-4 w-4 text-gray-400" />
      </div>
    </motion.div>
  );
}
