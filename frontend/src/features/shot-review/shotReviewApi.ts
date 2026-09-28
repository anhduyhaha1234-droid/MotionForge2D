/**
 * MF-END-24 — shot-review API client.
 *
 * Talks ONLY to routes that exist on the running backend (the acceptance
 * test cross-checks every entry of SHOT_REVIEW_ENDPOINTS against the real
 * FastAPI route table — a route that is not served fails the suite).
 * Mirrors the error unwrapping of src/lib/api.ts so callers render the
 * real backend detail instead of a generic message.
 */

import type {
  ReviewPublication,
  ReviewChunk,
  QcMarkerInput,
  ScopedRetryPayload,
} from "./shotReviewLogic";

const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
const API_BASE = rawApiUrl.replace(/\/+$/, "");

/**
 * The exact backend surface this feature consumes.  Paths are FastAPI
 * templates; `{...}` segments are path params.  Keep in sync with
 * app/api/routes/{s10_full_apply,qc_items,qc_navigation}.py.
 */
export const SHOT_REVIEW_ENDPOINTS = [
  { method: "GET", path: "/api/v2/full-apply/{run_id}" },
  { method: "POST", path: "/api/v2/full-apply/{run_id}/cancel" },
  { method: "POST", path: "/api/v2/full-apply/{run_id}/retry" },
  { method: "POST", path: "/api/v2/full-apply/{run_id}/resume" },
  { method: "POST", path: "/api/v2/full-apply/{run_id}/recompute" },
  { method: "GET", path: "/api/v2/projects/{project_id}/qc-items" },
  { method: "GET", path: "/api/v2/qc-navigation/{item_id}" },
] as const;

export class ShotReviewApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API ${status}`);
    this.name = "ShotReviewApiError";
    this.status = status;
    this.detail = detail;
  }

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

async function reviewFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const res = await fetch(`${API_BASE}${cleanPath}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
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
    throw new ShotReviewApiError(res.status, detail, `API ${res.status}`);
  }
  return (await res.json()) as T;
}

function withQuery(path: string, params: Record<string, string | undefined>): string {
  const qs = Object.entries(params)
    .filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].length > 0)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  return qs ? `${path}?${qs}` : path;
}

export interface RunStatusPayload {
  run_id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  status: string;
  frame_count: number;
  fps_num: number | null;
  fps_den: number | null;
  attempt: number;
  revision?: number;
  plan_id: string;
  plan_hash: string;
  chunks: ReviewChunk[];
  publications: ReviewPublication[];
  checkpoint: Record<string, unknown> | null;
}

export function getRunStatus(
  runId: string,
  workspaceId = "default",
  projectId?: string,
): Promise<RunStatusPayload> {
  return reviewFetch<RunStatusPayload>(
    withQuery(`/api/v2/full-apply/${encodeURIComponent(runId)}`, {
      workspace_id: workspaceId,
      project_id: projectId,
    }),
  );
}

export interface RunActionPayload {
  run_id?: string;
  status?: string | null;
  cancelled?: boolean;
  job_state?: string | null;
  successor_run_id?: string;
  [key: string]: unknown;
}

export function cancelRun(runId: string, workspaceId = "default", projectId?: string): Promise<RunActionPayload> {
  return reviewFetch<RunActionPayload>(
    withQuery(`/api/v2/full-apply/${encodeURIComponent(runId)}/cancel`, {
      workspace_id: workspaceId,
      project_id: projectId,
    }),
    { method: "POST" },
  );
}

export function retryRun(runId: string, workspaceId = "default", projectId?: string): Promise<RunActionPayload> {
  return reviewFetch<RunActionPayload>(
    withQuery(`/api/v2/full-apply/${encodeURIComponent(runId)}/retry`, {
      workspace_id: workspaceId,
      project_id: projectId,
    }),
    { method: "POST" },
  );
}

export function resumeRun(runId: string, workspaceId = "default", projectId?: string): Promise<RunActionPayload> {
  return reviewFetch<RunActionPayload>(
    withQuery(`/api/v2/full-apply/${encodeURIComponent(runId)}/resume`, {
      workspace_id: workspaceId,
      project_id: projectId,
    }),
    { method: "POST" },
  );
}

export interface RecomputePayload {
  correction_id: string;
  correction_kind: string;
  run_id: string;
  workspace_id: string;
  project_id: string;
  affected_chunk_ids: string[];
  result_hash: string;
  created: boolean;
  reused: boolean;
  revision_before?: number | null;
  revision_after?: number | null;
}

/** Scoped retry: recompute ONLY the given shot's chunks (idempotent by correction_id). */
export function recomputeScopedShot(
  runId: string,
  payload: ScopedRetryPayload,
  workspaceId = "default",
  projectId?: string,
): Promise<RecomputePayload> {
  return reviewFetch<RecomputePayload>(
    withQuery(`/api/v2/full-apply/${encodeURIComponent(runId)}/recompute`, {
      workspace_id: workspaceId,
      project_id: projectId,
    }),
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export interface QcItemRecord {
  id: string;
  project_id: string;
  video_item_id: string;
  reason_code: string;
  severity: string;
  status: string;
  category: string;
  detector: string;
  evidence_window_key: string;
  evidence: Record<string, unknown>;
  revision: number;
}

export interface QcItemListPayload {
  workspace_id: string;
  project_id: string;
  total: number;
  has_more: boolean;
  items: QcItemRecord[];
}

export function listQcItems(
  projectId: string,
  opts?: { videoItemId?: string; limit?: number },
): Promise<QcItemListPayload> {
  return reviewFetch<QcItemListPayload>(
    withQuery(`/api/v2/projects/${encodeURIComponent(projectId)}/qc-items`, {
      video_item_id: opts?.videoItemId,
      limit: opts?.limit ? String(opts.limit) : undefined,
    }),
  );
}

export interface QcNavigationPayload {
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
    method: string;
    target: string | null;
    endpoint: string | null;
    code: string | null;
    reason: string | null;
  };
  renderer_route: string | null;
}

/** Canonical location of one QC item (the ONLY source of a marker's frame/role). */
export function getQcNavigation(itemId: string): Promise<QcNavigationPayload> {
  return reviewFetch<QcNavigationPayload>(`/api/v2/qc-navigation/${encodeURIComponent(itemId)}`);
}

/** Marker input for the placement logic, from the two real reads. */
export function markerInputFrom(item: QcItemRecord, nav: QcNavigationPayload | null): QcMarkerInput {
  const loc = nav?.canonical_location;
  return {
    qc_item_id: item.id,
    severity: item.severity,
    reason_code: item.reason_code,
    location:
      loc && (loc.frame_index !== null || loc.timecode_ms !== null)
        ? {
            frame_index: loc.frame_index ?? null,
            timecode_ms: loc.timecode_ms ?? null,
            object_role_id: loc.object_role_id ?? null,
          }
        : null,
  };
}
