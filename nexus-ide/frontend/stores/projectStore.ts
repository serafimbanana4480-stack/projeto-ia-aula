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

export const useProjectStore = create<ProjectStore>((set) => ({
  currentProject: null,
  projects: [],
  setCurrentProject: (project) => {
    if (typeof window !== "undefined") {
      if (project) {
        window.localStorage.setItem("nexus.currentProject", JSON.stringify(project));
      } else {
        window.localStorage.removeItem("nexus.currentProject");
      }
    }
    set({ currentProject: project });
  },
  setProjects: (projects) => set({ projects }),
  addProject: (project) => set((state) => ({ projects: [project, ...state.projects] })),
}));
