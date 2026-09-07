/**
 * S12 export API client.
 *
 * Paths and payloads mirror app/api/routes/s12_export.py and
 * app/api/routes/s12_export_preflight.py. The client intentionally keeps
 * backend field names so pinned identity is visible at the call site.
 */

import { ApiError } from "./api";

export { ApiError } from "./api";

declare const process: { env: { NEXT_PUBLIC_API_URL?: string } };

const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
const API_BASE = rawApiUrl.replace(/\/+$/, "");

export const S12_EXPORT_REASON_CODES = [
  "S12_EXPORT_OK",
  "S12_EXPORT_NOT_READY",
  "S12_EXPORT_SOURCE_MISSING",
  "S12_EXPORT_SOURCE_NOT_READY",
  "S12_EXPORT_SOURCE_PARTIAL",
  "S12_EXPORT_LOCK_MISSING",
  "S12_EXPORT_STALE_CHECKPOINT",
  "S12_EXPORT_STALE_POLICY",
  "S12_EXPORT_CROSS_PROJECT",
  "S12_EXPORT_UNSUPPORTED_PROFILE",
  "S12_EXPORT_ASPECT_MISMATCH",
  "S12_EXPORT_DISK_INSUFFICIENT",
  "S12_EXPORT_UNKNOWN_PROJECT",
  "S12_EXPORT_UNKNOWN_VIDEO",
] as const;

export type S12ExportReasonCode = (typeof S12_EXPORT_REASON_CODES)[number];

export type S12ExportProfileId =
  | "master-4k-h264"
  | "master-4k-hevc"
  | "preview-1080p-h264";

export type S12ExportAspectHandling = "passthrough" | "letterbox" | "fail_closed";
export type S12ExportSourceKind = "native_4k" | "upscale_4k" | "below_4k";
export type S12ExportRunStatus =
  | "pending"
  | "running"
  | "verifying"
  | "completed"
  | "failed"
  | "cancelled";
export type S12ExportChunkState = "pending" | "running" | "completed" | "failed" | "skipped";
export type S12ExportJobState =
  | "pending"
  | "queued"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";

export interface S12ExportCheckpointPin {
  checkpoint_id: string;
  checkpoint_hash: string;
  checkpoint_revision: number;
}

export interface S12ExportLockPin {
  manifest_id: string;
  manifest_hash: string;
  source_generation: string;
}

export interface S12ExportPreflightBody {
  video_item_id: string;
  profile_id?: S12ExportProfileId;
  aspect_handling?: S12ExportAspectHandling;
  checkpoint: S12ExportCheckpointPin;
  lock: S12ExportLockPin;
}

export interface S12ExportProfile {
  profile_id: S12ExportProfileId;
  width: number;
  height: number;
  codec: "h264" | "hevc";
  upscale_method: string | null;
  supported: boolean;
  support_basis: string | null;
}

export interface S12ExportPreflightCheck {
  name: string;
  passed: boolean;
  reason: S12ExportReasonCode;
  detail: string;
}

export interface S12ExportPreflightResponse {
  contract_version: string;
  project_id: string;
  video_item_id: string;
  profile: S12ExportProfile;
  source_kind: S12ExportSourceKind;
  source_width: number | null;
  source_height: number | null;
  eligible: boolean;
  reasons: S12ExportReasonCode[];
  checks: S12ExportPreflightCheck[];
  estimate_bytes: number | null;
  estimate_basis: string;
  readiness_status: string;
  readiness_policy: string;
}

/** Immutable lineage and render pins accepted by POST /s12-exports/submit. */
export interface S12ExportSubmitPins {
  checkpoint_id: string;
  checkpoint_hash: string;
  checkpoint_revision: number;
  manifest_id: string;
  manifest_hash: string;
  manifest_generation: string;
  profile_id: string;
  plan_id: string;
  plan_hash: string;
  frame_count: number;
}

export interface S12ExportSubmitBody extends S12ExportSubmitPins {
  project_id: string;
  video_item_id: string;
  chunk_config?: Record<string, unknown>;
  source_path: string;
  fps: number;
  chunk_dir: string;
  scratch_dir: string;
  output_path: string;
  audio_source?: string | null;
  idempotency_key?: string | null;
}

