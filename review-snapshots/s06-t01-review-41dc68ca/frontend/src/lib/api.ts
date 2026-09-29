/**
 * MotionForge 2D — API Client
 *
 * Typed client for all backend endpoints.
 */

const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
const API_BASE = rawApiUrl.replace(/\/+$/, "");

/** Typed API failure (S06-T05). Carries the HTTP status and parsed JSON
 *  ``detail`` so the UI can surface 422 validation problems and 409
 *  stale-revision conflicts honestly instead of a generic message. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

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
    let detail: unknown = null;
    try {
      const body: unknown = await res.json();
      // FastAPI errors wrap the payload in {"detail": <payload>}; unwrap so
      // callers read the typed payload directly (S06-T05).
      detail =
        typeof body === "object" && body !== null && "detail" in body
          ? (body as { detail: unknown }).detail
          : body;
    } catch {
      const text = await res.text().catch(() => "");
      detail = text || null;
    }
    const bodyText =
      typeof detail === "string" ? detail : JSON.stringify(detail ?? "");
    throw new ApiError(res.status, detail, `API ${res.status}: ${bodyText}`);
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
  thumbnail_base64?: string;
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
  scene_details: SceneDetail[];
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

export interface ProjectSummary {
  project_id: string;
  name: string;
  task_status: string;
  source_video: string;
  scenes_count: number;
  updated_at: string;
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

// ─── Durable Character Library (S06-T01 + S06-R02) ────────────────────────

export type CharacterStatus = "draft" | "generating" | "needs_review" | "ready" | "archived";
export type CharacterType = "character" | "prop" | "other";
export type PackStatus = "draft" | "validating" | "ready" | "published" | "archived";

export interface CharacterData {
  id: string;
  workspace_id: string;
  name: string;
  code: string;
  character_type: CharacterType;
  symmetry: "symmetric" | "asymmetric";
  status: CharacterStatus;
  default_version_id: string | null;
  description: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface CharacterAssetData {
  id: string;
  pack_version_id: string;
  workspace_id: string;
  pose_slot: string;
  artifact_id: string;
  created_at: string;
  updated_at: string;
  /** Read-only artifact snapshot (S06-R02). Null when the linked Artifact is missing. */
  artifact_state: string | null;
  mime_type: string | null;
  sha256: string | null;
  size_bytes: number | null;
  /** Server-produced typed link to the pose image bytes (S06-R02). */
  content_url: string | null;
}

export interface PackVersionData {
  id: string;
  character_id: string;
  workspace_id: string;
  version: number;
  status: PackStatus;
  validation_json: string | null;
  published_at: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  assets: CharacterAssetData[];
}

export interface PackVersionValidationData {
  version_id: string;
  character_id: string;
  workspace_id: string;
  status: "valid" | "invalid";
  complete: boolean;
  missing_slots: string[];
  errors: string[];
}

export interface CharacterListResponse {
  workspace_id: string;
  limit: number;
  offset: number;
  total: number;
  characters: CharacterData[];
}

/** The six required core pose slots (S06-T03 contract). */
export const CORE_POSE_SLOTS = ["front", "three_quarter", "side", "back", "sitting", "walking"] as const;
export type CorePoseSlot = (typeof CORE_POSE_SLOTS)[number];

export const POSE_SLOT_LABELS: Record<CorePoseSlot, string> = {
  front: "Mặt trước",
  three_quarter: "Ba phần tư",
  side: "Nghiêng bên",
  back: "Sau lưng",
  sitting: "Ngồi",
  walking: "Đi bộ",
};

export const CHARACTER_STATUS_LABELS: Record<CharacterStatus, string> = {
  draft: "Nháp",
  generating: "Đang tạo",
  needs_review: "Cần duyệt",
  ready: "Sẵn sàng",
  archived: "Đã lưu trữ",
};

export const PACK_STATUS_LABELS: Record<PackStatus, string> = {
  draft: "Nháp",
  validating: "Đang kiểm tra",
  ready: "Sẵn sàng",
  published: "Đã xuất bản",
  archived: "Đã lưu trữ",
};

// ─── API Functions ──────────────────────────────────────────────────────────

