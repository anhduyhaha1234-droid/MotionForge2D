export type PilotPackVerdict = {
  compatible: boolean;
  code?: string;
  reason?: string;
  missing?: string[];
  required?: string[];
  pack_id?: string;
  pack_version?: string;
  pack_content_sha256?: string;
  pack_manifest_sha256?: string;
  approval_status?: string;
  semantic_review_status?: string;
  pack?: {
    approval_status?: string;
    semantic_review_status?: string;
  };
};

export type PilotContext = {
  project_id: string;
  legacy_project_id: string;
  durable_project_id: string | null;
  durable_video_item_id: string | null;
  generation: string;
  chain_status: string;
  source_name: string;
  source_sha256: string;
  width: number;
  height: number;
  fps_num: number;
  fps_den: number;
  frame_count: number;
  duration_seconds: number;
  allowed_frame_window: [number, number];
  asset_sha256: string;
  asset_url: string;
  import_endpoint: string;
  analyze_endpoint: string;
  legacy_id_bridge: Record<string, string | null>;
  composition_revision: string | null;
  pack_required_capabilities: string[];
  pack_verdict_for_pinned_asset: PilotPackVerdict;
  selected_pack_id: string | null;
  clean_plate_required: boolean;
  clean_plate_verdict: PilotPackVerdict;
  selected_clean_plate_id: string | null;
};

export type PilotJob = {
  job: {
    job_id: string;
    status: string;
    progress: number;
    message: string;
    error?: string | null;
    job_type: string;
  };
  manifest: Record<string, unknown> | null;
  media: Record<string, string>;
};

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888").replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = `API ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail ?? payload);
    } catch {
      detail = await response.text().catch(() => detail);
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function resolvePilotContext(projectId: string, generation = "1", packId?: string, cleanPlateId?: string): Promise<PilotContext> {
  return request<PilotContext>("/api/v2/pilot-preview/context", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, generation, ...(packId ? { pack_id: packId } : {}), ...(cleanPlateId ? { clean_plate_id: cleanPlateId } : {}) }),
  });
}

export function submitPilotPreview(payload: Record<string, unknown>): Promise<{ job_id: string; status: string; manifest: Record<string, unknown> }> {
  return request("/api/v2/pilot-preview/jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function readPilotJob(jobId: string): Promise<PilotJob> {
  return request<PilotJob>(`/api/v2/pilot-preview/jobs/${encodeURIComponent(jobId)}`);
}

export function pilotMediaUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function pilotAssetUrl(): string {
  return `${API_BASE}/api/v2/pilot-preview/asset`;
}
