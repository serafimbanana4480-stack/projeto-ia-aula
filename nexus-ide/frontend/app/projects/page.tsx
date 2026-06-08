"use client";
import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { createProject, getProjects } from "../../lib/api";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import { FolderKanban, Plus, Settings, Trash2, Clock, FolderOpen } from "lucide-react";
import type { ProjectData } from "../../lib/mock-data";
import { useProjectStore } from "../../stores/projectStore";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectData[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({
    name: "",
    path: "",
    description: "",
    mode: "auto",
    preferred_model: "",
    trust: false,
  });
  const pathInputRef = useRef<HTMLInputElement>(null);
  const { setCurrentProject } = useProjectStore();

  async function loadProjects() {
    try {
      setLoading(true);
      const data = await getProjects();
      if (Array.isArray(data)) {
        setProjects(data);
      }
    } catch {
      // Backend unavailable — show empty state
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProjects();
  }, []);

  async function handleCreateProject() {
    try {
      const result = await createProject(form);
      if (result && typeof result === "object" && "project" in result) {
        setShowCreateModal(false);
        setForm({ name: "", path: "", description: "", mode: "auto", preferred_model: "", trust: false });
        await loadProjects();
        return;
      }
    } catch {
      // Backend unavailable — create locally
    }
    // Fallback: create project locally
    const localProject: ProjectData = {
      id: `local-${Date.now()}`,
      name: form.name || "Untitled",
      path: form.path || "/unknown",
      description: form.description,
      mode: form.mode,
      preferred_model: form.preferred_model,
      trust: form.trust,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    setProjects((prev) => [localProject, ...prev]);
    setShowCreateModal(false);
    setForm({ name: "", path: "", description: "", mode: "auto", preferred_model: "", trust: false });
  }

  function handleOpenProject(project: ProjectData) {
    setCurrentProject(project);
  }

  function handleBrowseFolder() {
    // Use the native File System Access API if available (Chromium browsers)
    if ("showDirectoryPicker" in window) {
      (window as unknown as { showDirectoryPicker: () => Promise<FileSystemDirectoryHandle> }).showDirectoryPicker()
        .then(async (dirHandle: FileSystemDirectoryHandle) => {
          // Try to get the full path using File System Access API
          let fullPath = dirHandle.name;
          try {
            // Request permission to read the directory
            const permission = await (dirHandle as FileSystemDirectoryHandle & { requestPermission: (opts: { mode: string }) => Promise<string> }).requestPermission({ mode: "read" });
            if (permission === "granted") {
              // We can't get the absolute path from File System Access API
              // So we use the fallback prompt to ask the user
              const userPath = prompt(
                `Caminho absoluto para a pasta "${dirHandle.name}":`,
                `C:/Users/rodri/Desktop/${dirHandle.name}`
              );
              if (userPath) {
                fullPath = userPath.trim();
              }
            }
          } catch {
            // Permission denied — use name only
          }
          setForm((prev) => ({
            ...prev,
            path: fullPath,
            name: prev.name || dirHandle.name,
          }));
        })
        .catch(() => {
          // User cancelled or not supported — fallback to prompt
          const path = prompt("Caminho absoluto da pasta do projeto:", "C:/Users/rodri/Desktop/");
          if (path) {
            setForm((prev) => ({
              ...prev,
              path: path.trim(),
              name: prev.name || path.split(/[/\\]/).pop() || "Project",
            }));
          }
        });
    } else {
      // Fallback: prompt the user to type the path
      const path = prompt("Caminho absoluto da pasta do projeto:", "C:/Users/rodri/Desktop/");
      if (path) {
        setForm((prev) => ({
          ...prev,
          path: path.trim(),
          name: prev.name || path.split(/[/\\]/).pop() || "Project",
        }));
      }
    }
  }

  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        <main className="flex-1 overflow-auto p-6">
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
            <div className="mb-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <FolderKanban className="h-6 w-6 text-nexus-accent" />
                <h1 className="text-2xl font-bold">Projects</h1>
  
              </div>
              <button
                onClick={() => setShowCreateModal(true)}
                className="flex items-center gap-2 rounded bg-nexus-accent px-4 py-2 text-sm font-medium text-black hover:bg-nexus-accent/80"
              >
                <Plus className="h-4 w-4" />
                New Project
              </button>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {projects.map((project, index) => (
                <motion.div
                  key={project.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  onClick={() => handleOpenProject(project)}
                  className="cursor-pointer rounded border border-nexus-border bg-nexus-panel/50 p-4 hover:border-nexus-accent/50 transition-colors"
                >
                  <div className="mb-3 flex items-start justify-between">
                    <div className="min-w-0 flex-1">
                      <h3 className="text-sm font-semibold truncate">{project.name}</h3>
                      <p className="text-xs text-gray-500 font-mono truncate">{project.path}</p>
                    </div>
                    <div className="flex gap-1 ml-2 shrink-0">
                      <button
                        onClick={(e) => { e.stopPropagation(); }}
                        className="rounded p-1 text-gray-400 hover:bg-nexus-border hover:text-gray-300"
                      >
                        <Settings className="h-3 w-3" />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); }}
                        className="rounded p-1 text-gray-400 hover:bg-red-500/20 hover:text-red-400"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>

                  {project.description && (
                    <p className="mb-3 text-xs text-gray-400 line-clamp-2">
                      {project.description}
                    </p>
                  )}

                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      <span>{new Date(project.updated_at).toLocaleDateString()}</span>
                    </div>
                    <div className="rounded bg-nexus-border px-2 py-0.5">
                      {project.mode}
                    </div>
                    {project.preferred_model && (
                      <div className="rounded bg-nexus-accent/10 px-2 py-0.5 text-nexus-accent">
                        {project.preferred_model}
                      </div>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>

            {loading && (
              <div className="flex h-64 items-center justify-center">
                <div className="flex items-center gap-3 text-sm text-nexus-muted">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
                  <span>Loading projects...</span>
                </div>
              </div>
            )}
            {!loading && projects.length === 0 && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex h-64 items-center justify-center text-gray-500"
              >
                <div className="text-center">
                  <FolderKanban className="mx-auto mb-3 h-12 w-12 text-nexus-border" />
                  <p className="text-sm">No projects yet</p>
                  <p className="text-xs">Create your first project to get started</p>
                </div>
              </motion.div>
            )}
          </motion.div>
        </main>
      </div>

      <BottomHUD />

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-lg rounded border border-nexus-border bg-nexus-panel p-5"
          >
            <h2 className="mb-4 text-lg font-semibold">Create Project</h2>
            <div className="space-y-3">
              <input
                value={form.name}
                onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="Project name (auto-filled from folder)"
                className="w-full rounded bg-nexus-border px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-nexus-accent"
              />

              {/* Path input with Browse button */}
              <div className="flex gap-2">
                <input
                  ref={pathInputRef}
                  value={form.path}
                  onChange={(e) => setForm((prev) => ({ ...prev, path: e.target.value }))}
                  placeholder="/absolute/path/to/project"
                  className="flex-1 rounded bg-nexus-border px-3 py-2 text-sm font-mono outline-none focus:ring-1 focus:ring-nexus-accent"
                />
                <button
                  onClick={handleBrowseFolder}
                  className="flex items-center gap-1.5 rounded bg-nexus-border px-3 py-2 text-sm text-gray-300 hover:bg-nexus-border/80 hover:text-white transition-colors"
                  title="Browse for folder"
                >
                  <FolderOpen className="h-4 w-4" />
                  Browse
                </button>
              </div>

              <textarea
                value={form.description}
                onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                placeholder="Description (optional)"
                className="min-h-20 w-full rounded bg-nexus-border px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-nexus-accent resize-none"
              />

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs text-gray-500">Mode</label>
                  <select
                    value={form.mode}
                    onChange={(e) => setForm((prev) => ({ ...prev, mode: e.target.value }))}
                    className="w-full rounded bg-nexus-border px-3 py-2 text-sm outline-none"
                  >
                    <option value="auto">Auto</option>
                    <option value="agent">Agent</option>
                    <option value="plan">Plan</option>
                    <option value="micro">Micro</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-gray-500">Preferred Model</label>
                  <select
                    value={form.preferred_model}
                    onChange={(e) => setForm((prev) => ({ ...prev, preferred_model: e.target.value }))}
                    className="w-full rounded bg-nexus-border px-3 py-2 text-sm outline-none"
                  >
                    <option value="">Default</option>
                    <option value="qwen2.5-coder:7b">qwen2.5-coder:7b</option>
                    <option value="qwen2.5:3b">qwen2.5:3b</option>
                    <option value="deepseek-r1:8b">deepseek-r1:8b</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="trust"
                  checked={form.trust}
                  onChange={(e) => setForm((prev) => ({ ...prev, trust: e.target.checked }))}
                  className="rounded border-nexus-border"
                />
                <label htmlFor="trust" className="text-xs text-gray-400">
                  Trust project (allow file writes without confirmation)
                </label>
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="flex-1 rounded border border-nexus-border px-3 py-2 text-sm hover:bg-nexus-border/50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateProject}
                  disabled={!form.name && !form.path}
                  className="flex-1 rounded bg-nexus-accent px-3 py-2 text-sm font-medium text-black disabled:opacity-50"
                >
                  Create
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
}
