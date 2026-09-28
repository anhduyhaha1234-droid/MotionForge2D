/**
 * MF-END-24 — shot-review logic (pure, dependency-free).
 *
 * Every function here is a pure derivation over REAL backend payloads
 * (GET /api/v2/full-apply/{run_id}, qc-items + qc-navigation).  No imports,
 * no timers, no randomness: the module is executable as-is by Node's
 * type-stripping loader so the acceptance tests can run the SHIPPED logic
 * instead of re-implementing it.  Nothing in this file synthesises progress,
 * frames or locations — missing data is a typed refusal, never a guess.
 */

export interface ReviewChunk {
  id: string;
  chunk_index: number;
  order_index: number;
  shot_id: string;
  layer_id: string | null;
  object_role_id: string | null;
  core_start_frame: number;
  core_end_frame: number;
  content_hash: string;
  state: string;
  attempt: number;
  artifact_id: string | null;
  verified: boolean;
}

export interface ReviewPublication {
  id: string;
  artifact_id: string;
  content_hash: string;
  frame_count: number;
  frame_metadata: Record<string, unknown>;
  state: string;
}

export interface ReviewRun {
  run_id: string;
  status: string;
  frame_count: number;
  fps_num: number | null;
  fps_den: number | null;
  attempt: number;
  revision?: number;
  chunks: ReviewChunk[];
  publications: ReviewPublication[];
}

export interface ShotSummary {
  shot_id: string;
  chunk_ids: string[];
  chunk_count: number;
  order_index: number;
  start_frame: number;
  end_frame: number;
  state: string;
  attempt: number;
  completed: number;
  verified: boolean;
  progress_pct: number | null;
  has_output: boolean;
  artifact_ids: string[];
  content_hashes: string[];
  layer_ids: string[];
  role_ids: string[];
}

export interface ShotOutputRef {
  publication_id: string;
  artifact_id: string;
  content_hash: string;
  frame_count: number;
}

export interface QcMarkerLocation {
  frame_index: number | null;
  timecode_ms: number | null;
  object_role_id: string | null;
}

export interface QcMarkerInput {
  qc_item_id: string;
  severity: string;
  reason_code: string;
  location: QcMarkerLocation | null;
}

export type PlacedMarker =
  | {
      status: "ok";
      qc_item_id: string;
      severity: string;
      reason_code: string;
      /** Canonical frame from qc-navigation (null when only a timecode exists). */
      frame: number | null;
      /** Seek target in seconds (timecode_ms, or frame/fps when the run has fps). */
      seconds: number | null;
      role_id: string | null;
    }
  | {
      status: "no_location";
      qc_item_id: string;
      severity: string;
      reason_code: string;
      reason_vi: string;
    };

export interface ReviewControls {
  cancel: boolean;
  resume: boolean;
  retry: boolean;
  note_vi: string;
}

export interface ScopedRetryAuthority {
  correction_id: string;
  correction_kind: string;
  target_layer_ids: string[];
}

export interface ScopedRetryPayload {
  correction_id: string;
  correction_kind: string;
  target_layer_ids: string[];
  target_shot_ids: string[];
  expected_revision: number | null;
}

export interface ReviewErrorInput {
  status?: number | null;
  code?: string | null;
  message?: string | null;
}

export interface ReviewErrorCopy {
  code: string;
  title_vi: string;
  action_vi: string;
  retryable: boolean;
}

/** Normalise a state name so unknown backend states are never guessed. */
export function shotStateOf(states: string[]): string {
  if (states.length === 0) return "pending";
  if (states.some((s) => s === "running")) return "running";
  if (states.some((s) => s === "failed")) return "failed";
  if (states.every((s) => s === "completed" || s === "skipped")) return "completed";
  if (states.every((s) => s === "pending")) return "pending";
  return "pending";
}