/** Alias matching the backend route's request terminology. */
export type S12ExportSubmitRequest = S12ExportSubmitBody;

export interface S12ExportChunkStatus {
  chunk_index: number;
  state: S12ExportChunkState;
  verified: 0 | 1;
  attempt: number;
}

export interface S12ExportRunStatusPayload {
  run_id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  profile_id: string;
  plan_id: string;
  plan_hash: string;
  status: S12ExportRunStatus;
  frame_count: number;
  attempt: number;
  revision: number;
  job_id: string | null;
  job_state: S12ExportJobState | null;
  chunks: S12ExportChunkStatus[];
}

export interface S12ExportSubmitResult {
  run_id: string;
  status: S12ExportRunStatus;
  job_id: string | null;
  job_state: S12ExportJobState | null;
  created: boolean;
}

export interface S12ExportCancelResult {
  run_id: string;
  status: "cancelled";
  cancelled: boolean;
  job_state: S12ExportJobState | null;
}

export interface S12ExportRetryResult {
  run_id: string;
  predecessor_run_id: string;
  status: S12ExportRunStatus;
  attempt: number;
  job_id: string | null;
  created: boolean;
}

export interface S12ExportErrorCopy {
  message: string;
  action: string;
}

export type S12ExportHttpErrorStatus = 404 | 409 | 422;

export const S12_EXPORT_HTTP_ERROR_COPY: Readonly<
  Record<S12ExportHttpErrorStatus, S12ExportErrorCopy>
> = {
  404: {
    message: "Không tìm thấy project, video hoặc export run được yêu cầu.",
    action: "Kiểm tra lại project_id, video_item_id, run_id và workspace rồi thử lại.",
  },
  409: {
    message: "Yêu cầu export xung đột với trạng thái hoặc công việc đang tồn tại.",
    action: "Tải lại trạng thái; không tạo job trùng và chỉ retry khi run đã failed hoặc cancelled.",
  },
  422: {
    message: "Dữ liệu export không hợp lệ hoặc preflight bị từ chối.",
    action: "Kiểm tra lại các pin checkpoint/manifest, profile, aspect và các trường bắt buộc.",
  },
};

export const S12_EXPORT_REASON_COPY: Readonly<
  Record<S12ExportReasonCode, S12ExportErrorCopy>
> = {
  S12_EXPORT_OK: {
    message: "Preflight export hợp lệ.",
    action: "Có thể tiếp tục gửi export với đúng các pin đã được kiểm tra.",
  },
  S12_EXPORT_NOT_READY: {
    message: "Project chưa sẵn sàng để export.",
    action: "Hoàn tất các bước readiness bắt buộc rồi chạy preflight lại.",
  },
  S12_EXPORT_SOURCE_MISSING: {
    message: "Không tìm thấy source media của video.",
    action: "Khôi phục hoặc chọn lại source media rồi chạy preflight lại.",
  },
  S12_EXPORT_SOURCE_NOT_READY: {
    message: "Source media chưa ở trạng thái sẵn sàng.",
    action: "Chờ source media hoàn tất xử lý rồi chạy preflight lại.",
  },
  S12_EXPORT_SOURCE_PARTIAL: {
    message: "Source media là file partial và không được coi là hoàn tất.",
    action: "Chờ bản source đầy đủ, không dùng đường dẫn có hậu tố .partial.",
  },
  S12_EXPORT_LOCK_MISSING: {
    message: "Không tìm thấy structural-lock manifest được pin.",
    action: "Tạo hoặc chọn manifest đúng video rồi cập nhật lock pin.",
  },
  S12_EXPORT_STALE_CHECKPOINT: {
    message: "Checkpoint đã cũ hoặc hash/revision không khớp.",
    action: "Chọn checkpoint mới nhất và gửi lại đúng checkpoint_hash cùng revision.",
  },
  S12_EXPORT_STALE_POLICY: {
    message: "Chính sách readiness đã thay đổi và không còn hiện hành.",
    action: "Tải lại readiness, tạo pin hợp lệ và chạy preflight lại.",
  },
  S12_EXPORT_CROSS_PROJECT: {
    message: "Một pin export thuộc project khác.",
    action: "Chọn checkpoint, video và manifest cùng một project/workspace.",
  },
  S12_EXPORT_UNSUPPORTED_PROFILE: {
    message: "Profile export không được hỗ trợ.",
    action: "Chọn profile được backend báo supported rồi chạy preflight lại.",
  },
  S12_EXPORT_ASPECT_MISMATCH: {
    message: "Tỷ lệ khung hình không phù hợp với chính sách export.",
    action: "Chọn aspect_handling hợp lệ hoặc xử lý source trước khi export.",
  },
  S12_EXPORT_DISK_INSUFFICIENT: {
    message: "Không đủ dung lượng đĩa cho export.",
    action: "Giải phóng dung lượng ở vùng lưu trữ rồi chạy preflight lại.",
  },
  S12_EXPORT_UNKNOWN_PROJECT: {
    message: "Không tìm thấy project.",
    action: "Kiểm tra project_id và workspace rồi thử lại.",
  },
  S12_EXPORT_UNKNOWN_VIDEO: {
    message: "Không tìm thấy video trong project.",
    action: "Kiểm tra video_item_id và chọn video thuộc đúng project.",
  },
};

