"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard, Bot, GitBranch, Database, ListChecks,
  BookOpen, Zap, Cpu, Network, Key, MonitorPlay, Eye,
  GraduationCap, Activity, DollarSign, Shield, Terminal,
  Settings, ChevronDown, ChevronRight, Layers, Globe,
  Brain, Gauge, SlidersHorizontal, User,
} from "lucide-react";

type NavSection = {
  label: string;
  items: NavItem[];
};

type NavItem = {
  label: string;
  href: string;
  icon: React.ElementType;
  badge?: string | number;
  children?: NavItem[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Overview",
    items: [
      { label: "Dashboard", href: "/nexus", icon: LayoutDashboard },
      { label: "Agent Monitor", href: "/nexus/agents", icon: Bot },
      { label: "Workflows", href: "/nexus/workflows", icon: GitBranch },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { label: "Task Orchestration", href: "/nexus/tasks", icon: ListChecks },
      { label: "Memory System", href: "/nexus/memory", icon: Brain },
      { label: "Knowledge Base", href: "/nexus/knowledge", icon: BookOpen },
      { label: "RAG System", href: "/nexus/rag", icon: Database },
    ],
  },
  {
    label: "Execution",
    items: [
      { label: "Tool Registry", href: "/nexus/tools", icon: Cpu },
      { label: "Browser Sessions", href: "/nexus/browser", icon: MonitorPlay },
      { label: "Code Executor", href: "/nexus/executor", icon: Terminal },
      { label: "Vision System", href: "/nexus/vision", icon: Eye },
    ],
  },
  {
    label: "Models",
    items: [
      { label: "Model Hub", href: "/nexus/models", icon: Layers },
      { label: "Vector DB", href: "/nexus/vector-db", icon: Network },
      { label: "Training", href: "/nexus/training", icon: GraduationCap },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Monitoring", href: "/nexus/monitoring", icon: Activity },
      { label: "Cost Analytics", href: "/nexus/costs", icon: DollarSign },
      { label: "Security", href: "/nexus/security", icon: Shield },
      { label: "Automations", href: "/nexus/automations", icon: Zap },
    ],
  },
  {
    label: "System",
    items: [
      { label: "Settings", href: "/nexus/settings", icon: Settings },
      { label: "API Control", href: "/nexus/api", icon: SlidersHorizontal },
      { label: "Human in Loop", href: "/nexus/hitl", icon: User },
    ],
  },
];

function NavGroup({ section }: { section: NavSection }) {
  const [open, setOpen] = useState(true);
  const pathname = usePathname();

  return (
    <div className="mb-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-1.5 text-[10px] uppercase tracking-widest text-slate-500 font-bold hover:text-slate-300 transition-colors"
      >
        {section.label}
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="space-y-0.5 pt-1 pb-1">
              {section.items.map(item => {
                const active = pathname === item.href || pathname.startsWith(item.href + "/");
                return (
                  <Link
                    key={item.href}
                    href={item.href as any}
                    className={`nexus-nav-item ${active ? "active" : ""}`}
                  >
                    <item.icon size={14} className={active ? "text-violet-400" : ""} />
                    <span className="flex-1">{item.label}</span>
                    {item.badge && (
                      <span className="nexus-badge">{item.badge}</span>
                    )}
                  </Link>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function NexusSidebar() {
  return (
    <aside className="w-60 shrink-0 flex flex-col border-r border-slate-700/50 bg-[#0a0a25]/95 backdrop-blur-2xl h-full shadow-[4px_0_24px_rgba(0,0,0,0.3)]">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-slate-700/50 bg-gradient-to-b from-slate-800/20 to-transparent">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-600 to-cyan-500 flex items-center justify-center shrink-0 shadow-[0_0_15px_rgba(124,58,237,0.4)] border border-white/10">
            <Brain size={18} className="text-white" />
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-[0.2em] text-cyan-300 font-black leading-none">Nexus Omega</p>
            <p className="text-[10px] text-slate-400 font-bold mt-1 tracking-wider">COMMAND CENTER</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {NAV_SECTIONS.map(section => (
          <NavGroup key={section.label} section={section} />
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-slate-800/60">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_6px_rgba(16,185,129,0.8)]" />
          <span className="text-[11px] text-slate-500">All systems operational</span>
        </div>
        <p className="text-[10px] text-slate-600 mt-1">v2.0 — Autonomous Mode</p>
      </div>
    </aside>
  );
}
