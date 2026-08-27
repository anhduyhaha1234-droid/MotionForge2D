/**
 * S09 Reskin feature — thin typed exports/API client only.
 *
 * This module is intentionally THIN (S09-T01 allowlist): it re-exports the
 * shared API client helpers for reskin-config endpoints and the response
 * shapes used by later S09 tasks (T04 DemoCompare, T06 ApprovalDialog).
 * No UI components live here yet; no business logic is duplicated — every
 * mutation goes through the backend /api/v2/reskin-configs contract
 * (idempotency + revision CAS enforced server-side).
 *
 * `apiFetch` is private in @/lib/api, so this thin module keeps a minimal
 * local fetch wrapper with the SAME envelope-unwrapping semantics
 * (ApiError carrying the backend `detail`). No duplicated business logic.
 */
import { ApiError } from "@/lib/api";

/** Re-exported so S09 UI tasks can branch on HTTP 409 without importing internals. */
export { ApiError };

async function reskinFetch<T>(path: string, options?: RequestInit): Promise<T> {
	// Thin wrapper kept local because lib/api does not export apiFetch.
	// It mirrors the exact envelope-unwrapping behaviour of lib/api.apiFetch.
	const rawApiUrl =
		process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
	const API_BASE = rawApiUrl.replace(/\/+$/, "");
	const url = `${API_BASE}${path}`;
	const res = await fetch(url, {
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

/** The transform contract mirrored from app/schemas/reskin_config.py. */
export interface ReskinAnchor {
  x: number;
  y: number;
}

export interface ReskinOffset {
  x: number;
  y: number;
}

export type ReskinFitMode = "contain" | "cover" | "stretch";
export type ReskinClipMode = "asset_alpha" | "original_mask" | "intersection";

export interface ReskinParams {
  anchor: ReskinAnchor;
  scale: number;
  fit_mode: ReskinFitMode;
  clip_mode: ReskinClipMode;
  offset: ReskinOffset;
  rotation_offset_deg: number;
  opacity: number;
}

export interface ReskinConfigData {
  id: string;
  workspace_id: string;
  project_id: string;
  object_role_id: string;
  cast_mapping_id: string | null;
  character_id: string;
  pack_version_id: string;
  params: ReskinParams;
  idempotency_key: string | null;
  /** Pinned StructuralLockManifest (Source-Locked), null when unpinned. */
  structural_lock_manifest_id: string | null;
  /** Derived server-side from the pinned manifest's policy_version. */
  lock_policy_version: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface ReskinConfigListResponse {
  workspace_id: string;
  project_id?: string | null;
  limit: number;
  offset: number;
  total: number;
  configs: ReskinConfigData[];
}

export interface ReskinConfigCreateRequest {
  project_id: string;
  object_role_id: string;
  character_id: string;
  pack_version_id: string;
  params: ReskinParams;
  idempotency_key?: string | null;
  cast_mapping_id?: string | null;
  /** Pin a StructuralLockManifest; validated fail-closed server-side. */
  structural_lock_manifest_id?: string | null;
}

export interface ReskinConfigUpdateRequest {
  revision: number;
  params?: ReskinParams;
  pack_version_id?: string | null;
  character_id?: string | null;
  /** Omitted → keep pin; explicit id → re-pin; "" → unpin. */
  structural_lock_manifest_id?: string | null;
}

/** One persisted per-segment renderer-route decision (read model). */
export interface RendererRouteEvidence {
  occurrence_segment_id: string;
  /** Exact RENDERER_ROUTES enum value persisted for this segment. */
  route: string;
  anchor: ReskinAnchor;
  start_frame: number;
  end_frame: number;
  confidence: number;
  confidence_source: string;
  reasons: string[];
  provenance: Record<string, unknown> | null;
  structural_lock_manifest_id: string | null;
}

/** Create a durable ReskinConfig pin (idempotent replay → 200 with existing row). */
export function createReskinConfig(
  req: ReskinConfigCreateRequest,
): Promise<ReskinConfigData> {
  return reskinFetch<ReskinConfigData>("/api/v2/reskin-configs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

/** List reskin configs for a workspace, optionally filtered by project. */
export function listReskinConfigs(
  projectId?: string,
  limit = 50,
  offset = 0,
): Promise<ReskinConfigListResponse> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (projectId) query.set("project_id", projectId);
  return reskinFetch<ReskinConfigListResponse>(
    `/api/v2/reskin-configs?${query.toString()}`,
  );
}

/** Fetch one config by id (404 without cross-workspace leak). */
export function getReskinConfig(configId: string): Promise<ReskinConfigData> {
  return reskinFetch<ReskinConfigData>(`/api/v2/reskin-configs/${configId}`);
}

/** CAS update: stale revision → HTTP 409, zero mutation. */
export function updateReskinConfig(
  configId: string,
  req: ReskinConfigUpdateRequest,
): Promise<ReskinConfigData> {
  return reskinFetch<ReskinConfigData>(`/api/v2/reskin-configs/${configId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

/** CompatibilityPolicy evidence per occurrence segment (read-only).
 *  Empty list when the config has no pinned StructuralLockManifest. */
export function getRendererRouteEvidence(
  configId: string,
): Promise<RendererRouteEvidence[]> {
  return reskinFetch<RendererRouteEvidence[]>(
    `/api/v2/reskin-configs/${configId}/renderer-route-evidence`,
  );
}
