/**
 * MF-END-10 — typed client cho kho tham chiếu + gợi ý bộ cast.
 *
 * CHỈ gọi các endpoint đã tồn tại trong tree này (không tự bịa route mới):
 *  - POST /api/v2/project-cast/recommendations              (MF-END-06, READ-ONLY)
 *  - POST /api/v2/project-cast/recommendations/confirm      (MF-END-07, mutation duy nhất)
 *  - POST /api/v2/characters/versions/{id}/reference-artwork        (MF-END-03, nhập ảnh có tác giả)
 *  - POST /api/v2/characters/versions/{id}/reference-asset-jobs     (MF-END-09, tạo asset thiếu)
 *  - GET|cancel|retry /api/v2/characters/reference-asset-jobs/{id}  (MF-END-09 trạng thái)
 *  - GET /api/v2/object-intelligence/roles/{roleId}         (resolve video_item_id của role)
 *
 * Bản đồ route này được test khoá lại bằng chuỗi ký tự trong
 * `tests/product_delivery/test_mf_end_10.py` (static contract) và bằng
 * OpenAPI của app thật (runtime contract).
 */

import { ApiError } from "@/lib/api";

const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
const API_BASE = rawApiUrl.replace(/\/+$/, "");

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const res = await fetch(`${API_BASE}${cleanPath}`, { ...options });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail: unknown = text;
    if (text) {
      try {
        const body: unknown = JSON.parse(text);
        detail =
          typeof body === "object" && body !== null && "detail" in body
            ? (body as { detail: unknown }).detail
            : body;
      } catch {
        detail = text;
      }
    }
    throw new ApiError(res.status, detail, `API ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/* ─── Kiểu dữ liệu (khớp DTO backend, không thêm field lạ) ──────────────── */

export type SelectionMode = "series_pin" | "advisory" | "metadata" | "none";

export interface CandidateReason {
  code: string;
  detail: string;
}

export interface SeriesPinInfo {
  snapshot_id: string;
  snapshot_index: number;
  entries_sha256: string;
  live_ok: boolean;
  problems: string[];
}

export interface CastCandidate {
  pack_version_id: string;
  pack_version: number;
  character_id: string;
  character_name: string;
  character_code: string;
  character_type: string;
  pack_contract_version: string;
  source: "series_snapshot" | "library";
  snapshot_id: string | null;
  snapshot_index: number | null;
  live_ok: boolean | null;
  live_problems: string[];
  rank: number;
  available_views: string[];
  missing_views: string[];
  covers_required_views: boolean;
  missing_capabilities: string[];
  style_version: string | null;
  style_match: boolean | null;
  reasons: CandidateReason[];
}

export interface FilteredPack {
  pack_version_id: string;
  character_id: string;
  character_name: string;
  reasons: CandidateReason[];
}

export interface GenerationPlan {
  required: boolean;
  views: string[];
  estimated_cost_units: number;
  unit: string;
  note: string;
}

export interface RoleAdvisory {
  status: "not_requested" | "not_needed" | "ok" | "unavailable";
  requested: boolean;
  calls: number;
  choice_pack_version_id: string | null;
  choice_applied: boolean;
  error: string | null;
  notes: CandidateReason[];
}

export interface RoleRecommendation {
  role_key: string;
  object_role_id: string | null;
  kind: string;
  required_views: string[];
  required_capabilities: string[];
  style_version: string | null;
  series_pin: SeriesPinInfo | null;
  candidates: CastCandidate[];
  filtered: FilteredPack[];
  selected_pack_version_id: string | null;
  selected_character_id: string | null;
  selection_mode: SelectionMode;
  missing_views: string[];
  generation: GenerationPlan;
  advisory: RoleAdvisory;
}

export interface CastRecommendationResult {
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  series: {
    snapshot_id: string;
    snapshot_index: number;
    entries_sha256: string;
    role_keys: string[];
  } | null;
  roles: RoleRecommendation[];
  advisory: {
    status: string;
    route: { provider: string; model: string; api_mode: string; fallback_allowed: boolean };
    calls: number;
    error: string | null;
  };
  read_only: boolean;
  mutations: number;
  manual_choice_available: boolean;
}

export interface CastConfirmTrace {
  role_key: string;
  selection_mode: "series_pin" | "advisory" | "metadata" | "manual";
  selected_pack_version_id: string;
  required_views: string[];
  required_capabilities: string[];
  style_version?: string | null;
  series_snapshot_id?: string | null;
  series_snapshot_index?: number | null;
  series_entries_sha256?: string | null;
}

export interface CastConfirmRequest {
  video_item_id: string;
  object_role_id: string;
  character_id: string;
  pack_version_id: string;
  idempotency_key: string;
  expected_revision?: number;
  fallback_acknowledged?: boolean;
  recommendation: CastConfirmTrace;
}

export interface CastConfirmWarning {
  code: string;
  detail: string;
  action: string | null;
}

export interface CastConfirmResult {
  workspace_id: string;
  project_id: string;
  mapping: {
    id: string;
    workspace_id: string;
    project_id: string;
    object_role_id: string;
    character_id: string;
    pack_version_id: string;
    revision: number;
  };
  trace: {
    role_key: string;
    selection_mode: string;
    selected_pack_version_id: string;
    verified_source: "series_pin" | "library_candidate";
  };
  warnings: CastConfirmWarning[];
  missing_views: string[];
  generation: GenerationPlan;
  created: boolean;
  replayed: boolean;
  mutations: number;
  read_only: boolean;
}

export interface ReferenceArtworkResult {
  asset_id: string;
  version_id: string;
  character_id: string;
  workspace_id: string;
  reference_key: string;
  view: string;
  role: string;
  artifact_id: string;
  sha256: string;
  size_bytes: number;
  mime_type: string;
  width: number;
  height: number;
  decoded_mode: string;
  has_alpha: boolean;
  purpose: string;
  source_filename: string;
  replaced_existing: boolean;
  content_url: string | null;
}

export type ReferenceAssetJobState =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | string;

export interface ReferenceAssetJob {
  job_id: string;
  state: ReferenceAssetJobState;
  progress: number;
  message: string;
  job_type: string;
  content_key: string | null;
  reference_key: string | null;
  view: string | null;
  role: string | null;
  duplicate: boolean;
}

export interface ReferenceAssetJobSubmit {
  job: ReferenceAssetJob;
  content_key: string;
  reference_key: string;
  view: string;
  role: string;
  duplicate: boolean;
}

/* ─── Hàm gọi API ───────────────────────────────────────────────────────── */

/** Role thật của video — dùng để resolve `video_item_id` cho phần gợi ý. */
export function getObjectRole(roleId: string) {
  return apiFetch<{
    id: string;
    workspace_id: string;
    project_id: string;
    video_item_id: string;
    name: string;
    kind: string;
    status: string;
  }>(`/api/v2/object-intelligence/roles/${roleId}`);
}

/** Gợi ý bộ cast (READ-ONLY — không tạo/đổi pin nào). */
export function recommendCast(req: { video_item_id: string; advisory?: "auto" | "off" }) {
  return apiFetch<CastRecommendationResult>(`/api/v2/project-cast/recommendations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video_item_id: req.video_item_id,
      advisory: req.advisory ?? "auto",
    }),
  });
}

