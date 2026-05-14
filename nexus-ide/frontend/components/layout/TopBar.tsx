"use client";

import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Brain, ChevronDown, BookOpen, Sparkles } from "lucide-react";
import { useProjectStore } from "../../stores/projectStore";

export default function TopBar() {
  const router = useRouter();
  const { currentProject } = useProjectStore();

  return (
    <motion.header
      initial={{ y: -12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="flex h-14 items-center justify-between border-b border-nexus-border bg-nexus-panel px-5"
    >
      {/* Left: Logo + Project selector */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-nexus-accent/15 text-nexus-accent">
            <Brain className="h-5 w-5" />
          </div>
          <span className="text-sm font-bold tracking-wide">LUSO AI</span>
        </div>

        <div className="h-5 w-px bg-nexus-border" />

        <button className="flex items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card px-3 py-1.5 text-xs text-nexus-text hover:border-nexus-accent/30 transition-colors">
          <Sparkles className="h-3.5 w-3.5 text-nexus-accent" />
          <span className="font-medium">
            {currentProject?.name ?? "Real Estate Portugal"}
          </span>
          <ChevronDown className="h-3 w-3 text-nexus-muted" />
        </button>
      </div>

      {/* Right: Costs, Docs, Profile */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card px-3 py-1.5">
          <span className="text-[11px] text-nexus-muted">Custos limit</span>
          <span className="text-xs font-semibold">€2.48</span>
          <span className="rounded bg-green-500/15 px-1 py-0.5 text-[10px] font-medium text-green-400">
            +12%
          </span>
          <ChevronDown className="h-3 w-3 text-nexus-muted" />
        </div>

        <button
          onClick={() => router.push("/documents")}
          className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-3 py-1.5 text-xs text-nexus-muted hover:text-nexus-text transition-colors"
        >
          <BookOpen className="h-3.5 w-3.5" />
          Documentação
        </button>

        <button className="flex items-center gap-2 text-xs">
          <div className="h-7 w-7 overflow-hidden rounded-full bg-nexus-accent/20">
            <img
              src="https://ui-avatars.com/api/?name=Luso&background=7c6afb&color=fff&size=64"
              alt="User"
              className="h-full w-full object-cover"
            />
          </div>
          <div className="text-left leading-tight">
            <div className="font-medium">Luso</div>
            <div className="text-[10px] text-nexus-muted">Admin</div>
          </div>
        </button>
      </div>
    </motion.header>
  );
}
