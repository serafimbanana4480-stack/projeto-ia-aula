"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BookOpen,
  Brain,
  ChevronDown,
  ChevronRight,
  Cpu,
  FileCode2,
  LayoutDashboard,
  ListChecks,
  Menu,
  Search,
  Settings,
  ShieldCheck,
  Wrench,
  X,
} from "lucide-react";

type KnownRoute =
  | "/nexus"
  | "/nexus/hitl"
  | "/dashboard/tasks"
  | "/documents"
  | "/search"
  | "/editor"
  | "/tools"
  | "/models"
  | "/analytics"
  | "/settings";

type NavItem = {
  label: string;
  href: KnownRoute;
  icon: React.ElementType;
};

type NavSection = {
  label: string;
  items: NavItem[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Visão geral",
    items: [
      { label: "Dashboard", href: "/nexus", icon: LayoutDashboard },
      { label: "Tarefas", href: "/dashboard/tasks", icon: ListChecks },
      { label: "Aprovações", href: "/nexus/hitl", icon: ShieldCheck },
    ],
  },
  {
    label: "Trabalho",
    items: [
      { label: "Documentos", href: "/documents", icon: BookOpen },
      { label: "Pesquisa", href: "/search", icon: Search },
      { label: "Editor", href: "/editor", icon: FileCode2 },
    ],
  },
  {
    label: "Recursos",
    items: [
      { label: "Ferramentas", href: "/tools", icon: Wrench },
      { label: "Modelos", href: "/models", icon: Cpu },
      { label: "Métricas", href: "/analytics", icon: Activity },
    ],
  },
  {
    label: "Conta",
    items: [
      { label: "Definições", href: "/settings", icon: Settings },
    ],
  },
];

function isActiveRoute(pathname: string, href: string): boolean {
  if (href === "/nexus") return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavGroup({ section }: { section: NavSection }) {
  const pathname = usePathname();
  const activeInSection = section.items.some((item) => isActiveRoute(pathname, item.href));
  const [open, setOpen] = useState(true);
  const sectionId = `nexus-nav-${section.label.toLowerCase().replaceAll(" ", "-")}`;

  useEffect(() => {
    if (activeInSection) setOpen(true);
  }, [activeInSection]);

  return (
    <section className="mb-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={sectionId}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-8 w-full items-center justify-between rounded-md px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500 transition-colors hover:bg-white/[0.04] hover:text-slate-300"
      >
        {section.label}
        {open ? <ChevronDown size={12} aria-hidden="true" /> : <ChevronRight size={12} aria-hidden="true" />}
      </button>
      {open && (
        <nav id={sectionId} aria-label={section.label} className="space-y-0.5 pt-1">
          {section.items.map((item) => {
            const active = isActiveRoute(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-9 items-center gap-2.5 rounded-lg px-3 text-[13px] transition-colors ${
                  active
                    ? "border border-violet-400/25 bg-violet-500/10 font-medium text-slate-100"
                    : "border border-transparent text-slate-400 hover:bg-white/[0.05] hover:text-slate-100"
                }`}
              >
                <Icon size={15} className={active ? "text-violet-300" : "text-slate-500"} aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      )}
    </section>
  );
}

export default function NexusSidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => setMobileOpen(false), [pathname]);
  useEffect(() => {
    if (!mobileOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileOpen]);

  const hiddenOnMobile = !mobileOpen;

  return (
    <>
      <button
        type="button"
        aria-label={mobileOpen ? "Fechar menu" : "Abrir menu"}
        aria-controls="nexus-secondary-navigation"
        aria-expanded={mobileOpen}
        onClick={() => setMobileOpen((open) => !open)}
        className="fixed left-3 top-3 z-50 flex h-8 w-8 items-center justify-center rounded-lg border border-slate-700 bg-[#10102b] text-slate-200 shadow-md md:hidden"
      >
        {mobileOpen ? <X size={16} aria-hidden="true" /> : <Menu size={16} aria-hidden="true" />}
      </button>
      {mobileOpen && (
        <div
          aria-hidden="true"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/55 md:hidden"
        />
      )}
      <aside
        id="nexus-secondary-navigation"
        aria-label="Navegação NEXUS"
        aria-hidden={hiddenOnMobile || undefined}
        inert={hiddenOnMobile}
        className={`fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-slate-700/50 bg-[#0a0a25]/95 shadow-[4px_0_24px_rgba(0,0,0,0.3)] backdrop-blur-2xl transition-transform duration-200 md:relative md:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${mobileOpen ? "pt-12 md:pt-0" : "pt-0"}`}
      >
        <Link
          href="/nexus"
          className="border-b border-slate-700/50 bg-gradient-to-b from-slate-800/20 to-transparent px-4 py-5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400"
        >
          <span className="flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-violet-600 to-cyan-500 shadow-[0_0_15px_rgba(124,58,237,0.25)]">
              <Brain size={18} className="text-white" aria-hidden="true" />
            </span>
            <span>
              <span className="block text-[11px] font-black uppercase leading-none tracking-[0.2em] text-cyan-300">NEXUS</span>
              <span className="mt-1 block text-[10px] font-bold tracking-wider text-slate-400">Workspace</span>
            </span>
          </span>
        </Link>

        <nav aria-label="Secções" className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
          {NAV_SECTIONS.map((section) => <NavGroup key={section.label} section={section} />)}
        </nav>

        <footer className="border-t border-slate-800/60 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">NEXUS IDE</p>
        </footer>
      </aside>
    </>
  );
}
