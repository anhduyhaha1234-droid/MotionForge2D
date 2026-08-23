/**
 * S08-T04 shared E2E helpers — drive the REAL isolated QA backend
 * (localhost:8014) through the approved public APIs. No mocks, no fake
 * data: every role/occurrence/suggestion is created via the T01/T03 APIs
 * and the extraction runs the deterministic provider selected by the QA
 * backend environment (never a production fallback).
 */

import path from "path";

/**
 * QA backend base. Default kept for S08-T04-C1 (port 8025) so existing specs
 * are unchanged; the S08-T04-C2 run sets QA_API_BASE=http://localhost:8026.
 */
export const API = process.env.QA_API_BASE ?? "http://localhost:8025";
/**
 * 4-segment multi-scene fixture (4×2s distinct color patterns) so the
 * scene detector creates REAL scene rows for T01 occurrence ownership.
 */
export const VIDEO_PATH = path.join(__dirname, "fixtures", "s08t04-scenes-8s.mp4");
/** Single-segment 2s clip — used for the source-replacement / multi-video case. */
export const VIDEO_PATH_2 = path.join(__dirname, "fixtures", "s08t04-single-2s.mp4");

export interface JsonObj {
  [key: string]: unknown;
}

export async function apiJson(
  urlPath: string,
  options?: RequestInit,
): Promise<JsonObj> {
  const res = await fetch(`${API}${urlPath}`, options);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status} for ${urlPath}: ${body.slice(0, 300)}`);
  }
  return (await res.json()) as JsonObj;
}

export async function createProject(name: string): Promise<string> {
  const data = (await apiJson("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  })) as { project_id: string };
  return data.project_id;
}

export async function uploadVideo(projectId: string, videoPath: string): Promise<void> {
  const buf = (await import("fs")).readFileSync(videoPath);
  const form = new FormData();
  form.append("file", new Blob([buf]), path.basename(videoPath));
  const res = await fetch(`${API}/api/projects/${projectId}/video`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`upload ${res.status}`);
}

export async function postAnalyze(projectId: string): Promise<void> {
  await apiJson(`/api/projects/${projectId}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ generation: "1", title: null }),
  });
}

export interface ChainJson {
  video_item_id: string | null;
  generation: string;
  source_sha256: string | null;
  chain_status: string;
  scenes_count: number | null;
  [key: string]: unknown;
}

export async function getChain(projectId: string): Promise<ChainJson> {
  return (await apiJson(`/api/projects/${projectId}/analyze`)) as ChainJson;
}

/** Poll the backend-owned chain until terminal (generous budget). */
export async function waitChainCompleted(projectId: string, timeoutMs = 240_000): Promise<ChainJson> {
  const start = Date.now();
  for (;;) {
    const chain = await getChain(projectId);
    if (chain.chain_status === "completed") return chain;
    if (Date.now() - start > timeoutMs) {
      throw new Error(`chain not completed after ${timeoutMs}ms: ${chain.chain_status}`);
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

export interface ExtractionSubmitJson {
  job_id: string;
  reused: boolean;
  [key: string]: unknown;
}

export async function submitExtraction(
  projectId: string,
  videoItemId: string,
  sourceSha: string,
): Promise<ExtractionSubmitJson> {
  return (await apiJson("/api/v2/object-intelligence/extraction", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      video_item_id: videoItemId,
      generation: "1",
      source_sha256: sourceSha,
    }),
  })) as ExtractionSubmitJson;
}

export interface ExtractionJobJson {
  job_id: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
  progress: number;
  message: string;
  error: string | null;
  provider: string | null;
  extractor_version: string | null;
  candidates: Array<{
    name: string;
    confidence: number;
    artifacts: unknown[];
    occurrences: Array<{ scene_id: string }>;
  }>;
  outputs: Array<{ name: string; purpose: string }>;
  [key: string]: unknown;
}

export async function getExtractionJob(jobId: string): Promise<ExtractionJobJson> {
  return (await apiJson(
    `/api/v2/object-intelligence/extraction/${jobId}`,
  )) as unknown as ExtractionJobJson;
}

