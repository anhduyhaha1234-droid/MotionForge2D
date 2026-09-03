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
  channel_id: string;
  task_status: string;
  created_at: string;
  updated_at: string;
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

// ─── S07 Project Cast (T01 mapping + T02 picker/compat) ─────────────────────

export interface ProjectCastData {
  id: string;
  workspace_id: string;
  project_id: string;
  object_role_id: string;
  character_id: string;
  pack_version_id: string;
  idempotency_key: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectCastListResponse {
  workspace_id: string;
  project_id: string | null;
  limit: number;
  offset: number;
  total: number;
  mappings: ProjectCastData[];
}

export type CompatibilityReason =
  | "workspace_mismatch"
  | "source_overlay_refusal"
  | "object_kind_mismatch"
  | "incomplete_pack"
  | "unpublished_pack"
  | "missing_required_pose"
  | "missing_required_capability"
  | "generation_mismatch"
  | "stale_revision";

export interface PickerPackItem {
  id: string;
  character_id: string;
  workspace_id: string;
  version: number;
  status: string;
  character_name: string;
  character_code: string;
  character_type: string;
  symmetry: string;
  published_at: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  asset_count: number;
  pose_slots: string[];
}

export interface PickerPacksResponse {
  workspace_id: string;
  limit: number;
  offset: number;
  total: number;
  packs: PickerPackItem[];
  query: string | null;
}

export interface CompatibilityEvaluateResponse {
  compatible: boolean;
  reasons: CompatibilityReason[];
  fallback_allowed: boolean;
  fallback_description: string | null;
  blocked: boolean;
  pinned_version_id: string | null;
  current_revision: number | null;
  workspace_id: string;
}

// ─── S08 Object Intelligence (T01 roles/occurrences) ─────────────────────

export interface ObjectOccurrence {
  id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  role_id: string;
  scene_id: string;
  frame_index: number;
  time_ms: number;
  bbox: BoundingBox;
  confidence: number;
  confidence_source: string;
  algorithm: string | null;
  algorithm_version: string | null;
  reasons: string[];
  review_state: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export type ObjectRoleStatus = "suggested" | "confirmed" | "superseded";

/**
 * Canonical seven-kind ObjectRole taxonomy (S08-A01 — backend authoritative
 * via GET /api/v2/object-intelligence/kinds).  The gallery filter, badges
 * and edit dialog derive their options from the kinds endpoint so no second
 * production authority is created in the frontend.
 */
export type ObjectRoleKind =
  | "character"
  | "prop"
  | "background"
  | "foreground"
  | "graphic"
  | "source_overlay"
  | "other";

/** One canonical kind with its backend-owned policy flag (S08-A01). */
export interface RoleKindData {
  name: ObjectRoleKind;
  /** True = removal-only (source_overlay): never a replacement/Character
   *  Pack candidate, never a grouping participant. */
  removal_only: boolean;
}

export interface RoleKindsResponse {
  kinds: RoleKindData[];
  /** The backend-owned removal-only kind name (source_overlay). */
  source_overlay: string;
}

/**
 * The NEWEST VALID media association of a role (S08-T05-C1, finding D):
 * resolved by the backend from the durable object_role_artifact
 * associations (superseded_by_id IS NULL). Content is servable through the
 * contained image endpoint — never a client filesystem path or name join.
 */
export interface RoleMedia {
  association_id: string;
  artifact_id: string;
  purpose: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  mime_type: string | null;
  source_generation: string;
  source_job_id: string;
}

/** Content URL of a role media artifact (contained endpoint, ETag/nosniff).
 *  ABSOLUTE — the Next dev proxy rewrites relative /api to a hardcoded port,
 *  so real byte URLs must go straight to the configured API base. */
export function roleMediaContentUrl(media: RoleMedia): string {
  return `${API_BASE}/api/v2/object-intelligence/extraction/${encodeURIComponent(media.source_job_id)}/artifacts/${encodeURIComponent(media.artifact_id)}/content`;
}

export interface ObjectRole {
  id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  source_generation: string;
  name: string;
  /** Canonical seven-kind taxonomy (S08-A01). */
  kind: ObjectRoleKind;
  status: ObjectRoleStatus;
  supersedes_role_id: string | null;
  legacy_object_id: string | null;
  legacy_scene_id: number | null;
  description: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  occurrences: ObjectOccurrence[];
  media: RoleMedia[];
  /** True when the role's media is association-managed (never name-fallback). */
  has_media_associations: boolean;
}

export interface ObjectRoleListResponse {
  workspace_id: string;
  limit: number;
  offset: number;
  total: number;
  roles: ObjectRole[];
  /** "current" | "historical" — never mixed (T01-C2 generation isolation). */
  scope: string;
  /** Backend-authoritative current source generation (T01-C2/T02-C2). */
  current_generation: string | null;
}

// ─── S08 Object Extraction (T02 durable job) ─────────────────────────────

export interface ExtractionOutput {
  artifact_id: string;
  name: string;
  purpose: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  mime_type: string | null;
}

export interface ExtractionCandidate {
  index: number;
  /** STABLE role id (deterministic per job + candidate index) — never a name. */
  role_id: string;
  name: string;
  kind: string;
  confidence: number;
  reasons: string[];
  occurrences: Record<string, unknown>[];
  artifacts: ExtractionOutput[];
}

export type ExtractionJobStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";

export interface ExtractionJob {
  job_id: string;
  job_type: string;
  status: ExtractionJobStatus;
  progress: number;
  message: string;
  error: string | null;
  provider: string | null;
  extractor_version: string | null;
  generation: string | null;
  source_sha256: string | null;
  video_item_id: string | null;
  created_at: string | null;
  finished_at: string | null;
  outputs: ExtractionOutput[];
  candidates: ExtractionCandidate[];
}

export interface ExtractionSubmitResult {
  job_id: string;
  reused: boolean;
  job_type: string;
  status: string;
}

export interface ExtractionOutputsResult {
  job_id: string;
  job_type: string;
  status: string;
  outputs: ExtractionOutput[];
  candidates: ExtractionCandidate[];
}

// ─── S08 Grouping (T03 suggestions + curation) ───────────────────────────

export type SuggestionStatus = "pending" | "dismissed" | "superseded";

export interface GroupingSuggestion {
  id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  source_generation: string;
  status: SuggestionStatus;
  role_ids: string[];
  target_role_id: string | null;
  confidence: number;
  reasons: string[];
  algorithm: string;
  algorithm_version: string;
  scope: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface SuggestionListResponse {
  workspace_id: string;
  limit: number;
  offset: number;
  total: number;
  suggestions: GroupingSuggestion[];
  /** "current" | "historical" — current-generation default (T03-C2). */
  scope: string;
  /** Backend-authoritative current source generation (T03-C2). */
  current_generation: string | null;
}

export interface GenerateSuggestionsResult {
  video_item_id: string;
  source_generation: string;
  algorithm: string;
  algorithm_version: string;
  scope: string;
  created_count: number;
  replayed_count: number;
  superseded_count: number;
  total: number;
  suggestions: GroupingSuggestion[];
}

export interface GroupingOperation {
  id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  operation_type: string;
  target_role_id: string;
  source_role_ids: string[];
  created_role_ids: string[];
  transfer_map: Array<{ role_id: string; occurrence_ids: string[] }>;
  suggestion_id: string | null;
  idempotency_key: string | null;
  revision_after: number;
  note: string | null;
  created_at: string;
}

export interface OperationListResponse {
  workspace_id: string;
  limit: number;
  offset: number;
  total: number;
  operations: GroupingOperation[];
}

export interface MergeResult {
  operation: GroupingOperation;
  target_role: ObjectRole;
}

export interface SplitResult {
  operation: GroupingOperation;
  created_role: ObjectRole;
}

export interface ConfirmResult {
  operation: GroupingOperation;
  role: ObjectRole;
}

// ─── S08 Targeted Correction (T05 impacted scope + recompute) ──────────────

export type CorrectionKind = "reassign" | "candidate_edit" | "merge" | "split";

export interface CorrectionImpactData {
  correction_type: string;
  affected_role_ids: string[];
  affected_occurrence_ids: string[];
  invalidated_suggestion_ids: string[];
  artifact_role_ids: string[];
  regenerate_suggestions: boolean;
  recompute_needed: boolean;
  counts: Record<string, number>;
}

export interface RecomputeState {
  recompute_needed: boolean;
  job_id: string | null;
  status: string | null;
  progress: number | null;
  error: string | null;
}

export interface ObjectCorrection {
  id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  correction_type: CorrectionKind;
  status: "pending" | "applied" | "cancelled";
  request: Record<string, unknown>;
  impact: CorrectionImpactData;
  result: Record<string, unknown> | null;
  recompute_job_id: string | null;
  applied_at: string | null;
  idempotency_key: string | null;
  natural_key: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  recompute: RecomputeState | null;
}

export interface CorrectionCreateResult {
  correction: ObjectCorrection;
  created: boolean;
  status: string;
}

export interface CorrectionListResponse {
  workspace_id: string;
  limit: number;
  offset: number;
  total: number;
  corrections: ObjectCorrection[];
}

/** Canonical correction request payload (kind selects the field set). */
export interface CorrectionRequestPayload {
  kind: CorrectionKind;
  project_id: string;
  video_item_id: string;
  generation: string;  // reassign
  occurrence_id?: string;
  occurrence_revision?: number;
  source_role_id?: string;
  target_role_id?: string;
  // candidate_edit
  target?: "role" | "occurrence";
  role_id?: string;
  role_revision?: number;
  name?: string;
  role_kind?: string;
  description?: string;
  bbox?: BoundingBox;
  confidence?: number;
  review_state?: string;
  reasons?: string[];
  // merge / split
  target_revision?: number;
  source_role_ids?: string[];
  suggestion_id?: string | null;
  original_role_id?: string;
  note?: string;
  idempotency_key?: string;
}

// ─── S11 QC Review queue (T02B/T04A/T04B surfaces — T04D wrappers) ────────

export interface QcItemData {
  id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  segment_row_id: string | null;
  segment_logical_id: string | null;
  layer_ref_type: string;
  layer_ref_id: string;
  reason_code: string;
  evidence_window_key: string;
  evidence: Record<string, unknown>;
  status: string;
  severity: string;
  category: string;
  detector: string;
  detector_revision: string;
  confidence: number;
  confidence_source: string;
  checkpoint_ref: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface QcItemListParams {
  status?: string;
  severity?: string;
  category?: string;
  video_item_id?: string;
  limit?: number;
  offset?: number;
}

export interface QcItemListResponse {
  workspace_id: string;
  project_id: string;
  limit: number;
  offset: number;
  total: number;
  has_more: boolean;
  items: QcItemData[];
}

export interface QcNavigationData {
  qc_item_id: string;
  layer_ref_type: string;
  canonical_location: {
    scene_id: number | null;
    frame_index: number | null;
    timecode_ms: number | null;
    object_role_id: string | null;
    segment_row_id: string | null;
    segment_logical_id: string | null;
  };
  action: {
    kind: "navigate" | "explain";
    method: "GET";
    target: string | null;
    endpoint: string | null;
    code: string | null;
    reason: string | null;
  };
  renderer_route: string | null;
}

// ─── S11 Readiness aggregate (T05A payload — T05B additive wrapper) ───────

export type ReadinessStatus = "ready" | "blocked" | "not_run";

/** Canonical structured location of one blocker (mirrors T04A DTO). */
export interface ReadinessLocationData {
  scene_id: number | null;
  frame_index: number | null;
  timecode_ms: number | null;
  object_role_id: string | null;
  segment_row_id: string | null;
  segment_logical_id: string | null;
}

/** WS-07 navigation action — navigate (real target) or explain (no dead link). */
export interface ReadinessActionData {
  kind: "navigate" | "explain";
  method: "GET";
  target: string | null;
  endpoint: string | null;
  code: string | null;
  reason: string | null;
}

/** One unresolved blocker of a CURRENT check run (WS-07 full detail). */
export interface ReadinessBlockerData {
  qc_item_id: string;
  code: string;
  video_item_id: string;
  layer_ref_type: string;
  layer_ref_id: string;
  location: ReadinessLocationData;
  reason_vi: string;
  action_vi: string;
  action: ReadinessActionData;
}

/** Per-video fail-closed verdict (T03G check-run evidence). */
export interface ReadinessVideoData {
  video_item_id: string;
  status: ReadinessStatus;
  run_state: string;
  check_state_detail: string;
  zero_item_completion: boolean | null;
  latest_job_id: string | null;
  blockers: number;
}

/** GET /api/v2/projects/{project_id}/readiness (Decision F, GET-only). */
export interface ReadinessResponseData {
  status: ReadinessStatus;
  blockers: ReadinessBlockerData[];
  warning_count: number;
  videos: ReadinessVideoData[];
  policy_version: string;
  content_hash: string;
  computed_at: string;
}

// ─── S08 Grouping policy (T03-C1 backend-authoritative metadata) ──────────

export interface GroupingPolicyData {
  algorithm: string;
  algorithm_version: string;
  calibration_version: string;
  review_threshold: number;
  advisory: boolean;
  confidence_semantics: string[];
  note: string;
}

// ─── Durable Video Items (S03 — project video selector) ───────────────────

export interface ProjectVideoItem {
  video_item_id: string;
  project_id: string;
  workspace_id: string;
  title: string;
  position: number;
  status: string;
  source_artifact_id: string | null;
  duration_ms: number | null;
  width: number | null;
  height: number | null;
  fps_num: number | null;
  fps_den: number | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface VideoListResponse {
  project_id: string;
  workspace_id: string;
  active_only: boolean;
  videos: ProjectVideoItem[];
}

// ─── Durable v2 Project (S03 — production authority for project identity) ─

/** Durable SQLite Project DTO (S03-T02 GET /api/v2/projects). */
export interface DurableProjectData {
  project_id: string;
  workspace_id: string;
  name: string;
  description: string;
  status: string;
  source_channel_id: string | null;
  production_channel_id: string | null;
  default_output_profile: string | null;
  resume_step: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface DurableProjectListResponse {
  workspace_id: string;
  active_only: boolean;
  projects: DurableProjectData[];
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

  // ─── S08 Object Intelligence (T01 roles/occurrences) ───────────────────

  /** Paged Object Role summaries of one video item (infinite-load).
   *  ``kind`` (S08-A01) is an optional canonical-kind filter — one of the
   *  seven ObjectRole kinds; an unknown kind is a stable 422 from the
   *  backend (never a silent empty). */
  listObjectRoles: (
    videoItemId: string,
    opts?: { status?: string; kind?: ObjectRoleKind; limit?: number; offset?: number },
  ) =>
    apiFetch<ObjectRoleListResponse>(
      `/api/v2/object-intelligence/roles?video_item_id=${encodeURIComponent(videoItemId)}${opts?.status ? `&status=${encodeURIComponent(opts.status)}` : ""}${opts?.kind ? `&kind=${encodeURIComponent(opts.kind)}` : ""}&limit=${opts?.limit ?? 20}&offset=${opts?.offset ?? 0}`,
    ),

  /** Canonical seven-kind ObjectRole taxonomy (S08-A01). */
  getObjectRoleKinds: () =>
    apiFetch<RoleKindsResponse>("/api/v2/object-intelligence/kinds"),

  getObjectRole: (roleId: string) =>
    apiFetch<ObjectRole>(`/api/v2/object-intelligence/roles/${roleId}`),

  // ─── S08 Object Extraction (T02 durable job) ───────────────────────────

  /** Submit one durable DISCOVER_OBJECTS job (provider resolved by the
   *  backend: production default fails closed, QA env may select the
   *  deterministic adapter explicitly). */
  submitObjectExtraction: (req: {
    projectId: string;
    videoItemId: string;
    generation?: string;
    sourceSha256?: string | null;
  }) =>
    apiFetch<ExtractionSubmitResult>("/api/v2/object-intelligence/extraction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: req.projectId,
        video_item_id: req.videoItemId,
        generation: req.generation ?? "1",
        source_sha256: req.sourceSha256 ?? null,
      }),
    }),

