"use client";

import { useState, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { motion } from "framer-motion";
import {
  LayoutDashboard,
  MessageSquare,
  FolderKanban,
  Cpu,
  Database,
  Globe,
  BarChart3,
  FileText,
  Settings,
  HardDrive,
  Plus,
  Wrench,
  ChevronRight,
} from "lucide-react";
import { useProjectStore } from "../../stores/projectStore";
import { getProjects } from "../../lib/api";
import { apiUrl } from "../../lib/api";

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  path: string;
}

const navItems: NavItem[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: <LayoutDashboard className="h-4 w-4" />,
    path: "/dashboard",
  },
  {
    id: "chat",
    label: "Chat",
    icon: <MessageSquare className="h-4 w-4" />,
    path: "/",
  },
  {
    id: "projects",
    label: "Projetos",
    icon: <FolderKanban className="h-4 w-4" />,
    path: "/projects",
  },
  {
    id: "tools",
    label: "Ferramentas",
    icon: <Wrench className="h-4 w-4" />,
    path: "/scraping",
  },
  {
    id: "models",
    label: "Modelos IA",
    icon: <Cpu className="h-4 w-4" />,
    path: "/models",
  },
  {
    id: "database",
    label: "Base de Dados",
    icon: <Database className="h-4 w-4" />,
    path: "/database",
  },
  {
    id: "scraping",
    label: "Scraping",
    icon: <Globe className="h-4 w-4" />,
    path: "/scraping",
  },
  {
    id: "analysis",
    label: "Análises",
    icon: <BarChart3 className="h-4 w-4" />,
    path: "/analysis",
  },
  {
    id: "documents",
    label: "Documentos",
    icon: <FileText className="h-4 w-4" />,
    path: "/documents",
  },
  {
    id: "settings",
    label: "Definições",
    icon: <Settings className="h-4 w-4" />,
    path: "/settings",
  },
];