export const api = {
  // Projects
  createProject: (name: string) =>
    apiFetch<{ project_id: string }>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  listAllProjects: () =>
    apiFetch<ProjectSummary[]>("/api/projects"),

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
    apiFetch<{ object_id: string; project: ProjectData }>(`/api/projects/${projectId}/objects`, {
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
        // Backend expects { replacement_config: {...} }
        body: JSON.stringify({ replacement_config: settings }),
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

  getInpaintedFrameUrl: (projectId: string, objectId: string, frameIndex: number) =>
    `${API_BASE}/api/projects/${projectId}/objects/${objectId}/inpainted/${frameIndex}`,

  getObjectCropUrl: (projectId: string, objectId: string) =>
    `${API_BASE}/api/projects/${projectId}/objects/${objectId}/crop`,

  listObjects: (projectId: string) =>
    apiFetch<
      Array<
        TrackedObject & { thumbnail_base64: string }
      >
    >(`/api/projects/${projectId}/objects`),

  clearObjects: (projectId: string) =>
    apiFetch<{ status: string; project: ProjectData }>(
      `/api/projects/${projectId}/objects`,
      { method: "DELETE" },
    ),

  deleteObject: (projectId: string, objectId: string) =>
    apiFetch<{ status: string; project: ProjectData }>(
      `/api/projects/${projectId}/objects/${objectId}`,
      { method: "DELETE" },
    ),

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

  // ─── Character Preset Library (multi-pose templates) ────────────────────

  listCharacterPresets: () =>
    apiFetch<{
      status: string;
      characters: {
        id: string;
        label: string;
        poses: { pose: string; label: string; filename: string; url: string }[];
      }[];
    }>(`/api/projects/presets/characters`),

  getCharacterPresetImageUrl: (setKey: string, pose: string) =>
    `${API_BASE}/api/projects/presets/characters/${setKey}/${pose}/image`,

  applyCharacterPreset: (projectId: string, setKey: string, pose: string) =>
    apiFetch<{
      status: string;
      object_id: string;
      asset_path: string;
      pose: string;
      set_key: string;
    }>(`/api/projects/${projectId}/presets/characters/${setKey}/${pose}/apply`, {
      method: "POST",
    }),

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

  deleteProject: (projectId: string) =>
    apiFetch<{ ok: boolean; deleted: string }>(
      `/api/projects/${projectId}`,
      { method: "DELETE" },
    ),

  autoSegmentObjects: (projectId: string, sceneId = 0) =>
    apiFetch<{
      scene_id: number;
      objects_found: number;
      objects: Array<{
        object_index: number;
        name?: string;
        crop_png_base64?: string;
        bbox: { x: number; y: number; width: number; height: number };
        area: number;
        centroid: { x: number; y: number };
      }>;
    }>(
      `/api/projects/${projectId}/auto-segment-objects?scene_id=${sceneId}`,
      { method: "POST" },
    ),

  // ─── Durable Character Library (S06-T01 + S06-R02) ─────────────────────

  listCharacters: (includeArchived = false, limit = 200) =>
    apiFetch<CharacterListResponse>(
      `/api/v2/characters?include_archived=${includeArchived}&limit=${limit}`,
    ),

  getCharacter: (characterId: string) =>
    apiFetch<CharacterData>(`/api/v2/characters/${characterId}`),

  listCharacterVersions: (characterId: string) =>
    apiFetch<PackVersionData[]>(`/api/v2/characters/${characterId}/versions`),

  getPackVersionValidation: (versionId: string) =>
    apiFetch<PackVersionValidationData>(
      `/api/v2/characters/versions/${versionId}/validation`,
    ),

  /** Publish a draft pack version (S06-T05). Uses the approved FLAT endpoint
   *  ``POST /api/v2/characters/versions/{version_id}/publish`` with the
   *  caller's current revision for CAS safety. 422 (invalid pack) and 409
   *  (stale revision) throw ApiError with the server detail. */
  publishCharacterVersion: (versionId: string, revision: number) =>
    apiFetch<PackVersionData>(
      `/api/v2/characters/versions/${versionId}/publish`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision }),
      },
    ),

  /** Absolute URL for a pose asset's image bytes (R02 content endpoint). */
  getCharacterAssetContentUrl: (asset: Pick<CharacterAssetData, "content_url">) =>
    asset.content_url ? `${API_BASE}${asset.content_url}` : null,
};
