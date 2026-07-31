/**
 * MotionForge 2D — API Client
 *
 * Typed client for all backend endpoints.
 */

const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
const API_BASE = rawApiUrl.replace(/\/+$/, "");

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${API_BASE}${cleanPath}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ─── Types ─────────────────────────────────────────────────────────────────

export interface VideoMetadata {
  width: number;
  height: number;
  fps: number;
  duration_seconds: number;
  total_frames: number;
  codec: string;
  has_audio: boolean;
  audio_codec: string | null;
}

export interface SceneInfo {
  scene_id: number;
  start_frame: number;
  end_frame: number;
  start_time_sec: number;
  end_time_sec: number;
  duration_sec: number;
  frame_count: number;
}

export interface SceneDetail {
  scene_id: number;
  start_frame: number;
  end_frame: number;
  start_time_sec: number;
  end_time_sec: number;
  duration_sec: number;
  frame_count: number;
  status: "pending" | "draft" | "approved";
  audio_path: string;
  notes: string;
}

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SelectionInput {
  mode: "point" | "bounding_box";
  frame_index: number;
  x: number;
  y: number;
  width?: number;
  height?: number;
}

export interface FrameMotion {
  frame_index: number;
  centroid_x: number;
  centroid_y: number;
  bbox: BoundingBox;
  scale_x: number;
  scale_y: number;
  rotation_deg: number;
  opacity: number;
  visibility: boolean;
  area: number;
  confidence: number;
  occluded: boolean;
  needs_review: boolean;
  mask_path: string | null;
}

export type ClipMode = "asset_alpha" | "original_mask" | "intersection";

export interface ReplacementConfig {
  mode: "none" | "static_asset" | "frame_sequence";
  asset_path: string | null;
  anchor: { x: number; y: number };
  offset: { x: number; y: number };
  scale: number;
  rotation_offset_deg: number;
  opacity: number;
  fit_mode: "contain" | "cover" | "stretch";
  clip_mode: ClipMode;
  frameSequenceDir?: string;
  frameSequenceFps?: number;
}

export interface TrackedObject {
  object_id: string;
  name: string;
  kind: string;
  selection: SelectionInput;
  scene_id: number;
  replacement: ReplacementConfig | null;
  motion: {
    scene_id: number;
    frames: FrameMotion[];
    reference_bbox: BoundingBox | null;
    tracking_backend: string;
    model_version: string;
  } | null;
}

export interface ProjectData {
  version: string;
  name: string;
  source_video: string;
  video_metadata: VideoMetadata | null;
  scenes: SceneInfo[];
  objects: TrackedObject[];
}

export interface JobInfo {
  job_id: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
  progress: number;
  message: string;
  current_step: string;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  result: Record<string, unknown> | null;
}

export interface GalleryFrame {
  frame_index: number;
  crop_path: string;
  mask_path: string;
  reason: string;
}

export interface GalleryManifest {
  object_id: string;
  project_id: string;
  thumbnail_path: string;
  crops: GalleryFrame[];
}

export interface MaskPreviewRequest {
  frame_index: number;
  selection: SelectionInput;
  backend?: string;
}

export interface MaskPreviewResponse {
  mask_png_base64: string;
  frame_index: number;
  nonzero_pixels: number;
}

export interface DubbingConfig {
  scene_id: number;
  source_lang: string;
  target_lang: string;
  whisper_model: string;
  tts_voice: string;
}

export interface DubbingResult {
  vocal_track: string;
  bgm_track: string;
  original_srt: string;
  translated_srt: string;
  final_audio: string;
  segments: Array<{ start: number; end: number; text: string; original?: string }>;
}

export interface DubbingSegment {
  start: number;
  end: number;
  text: string;
  original?: string;
}

export interface CharacterMapping {
  original_name: string;
  replacement_asset: string;
  voice_config: Record<string, unknown>;
  replacement_config: Record<string, unknown>;
}

