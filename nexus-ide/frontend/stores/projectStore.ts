import { create } from "zustand";
import { getProjects } from "../lib/api";

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
  projectsLoaded: boolean;
  projectsLoading: boolean;
  projectsError: string | null;
  setCurrentProject: (project: Project | null) => void;
  setProjects: (projects: Project[]) => void;
  addProject: (project: Project) => void;
  loadProjects: () => Promise<void>;
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  currentProject: null, // Inicializa com null para evitar hydration mismatch
  projects: [],
  projectsLoaded: false,
  projectsLoading: false,
  projectsError: null,
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
  setProjects: (projects) => set({ projects, projectsLoaded: true }),
  addProject: (project) =>
    set((state) => ({ projects: [project, ...state.projects] })),
  loadProjects: async () => {
    if (get().projectsLoaded || get().projectsLoading) return;
    set({ projectsLoading: true, projectsError: null });
    try {
      const data = await getProjects();
      set({ projects: data, projectsLoaded: true, projectsLoading: false });
    } catch (error) {
      set({
        projectsError: error instanceof Error ? error.message : "Failed to load projects",
        projectsLoading: false,
      });
      throw error;
    }
  },
}));