/** Group run chunks into one unit per SHOT (multi-chunk shots stay one unit). */
export function groupChunksIntoShots(chunks: ReviewChunk[]): ShotSummary[] {
  const byShot = new Map<string, ReviewChunk[]>();
  for (const c of chunks) {
    const list = byShot.get(c.shot_id);
    if (list) list.push(c);
    else byShot.set(c.shot_id, [c]);
  }
  const shots: ShotSummary[] = [];
  for (const [shotId, list] of byShot.entries()) {
    const ordered = [...list].sort((a, b) => a.order_index - b.order_index);
    const completed = ordered.filter((c) => c.state === "completed").length;
    const artifactIds = ordered
      .map((c) => c.artifact_id)
      .filter((v): v is string => typeof v === "string" && v.length > 0);
    const hashes = ordered
      .map((c) => c.content_hash)
      .filter((v): v is string => typeof v === "string" && v.length > 0);
    shots.push({
      shot_id: shotId,
      chunk_ids: ordered.map((c) => c.id),
      chunk_count: ordered.length,
      order_index: ordered[0]?.order_index ?? 0,
      start_frame: Math.min(...ordered.map((c) => c.core_start_frame)),
      end_frame: Math.max(...ordered.map((c) => c.core_end_frame)),
      state: shotStateOf(ordered.map((c) => c.state)),
      attempt: Math.max(...ordered.map((c) => c.attempt)),
      completed,
      verified: ordered.every((c) => c.verified),
      progress_pct: ordered.length === 0 ? null : Math.round((completed / ordered.length) * 100),
      has_output: artifactIds.length > 0,
      artifact_ids: artifactIds,
      content_hashes: hashes,
      layer_ids: [...new Set(ordered.map((c) => c.layer_id).filter((v): v is string => !!v))],
      role_ids: [...new Set(ordered.map((c) => c.object_role_id).filter((v): v is string => !!v))],
    });
  }
  return shots.sort((a, b) => a.order_index - b.order_index);
}

/** Run progress — completed chunks / total, from backend states only. */
export function runProgress(chunks: ReviewChunk[]): number | null {
  if (chunks.length === 0) return null;
  const done = chunks.filter((c) => c.state === "completed").length;
  return Math.round((done / chunks.length) * 100);
}

/** Bind a shot to its published output (never guesses across shots). */
export function shotOutputRefs(
  shot: ShotSummary,
  publications: ReviewPublication[],
): ShotOutputRef[] {
  const refs: ShotOutputRef[] = [];
  for (const p of publications) {
    if (p.state && p.state !== "completed") continue;
    const byArtifact = shot.artifact_ids.includes(p.artifact_id);
    const byHash = shot.content_hashes.includes(p.content_hash);
    if (!byArtifact && !byHash) continue;
    refs.push({
      publication_id: p.id,
      artifact_id: p.artifact_id,
      content_hash: p.content_hash,
      frame_count: p.frame_count,
    });
  }
  return refs;
}

function validFps(fpsNum: number | null, fpsDen: number | null): boolean {
  return (
    typeof fpsNum === "number" &&
    typeof fpsDen === "number" &&
    Number.isFinite(fpsNum) &&
    Number.isFinite(fpsDen) &&
    fpsNum > 0 &&
    fpsDen > 0
  );
}

/** frame -> seconds using the run's real fps (null when fps is unknown). */
export function frameToSeconds(frame: number, fpsNum: number | null, fpsDen: number | null): number | null {
  if (!validFps(fpsNum, fpsDen) || !Number.isFinite(frame) || frame < 0) return null;
  return (frame * (fpsDen as number)) / (fpsNum as number);
}

/** seconds -> frame using the run's real fps (null when fps is unknown). */
export function secondsToFrame(seconds: number, fpsNum: number | null, fpsDen: number | null): number | null {
  if (!validFps(fpsNum, fpsDen) || !Number.isFinite(seconds) || seconds < 0) return null;
  return Math.round((seconds * (fpsNum as number)) / (fpsDen as number));
}

/** The shot's window on the run timeline (time map for before/after sync). */
export function shotWindowOnRun(
  shot: ShotSummary,
  fpsNum: number | null,
  fpsDen: number | null,
): { start_sec: number; end_sec: number; duration_sec: number } | null {
  const start = frameToSeconds(shot.start_frame, fpsNum, fpsDen);
  const end = frameToSeconds(shot.end_frame + 1, fpsNum, fpsDen);
  if (start === null || end === null) return null;
  return { start_sec: start, end_sec: end, duration_sec: Math.max(0, end - start) };
}

