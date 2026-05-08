"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { createProject, getProjects } from "../../lib/api";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import { FolderKanban, Plus, Settings, Trash2, Clock } from "lucide-react";

interface Project {
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

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [form, setForm] = useState({
    name: "",
    path: "",
    description: "",
    mode: "auto",
    preferred_model: "",
    trust: false,
  });

  async function loadProjects() {
    try {
      const data = await getProjects();
      setProjects(data || []);
    } catch (error) {
      console.error("Failed to fetch projects:", error);
    }
  }

  useEffect(() => {
    loadProjects();
  }, []);

  async function handleCreateProject() {
    try {
      const result = await createProject(form);
      if (result.project) {
        setShowCreateModal(false);
        setForm({
          name: "",
          path: "",
          description: "",
          mode: "auto",
          preferred_model: "",
          trust: false,
        });
        await loadProjects();
      }
    } catch (error) {
      console.error("Failed to create project:", error);
    }
  }

  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        
        <main className="flex-1 overflow-auto p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
          >
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
                  transition={{ delay: index * 0.1 }}
                  className="rounded border border-nexus-border bg-nexus-panel/50 p-4 hover:border-nexus-accent/50"
                >
                  <div className="mb-3 flex items-start justify-between">
                    <div>
                      <h3 className="text-sm font-semibold">{project.name}</h3>
                      <p className="text-xs text-gray-500">{project.path}</p>
                    </div>
                    <div className="flex gap-1">
                      <button className="rounded p-1 text-gray-400 hover:bg-nexus-border hover:text-gray-300">
                        <Settings className="h-3 w-3" />
                      </button>
                      <button className="rounded p-1 text-gray-400 hover:bg-red-500/20 hover:text-red-400">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                  
                  {project.description && (
                    <p className="mb-3 text-xs text-gray-400">{project.description}</p>
                  )}
                  
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      <span>{new Date(project.updated_at).toLocaleDateString()}</span>
                    </div>
                    <div className="rounded bg-nexus-border px-2 py-0.5">
                      {project.mode}
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>

            {projects.length === 0 && (
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
          <div className="w-full max-w-lg rounded border border-nexus-border bg-nexus-panel p-4">
            <h2 className="mb-4 text-lg font-semibold">Create Project</h2>
            <div className="space-y-3">
              <input
                value={form.name}
                onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="Project name"
                className="w-full rounded bg-nexus-border px-3 py-2 text-sm"
              />
              <input
                value={form.path}
                onChange={(e) => setForm((prev) => ({ ...prev, path: e.target.value }))}
                placeholder="/absolute/path/to/project"
                className="w-full rounded bg-nexus-border px-3 py-2 text-sm"
              />
              <textarea
                value={form.description}
                onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                placeholder="Description"
                className="min-h-24 w-full rounded bg-nexus-border px-3 py-2 text-sm"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="flex-1 rounded border border-nexus-border px-3 py-2 text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateProject}
                  className="flex-1 rounded bg-nexus-accent px-3 py-2 text-sm font-medium text-black"
                >
                  Create
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
