/**
 * MotionForge 2D — API Client
 *
 * Typed client for all backend endpoints.
 */

const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
const API_BASE = rawApiUrl.replace(/\/+$/, "");

/**
 * API error carrying the HTTP status and the FastAPI error payload.
 *
 * FastAPI wraps every error body in `{"detail": <payload>}`; this class
 * unwraps the envelope so callers render the real backend message (e.g.
 * the durable job 400 "Cannot cancel job in state: X" or the preflight
 * taxonomy codes), never a generic "failed".
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** Human-readable backend detail (string payload or JSON text). */
  detailText(): string {
    if (typeof this.detail === "string" && this.detail) return this.detail;
    if (this.detail === null || this.detail === undefined) return "";
    try {
      return JSON.stringify(this.detail);
    } catch {
      return String(this.detail);
    }
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
    const text = await res.text().catch(() => "");
    let detail: unknown = text;
    if (text) {
      try {
        const body: unknown = JSON.parse(text);
        detail =
          typeof body === "object" &&
          body !== null &&
          "detail" in body &&
          (body as { detail: unknown }).detail !== undefined
            ? (body as { detail: unknown }).detail
            : body;
      } catch {
        detail = text;
      }
    }
    throw new ApiError(res.status, detail, `API ${res.status}: ${detailTextOf(detail)}`);
  }
  return res.json() as Promise<T>;
}

function detailTextOf(detail: unknown): string {
  if (typeof detail === "string" && detail) return detail;
  if (detail === null || detail === undefined) return "";
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
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

/**
 * Durable job status as returned by GET /api/jobs/{id} (S02-T05 cutover).
 *
 * Real backend shape (verified against app/api/routes/jobs.py +
 * app/api/helpers.py job_response): `job_id`, `status` (renamed from
 * `state`), `progress` (0..100 from the durable state machine), `message`
 * (state-derived), `result_path`, `error` (envelope message string),
 * `job_type`. `status` may include `pending` (additive durable state,
 * contract §11.2). The UI MUST NOT invent progress — only these fields.
 */
export interface JobInfo {
  job_id: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed" | "pending";
  progress: number;
  message: string;
  result_path: string | null;
  error: string | null;
  job_type: string;
  /** Legacy optional fields (not present in the durable response). */
  current_step?: string;
  started_at?: string | null;
  completed_at?: string | null;
  error_code?: string | null;
  result?: Record<string, unknown> | null;
}

/**
 * One step of the approved T02→T03→T04 chain (S05-C01). Every value is
 * read from the durable Job row by the backend chain-state endpoint —
 * `status` is the real Job state machine value (`not_created` when the
 * step's job does not exist yet), `progress` is the real checkpoint
 * progress, `error`/`error_code` come from the persisted error envelope.
 */
export type ChainStepName = "import" | "proxy" | "scene_detect";
export type ChainStepStatus =
  | "not_created"
  | "pending"
  | "queued"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";

export interface ChainStepInfo {
  step: ChainStepName;
  job_id: string | null;
  status: ChainStepStatus;
  progress: number;
  message: string;
  error: string | null;
  error_code: string | null;
  predecessor_job_id: string | null;
}

export type ChainStatus = "idle" | "running" | "completed" | "failed" | "cancelled";

/**
 * Backend-owned chain state returned by POST/GET /api/projects/{id}/analyze
 * and POST /api/projects/{id}/analyze/retry. `chain_status` and
 * `active_step` are derived from the real durable rows; `progress` is the
 * mean of the real per-step checkpoint progresses; `source_sha256` is the
 * immutable chain identity (source content SHA-256, S05-C02). No value is
 * mocked.
 */
export interface AnalyzeChainState {
  project_id: string;
  video_item_id: string | null;
  generation: string;
  source_name: string | null;
  source_sha256: string | null;
  chain_status: ChainStatus;
  active_step: ChainStepName | null;
  progress: number;
  steps: {
    import: ChainStepInfo;
    proxy: ChainStepInfo;
    scene_detect: ChainStepInfo;
  };
  source_artifact_id: string | null;
  proxy_artifact_id: string | null;
  scenes_count: number | null;
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

  getScenes: (projectId: string) =>
    apiFetch<SceneInfo[]>(`/api/projects/${projectId}/scenes`),

  /**
   * LEGACY path only — used exclusively by the pre-S05 ScreenA workflow
   * (create project → upload → legacy ingest → chunk). The S05-C01
   * Import/Analyze UI does NOT use this; it drives the approved chain via
   * analyzeProject/getAnalyzeChain/retryAnalyzeChain.
   */
  triggerIngest: (projectId: string) =>
    apiFetch<JobInfo>(`/api/projects/${projectId}/ingest`, {
      method: "POST",
    }),

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
    apiFetch<{ status: string; job_id: string }>(`/api/jobs/${jobId}/cancel`, {
      method: "POST",
    }),

  /**
   * ONE UI-facing submission drives the approved durable chain
   * T02 ANALYZE_MEDIA import → T03 GENERATE_PROXY → T04 ANALYZE_MEDIA
   * scene_detect (S05-C02). The request is submission-only; chain
   * progression is owned by the backend orchestration service (its
   * background loop materializes the proxy/scene_detect jobs as each
   * predecessor durably completes — no polling required, survives API
   * restarts). The chain identity is the source SHA-256 + generation;
   * re-submitting the same source reuses the chain, a different source
   * starts a fresh chain.
   */
  analyzeProject: (projectId: string, title?: string) =>
    apiFetch<AnalyzeChainState>(
      `/api/projects/${projectId}/analyze`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ generation: "1", title: title ?? null }),
      },
    ),

  /**
   * Backend-owned chain state (active step, real checkpoint progress,
   * terminal states). Polled by the UI — STRICTLY READ-ONLY: this GET
   * never creates jobs or mutates rows; the orchestration service owns
   * chain progression.
   */
  getAnalyzeChain: (projectId: string, generation = "1") =>
    apiFetch<AnalyzeChainState>(
      `/api/projects/${projectId}/analyze?generation=${generation}`,
    ),

  /**
   * Retry the newest failed/cancelled chain job via a successor Job
   * (DURABLE_JOB_CONTRACT §8.5): owner validation + idempotency — a
   * duplicate retry reuses the already-created successor (never a
   * 500 IdempotencyKeyInUse without a path).
   */
  retryAnalyzeChain: (projectId: string, generation = "1") =>
    apiFetch<AnalyzeChainState>(
      `/api/projects/${projectId}/analyze/retry?generation=${generation}`,
      { method: "POST" },
    ),

  /**
   * Atomically cancel the chain's CURRENTLY ACTIVE durable step
   * (S05-C04-R3). The backend re-resolves the active job AT CANCEL TIME
   * (never a polled client snapshot), so a click during an
   * import→proxy→scene transition still cancels the active step: 200
   * `{status: "cancel_requested", job_id}` when a job was cancelled
   * (idempotent while `cancelling`, same semantics as POST
   * /api/jobs/{id}/cancel); 400 when the chain has genuinely
   * completed/terminated — the UI then refetches and shows the terminal
   * state. Never creates a successor.
   */
  cancelAnalyzeChain: (projectId: string, generation = "1") =>
    apiFetch<{ status: string; job_id: string }>(
      `/api/projects/${projectId}/analyze/cancel?generation=${generation}`,
      { method: "POST" },
    ),

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
};