/** Place a QC marker on the timeline from its canonical location only. */
export function placeQcMarker(
  marker: QcMarkerInput,
  fpsNum: number | null,
  fpsDen: number | null,
): PlacedMarker {
  const loc = marker.location;
  const base = {
    qc_item_id: marker.qc_item_id,
    severity: marker.severity,
    reason_code: marker.reason_code,
  };
  if (loc === null) {
    return { ...base, status: "no_location", reason_vi: "QC item chưa có vị trí canonical — không suy đoán frame." };
  }
  const frameFromLoc =
    typeof loc.frame_index === "number" && Number.isFinite(loc.frame_index) && loc.frame_index >= 0
      ? loc.frame_index
      : null;
  const secondsFromMs =
    typeof loc.timecode_ms === "number" && Number.isFinite(loc.timecode_ms) && loc.timecode_ms >= 0
      ? loc.timecode_ms / 1000
      : null;
  // seconds: prefer the canonical timecode; otherwise convert the frame with
  // the run's real fps.  The FRAME itself never needs fps (it comes straight
  // from qc-navigation) — fps is only a seek helper.
  let seconds: number | null = secondsFromMs;
  if (seconds === null && frameFromLoc !== null) {
    seconds = frameToSeconds(frameFromLoc, fpsNum, fpsDen);
  }
  let frame: number | null = frameFromLoc;
  if (frame === null && secondsFromMs !== null) {
    frame = secondsToFrame(secondsFromMs, fpsNum, fpsDen);
  }
  if (frame === null && seconds === null) {
    return { ...base, status: "no_location", reason_vi: "QC item không có frame_index lẫn timecode — mở đúng frame là không thể." };
  }
  return { ...base, status: "ok", frame, seconds, role_id: loc.object_role_id };
}

/** Which real API controls apply to a run status (no dead buttons). */
export function reviewControls(status: string): ReviewControls {
  switch (status) {
    case "pending":
      return { cancel: true, resume: true, retry: false, note_vi: "Run đang chờ — có thể tạm dừng (huỷ) hoặc để chạy tiếp." };
    case "running":
      return { cancel: true, resume: true, retry: false, note_vi: "Run đang chạy — tạm dừng sẽ dừng job; chạy lại phần lỗi bằng Thử lại shot." };
    case "verifying":
      return { cancel: true, resume: true, retry: false, note_vi: "Run đang xác minh — tạm dừng sẽ dừng job đang chạy." };
    case "failed":
      return { cancel: false, resume: true, retry: true, note_vi: "Run thất bại — Thử lại tạo lượt kế tiếp giữ nguyên chunk đã đạt." };
    case "cancelled":
      return { cancel: false, resume: false, retry: true, note_vi: "Run đã tạm dừng — dùng Thử lại để tạo lượt kế tiếp (resume không áp dụng cho run đã huỷ)." };
    case "completed":
      return { cancel: false, resume: false, retry: false, note_vi: "Run đã hoàn tất — không còn thao tác chạy/dừng." };
    default:
      return { cancel: false, resume: false, retry: false, note_vi: "Trạng thái run không xác định — chỉ đọc, không thao tác." };
  }
}

/**
 * Scoped-retry payload for ONE shot.  Requires an APPLIED correction
 * authority of the run (the recompute endpoint refuses anything else);
 * returns null when the authority is missing — the UI shows the typed
 * refusal instead of inventing a correction id.
 */
export function scopedRetryPayload(
  shotId: string,
  authority: ScopedRetryAuthority | null,
  revision: number | null,
): ScopedRetryPayload | null {
  if (!authority || !authority.correction_id || authority.target_layer_ids.length === 0) return null;
  if (!shotId) return null;
  return {
    correction_id: authority.correction_id,
    correction_kind: authority.correction_kind,
    target_layer_ids: [...authority.target_layer_ids],
    target_shot_ids: [shotId],
    expected_revision: revision,
  };
}

/**
 * Extract the applied-correction authority the review UI may replay for a
 * scoped retry.  Reads ONLY explicit checkpoint fields; anything malformed
 * yields null (typed refusal downstream).
 */
