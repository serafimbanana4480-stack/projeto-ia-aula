"use client";
import { useState, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  MessageSquare,
  FolderKanban,
  Cpu,
  Database,
  Globe,
  BarChart3,
  FileText,
  HardDrive,
  ChevronRight,
} from "lucide-react";

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  path: string;
}

const navItems: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, path: "/dashboard" },
  { id: "chat", label: "Chat", icon: <MessageSquare className="h-4 w-4" />, path: "/" },
  { id: "projects", label: "Projects", icon: <FolderKanban className="h-4 w-4" />, path: "/projects" },
  { id: "models", label: "Models", icon: <Cpu className="h-4 w-4" />, path: "/models" },
  { id: "database", label: "Database", icon: <Database className="h-4 w-4" />, path: "/database" },
  { id: "scraping", label: "Web Scraping", icon: <Globe className="h-4 w-4" />, path: "/scraping" },
  { id: "analysis", label: "Analysis", icon: <BarChart3 className="h-4 w-4" />, path: "/analysis" },
  { id: "documents", label: "Documents", icon: <FileText className="h-4 w-4" />, path: "/documents" },
];

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [activeItem, setActiveItem] = useState("chat");
  const [expanded, setExpanded] = useState(true);

  // Sync activeItem with current pathname
  useEffect(() => {
    const active = navItems.find((item) => item.path === pathname);
    if (active) {
      setActiveItem(active.id);
    }
  }, [pathname]);

  const handleNav = (item: NavItem) => {
    setActiveItem(item.id);
    router.push(item.path as any);
  };

  return (
    <motion.div
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="flex w-64 flex-col border-r border-nexus-border bg-nexus-panel/50 backdrop-blur-md"
    >
      <div className="flex items-center justify-between p-3">
        <span className="text-xs font-semibold text-gray-400">NAVIGATION</span>
        <button
          onClick={() => setExpanded(!expanded)}
          className="rounded p-1 hover:bg-nexus-border"
        >
          <ChevronRight
            className={`h-4 w-4 text-gray-400 transition-transform ${
              expanded ? "rotate-90" : ""
            }`}
          />
        </button>
      </div>

      <nav className="flex-1 space-y-1 px-2">
        {navItems.map((item, index) => (
          <motion.button
            key={item.id}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.05 }}
            onClick={() => handleNav(item)}
            className={`flex w-full items-center gap-3 rounded px-3 py-2 text-sm transition-colors ${
              activeItem === item.id
                ? "bg-nexus-accent text-black"
                : "text-gray-400 hover:bg-nexus-border hover:text-gray-300"
            }`}
          >
            {item.icon}
            <AnimatePresence>
              {expanded && (
                <motion.span
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: "auto" }}
                  exit={{ opacity: 0, width: 0 }}
                >
                  {item.label}
                </motion.span>
              )}
            </AnimatePresence>
          </motion.button>
        ))}
      </nav>

      <div className="border-t border-nexus-border p-3">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <HardDrive className="h-4 w-4" />
          <span>Storage</span>
          <span className="ml-auto">62%</span>
        </div>
        <div className="mt-1 h-1 rounded-full bg-nexus-border">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: "62%" }}
            transition={{ duration: 1, delay: 0.5 }}
            className="h-full rounded-full bg-nexus-accent"
          />
        </div>
      </div>
    </motion.div>
  );
}