export async function waitExtractionTerminal(
  jobId: string,
  timeoutMs = 90_000,
): Promise<ExtractionJobJson> {
  const start = Date.now();
  for (;;) {
    const job = await getExtractionJob(jobId);
    if (job.status === "completed" || job.status === "failed" || job.status === "cancelled") {
      return job;
    }
    if (Date.now() - start > timeoutMs) {
      throw new Error(`extraction not terminal after ${timeoutMs}ms: ${job.status}`);
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
}

export interface RoleMediaJson {
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

export interface RoleJson {
  id: string;
  name: string;
  status: string;
  revision: number;
  project_id: string;
  video_item_id: string;
  source_generation: string;
  media: RoleMediaJson[];
  has_media_associations: boolean;
  occurrences: Array<{
    id: string;
    scene_id: string;
    frame_index: number;
    confidence: number;
    algorithm: string | null;
    algorithm_version: string | null;
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
}

export async function listRoles(videoItemId: string): Promise<RoleJson[]> {
  const data = (await apiJson(
    `/api/v2/object-intelligence/roles?video_item_id=${encodeURIComponent(videoItemId)}&limit=200`,
  )) as { roles: RoleJson[] };
  return data.roles;
}

/** Paged role summaries (the gallery's infinite-load contract). */
export async function listRolesPaged(
  videoItemId: string,
  limit = 16,
  offset = 0,
): Promise<{ roles: RoleJson[]; total: number }> {
  const data = (await apiJson(
    `/api/v2/object-intelligence/roles?video_item_id=${encodeURIComponent(videoItemId)}&limit=${limit}&offset=${offset}`,
  )) as { roles: RoleJson[]; total: number };
  return data;
}

/** Backend-authoritative current extraction lookup (source-generation filter). */
export async function getCurrentExtractionApi(
  videoItemId: string,
  sourceGeneration?: string,
): Promise<ExtractionJobJson | null> {
  const url = `/api/v2/object-intelligence/extraction/current?video_item_id=${encodeURIComponent(videoItemId)}${
    sourceGeneration ? `&source_generation=${encodeURIComponent(sourceGeneration)}` : ""
  }`;
  try {
    return (await apiJson(url)) as unknown as ExtractionJobJson;
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("API 404")) return null;
    throw err;
  }
}

/** Backend grouping policy metadata (thresholds/semantics). */
export async function getGroupingPolicyApi(): Promise<{
  algorithm: string;
  algorithm_version: string;
  calibration_version: string;
  review_threshold: number;
  confidence_semantics: string[];
  [key: string]: unknown;
}> {
  return (await apiJson(
    "/api/v2/object-intelligence/grouping/policy",
  )) as unknown as Awaited<ReturnType<typeof getGroupingPolicyApi>>;
}

export async function createRole(
  name: string,
  projectId: string,
  videoItemId: string,
  sourceGeneration = "1",
): Promise<RoleJson> {
  return (await apiJson("/api/v2/object-intelligence/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      video_item_id: videoItemId,
      source_generation: sourceGeneration,
      name,
      kind: "character",
      status: "suggested",
      description: null,
    }),
  })) as RoleJson;
}

/**
 * Create one scene/frame evidence for a role. T01 requires the scene id
 * to be a REAL Scene row of this video item — the only API source of real
 * scene ids is the completed extraction job's candidate occurrences.
 */
export async function createOccurrence(
  roleId: string,
  sceneId: string,
  frameIndex: number,
  timeMs: number,
  bbox: { x: number; y: number; width: number; height: number },
  confidence: number,
): Promise<JsonObj> {
  return apiJson(`/api/v2/object-intelligence/roles/${roleId}/occurrences`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scene_id: sceneId,
      frame_index: frameIndex,
      time_ms: timeMs,
      bbox,
      confidence,
      confidence_source: "user",
      algorithm: "seed",
      algorithm_version: "1",
      reasons: ["seed-evidence"],
      review_state: "unreviewed",
    }),
  });
}

