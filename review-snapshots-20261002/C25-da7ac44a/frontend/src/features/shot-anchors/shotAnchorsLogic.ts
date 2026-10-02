/**
 * MF-END-25 (C25) — shot-anchors: PURE logic for the "build/review anchors" step.
 *
 * Anchors are the G2 gate of the product journey: each shot (occurrence
 * segment) has ONE start anchor in normalized source-frame coordinates
 * (x, y ∈ [0, 1]) plus the renderer route the engine will use.  This module
 * holds only deterministic, dependency-free logic so the CI node battery can
 * execute the SHIPPED functions verbatim (no re-implementation, no mock).
 *
 * Rules encoded here:
 *   - an anchor is MEASURED only when the backend returned it for that
 *     segment (never defaulted to (0.5, 0.5) client-side);
 *   - an out-of-range / non-finite anchor is INVALID, never clamped silently;
 *   - every config/segment read must belong to the SAME project (a row from
 *     another project is a typed refusal — comparisons must not mix projects);
 *   - saving an anchor is a full-params CAS write: only `anchor` may change
 *     and the caller's revision must be current (stale → 409, zero mutation).
 */

export const ANCHOR_MIN = 0;
export const ANCHOR_MAX = 1;

export interface AnchorPoint {
  x: number;
  y: number;
}

/** One persisted per-segment renderer-route decision (real read model). */
export interface AnchorEvidenceRow {
  occurrence_segment_id: string;
  route: string;
  anchor: Record<string, number>;
  start_frame: number;
  end_frame: number;
  confidence: number;
  confidence_source: string;
  reasons?: string[];
  provenance?: Record<string, unknown> | null;
  structural_lock_manifest_id?: string | null;
}

export interface ShotAnchor {
  segmentId: string;
  route: string;
  anchor: AnchorPoint;
  startFrame: number;
  endFrame: number;
  frameCount: number;
  confidence: number;
  confidenceSource: string;
  reasons: string[];
  /** true only when the anchor came from the backend row. */
  measured: boolean;
}

export interface AnchorCoverage {
  expected: number;
  measured: number;
  missing: number;
  invalid: number;
  ready: boolean;
  missingSegmentIds: string[];
}

export type AnchorEditRefusal =
  | "anchor_not_finite"
  | "anchor_out_of_range"
  | "project_scope_mismatch"
  | "revision_missing";