export function correctionAuthorityFromCheckpoint(checkpoint: Record<string, unknown> | null): ScopedRetryAuthority | null {
  if (!checkpoint) return null;
  const raw = checkpoint.correction;
  if (typeof raw !== "object" || raw === null) return null;
  const rec = raw as Record<string, unknown>;
  const id = typeof rec.correction_id === "string" ? rec.correction_id : null;
  const kind = typeof rec.correction_kind === "string" ? rec.correction_kind : null;
  const layers = Array.isArray(rec.target_layer_ids)
    ? rec.target_layer_ids.filter((v): v is string => typeof v === "string" && v.length > 0)
    : [];
  if (!id || !kind || layers.length === 0) return null;
  return { correction_id: id, correction_kind: kind, target_layer_ids: layers };
}

/** Map real backend/transport errors to Vietnamese copy + an action. */
export function classifyReviewError(input: ReviewErrorInput): ReviewErrorCopy {
  const code = (input.code ?? "").trim();
  const message = (input.message ?? "").toLowerCase();
  const status = typeof input.status === "number" ? input.status : null;
  if (code.startsWith("shot_cache_")) {
    const copy: Record<string, ReviewErrorCopy> = {
      shot_cache_receipt_conflict: {
        code,
        title_vi: "Xung đột receipt cache của shot",
        action_vi: "Mở đúng shot bị đánh dấu, chạy lại shot đó; các shot khác giữ nguyên hash.",
        retryable: true,
      },
      shot_cache_submit_in_doubt: {
        code,
        title_vi: "Lần submit trước chưa rõ kết quả",
        action_vi: "Không submit lại tự động — xem trạng thái run rồi thử lại shot bằng nút Thử lại shot.",
        retryable: false,
      },
      shot_cache_attempt_cancelled: {
        code,
        title_vi: "Shot bị huỷ giữa lúc render",
        action_vi: "Thử lại shot này để tạo lượt render mới.",
        retryable: true,
      },
      shot_cache_attempt_unknown: {
        code,
        title_vi: "Không tìm thấy lượt render của shot",
        action_vi: "Tải lại trạng thái run; nếu vẫn thiếu, thử lại shot để tạo lượt mới.",
        retryable: true,
      },
      shot_cache_state_invalid: {
        code,
        title_vi: "Trạng thái cache không hợp lệ",
        action_vi: "Tải lại trạng thái run trước khi thao tác tiếp.",
        retryable: false,
      },
      shot_cache_replay_artifact_stale: {
        code,
        title_vi: "Artifact cache của shot đã cũ",
        action_vi: "Chạy lại shot này — receipt cũ sẽ được thay bằng bản mới.",
        retryable: true,
      },
      shot_cache_key_invalid: {
        code,
        title_vi: "Khoá nội dung shot không hợp lệ",
        action_vi: "Kiểm tra nguồn/cast của shot rồi chạy lại; không sửa graph Comfy thủ công.",
        retryable: false,
      },
    };
    const hit = copy[code];
    if (hit) return hit;
    return {
      code,
      title_vi: "Lỗi cache render của shot",
      action_vi: "Xem chi tiết lỗi và thử lại shot bị ảnh hưởng.",
      retryable: true,
    };
  }
  if (message.includes("out of memory") || message.includes("outofmemoryerror") || message.includes("cuda oom")) {
    return {
      code: code || "engine_out_of_memory",
      title_vi: "Hết bộ nhớ GPU khi render (OOM)",
      action_vi: "Giảm tải (profile nhẹ hơn/chunk ngắn hơn) rồi thử lại shot lỗi; không đổi graph thủ công.",
      retryable: true,
    };
  }
  if (message.includes("no durable job manifest") || message.includes("missing source") || message.includes("source media")) {
    return {
      code: code || "source_media_missing",
      title_vi: "Thiếu nguồn/authority của run",
      action_vi: "Khôi phục hoặc chọn lại source media của video rồi submit lại run.",
      retryable: false,
    };
  }
  if (message.includes("affected closure is empty") || message.includes("no matching layer")) {
    return {
      code: code || "recompute_closure_empty",
      title_vi: "Không có chunk nào khớp phạm vi sửa",
      action_vi: "Chọn đúng shot/layer cần sửa — phạm vi trống thì không render lại gì.",
      retryable: false,
    };
  }
  switch (status) {
    case 404:
      return {
        code: code || "not_found",
        title_vi: "Không tìm thấy run/correction",
        action_vi: "Kiểm tra lại run_id/project và tải lại trạng thái mới nhất.",
        retryable: false,
      };
    case 409:
      return {
        code: code || "state_conflict",
        title_vi: "Xung đột trạng thái",
        action_vi: "Đã có tiến trình khác cho run này — tải lại trạng thái rồi thao tác lại.",
        retryable: true,
      };
    case 422:
      return {
        code: code || "invalid_request",
        title_vi: "Yêu cầu không hợp lệ",
        action_vi: "Xem chi tiết lỗi, chỉnh tham số đúng rồi gửi lại.",
        retryable: false,
      };
    case 500:
    case 502:
    case 503:
    case 504:
      return {
        code: code || "backend_error",
        title_vi: "Lỗi backend tạm thời",
        action_vi: "Chờ backend ổn định rồi thử lại (retry an toàn, không nhân đôi submit).",
        retryable: true,
      };
    default:
      break;
  }
  if (message.includes("failed to fetch") || message.includes("networkerror") || message.includes("load failed")) {
    return {
      code: code || "network_unreachable",
      title_vi: "Không kết nối được backend",
      action_vi: "Kiểm tra backend đang chạy (mặc định http://localhost:8888) rồi thử lại.",
      retryable: true,
    };
  }
  return {
    code: code || "unknown_error",
    title_vi: "Lỗi không xác định",
    action_vi: "Tải lại trạng thái; nếu vẫn lỗi, xem log backend để biết nguyên nhân.",
    retryable: true,
  };
}