  /** Read-only job status + published outputs (empty until completed). */
  getExtractionJob: (jobId: string) =>
    apiFetch<ExtractionJob>(`/api/v2/object-intelligence/extraction/${jobId}`),

  /** Committed output set of a terminal extraction job (409 while active). */
  getExtractionOutputs: (jobId: string) =>
    apiFetch<ExtractionOutputsResult>(
      `/api/v2/object-intelligence/extraction/${jobId}/outputs`,
    ),

  /**
   * Backend-authoritative lookup of the CURRENT completed extraction for a
   * video item (404 when none). source_generation filters so a source
   * replacement NEVER surfaces previous-generation media. Browser storage is
   * never required — the backend is the authority.
   */
  getCurrentExtraction: (videoItemId: string, sourceGeneration?: string) =>
    apiFetch<ExtractionJob>(
      `/api/v2/object-intelligence/extraction/current?video_item_id=${encodeURIComponent(videoItemId)}${sourceGeneration ? `&source_generation=${encodeURIComponent(sourceGeneration)}` : ""}`,
    ),

  /** Backend-authoritative grouping policy (thresholds/semantics metadata). */
  getGroupingPolicy: () =>
    apiFetch<GroupingPolicyData>("/api/v2/object-intelligence/grouping/policy"),

  /** Video Items of a project (S03) — powers the multi-video selector. */
  listProjectVideos: (projectId: string) =>
    apiFetch<VideoListResponse>(`/api/v2/projects/${encodeURIComponent(projectId)}/videos`),