function formatBytes(bytes: number): string {
  if (bytes < 1e6) return `${(bytes / 1e3).toFixed(0)} KB`;
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

interface ProjectData {
  id: string;
  name: string;
  path: string;
  description: string;
  mode: string;
  preferred_model: string;
  trust: boolean;
  created_at: string;
  updated_at: string;
}

interface DiskMetrics {
  disk_percent: number;
  disk_used_bytes: number;
  disk_total_bytes: number;
}

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [activeItem, setActiveItem] = useState("chat");
  const { currentProject, setCurrentProject } = useProjectStore();
  const [recentProjects, setRecentProjects] = useState<ProjectData[]>([]);
  const [diskMetrics, setDiskMetrics] = useState<DiskMetrics | null>(null);

  useEffect(() => {
    const active = navItems.find((item) => item.path === pathname);
    if (active) setActiveItem(active.id);
  }, [pathname]);

  // Fetch real projects from backend
  useEffect(() => {
    const fetchProjects = async () => {
      try {
        const data = await getProjects();
        if (Array.isArray(data) && data.length > 0) {
          setRecentProjects(data.slice(0, 5));
        }
      } catch (error) {
        console.error("Failed to fetch projects:", error);
      }
    };

    fetchProjects();
    const interval = setInterval(fetchProjects, 30000);
    return () => clearInterval(interval);
  }, []);

  // Fetch real disk metrics from backend
  useEffect(() => {
    const fetchDiskMetrics = async () => {
      try {
        const response = await fetch(apiUrl("/api/metrics/current"));
        if (response.ok) {
          const data = await response.json();
          setDiskMetrics({
            disk_percent: data.disk_percent ?? 0,
            disk_used_bytes: data.disk_used_bytes ?? 0,
            disk_total_bytes: data.disk_total_bytes ?? 0,
          });
        }
      } catch (error) {
        // Disk metrics not available
      }
    };

    fetchDiskMetrics();
    const interval = setInterval(fetchDiskMetrics, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleNav = (item: NavItem) => {
    setActiveItem(item.id);
    router.push(item.path as any);
  };

  const formatProjectDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

      if (diffHours < 1) return "agora";
      if (diffHours < 24) return `há ${diffHours}h`;
      if (diffDays < 7) return `há ${diffDays}d`;
      return date.toLocaleDateString();
    } catch {
      return "";
    }
  };

  // Generate colors for projects based on name
  const getProjectColor = (_name: string, index: number) => {
    const colors = ["#7c6afb", "#60a5fa", "#fbbf24", "#5eead4", "#f87171"];
    return colors[index % colors.length];
  };

  return (
    <motion.aside
      initial={{ x: -16, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="flex w-[260px] shrink-0 flex-col border-r border-nexus-border bg-nexus-panel"
    >
      {/* New Project Button */}
      <div className="p-4">
        <button
          onClick={() => router.push("/projects")}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-nexus-accent px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-nexus-accent/20 hover:bg-nexus-accent/90 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Novo Projeto
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-3">
        {navItems.map((item, index) => (
          <motion.button
            key={item.id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.03 }}
            onClick={() => handleNav(item)}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all ${
              activeItem === item.id
                ? "bg-nexus-accent/15 text-nexus-accent font-medium"
                : "text-nexus-muted hover:bg-nexus-card hover:text-nexus-text"
            }`}
          >
            <span className={activeItem === item.id ? "text-nexus-accent" : ""}>
              {item.icon}
            </span>
            <span>{item.label}</span>
          </motion.button>
        ))}
      </nav>

      {/* Recent Projects */}
      <div className="px-4 pb-2">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-nexus-muted">
          Projetos Recentes
        </div>
        <div className="space-y-1">
          {recentProjects.length > 0 ? (
            recentProjects.map((p, index) => (
              <button
                key={p.id}
                onClick={() =>
                  setCurrentProject({
                    id: p.id,
                    name: p.name,
                    path: p.path,
                    description: p.description,
                    mode: p.mode,
                    preferred_model: p.preferred_model,
                    trust: p.trust,
                    created_at: p.created_at,
                    updated_at: p.updated_at,
                  })
                }
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors ${
                  currentProject?.id === p.id
                    ? "bg-nexus-accent/10"
                    : "hover:bg-nexus-card"
                }`}
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: getProjectColor(p.name, index) }}
                />
                <div className="flex-1 overflow-hidden">
                  <div className="truncate text-xs font-medium">{p.name}</div>
                  <div className="text-[10px] text-nexus-muted">
                    Atualizado {formatProjectDate(p.updated_at)}
                  </div>
                </div>
              </button>
            ))
          ) : (
            <div className="px-3 py-2 text-xs text-nexus-muted">
              Nenhum projeto ainda
            </div>
          )}
        </div>
        <button
          onClick={() => router.push("/projects")}
          className="mt-2 flex items-center gap-1 text-[11px] text-nexus-accent hover:underline"
        >
          Ver todos os projetos
          <ChevronRight className="h-3 w-3" />
        </button>
      </div>

      {/* Storage */}
      <div className="border-t border-nexus-border p-4">
        <div className="mb-2 flex items-center justify-between text-xs text-nexus-muted">
          <div className="flex items-center gap-1.5">
            <HardDrive className="h-3.5 w-3.5" />
            Armazenamento
          </div>
          <span className="font-medium text-nexus-text">
            {diskMetrics
              ? `${diskMetrics.disk_percent.toFixed(0)}% usado`
              : "—"}
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-nexus-border">
          <motion.div
            initial={{ width: 0 }}
            animate={{
              width: diskMetrics ? `${diskMetrics.disk_percent}%` : "0%",
            }}
            transition={{ duration: 1, delay: 0.4 }}
            className="h-full rounded-full bg-nexus-accent"
          />
        </div>
        <div className="mt-1 text-[10px] text-nexus-muted">
          {diskMetrics
            ? `${formatBytes(diskMetrics.disk_used_bytes)} / ${formatBytes(diskMetrics.disk_total_bytes)}`
            : "A carregar..."}
        </div>
      </div>
    </motion.aside>
  );
}