/**
 * Single-flight mutation latch: two rapid clicks on ONE intent issue exactly
 * one request; the second caller receives the in-flight promise.  After the
 * promise settles a new call starts a new request (explicit retry).
 */
export function createSingleFlight(): {
  run: <T>(fn: () => Promise<T>) => Promise<T>;
  isPending: () => boolean;
} {
  let pending: Promise<unknown> | null = null;
  return {
    run<T>(fn: () => Promise<T>): Promise<T> {
      if (pending) return pending as Promise<T>;
      const p = (async () => {
        try {
          return await fn();
        } finally {
          pending = null;
        }
      })();
      pending = p;
      return p;
    },
    isPending(): boolean {
      return pending !== null;
    },
  };
}

/** URL + localStorage persistence so a refresh keeps the review state. */
export interface ReviewState {
  runId: string | null;
  shotId: string | null;
  frame: number | null;
  /** Seek position in seconds (QC marker timecode) — survives a refresh too. */
  seconds?: number | null;
}

export function serializeReviewState(state: ReviewState): string {
  const parts: string[] = [];
  if (state.runId) parts.push(`run=${encodeURIComponent(state.runId)}`);
  if (state.shotId) parts.push(`shot=${encodeURIComponent(state.shotId)}`);
  if (typeof state.frame === "number" && Number.isFinite(state.frame) && state.frame >= 0) {
    parts.push(`frame=${Math.floor(state.frame)}`);
  }
  if (typeof state.seconds === "number" && Number.isFinite(state.seconds) && state.seconds >= 0) {
    parts.push(`sec=${state.seconds}`);
  }
  return parts.join("&");
}

export function parseReviewState(search: string): ReviewState {
  const out: ReviewState = { runId: null, shotId: null, frame: null, seconds: null };
  const qs = search.startsWith("?") ? search.slice(1) : search;
  if (!qs) return out;
  for (const pair of qs.split("&")) {
    const idx = pair.indexOf("=");
    if (idx <= 0) continue;
    const key = pair.slice(0, idx);
    const value = decodeURIComponent(pair.slice(idx + 1));
    if (key === "run" && value) out.runId = value;
    else if (key === "shot" && value) out.shotId = value;
    else if (key === "frame") {
      const n = Number.parseInt(value, 10);
      if (Number.isFinite(n) && n >= 0) out.frame = n;
    } else if (key === "sec") {
      const n = Number.parseFloat(value);
      if (Number.isFinite(n) && n >= 0) out.seconds = n;
    }
  }
  return out;
}

export const REVIEW_STORAGE_KEY = "mf.shotReview.state";