export const S12_EXPORT_GENERIC_ERROR_COPY: S12ExportErrorCopy = {
  message: "Export gặp lỗi từ backend.",
  action: "Giữ nguyên run_id/job_id, tải lại trạng thái và liên hệ hỗ trợ nếu lỗi lặp lại.",
};

/** Resolve the approved Vietnamese message/action for an S12 API error. */
export function getS12ExportErrorCopy(error: unknown): S12ExportErrorCopy {
  if (!(error instanceof ApiError)) return S12_EXPORT_GENERIC_ERROR_COPY;
  const detail = error.detailText();
  const reason = S12_EXPORT_REASON_CODES.find((code) => detail.includes(code));
  if (reason) return S12_EXPORT_REASON_COPY[reason];
  if (error.status === 404 || error.status === 409 || error.status === 422) {
    return S12_EXPORT_HTTP_ERROR_COPY[error.status];
  }
  return S12_EXPORT_GENERIC_ERROR_COPY;
}

/**
 * Completion truth is status-only: completed derives only from status
 * "completed"; an output or source with a .partial suffix never counts as
 * completed.
 */
export function isS12ExportCompleted(status: S12ExportRunStatus): boolean {
  return status === "completed";
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
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

function withQuery(
  path: string,
  params: Record<string, string | undefined>,
): string {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value as string)}`)
    .join("&");
  return query ? `${path}?${query}` : path;
}

export function preflightExport(
  projectId: string,
  body: S12ExportPreflightBody,
): Promise<S12ExportPreflightResponse> {
  return apiFetch<S12ExportPreflightResponse>(
    `/api/v2/projects/${encodeURIComponent(projectId)}/export/preflight`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function submitExport(
  body: S12ExportSubmitBody,
  workspaceId = "default",
): Promise<S12ExportSubmitResult> {
  return apiFetch<S12ExportSubmitResult>(
    withQuery("/s12-exports/submit", { workspace_id: workspaceId }),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function exportStatus(
  runId: string,
  workspaceId = "default",
  projectId?: string,
): Promise<S12ExportRunStatusPayload> {
  return apiFetch<S12ExportRunStatusPayload>(
    withQuery(`/s12-exports/${encodeURIComponent(runId)}`, {
      workspace_id: workspaceId,
      project_id: projectId,
    }),
  );
}

export function cancelExport(
  runId: string,
  workspaceId = "default",
  projectId?: string,
): Promise<S12ExportCancelResult> {
  return apiFetch<S12ExportCancelResult>(
    withQuery(`/s12-exports/${encodeURIComponent(runId)}/cancel`, {
      workspace_id: workspaceId,
      project_id: projectId,
    }),
    { method: "POST" },
  );
}

export function retryExport(
  runId: string,
  workspaceId = "default",
  projectId?: string,
): Promise<S12ExportRetryResult> {
  return apiFetch<S12ExportRetryResult>(
    withQuery(`/s12-exports/${encodeURIComponent(runId)}/retry`, {
      workspace_id: workspaceId,
      project_id: projectId,
    }),
    { method: "POST" },
  );
}