/**
 * The REAL scene rows of a video item, taken from the committed extraction
 * job's candidates (each candidate carries its real scene_id) in stable
 * creation order. Used to seed curation roles on genuine scenes.
 */
export function sceneIdsFromJob(
  job: { candidates: Array<{ occurrences: Array<{ scene_id: string }> }> },
): string[] {
  const seen: string[] = [];
  for (const candidate of job.candidates) {
    for (const occ of candidate.occurrences) {
      if (!seen.includes(occ.scene_id)) seen.push(occ.scene_id);
    }
  }
  return seen;
}

export async function confirmRoleApi(roleId: string, videoItemId: string, revision: number): Promise<JsonObj> {
  return apiJson(`/api/v2/object-intelligence/grouping/roles/${roleId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      revision,
      video_item_id: videoItemId,
      idempotency_key: null,
      note: null,
    }),
  });
}

/** Merge via the real T03 API (used as an EXTERNAL writer in tests). */
export async function mergeRolesApi(
  targetRoleId: string,
  videoItemId: string,
  revision: number,
  sourceRoleIds: string[],
): Promise<JsonObj> {
  return apiJson(`/api/v2/object-intelligence/grouping/roles/${targetRoleId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      revision,
      video_item_id: videoItemId,
      source_role_ids: sourceRoleIds,
      idempotency_key: null,
      note: "external-writer",
    }),
  });
}

export async function getRole(roleId: string): Promise<RoleJson> {
  return (await apiJson(`/api/v2/object-intelligence/roles/${roleId}`)) as RoleJson;
}

/** Detail read with the HTTP status — stale roles 404 under the current scope. */
export async function getRoleWithStatus(
  roleId: string,
  generation?: string,
): Promise<{ status: number; role: RoleJson | null }> {
  const url = `/api/v2/object-intelligence/roles/${roleId}${
    generation ? `?generation=${encodeURIComponent(generation)}` : ""
  }`;
  try {
    const role = (await apiJson(url)) as RoleJson;
    return { status: 200, role };
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("API 404")) {
      return { status: 404, role: null };
    }
    throw err;
  }
}

/** Default (current) roles list response WITH the backend current generation. */
export async function listRolesMeta(videoItemId: string): Promise<{
  roles: RoleJson[];
  total: number;
  scope: string;
  current_generation: string | null;
}> {
  return (await apiJson(
    `/api/v2/object-intelligence/roles?video_item_id=${encodeURIComponent(videoItemId)}&limit=200`,
  )) as unknown as Awaited<ReturnType<typeof listRolesMeta>>;
}

/** Explicit-generation role view (historical/current scope). */
export async function listRolesGeneration(
  videoItemId: string,
  generation: string,
): Promise<{ roles: RoleJson[]; scope: string; current_generation: string | null }> {
  return (await apiJson(
    `/api/v2/object-intelligence/roles?video_item_id=${encodeURIComponent(videoItemId)}&generation=${encodeURIComponent(generation)}&limit=200`,
  )) as unknown as Awaited<ReturnType<typeof listRolesGeneration>>;
}

export async function generateSuggestions(
  videoItemId: string,
  sourceGeneration = "1",
): Promise<JsonObj> {
  return apiJson("/api/v2/object-intelligence/grouping/suggestions/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video_item_id: videoItemId,
      source_generation: sourceGeneration,
      scope: "video",
      algorithm_version: "1",
      idempotency_key: null,
    }),
  });
}

export async function listSuggestions(videoItemId: string): Promise<Array<{ id: string; confidence: number; status: string }>> {
  const data = (await apiJson(
    `/api/v2/object-intelligence/grouping/suggestions?video_item_id=${encodeURIComponent(videoItemId)}&status=pending&limit=200`,
  )) as { suggestions: Array<{ id: string; confidence: number; status: string }> };
  return data.suggestions;
}

export async function listAllSuggestions(videoItemId: string): Promise<Array<{ id: string; confidence: number; status: string }>> {
  const data = (await apiJson(
    `/api/v2/object-intelligence/grouping/suggestions?video_item_id=${encodeURIComponent(videoItemId)}&limit=200`,
  )) as { suggestions: Array<{ id: string; confidence: number; status: string }> };
  return data.suggestions;
}