export interface ProjectPreset {
  name: string;
  description: string;
  version: string;
  mappings: CharacterMapping[];
  dubbing_config: Record<string, unknown>;
}

export interface PresetInfo {
  filename: string;
  name: string;
  description: string;
  mapping_count: number;
}

export interface GpuInfo {
  has_nvenc: boolean;
  gpu_name: string;
  encoder: string;
}

export interface ChannelWorkspace {
  channel_id: string;
  name: string;
  target_lang: string;
  default_preset_id: string;
  created_at: string;
}

export interface ChannelProject {
  project_id: string;
  name: string;
  task_status: "draft" | "in_progress" | "ready_to_stitch" | "completed";
  created_at: string;
  scene_count: number;
  object_count: number;
}

// ─── API Functions ──────────────────────────────────────────────────────────

export const api = {
  // Projects
  createProject: (name: string) =>
    apiFetch<{ project_id: string }>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  getProject: (id: string) =>
    apiFetch<ProjectData>(`/api/projects/${id}`),

  uploadVideo: async (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/video`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json() as Promise<{ video_path: string }>;
  },

  triggerIngest: (projectId: string) =>
    apiFetch<{ job_id: string }>(`/api/projects/${projectId}/ingest`, {
      method: "POST",
    }),

  getScenes: (projectId: string) =>
    apiFetch<SceneInfo[]>(`/api/projects/${projectId}/scenes`),

  getFrameUrl: (projectId: string, frameIndex: number) =>
    `${API_BASE}/api/projects/${projectId}/frames/${frameIndex}`,

  // Objects
  previewMask: (projectId: string, req: MaskPreviewRequest) =>
    apiFetch<MaskPreviewResponse>(
      `/api/projects/${projectId}/objects/preview-mask`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      },
    ),

  createObject: (projectId: string, obj: { name: string; selection: SelectionInput; scene_id: number }) =>
    apiFetch<TrackedObject>(`/api/projects/${projectId}/objects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(obj),
    }),

  propagateObject: (projectId: string, objectId: string) =>
    apiFetch<{ job_id: string }>(
      `/api/projects/${projectId}/objects/${objectId}/propagate`,
      { method: "POST" },
    ),

  getObject: (projectId: string, objectId: string) =>
    apiFetch<TrackedObject>(`/api/projects/${projectId}/objects/${objectId}`),

  getGallery: (projectId: string, objectId: string) =>
    apiFetch<GalleryManifest>(
      `/api/projects/${projectId}/objects/${objectId}/gallery`,
    ),

  uploadReplacement: async (projectId: string, objectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/objects/${objectId}/replacement`,
      { method: "POST", body: form },
    );
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json() as Promise<{ asset_path: string }>;
  },

  updateReplacementSettings: (
    projectId: string,
    objectId: string,
    settings: Partial<ReplacementConfig>,
  ) =>
    apiFetch<ReplacementConfig>(
      `/api/projects/${projectId}/objects/${objectId}/replacement-settings`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      },
    ),

  // Render
  triggerPreview: (projectId: string) =>
    apiFetch<{ job_id: string }>(`/api/projects/${projectId}/preview`, {
      method: "POST",
    }),

  triggerRender: (projectId: string) =>
    apiFetch<{ job_id: string }>(`/api/projects/${projectId}/render`, {
      method: "POST",
    }),

  // Jobs
  getJob: (jobId: string) => apiFetch<JobInfo>(`/api/jobs/${jobId}`),

  cancelJob: (jobId: string) =>
    apiFetch<{ ok: boolean }>(`/api/jobs/${jobId}/cancel`, {
      method: "POST",
    }),

  // Image URLs (direct links, no fetch)
  getMaskImageUrl: (projectId: string, objectId: string, frameIndex: number) =>
    `${API_BASE}/api/projects/${projectId}/objects/${objectId}/masks/${frameIndex}`,

  getCropImageUrl: (projectId: string, objectId: string, frameIndex: number) =>
    `${API_BASE}/api/projects/${projectId}/objects/${objectId}/crops/${frameIndex}`,

  getReplacementImageUrl: (projectId: string, objectId: string) =>
    `${API_BASE}/api/projects/${projectId}/objects/${objectId}/replacement-image`,

  // ─── Scene Approval ───────────────────────────────────────────────────

  chunkScenes: (projectId: string, threshold?: number) =>
    apiFetch<{ scene_count: number; scenes: SceneDetail[] }>(
      `/api/projects/${projectId}/scenes/chunk?threshold=${threshold ?? 27.0}`,
      { method: "POST" },
    ),

  getSceneDetails: (projectId: string) =>
    apiFetch<SceneDetail[]>(`/api/projects/${projectId}/scenes/details`),

  updateSceneStatus: (
    projectId: string,
    sceneId: number,
    status: "pending" | "draft" | "approved",
    notes?: string,
  ) =>
    apiFetch<{ ok: boolean }>(
      `/api/projects/${projectId}/scenes/${sceneId}/status`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, notes: notes ?? "" }),
      },
    ),

  getSceneAudioUrl: (projectId: string, sceneId: number) =>
    `${API_BASE}/api/projects/${projectId}/scenes/${sceneId}/audio`,

  stitchScenes: (projectId: string) =>
    apiFetch<{ ok: boolean; output_path: string }>(
      `/api/projects/${projectId}/scenes/stitch`,
      { method: "POST" },
    ),

  extractSceneFrames: (projectId: string, sceneId: number, format = "jpg") =>
    apiFetch<{ scene_id: number; frame_count: number; format: string }>(
      `/api/projects/${projectId}/scenes/${sceneId}/extract-frames?format=${format}`,
      { method: "POST" },
    ),

  // ─── Bulk Mapping ────────────────────────────────────────────────────

  applyBulkMapping: (
    projectId: string,
    objectId: string,
    sceneIds: number[],
  ) =>
    apiFetch<{ applied_to: string[]; scene_ids: number[] }>(
      `/api/projects/${projectId}/objects/${objectId}/apply-bulk`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ object_id: objectId, scene_ids: sceneIds }),
      },
    ),

  // ─── Inpainting ──────────────────────────────────────────────────────

  inpaintScene: (projectId: string, sceneId: number) =>
    apiFetch<{ ok: boolean }>(
      `/api/projects/${projectId}/scenes/${sceneId}/inpaint`,
      { method: "POST" },
    ),

  // ─── Sequence Frame URL ─────────────────────────────────────────────

  getSequenceFrameUrl: (projectId: string, objectId: string, index: number) =>
    `${API_BASE}/api/projects/${projectId}/objects/${objectId}/sequence-frame?index=${index}`,

  // ─── Dubbing ────────────────────────────────────────────────────────

  separateAudio: (projectId: string, sceneId: number) =>
    apiFetch<{ vocal_track: string; bgm_track: string }>(
      `/api/projects/${projectId}/dubbing/separate?scene_id=${sceneId}`,
      { method: "POST" },
    ),

  transcribeScene: (
    projectId: string,
    sceneId: number,
    sourceLang?: string,
    whisperModel?: string,
  ) =>
    apiFetch<{ segments: DubbingSegment[]; srt_path: string }>(
      `/api/projects/${projectId}/dubbing/transcribe?scene_id=${sceneId}&source_lang=${sourceLang ?? "vi"}&whisper_model=${whisperModel ?? "base"}`,
      { method: "POST" },
    ),

  translateSubtitles: (
    projectId: string,
    sceneId: number,
    targetLang: string,
    sourceLang?: string,
  ) =>
    apiFetch<{ segments: DubbingSegment[]; srt_path: string }>(
      `/api/projects/${projectId}/dubbing/translate?scene_id=${sceneId}&target_lang=${targetLang}&source_lang=${sourceLang ?? "auto"}`,
      { method: "POST" },
    ),

  generateTts: (
    projectId: string,
    sceneId: number,
    targetLang?: string,
    ttsVoice?: string,
  ) =>
    apiFetch<{ tts_count: number; tts_dir: string }>(
      `/api/projects/${projectId}/dubbing/tts?scene_id=${sceneId}&target_lang=${targetLang ?? "en"}&tts_voice=${ttsVoice ?? "en-US-AriaNeural"}`,
      { method: "POST" },
    ),

  remuxDubbedAudio: (projectId: string, sceneId: number) =>
    apiFetch<{ final_audio: string }>(
      `/api/projects/${projectId}/dubbing/remux?scene_id=${sceneId}`,
      { method: "POST" },
    ),

  fullDubbingPipeline: (projectId: string, config: DubbingConfig) =>
    apiFetch<DubbingResult>(
      `/api/projects/${projectId}/dubbing/full`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      },
    ),

  // ─── Scene Objects ──────────────────────────────────────────────────────

  getSceneObjects: (projectId: string, sceneId: number) =>
    apiFetch<TrackedObject[]>(
      `/api/projects/${projectId}/scenes/${sceneId}/objects`,
    ),

  // ─── Presets ────────────────────────────────────────────────────────────

  savePreset: (projectId: string, name: string, description?: string) =>
    apiFetch<{ ok: boolean; path: string; mapping_count: number }>(
      `/api/projects/${projectId}/presets/save`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: description ?? "" }),
      },
    ),

  listPresets: (projectId: string) =>
    apiFetch<PresetInfo[]>(
      `/api/projects/${projectId}/presets`,
    ),

  applyPreset: (projectId: string, presetFilename: string) =>
    apiFetch<{ ok: boolean; updated_objects: number }>(
      `/api/projects/${projectId}/presets/${presetFilename}/apply`,
      { method: "POST" },
    ),

  // ─── Multi-Format Render ────────────────────────────────────────────────

  renderWithFormat: (projectId: string, format: string) =>
    apiFetch<{ job_id: string }>(
      `/api/projects/${projectId}/render?format=${format}`,
      { method: "POST" },
    ),

  // ─── Export ─────────────────────────────────────────────────────────────

  exportProjectZip: (projectId: string) =>
    `/api/projects/${projectId}/export`,

  // ─── Channels ───────────────────────────────────────────────────────────

  createChannel: (name: string, targetLang?: string) =>
    apiFetch<ChannelWorkspace>(
      `/api/projects/channels`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, target_lang: targetLang ?? "en" }),
      },
    ),

  listChannels: () =>
    apiFetch<ChannelWorkspace[]>("/api/projects/channels"),

  getChannelProjects: (channelId: string) =>
    apiFetch<ChannelProject[]>(`/api/projects/channels/${channelId}/projects`),

  deleteChannel: (channelId: string) =>
    apiFetch<{ ok: boolean }>(
      `/api/projects/channels/${channelId}`,
      { method: "DELETE" },
    ),

  updateTaskStatus: (projectId: string, taskStatus: string) =>
    apiFetch<{ ok: boolean }>(
      `/api/projects/${projectId}/task-status`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_status: taskStatus }),
      },
    ),

  assignChannel: (projectId: string, channelId: string) =>
    apiFetch<{ ok: boolean }>(
      `/api/projects/${projectId}/assign-channel?channel_id=${channelId}`,
      { method: "PATCH" },
    ),

  // ─── Performance & Automation ─────────────────────────────────────────

  getGpuInfo: () =>
    apiFetch<GpuInfo>("/api/projects/gpu-info"),

  autoMatchCharacter: (projectId: string, objectId: string) =>
    apiFetch<{ matched: string[]; count: number }>(
      `/api/projects/${projectId}/objects/${objectId}/auto-match`,
      { method: "POST" },
    ),

  cleanupProject: (projectId: string) =>
    apiFetch<{ ok: boolean; files_removed: number; dirs_removed: number; bytes_freed: number }>(
      `/api/projects/${projectId}/cleanup`,
      { method: "POST" },
    ),
};
