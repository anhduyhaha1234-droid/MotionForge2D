/**
 * MF-END-27 — typed client cho batch series (hai video cùng một bộ cast).
 *
 * CHỈ gọi các endpoint đã tồn tại trong tree này (không tự bịa route mới):
 *  - POST /api/v2/projects/{id}/series-batches            (MF-END-27, queue/advance)
 *  - GET  /api/v2/projects/{id}/series-batches            (MF-END-27, đọc view, không submit)
 *  - POST /api/v2/projects/{id}/series-batches/advance    (MF-END-27, mở video kế tiếp)
 *  - POST /api/v2/projects/{id}/series-batches/cancel     (MF-END-27, huỷ đúng MỘT video)
 *
 * Server giữ nguyên hàng đợi job hiện có: batch không tạo queue thứ hai và
 * không tự sinh định danh export — payload export do authority hiện có kiểm.
 *
 * Bản đồ route này được khoá bằng chuỗi ký tự trong
 * `tests/product_delivery/test_mf_end_27.py` (static contract) và bằng
 * OpenAPI của app thật (runtime contract).
 */

import { ApiError } from "@/lib/api";

const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
const API_BASE = rawApiUrl.replace(/\/+$/, "");

export type BatchVideoState =
  | "pending"
  | "deferred_lease"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface SeriesBatchVideoRow {
  video_item_id: string;
  ordinal: number;
  run_id: string | null;
  job_id: string | null;
  run_state: string | null;
  job_state: string | null;
  state: BatchVideoState;
  output: { path: string; size_bytes: number; sha256: string | null } | null;
  error: Record<string, unknown> | null;
  submitted?: { run_id: string | null; job_id: string | null };
}

export interface SeriesBatchView {
  schema: string;
  batch_key: string;
  project_id: string;
  state: string;
  pack_hash: string | null;
  cast: Record<string, unknown>;
  videos: SeriesBatchVideoRow[];
  lease: { max_heavy_in_flight: number; active_heavy: number; serialized: boolean };
  metrics: Record<string, unknown>;
  prepare?: Record<string, unknown>;
}

export interface SeriesBatchCreateBody {
  video_item_ids: string[];
  exports: Record<string, Record<string, unknown>>;
  generation?: string;
  measured?: Record<string, unknown> | null;
}

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
  return (await res.json()) as T;
}

function jsonInit(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const seriesBatchApi = {
  /** Queue (hoặc xếp lại — idempotent) batch cho một bộ video của project. */
  createBatch: (projectId: string, body: SeriesBatchCreateBody) =>
    apiFetch<SeriesBatchView>(`/api/v2/projects/${projectId}/series-batches`, jsonInit(body)),

  /** Đọc trạng thái batch từ hàng đợi job thật (không submit gì). */
  getBatch: (projectId: string, videoItemIds: string[], generation = "1") => {
    const ids = videoItemIds.join(",");
    return apiFetch<SeriesBatchView>(
      `/api/v2/projects/${projectId}/series-batches?video_item_ids=${encodeURIComponent(ids)}&generation=${encodeURIComponent(generation)}`,
    );
  },

  /** Mở video kế tiếp khi video trước đã kết thúc (heavy lease = 1). */
  advanceBatch: (projectId: string, body: SeriesBatchCreateBody) =>
    apiFetch<SeriesBatchView>(
      `/api/v2/projects/${projectId}/series-batches/advance`,
      jsonInit(body),
    ),

  /** Huỷ đúng một video; các video khác không bị đụng tới. */
  cancelVideo: (projectId: string, videoItemIds: string[], videoItemId: string, generation = "1") =>
    apiFetch<Record<string, unknown>>(
      `/api/v2/projects/${projectId}/series-batches/cancel`,
      jsonInit({
        video_item_ids: videoItemIds,
        video_item_id: videoItemId,
        generation,
      }),
    ),
};
