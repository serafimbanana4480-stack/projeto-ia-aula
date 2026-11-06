"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMediaQuery } from "../../hooks/useMediaQuery";
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
  // Stable ASCII slug: Portuguese labels would otherwise leak accents into ids.
  const sectionId = `nexus-nav-${section.label
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\W+/g, "-")}`;

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
        className="flex min-h-8 w-full items-center justify-between rounded-md px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-nexus-faint transition-colors hover:bg-white/[0.04] hover:text-nexus-text"
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
                className={`flex min-h-9 items-center gap-2.5 rounded-lg border px-3 text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/70 ${
                  active
                    ? "border-nexus-accent/25 bg-nexus-accent/10 font-medium text-nexus-text"
                    : "border-transparent text-nexus-muted hover:bg-white/[0.05] hover:text-nexus-text"
                }`}
              >
                <Icon size={15} className={active ? "text-nexus-accent-bright" : "text-nexus-faint"} aria-hidden="true" />
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
  const isMobile = useMediaQuery("(max-width: 767px)");

  useEffect(() => setMobileOpen(false), [pathname]);
  useEffect(() => {
    if (!mobileOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileOpen]);

  // The drawer is only genuinely hidden below `md`. On desktop it is always
  // visible, so marking it inert/aria-hidden there would remove the whole
  // navigation from the tab order and the accessibility tree.
  const hiddenFromAT = isMobile && !mobileOpen;

  return (
    <>
      <button
        type="button"
        aria-label={mobileOpen ? "Fechar menu" : "Abrir menu"}
        aria-controls="nexus-secondary-navigation"
        aria-expanded={mobileOpen}
        onClick={() => setMobileOpen((open) => !open)}
        className="fixed left-3 top-3 z-50 flex h-8 w-8 items-center justify-center rounded-lg border border-nexus-border bg-nexus-elevated text-nexus-text shadow-md transition-colors hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent md:hidden"
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
        aria-hidden={hiddenFromAT || undefined}
        inert={hiddenFromAT}
        className={`fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-nexus-border bg-nexus-panel/95 shadow-[4px_0_24px_rgba(0,0,0,0.3)] backdrop-blur-2xl transition-transform duration-200 md:relative md:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${mobileOpen ? "pt-12 md:pt-0" : "pt-0"}`}
      >
        <Link
          href="/nexus"
          className="border-b border-nexus-border bg-gradient-to-b from-white/[0.04] to-transparent px-4 py-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
        >
          <span className="flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-nexus-accent shadow-[0_0_15px_rgba(124,106,251,0.25)]">
              <Brain size={18} className="text-white" aria-hidden="true" />
            </span>
            <span>
              <span className="block text-[11px] font-black uppercase leading-none tracking-[0.2em] text-nexus-cyan">NEXUS</span>
              <span className="mt-1 block text-[10px] font-bold tracking-wider text-nexus-faint">Workspace</span>
            </span>
          </span>
        </Link>

        <nav aria-label="Secções" className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
          {NAV_SECTIONS.map((section) => <NavGroup key={section.label} section={section} />)}
        </nav>

        <footer className="border-t border-nexus-border px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-nexus-faint">NEXUS IDE</p>
        </footer>
      </aside>
    </>
  );
}