/** XÁC NHẬN một lựa chọn — thao tác ghi duy nhất của luồng chọn bộ. */
export function confirmCast(req: CastConfirmRequest) {
  return apiFetch<CastConfirmResult>(`/api/v2/project-cast/recommendations/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

/** Nhập ảnh tham chiếu có tác giả vào một phiên bản pack (draft). */
export function uploadReferenceArtwork(
  versionId: string,
  params: { reference_key: string; file: File; purpose?: string },
) {
  const form = new FormData();
  form.append("file", params.file);
  form.append("reference_key", params.reference_key);
  form.append("purpose", params.purpose ?? "artwork");
  return apiFetch<ReferenceArtworkResult>(
    `/api/v2/characters/versions/${versionId}/reference-artwork`,
    { method: "POST", body: form },
  );
}

/** Đăng ký ý định tạo asset tham chiếu còn thiếu (job bền vững, 202). */
export function submitReferenceAssetJob(
  versionId: string,
  req: {
    reference_key: string;
    view_prompt: string;
    source_reference_key?: string | null;
    style_version?: string | null;
    seed?: number | null;
    idempotency_key?: string | null;
  },
) {
  return apiFetch<ReferenceAssetJobSubmit>(
    `/api/v2/characters/versions/${versionId}/reference-asset-jobs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    },
  );
}

/** Trạng thái bền vững của một job tạo asset (kể cả khi mở lại app). */
export function getReferenceAssetJob(jobId: string) {
  return apiFetch<ReferenceAssetJob>(
    `/api/v2/characters/reference-asset-jobs/${encodeURIComponent(jobId)}`,
  );
}

export function cancelReferenceAssetJob(jobId: string) {
  return apiFetch<{ status: string; job_id: string }>(
    `/api/v2/characters/reference-asset-jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
  );
}

export function retryReferenceAssetJob(jobId: string, inputGeneration?: string) {
  return apiFetch<ReferenceAssetJobSubmit>(
    `/api/v2/characters/reference-asset-jobs/${encodeURIComponent(jobId)}/retry`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(inputGeneration ? { input_generation: inputGeneration } : {}),
    },
  );
}

/* ─── Tiện ích thuần (đơn vị nhỏ, dễ kiểm) ───────────────────────────────── */

/** Bộ 6 view lõi chấp nhận cho reference key (đồng bộ với CORE_POSE_SLOTS). */
export const REFERENCE_VIEWS = [
  "front",
  "three_quarter",
  "side",
  "back",
  "sitting",
  "walking",
] as const;

export type ReferenceView = (typeof REFERENCE_VIEWS)[number];

/** Role hợp lệ của reference key `<view>@<role>`. */
export const REFERENCE_ROLES = ["character", "prop", "other"] as const;

export const REFERENCE_VIEW_LABELS: Record<string, string> = {
  front: "Mặt trước",
  three_quarter: "Ba phần tư",
  side: "Nghiêng bên",
  back: "Sau lưng",
  sitting: "Ngồi",
  walking: "Đi bộ",
};

export const REFERENCE_ROLE_LABELS: Record<string, string> = {
  character: "Nhân vật",
  prop: "Đạo cụ",
  other: "Khác",
};

export function referenceKeyOf(view: string, role: string): string {
  return `${view}@${role}`;
}

/** Tách `<view>@<role>`; trả null cho pose legacy (không có `@`). */
export function parseReferenceKey(key: string): { view: string; role: string } | null {
  const parts = key.split("@");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  return { view: parts[0], role: parts[1] };
}

export function viewLabel(view: string): string {
  return REFERENCE_VIEW_LABELS[view] ?? view;
}

export function roleLabel(role: string): string {
  return REFERENCE_ROLE_LABELS[role] ?? role;
}
