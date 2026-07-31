/**
 * MotionForge 2D — Zustand Store (Persisted)
 *
 * Global state for the active project with localStorage persistence.
 */

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type {
  ProjectData,
  TrackedObject,
  SelectionInput,
  ReplacementConfig,
  JobInfo,
  GalleryManifest,
  FrameMotion,
  SceneDetail,
} from "@/lib/api";

type Screen = "start" | "selection" | "review" | "replacement" | "render";

type PreviewMode = "original" | "mask" | "result" | "comparison";

interface ProjectState {
  // Project
  projectId: string | null;
  project: ProjectData | null;
  screen: Screen;

  // Selection
  currentFrame: number;
  selection: SelectionInput | null;
  maskPreview: string | null; // base64 PNG

  // Object
  activeObject: TrackedObject | null;
  gallery: GalleryManifest | null;

  // Replacement
  replacement: ReplacementConfig;

  // Preview
  previewMode: PreviewMode;
  frameMotion: FrameMotion | null;

  // Jobs
  activeJobs: Record<string, JobInfo>;

  // Scenes
  scenes: SceneDetail[];
  activeSceneId: number | null;

  // Channel
  activeChannelId: string | null;

  // Persisted screen for rehydration
  persistedScreen: Screen | null;
  setPersistedScreen: (screen: Screen | null) => void;

  // Actions
  setProjectId: (id: string | null) => void;
  setProject: (data: ProjectData | null) => void;
  setScreen: (screen: Screen) => void;
  setCurrentFrame: (frame: number) => void;
  setSelection: (sel: SelectionInput | null) => void;
  setMaskPreview: (png: string | null) => void;
  setActiveObject: (obj: TrackedObject | null) => void;
  setGallery: (g: GalleryManifest | null) => void;
  setReplacement: (r: Partial<ReplacementConfig>) => void;
  resetReplacement: () => void;
  setPreviewMode: (mode: PreviewMode) => void;
  setFrameMotion: (motion: FrameMotion | null) => void;
  updateJob: (job: JobInfo) => void;
  removeJob: (id: string) => void;
  setScenes: (scenes: SceneDetail[]) => void;
  setActiveSceneId: (id: number | null) => void;
  setActiveChannelId: (id: string | null) => void;
  resetAll: () => void;
}

const DEFAULT_REPLACEMENT: ReplacementConfig = {
  mode: "none",
  asset_path: null,
  anchor: { x: 0.5, y: 0.5 },
  offset: { x: 0, y: 0 },
  scale: 1.0,
  rotation_offset_deg: 0,
  opacity: 1.0,
  fit_mode: "contain",
  clip_mode: "asset_alpha",
};

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      projectId: null,
      project: null,
      screen: "start",
      currentFrame: 0,
      selection: null,
      maskPreview: null,
      activeObject: null,
      gallery: null,
      replacement: { ...DEFAULT_REPLACEMENT },
      previewMode: "result",
      frameMotion: null,
      activeJobs: {},

      scenes: [],
      activeSceneId: null,

      activeChannelId: null,

      persistedScreen: null,
      setPersistedScreen: (screen) => set({ persistedScreen: screen }),

      setProjectId: (id) => set({ projectId: id }),
      setProject: (data) => set({ project: data }),
      setScreen: (screen) => set({ screen }),
      setCurrentFrame: (frame) => set({ currentFrame: frame }),
      setSelection: (sel) => set({ selection: sel }),
      setMaskPreview: (png) => set({ maskPreview: png }),
      setActiveObject: (obj) => set({ activeObject: obj }),
      setGallery: (g) => set({ gallery: g }),
      setReplacement: (r) =>
        set((s) => ({ replacement: { ...s.replacement, ...r } })),
      resetReplacement: () => set({ replacement: { ...DEFAULT_REPLACEMENT } }),
      setPreviewMode: (mode) => set({ previewMode: mode }),
      setFrameMotion: (motion) => set({ frameMotion: motion }),
      updateJob: (job) =>
        set((s) => ({ activeJobs: { ...s.activeJobs, [job.job_id]: job } })),
      removeJob: (id) =>
        set((s) => {
          const jobs = { ...s.activeJobs };
          delete jobs[id];
          return { activeJobs: jobs };
        }),
      setScenes: (scenes) => set({ scenes }),
      setActiveSceneId: (id) => set({ activeSceneId: id }),
      setActiveChannelId: (id) => set({ activeChannelId: id }),

      resetAll: () =>
        set({
          projectId: null,
          project: null,
          screen: "start",
          currentFrame: 0,
          selection: null,
          maskPreview: null,
          activeObject: null,
          gallery: null,
          replacement: { ...DEFAULT_REPLACEMENT },
          previewMode: "result",
          frameMotion: null,
          activeJobs: {},
          scenes: [],
          activeSceneId: null,
        }),
    }),
    {
      name: "motionforge-project-storage",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        projectId: state.projectId,
        screen: state.screen,
        activeSceneId: state.activeSceneId,
        activeChannelId: state.activeChannelId,
      }),
    }
  )
);
