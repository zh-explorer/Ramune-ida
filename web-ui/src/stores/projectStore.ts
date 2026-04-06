import { create } from "zustand";
import type { ProjectSummary, SystemInfo } from "../api/types";
import { getProjects, getSystem } from "../api/client";

interface ProjectState {
  projects: ProjectSummary[];
  activeProjectId: string | null;
  system: SystemInfo | null;
  loading: boolean;
  error: string | null;

  fetchProjects: () => Promise<void>;
  fetchSystem: () => Promise<void>;
  setActiveProject: (pid: string | null) => void;
  dataVersion: number;
  bumpDataVersion: () => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  activeProjectId: null,
  system: null,
  loading: false,
  error: null,

  fetchProjects: async () => {
    set({ loading: true, error: null });
    try {
      const data = await getProjects();
      set((state) => {
        const active = state.activeProjectId;
        const stillExists = data.projects.some((p) => p.project_id === active);
        return {
          projects: data.projects,
          loading: false,
          activeProjectId: stillExists
            ? active
            : data.projects.length > 0
              ? data.projects[0].project_id
              : null,
        };
      });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  fetchSystem: async () => {
    try {
      const data = await getSystem();
      set({ system: data });
    } catch {
      // silent
    }
  },

  setActiveProject: (pid) => set({ activeProjectId: pid }),
  dataVersion: 0,
  bumpDataVersion: () => set((s) => ({ dataVersion: s.dataVersion + 1 })),
}));