  /** Durable v2 project (backend-authoritative identity; 404 if unknown). */
  getDurableProject: (projectId: string) =>
    apiFetch<DurableProjectData>(`/api/v2/projects/${encodeURIComponent(projectId)}`),

  /** Durable v2 project list (SQLite only — never the legacy project dirs). */
  listDurableProjects: (activeOnly = true) =>
    apiFetch<DurableProjectListResponse>(`/api/v2/projects?active_only=${activeOnly}`),

  // ─── S08 Grouping (T03 suggestions + curation) ─────────────────────────

  /** Deterministic grouping run — always creates pending suggestions. */
  generateGroupingSuggestions: (
    videoItemId: string,
    sourceGeneration: string,
    idempotencyKey?: string,
  ) =>
    apiFetch<GenerateSuggestionsResult>(
      "/api/v2/object-intelligence/grouping/suggestions/generate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_item_id: videoItemId,
          source_generation: sourceGeneration,
          scope: "video",
          algorithm_version: "1",
          idempotency_key: idempotencyKey ?? null,
        }),
      },
    ),

  listGroupingSuggestions: (videoItemId: string, status = "pending", limit = 200) =>
    apiFetch<SuggestionListResponse>(
      `/api/v2/object-intelligence/grouping/suggestions?video_item_id=${encodeURIComponent(videoItemId)}&status=${encodeURIComponent(status)}&limit=${limit}`,
    ),