/** Fresh isolated project ready for object review (chain completed). */
export async function setupProject(name: string): Promise<{
  projectId: string;
  videoItemId: string;
  sourceSha: string;
}> {
  return setupProjectWithVideo(name, VIDEO_PATH);
}

/** setupProject with an explicit fixture (source-replacement / multi-video). */
export async function setupProjectWithVideo(
  name: string,
  videoPath: string,
): Promise<{
  projectId: string;
  videoItemId: string;
  sourceSha: string;
}> {
  const projectId = await createProject(name);
  await uploadVideo(projectId, videoPath);
  await postAnalyze(projectId);
  const chain = await waitChainCompleted(projectId);
  if (!chain.video_item_id) throw new Error("no video item after chain");
  return {
    projectId,
    videoItemId: chain.video_item_id,
    sourceSha: (chain.source_sha256 as string) ?? "",
  };
}

/** Full extraction for a project (submit + wait terminal). */
export async function runExtraction(
  projectId: string,
  videoItemId: string,
  sourceSha: string,
): Promise<{ jobId: string; job: ExtractionJobJson }> {
  const submitted = await submitExtraction(projectId, videoItemId, sourceSha);
  const job = await waitExtractionTerminal(submitted.job_id);
  if (job.status !== "completed") {
    throw new Error(`extraction ${submitted.job_id} ended ${job.status}: ${job.error}`);
  }
  return { jobId: submitted.job_id, job };
}

/** Seed N extra suggested roles (real scenes) — used for pagination tests. */
export async function seedRoles(
  projectId: string,
  videoItemId: string,
  sceneIds: string[],
  count: number,
  prefix = "Seed",
): Promise<RoleJson[]> {
  const roles: RoleJson[] = [];
  for (let i = 0; i < count; i++) {
    const role = await createRole(`${prefix}Role${String(i).padStart(2, "0")}`, projectId, videoItemId);
    const scene = sceneIds[i % sceneIds.length];
    await createOccurrence(
      role.id,
      scene,
      i,
      i * 1000,
      { x: 10 + i, y: 10, width: 40, height: 40 },
      0.9,
    );
    roles.push(role);
  }
  return roles;
}

/** Correction helper: preview → create → confirm → wait recompute terminal. */
export async function applyCorrectionApi(
  payload: Record<string, unknown>,
): Promise<{ correctionId: string; recomputeJobId: string | null }> {
  await apiJson("/api/v2/object-intelligence/corrections/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const created = (await apiJson("/api/v2/object-intelligence/corrections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, idempotency_key: `e2e-${Date.now()}-${Math.random()}` }),
  })) as { correction: { id: string; revision: number } };
  const applied = (await apiJson(
    `/api/v2/object-intelligence/corrections/${created.correction.id}/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision: created.correction.revision }),
    },
  )) as {
    recompute: { recompute_needed: boolean; job_id: string | null; status: string | null } | null;
  };
  if (!applied.recompute || !applied.recompute.recompute_needed || !applied.recompute.job_id) {
    return { correctionId: created.correction.id, recomputeJobId: null };
  }
  const jobId = applied.recompute.job_id;
  const start = Date.now();
  for (;;) {
    const correction = (await apiJson(
      `/api/v2/object-intelligence/corrections/${created.correction.id}`,
    )) as {
      recompute: { status: string | null; error: string | null } | null;
    };
    const status = correction.recompute?.status ?? "";
    if (status === "completed") return { correctionId: created.correction.id, recomputeJobId: jobId };
    if (status === "failed" || status === "cancelled") {
      throw new Error(`recompute ${status}: ${correction.recompute?.error ?? ""}`);
    }
    if (Date.now() - start > 180_000) throw new Error("recompute timeout");
    await new Promise((r) => setTimeout(r, 1500));
  }
}

export function galleryStorageKey(projectId: string): string {
  return `mf-gallery-extraction-${projectId}`;
}
