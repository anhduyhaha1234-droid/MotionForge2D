/**
 * MF-END-25 (C25) — shot-anchors typed API client.
 *
 * Every path here EXISTS in the app's own OpenAPI (the focused test
 * cross-checks this file against `/openapi.json`) — no invented routes:
 *
 *   GET   /api/v2/reskin-configs?project_id=…              list (project-scoped)
 *   GET   /api/v2/reskin-configs/{id}                      one config
 *   GET   /api/v2/reskin-configs/{id}/renderer-route-evidence   per-segment anchors
 *   PATCH /api/v2/reskin-configs/{id}                      CAS anchor write
 *   GET   /api/v2/structural-evidence/segments?video_item_id=…  shots of the video
 *   GET   /api/projects/{id}/frames/{index}                REAL source frame image
 *
 * Mirrors the envelope-unwrapping semantics of the sibling feature clients
 * (`features/demo`, `features/reskin`): a non-2xx response becomes an
 * `ApiError` carrying the backend `detail`.
 */
import { ApiError } from "@/lib/api";
import type { AnchorEvidenceRow } from "./shotAnchorsLogic";

async function anchorsFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
  const API_BASE = rawApiUrl.replace(/\/+$/, "");
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...options?.headers },
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
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ShotAnchorConfig {
  id: string;
  workspace_id: string;
  project_id: string;
  object_role_id: string;
  cast_mapping_id: string | null;
  character_id: string;
  pack_version_id: string;
  params: Record<string, unknown>;
  idempotency_key: string | null;
  structural_lock_manifest_id: string | null;
  lock_policy_version: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface ShotAnchorConfigList {
  workspace_id: string;
  project_id: string | null;
  limit: number;
  offset: number;
  total: number;
  configs: ShotAnchorConfig[];
}

export interface ShotSegment {
  id: string;
  logical_id: string;
  project_id: string;
  video_item_id: string;
  name: string;
  kind: string;
  start_frame: number;
  end_frame: number;
  source_generation: string;
  revision: number;
  state: string;
}

export interface ShotSegmentList {
  workspace_id: string;
  total: number;
  scope: string;
  current_generation: string | null;
  segments: ShotSegment[];
}

/** Reskin configs of ONE project (project_id is a required query filter). */
export function listProjectReskinConfigs(
  projectId: string,
  limit = 50,
  offset = 0,
): Promise<ShotAnchorConfigList> {
  const q = new URLSearchParams({
    project_id: projectId,
    limit: String(limit),
    offset: String(offset),
  });
  return anchorsFetch<ShotAnchorConfigList>(`/api/v2/reskin-configs?${q.toString()}`);
}

export function getReskinConfigById(configId: string): Promise<ShotAnchorConfig> {
  return anchorsFetch<ShotAnchorConfig>(`/api/v2/reskin-configs/${configId}`);
}

/** Per-segment anchors persisted by the engine for one config (real read). */
export function getConfigAnchorEvidence(configId: string): Promise<AnchorEvidenceRow[]> {
  return anchorsFetch<AnchorEvidenceRow[]>(
    `/api/v2/reskin-configs/${configId}/renderer-route-evidence`,
  );
}

/** CAS write: stale revision → ApiError(409) with ZERO mutation. */
export function updateConfigAnchor(
  configId: string,
  body: { revision: number; params: Record<string, unknown> },
): Promise<ShotAnchorConfig> {
  return anchorsFetch<ShotAnchorConfig>(`/api/v2/reskin-configs/${configId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Current-generation shots/segments of ONE video. */
export function listVideoSegments(videoItemId: string): Promise<ShotSegmentList> {
  const q = new URLSearchParams({ video_item_id: videoItemId });
  return anchorsFetch<ShotSegmentList>(
    `/api/v2/structural-evidence/segments?${q.toString()}`,
  );
}
