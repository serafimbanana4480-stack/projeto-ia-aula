import { create } from "zustand";

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

interface ProjectStore {
  currentProject: Project | null;
  projects: Project[];
  setCurrentProject: (project: Project | null) => void;
  setProjects: (projects: Project[]) => void;
  addProject: (project: Project) => void;
}

// Hydrate currentProject from localStorage on first load
function _loadPersistedProject(): Project | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem("nexus.currentProject");
    if (raw) return JSON.parse(raw) as Project;
  } catch {
    // Corrupted data — clear it
    window.localStorage.removeItem("nexus.currentProject");
  }
  return null;
}

export const useProjectStore = create<ProjectStore>((set) => ({
  currentProject: _loadPersistedProject(),
  projects: [],
  setCurrentProject: (project) => {
    if (typeof window !== "undefined") {
      if (project) {
        window.localStorage.setItem(
          "nexus.currentProject",
          JSON.stringify(project),
        );
      } else {
        window.localStorage.removeItem("nexus.currentProject");
      }
    }
    set({ currentProject: project });
  },
  setProjects: (projects) => set({ projects }),
  addProject: (project) =>
    set((state) => ({ projects: [project, ...state.projects] })),
}));