  /** Explicit rejection of one pending suggestion (CAS). */
  dismissSuggestion: (suggestionId: string, revision: number) =>
    apiFetch<GroupingSuggestion>(
      `/api/v2/object-intelligence/grouping/suggestions/${suggestionId}/dismiss`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision }),
      },
    ),

  /** Explicit durable confirm of one role (CAS + audit + idempotent replay). */
  confirmObjectRole: (
    roleId: string,
    videoItemId: string,
    revision: number,
    idempotencyKey?: string,
    note?: string,
  ) =>
    apiFetch<ConfirmResult>(
      `/api/v2/object-intelligence/grouping/roles/${roleId}/confirm`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision,
          video_item_id: videoItemId,
          idempotency_key: idempotencyKey ?? null,
          note: note ?? null,
        }),
      },
    ),

  /** Explicit durable merge of source roles into the target (CAS + audit). */
  mergeObjectRoles: (
    targetRoleId: string,
    videoItemId: string,
    revision: number,
    sourceRoleIds: string[],
    opts?: { suggestionId?: string | null; idempotencyKey?: string; note?: string },
  ) =>
    apiFetch<MergeResult>(
      `/api/v2/object-intelligence/grouping/roles/${targetRoleId}/merge`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision,
          video_item_id: videoItemId,
          source_role_ids: sourceRoleIds,
          suggestion_id: opts?.suggestionId ?? null,
          idempotency_key: opts?.idempotencyKey ?? null,
          note: opts?.note ?? null,
        }),
      },
    ),

  /** Explicit durable split of one merged original role out of the target. */
  splitObjectRole: (
    targetRoleId: string,
    videoItemId: string,
    revision: number,
    originalRoleId: string,
    opts?: { idempotencyKey?: string; note?: string },
  ) =>
    apiFetch<SplitResult>(
      `/api/v2/object-intelligence/grouping/roles/${targetRoleId}/split`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision,
          video_item_id: videoItemId,
          original_role_id: originalRoleId,
          idempotency_key: opts?.idempotencyKey ?? null,
          note: opts?.note ?? null,
        }),
      },
    ),

  /** Read-only curation audit history. */
  listGroupingOperations: (videoItemId: string, limit = 100) =>
    apiFetch<OperationListResponse>(
      `/api/v2/object-intelligence/grouping/operations?video_item_id=${encodeURIComponent(videoItemId)}&limit=${limit}`,
    ),

  // ─── S08 Targeted Correction (T05 impacted scope + recompute) ───────────

  /** Pre-confirmation impacted-scope report — ZERO durable writes. */
  previewCorrection: (req: CorrectionRequestPayload) =>
    apiFetch<CorrectionImpactData>("/api/v2/object-intelligence/corrections/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  /** Create the durable pending correction (natural-key replay -> 200). */
  createCorrection: (req: CorrectionRequestPayload) =>
    apiFetch<CorrectionCreateResult>("/api/v2/object-intelligence/corrections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  /** Apply the pending correction exactly once (atomic CAS). */
  confirmCorrection: (correctionId: string, revision: number) =>
    apiFetch<ObjectCorrection>(
      `/api/v2/object-intelligence/corrections/${correctionId}/confirm`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision }),
      },
    ),

  /** Read-only correction status (recompute outcome follows the successor chain). */
  getCorrection: (correctionId: string) =>
    apiFetch<ObjectCorrection>(`/api/v2/object-intelligence/corrections/${correctionId}`),

  /** Read-only correction history of one video item. */
  listCorrections: (videoItemId: string, limit = 50) =>
    apiFetch<CorrectionListResponse>(
      `/api/v2/object-intelligence/corrections?video_item_id=${encodeURIComponent(videoItemId)}&limit=${limit}`,
    ),

  /** Cancel: pending correction -> durable CAS cancel; applied -> durable job cancel. */
  cancelCorrection: (correctionId: string, revision: number) =>
    apiFetch<ObjectCorrection>(
      `/api/v2/object-intelligence/corrections/${correctionId}/cancel`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision }),
      },
    ),

  /** Retry the recompute work: successor Job (contract §6.4), idempotent. */
  retryCorrectionRecompute: (correctionId: string) =>
    apiFetch<ObjectCorrection>(
      `/api/v2/object-intelligence/corrections/${correctionId}/recompute/retry`,
      { method: "POST" },
    ),

  // ─── S11 QC Review queue (T02B/T04A/T04B — T04D additive wrappers) ───────

  /** Paged queue list of one project (lane-C G1: filters + deterministic order). */
  listQcItems: (projectId: string, opts: QcItemListParams = {}) => {
    const params = new URLSearchParams();
    if (opts.status) params.set("status", opts.status);
    if (opts.severity) params.set("severity", opts.severity);
    if (opts.category) params.set("category", opts.category);
    if (opts.video_item_id) params.set("video_item_id", opts.video_item_id);
    params.set("limit", String(opts.limit ?? 50));
    params.set("offset", String(opts.offset ?? 0));
    return apiFetch<QcItemListResponse>(
      `/api/v2/projects/${encodeURIComponent(projectId)}/qc-items?${params.toString()}`,
    );
  },

  /** One QCItem + its evidence refs (lane-C G2 detail shape). */
  getQcItem: (itemId: string) =>
    apiFetch<QcItemData>(`/api/v2/qc-items/${encodeURIComponent(itemId)}`),

  /** Canonical location + 1-1 navigation target (T04A / G13). */
  getQcNavigation: (itemId: string) =>
    apiFetch<QcNavigationData>(`/api/v2/qc-navigation/${encodeURIComponent(itemId)}`),

  /**
   * corrections-link (T04B consume pattern): map ONE QCItem to the S08-T05
   * pipeline request payload — candidate_edit on the occurrence anchored by
   * the item's STRUCTURED evidence (bridge build_correction_request mirror;
   * occurrence CAS from evidence, generation from the live role).
   */
  buildQcCorrectionRequest: (
    item: QcItemData,
    role: { source_generation: string } | null,
  ): CorrectionRequestPayload | null => {
    const evidence = item.evidence ?? {};
    const roleId = typeof evidence.object_role_id === "string" ? evidence.object_role_id : null;
    const occurrenceId =
      typeof evidence.occurrence_id === "string" ? evidence.occurrence_id : null;
    if (!roleId || !occurrenceId) return null;
    const occurrenceRevision =
      typeof evidence.occurrence_revision === "number" && !Number.isNaN(evidence.occurrence_revision)
        ? evidence.occurrence_revision
        : undefined;
    return {
      kind: "candidate_edit",
      project_id: item.project_id,
      video_item_id: item.video_item_id,
      generation: role?.source_generation ?? "1",
      target: "occurrence",
      role_id: roleId,
      occurrence_id: occurrenceId,
      occurrence_revision: occurrenceRevision,
      review_state: "rejected",
      reasons: [`qc:${item.reason_code}`],
      idempotency_key: `qc-item:${item.id}`,
    };
  },

  /**
   * Compute-on-the-fly project readiness aggregate (T05A / Decision F —
   * GET-only).  Returns the fail-closed verdict ready|blocked|not_run plus
   * the WS-07 blocker list (location/reason/action) and per-video check-run
   * evidence; the UI never mutates anything here.
   */
  getReadiness: (projectId: string) =>
    apiFetch<ReadinessResponseData>(
      `/api/v2/projects/${encodeURIComponent(projectId)}/readiness`,
    ),

