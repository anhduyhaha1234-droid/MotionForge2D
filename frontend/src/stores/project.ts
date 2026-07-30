/**
 * MotionForge 2D — Zustand Store
 *
 * Global state for the active project.
 */

import { create } from "zustand";
import type {
  ProjectData,
  TrackedObject,
  SelectionInput,
  ReplacementConfig,
  JobInfo,
  GalleryManifest,
  FrameMotion,
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

  // Actions
  setProjectId: (id: string) => void;
  setProject: (data: ProjectData) => void;
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

export const useProjectStore = create<ProjectState>((set) => ({
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
}));