export interface AnchorEditPlan {
  ok: boolean;
  refusal: AnchorEditRefusal | null;
  /** Full params object to send (PATCH is a full replacement). */
  params: Record<string, unknown> | null;
  revision: number | null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Read an anchor from a backend row WITHOUT inventing values. */
export function parseAnchor(raw: Record<string, number> | null | undefined): AnchorPoint | null {
  if (!raw || typeof raw !== "object") return null;
  const x = num(raw.x);
  const y = num(raw.y);
  if (x === null || y === null) return null;
  return { x, y };
}

/** Validate an anchor for persistence; never clamp. */
export function validateAnchor(anchor: AnchorPoint | null): {
  ok: boolean;
  refusal: AnchorEditRefusal | null;
} {
  if (!anchor) return { ok: false, refusal: "anchor_not_finite" };
  if (!Number.isFinite(anchor.x) || !Number.isFinite(anchor.y)) {
    return { ok: false, refusal: "anchor_not_finite" };
  }
  if (anchor.x < ANCHOR_MIN || anchor.x > ANCHOR_MAX) {
    return { ok: false, refusal: "anchor_out_of_range" };
  }
  if (anchor.y < ANCHOR_MIN || anchor.y > ANCHOR_MAX) {
    return { ok: false, refusal: "anchor_out_of_range" };
  }
  return { ok: true, refusal: null };
}

/** Project-context invariant: a row of another project must be refused. */
export function projectScopeMatches(rowProjectId: string | null, projectId: string): boolean {
  return typeof rowProjectId === "string" && rowProjectId === projectId;
}

function normaliseId(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * Map REAL evidence rows → shot anchors, restricted to the requested project.
 * Rows with an unparseable anchor are dropped from `measured` (reported by
 * coverage as `invalid`) instead of being coerced.
 */
export function buildShotAnchors(
  rows: AnchorEvidenceRow[],
  opts: { projectId: string; rowsProjectId: string | null },
): { anchors: ShotAnchor[]; refused: number; invalid: number; scopeOk: boolean } {
  const scopeOk = projectScopeMatches(opts.rowsProjectId, opts.projectId);
  if (!scopeOk) {
    return { anchors: [], refused: rows.length, invalid: 0, scopeOk: false };
  }
  const anchors: ShotAnchor[] = [];
  let invalid = 0;
  for (const row of rows) {
    const segmentId = normaliseId(row.occurrence_segment_id);
    if (!segmentId) {
      invalid += 1;
      continue;
    }
    const anchor = parseAnchor(row.anchor);
    const check = validateAnchor(anchor);
    if (!check.ok || !anchor) {
      invalid += 1;
      continue;
    }
    const startFrame = num(row.start_frame) ?? 0;
    const endFrame = num(row.end_frame) ?? 0;
    anchors.push({
      segmentId,
      route: typeof row.route === "string" ? row.route : "",
      anchor,
      startFrame,
      endFrame,
      frameCount: Math.max(0, endFrame - startFrame),
      confidence: num(row.confidence) ?? 0,
      confidenceSource: typeof row.confidence_source === "string" ? row.confidence_source : "",
      reasons: Array.isArray(row.reasons) ? row.reasons.filter((r) => typeof r === "string") : [],
      measured: true,
    });
  }
  anchors.sort((a, b) => a.startFrame - b.startFrame || a.segmentId.localeCompare(b.segmentId));
  return { anchors, refused: 0, invalid, scopeOk: true };
}

/** Coverage of anchors against the real shot/segment list of one video. */
export function anchorCoverage(
  anchors: ShotAnchor[],
  segments: { id: string }[],
  invalid = 0,
): AnchorCoverage {
  const measuredIds = new Set(anchors.map((a) => a.segmentId));
  const missingSegmentIds = segments
    .map((s) => s.id)
    .filter((id) => !measuredIds.has(id));
  return {
    expected: segments.length,
    measured: anchors.length,
    missing: missingSegmentIds.length,
    invalid,
    ready: segments.length > 0 && missingSegmentIds.length === 0 && invalid === 0,
    missingSegmentIds,
  };
}

/** Vietnamese copy for the anchor gate (single source for UI + tests). */
export const ANCHOR_GATE_COPY = {
  noVideo: "Chưa có video đã phân tích — hãy chạy Nhập & Phân tích trước.",
  noSegments: "Chưa có shot/segment nào cho video này (cần bước phân tích cảnh).",
  noConfigs: "Chưa có cấu hình reskin cho vai nào — hãy ghim bộ nhân vật (cast) trước.",
  ready: "Đã có anchor cho mọi shot — có thể sang bước dựng/apply.",
  missing: "Còn shot thiếu anchor — hệ thống chưa cho chạy bước video cho tới khi đủ.",
  invalid: "Có anchor không hợp lệ từ backend — cần chạy lại bước sinh route.",
  scopeMismatch: "Dữ liệu trả về thuộc dự án khác — đã chặn để không trộn project.",
} as const;

export function anchorGateMessage(coverage: AnchorCoverage | null, scopeOk: boolean): string {
  if (!scopeOk) return ANCHOR_GATE_COPY.scopeMismatch;
  if (!coverage) return ANCHOR_GATE_COPY.noVideo;
  if (coverage.invalid > 0) return ANCHOR_GATE_COPY.invalid;
  if (coverage.expected === 0) return ANCHOR_GATE_COPY.noSegments;
  if (coverage.ready) return ANCHOR_GATE_COPY.ready;
  return ANCHOR_GATE_COPY.missing;
}

/** CSS overlay position (%) of an anchor on a frame box. */
export function anchorOverlayStyle(anchor: AnchorPoint): { left: string; top: string } {
  const x = Math.min(ANCHOR_MAX, Math.max(ANCHOR_MIN, anchor.x));
  const y = Math.min(ANCHOR_MAX, Math.max(ANCHOR_MIN, anchor.y));
  return { left: `${(x * 100).toFixed(2)}%`, top: `${(y * 100).toFixed(2)}%` };
}

/**
 * Plan one anchor CAS write.  `params` is sent as a FULL replacement (server
 * contract), so every existing key is preserved and ONLY `anchor` changes.
 */
export function buildAnchorEdit(
  config: { params: Record<string, unknown>; revision: number },
  projectId: string,
  rowProjectId: string | null,
  anchor: AnchorPoint,
): AnchorEditPlan {
  if (!projectScopeMatches(rowProjectId, projectId)) {
    return { ok: false, refusal: "project_scope_mismatch", params: null, revision: null };
  }
  const check = validateAnchor(anchor);
  if (!check.ok) {
    return { ok: false, refusal: check.refusal, params: null, revision: null };
  }
  if (!Number.isInteger(config.revision) || config.revision < 1) {
    return { ok: false, refusal: "revision_missing", params: null, revision: null };
  }
  return {
    ok: true,
    refusal: null,
    params: { ...config.params, anchor: { x: anchor.x, y: anchor.y } },
    revision: config.revision,
  };
}

export interface AnchorErrorCopy {
  code: "conflict" | "invalid" | "not_found" | "forbidden" | "server" | "network";
  message: string;
  retryable: boolean;
}

/** Map a real HTTP failure to Vietnamese copy + whether a retry can help. */
export function classifyAnchorError(status: number | null, detail?: string): AnchorErrorCopy {
  if (status === null) {
    return {
      code: "network",
      message: "Không kết nối được máy chủ — kiểm tra backend rồi thử lại.",
      retryable: true,
    };
  }
  if (status === 409) {
    return {
      code: "conflict",
      message:
        "Anchor đã bị thay đổi ở nơi khác (409) — nạp lại cấu hình mới nhất rồi lưu lại.",
      retryable: true,
    };
  }
  if (status === 404) {
    return {
      code: "not_found",
      message: "Không tìm thấy cấu hình/shot này ở dự án hiện tại (404).",
      retryable: false,
    };
  }
  if (status === 422 || status === 400) {
    return {
      code: "invalid",
      message: `Yêu cầu anchor không hợp lệ (${status}) — anchor phải nằm trong [0,1].`,
      retryable: false,
    };
  }
  if (status === 403) {
    return { code: "forbidden", message: "Không có quyền sửa anchor này (403).", retryable: false };
  }
  return {
    code: "server",
    message: `Lỗi máy chủ (${status})${detail ? `: ${detail}` : ""} — thử lại sau.`,
    retryable: true,
  };
}

/** URL of the REAL source frame image served by the app (no local synthesis). */
export function sourceFrameUrl(
  baseUrl: string,
  projectId: string,
  frameIndex: number,
  sceneId = 0,
): string {
  const base = baseUrl.replace(/\/+$/, "");
  return `${base}/api/projects/${encodeURIComponent(projectId)}/frames/${frameIndex}?scene_id=${sceneId}`;
}