// ─── S07 Project Cast (T02 picker + compatibility) ───────────────────────

  /** Picker browse: only published/usable Pack Versions, search/filter, deterministic. */
  listPickerPacks: (opts?: { q?: string; limit?: number; offset?: number }) =>
    apiFetch<PickerPacksResponse>(
      `/api/v2/project-cast/picker/packs?limit=${opts?.limit ?? 50}&offset=${opts?.offset ?? 0}${opts?.q ? `&q=${encodeURIComponent(opts.q)}` : ""}`,
    ),

  /** Deterministic compatibility evaluate (pure, no mutation). */
  evaluateCastCompatibility: (req: {
    project_id: string;
    object_role_id: string;
    pack_version_id: string;
    expected_revision?: number | null;
    mapping_id?: string | null;
  }) =>
    apiFetch<CompatibilityEvaluateResponse>(`/api/v2/project-cast/compatibility/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: req.project_id,
        object_role_id: req.object_role_id,
        pack_version_id: req.pack_version_id,
        expected_revision: req.expected_revision ?? null,
        mapping_id: req.mapping_id ?? null,
      }),
    }),

  /** Project Cast Mapping CRUD (S07-T01). */
  listProjectCastMappings: (projectId: string, limit = 50, offset = 0) =>
    apiFetch<ProjectCastListResponse>(
      `/api/v2/project-cast?project_id=${encodeURIComponent(projectId)}&limit=${limit}&offset=${offset}`,
    ),

  getProjectCastMapping: (mappingId: string) =>
    apiFetch<ProjectCastData>(`/api/v2/project-cast/${mappingId}`),

  createProjectCastMapping: (req: {
    project_id: string;
    object_role_id: string;
    character_id: string;
    pack_version_id: string;
    idempotency_key?: string | null;
    fallback_acknowledged?: boolean;
  }) =>
    apiFetch<ProjectCastData>(`/api/v2/project-cast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  updateProjectCastMapping: (mappingId: string, req: { revision: number; character_id?: string | null; pack_version_id?: string | null; fallback_acknowledged?: boolean }) =>
    apiFetch<ProjectCastData>(`/api/v2/project-cast/${mappingId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  // ─── S10 Full Apply (T01C + T04A structural-compare) ─────────────────────

  /** Server-derived Full Apply eligibility of ONE approval checkpoint
   *  (mirrors GET /api/v2/s09-approvals/{id}/full-apply-authority).
   *  A v1 checkpoint fails closed with 422 REAPPROVAL_REQUIRED (detail carries
   *  the reason); a tampered v2 row fails closed 500; not found 404. */
  getFullApplyAuthority: (checkpointId: string, workspaceId = "default") =>
    apiFetch<{
      checkpoint_id: string;
      snapshot_schema: string;
      verified: boolean;
      eligibility: {
        full_apply_executable: boolean;
        reasons: string[];
        unsupported_routes: string[];
      };
      full_apply_authority: Record<string, unknown>;
    }>(
      `/api/v2/s09-approvals/${encodeURIComponent(checkpointId)}/full-apply-authority?workspace_id=${encodeURIComponent(workspaceId)}`,
    ),

  /** S10 FullApply run status — mirrors GET /api/v2/full-apply/{run_id}. */
  getS10FullApplyStatus: (runId: string, workspaceId = "default", projectId?: string) =>
    apiFetch<{
      run_id: string;
      workspace_id: string;
      project_id: string;
      video_item_id: string;
      apply_checkpoint_id: string;
      apply_checkpoint_hash: string;
      apply_checkpoint_revision: number;
      plan_id: string;
      plan_hash: string;
      status: string;
      frame_count: number;
      attempt: number;
      natural_key: string | null;
      idempotency_key: string | null;
      chunks: Array<{
        id: string;
        workspace_id: string;
        run_id: string;
        chunk_index: number;
        order_index: number;
        shot_id: string;
        layer_id: string | null;
        object_role_id: string | null;
        core_start_frame: number;
        core_end_frame: number;
        overlap_before: number;
        overlap_after: number;
        content_hash: string;
        state: string;
        attempt: number;
        artifact_id: string | null;
        verified: boolean;
      }>;
      publications: Array<{
        id: string;
        workspace_id: string;
        run_id: string;
        artifact_id: string;
        content_hash: string;
        frame_count: number;
        frame_metadata: Record<string, unknown>;
        checkpoint_id: string;
        checkpoint_hash: string;
        checkpoint_revision: number;
        state: string;
      }>;
      checkpoint: Record<string, unknown> | null;
    }>(
      `/api/v2/full-apply/${encodeURIComponent(runId)}?workspace_id=${encodeURIComponent(workspaceId)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`,
    ),

  submitS10FullApply: (
    projectId: string,
    body: {
      /** Minimal public identity/CAS contract — server derives the plan and
       *  render authority exclusively from the frozen v2 checkpoint. */
      video_item_id: string;
      apply_checkpoint_id: string;
      expected_checkpoint_hash: string;
      expected_checkpoint_revision: number;
      /** Bounded chunk/idempotency controls (optional, server defaults). */
      chunk_config?: Record<string, unknown> | null;
      chunk_frames?: number | null;
      overlap_frames?: number | null;
      fps_num?: number | null;
      fps_den?: number | null;
      idempotency_key?: string | null;
      natural_key?: string | null;
      /** Legacy authority copies kept OPTIONAL for canonical-compare
       *  compatibility only: if supplied the server compares each field
       *  against the frozen v2 authority and rejects ANY mismatch before a
       *  run/job is created (fail closed, zero mutation). The Apply UI never
       *  sends these — server authority is the only truth. */
      approved_checkpoint?: Record<string, unknown> | null;
      structural_lock_manifest?: Record<string, unknown> | null;
      scene_manifest?: unknown;
      mapping?: unknown;
      compatibility_policy?: Record<string, unknown> | null;
    },
    workspaceId = "default",
  ) =>
    apiFetch<{
      run_id: string;
      workspace_id: string;
      project_id: string;
      status: string;
      created: boolean;
      plan_id: string;
      plan_hash: string;
      frame_count: number;
      reused: boolean;
    }>(`/api/v2/projects/${encodeURIComponent(projectId)}/full-apply?workspace_id=${encodeURIComponent(workspaceId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  cancelS10FullApply: (runId: string, workspaceId = "default", projectId?: string) =>
    apiFetch<{ run_id: string; status: string; cancelled: boolean }>(
      `/api/v2/full-apply/${encodeURIComponent(runId)}/cancel?workspace_id=${encodeURIComponent(workspaceId)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`,
      { method: "POST" },
    ),

  retryS10FullApply: (runId: string, workspaceId = "default", projectId?: string) =>
    apiFetch<{ run_id: string; predecessor_run_id: string; status: string; attempt: number }>(
      `/api/v2/full-apply/${encodeURIComponent(runId)}/retry?workspace_id=${encodeURIComponent(workspaceId)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`,
      { method: "POST" },
    ),

  resumeS10FullApply: (runId: string, workspaceId = "default", projectId?: string) =>
    apiFetch<{ run_id: string; status: string; resumed: boolean }>(
      `/api/v2/full-apply/${encodeURIComponent(runId)}/resume?workspace_id=${encodeURIComponent(workspaceId)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`,
      { method: "POST" },
    ),

  structuralCompareS10: (
    runId: string,
    body: Record<string, unknown>,
    workspaceId = "default",
    projectId?: string,
  ) =>
    apiFetch<{
      status: string;
      passed: boolean;
      failures: Array<{
        code: string;
        reason: string;
        role: string;
        layer: string;
        segment: string;
        route: string;
        metric: string;
        value: unknown;
        threshold: unknown;
      }>;
      checks: Record<string, unknown>;
      policy_version: string | null;
      expected_policy_version: string | null;
      run_id: string;
      workspace_id: string;
    }>(`/api/v2/full-apply/${encodeURIComponent(runId)}/structural-compare?workspace_id=${encodeURIComponent(workspaceId)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
