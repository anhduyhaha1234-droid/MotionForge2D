"use client";

/**
 * MF-END-24 — ShotReviewPanel (the Demo/Apply review surface).
 *
 * One panel that lets a user: watch before/after in sync, see the shot list
 * with real progress, see QC markers at the exact frame/role, retry ONE
 * failed shot, and pause/cancel/retry/resume the run — all through the real
 * API.  State survives a refresh (URL params + localStorage).  Every button
 * carries Vietnamese helper text; every number is backend truth.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { BeforeAfterSync } from "./BeforeAfterSync";
import { QcMarkerList } from "./QcMarkerList";
import { ShotList } from "./ShotList";
import { useShotReview } from "./useShotReview";
import {
  REVIEW_STORAGE_KEY,
  parseReviewState,
  reviewControls,
  serializeReviewState,
  shotOutputRefs,
  shotWindowOnRun,
  type ShotOutputRef,
} from "./shotReviewLogic";

const HELPER = "text-[11px] leading-snug text-gray-400";

export interface ShotReviewPanelProps {
  runId: string | null;
  projectId?: string | null;
  videoItemId?: string | null;
  beforeUrl?: string | null;
  afterUrl?: string | null;
  /** Enable the URL/localStorage persistence (off for embedded demo cards). */
  persist?: boolean;
  compact?: boolean;
}

export function ShotReviewPanel({
  runId: runIdProp,
  projectId = null,
  videoItemId = null,
  beforeUrl = null,
  afterUrl = null,
  persist = true,
  compact = false,
}: ShotReviewPanelProps) {
  const [runId, setRunId] = useState<string | null>(runIdProp);
  const [activeShotId, setActiveShotId] = useState<string | null>(null);
  const [seekToSeconds, setSeekToSeconds] = useState<number | null>(null);
  const [markerFrame, setMarkerFrame] = useState<number | null>(null);
  const [activeMarkerId, setActiveMarkerId] = useState<string | null>(null);

  // Restore the review state on mount (refresh-safe), then keep it in the URL.
  useEffect(() => {
    if (!persist || typeof window === "undefined") return;
    queueMicrotask(() => {
      const fromUrl = parseReviewState(window.location.search);
      let restoredRun = runIdProp ?? fromUrl.runId;
      let restoredShot = fromUrl.shotId;
      let restoredFrame = fromUrl.frame;
      if (!restoredRun) {
        try {
          const raw = window.localStorage.getItem(REVIEW_STORAGE_KEY);
          if (raw) {
            const parsed = JSON.parse(raw) as { runId?: string | null; shotId?: string | null; frame?: number | null };
            restoredRun = restoredRun ?? parsed.runId ?? null;
            restoredShot = restoredShot ?? parsed.shotId ?? null;
            restoredFrame = restoredFrame ?? (typeof parsed.frame === "number" ? parsed.frame : null);
          }
        } catch {
          /* corrupted storage is ignored — state simply starts empty */
        }
      }
      if (restoredRun) setRunId(restoredRun);
      if (restoredShot) setActiveShotId(restoredShot);
      if (typeof restoredFrame === "number") setMarkerFrame(restoredFrame);
      if (typeof fromUrl.seconds === "number") setSeekToSeconds(fromUrl.seconds);
    });
  }, [persist, runIdProp]);

  useEffect(() => {
    if (!persist || typeof window === "undefined") return;
    const state = { runId, shotId: activeShotId, frame: markerFrame, seconds: seekToSeconds };
    const qs = serializeReviewState(state);
    try {
      const next = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
      window.history.replaceState(null, "", next);
      window.localStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* storage may be unavailable (private mode) — URL state still holds */
    }
  }, [persist, runId, activeShotId, markerFrame, seekToSeconds]);

  const review = useShotReview({
    runId,
    projectId,
    videoItemId,
  });

  const controls = reviewControls(review.data?.status ?? "");
  const outputRefs = useMemo(() => {
    const map: Record<string, ShotOutputRef[]> = {};
    if (!review.data) return map;
    for (const shot of review.shots) {
      map[shot.shot_id] = shotOutputRefs(shot, review.data.publications);
    }
    return map;
  }, [review.shots, review.data]);

  const activeShot = useMemo(
    () => review.shots.find((s) => s.shot_id === activeShotId) ?? null,
    [review.shots, activeShotId],
  );

  const shotWindow = useMemo(() => {
    if (!activeShot || !review.data) return null;
    return shotWindowOnRun(activeShot, review.data.fps_num, review.data.fps_den);
  }, [activeShot, review.data]);

  const busyShotId = review.action?.kind === "retry_shot" && !review.action.error ? review.action.shotId ?? null : null;

  const onRetryShot = useCallback(
    (shotId: string) => {
      setActiveShotId(shotId);
      void review.retryShot(shotId);
    },
    [review],
  );

  const onSeekMarker = useCallback(
    (seconds: number, markerId: string) => {
      setSeekToSeconds(seconds);
      setActiveMarkerId(markerId);
      const marker = review.markers.find((m) => m.status === "ok" && m.qc_item_id === markerId);
      setMarkerFrame(marker && marker.status === "ok" ? marker.frame : null);
    },
    [review.markers],
  );

  return (
    <section className="rounded border border-gray-700 bg-gray-900/60 p-4" data-testid="shot-review-panel">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-100">Xem lại shot: trước/sau, QC và thử lại phần lỗi</h2>
          <p className={HELPER}>
            Dữ liệu lấy trực tiếp từ run Full Apply + QC item của backend; trạng thái được giữ khi tải lại trang.
          </p>
        </div>
        <div className="flex flex-col items-start gap-1">
          <button
            type="button"
            onClick={() => void review.refresh()}
            className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700"
            data-testid="shot-review-refresh"
          >
            Làm mới trạng thái
          </button>
          <p className={HELPER}>Đọc lại run + QC item mới nhất từ backend.</p>
        </div>
      </header>

      {runId ? (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-gray-300">
            <span className="rounded bg-gray-800 px-2 py-0.5" data-testid="shot-review-status">
              Run: <span className="font-mono">{runId.slice(0, 8)}…</span> · trạng thái{" "}
              <span className="font-medium">{review.data?.status ?? "…"}</span>
            </span>
            <span className="rounded bg-gray-800 px-2 py-0.5" data-testid="shot-review-attempt">
              Lần thử: {review.data?.attempt ?? "—"}
            </span>
            <span className="rounded bg-gray-800 px-2 py-0.5" data-testid="shot-review-progress">
              Tiến độ: {review.progress ?? 0}% ({review.data?.chunks.filter((c) => c.state === "completed").length ?? 0}/
              {review.data?.chunks.length ?? 0} chunk)
            </span>
            {review.isPolling && <span className="text-[11px] text-indigo-300">đang cập nhật…</span>}
          </div>

          <div className="mt-3 flex flex-wrap items-start gap-3">
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => void review.cancel()}
                disabled={!controls.cancel}
                className="rounded bg-amber-700 px-3 py-1.5 text-xs text-white hover:bg-amber-600 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"
                data-testid="shot-review-cancel"
              >
                Tạm dừng run
              </button>
              <p className={HELPER}>Dừng job đang chạy; chạy lại sau bằng nút Thử lại run.</p>
            </div>
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => void review.resume()}
                disabled={!controls.resume}
                className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700 disabled:cursor-not-allowed disabled:text-gray-500"
                data-testid="shot-review-resume"
              >
                Chạy tiếp (resume)
              </button>
              <p className={HELPER}>Chỉ chạy tiếp chunk chưa xong; chunk đã xác minh được giữ nguyên.</p>
            </div>
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => void review.retry()}
                disabled={!controls.retry}
                className="rounded bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"
                data-testid="shot-review-retry"
              >
                Thử lại run (lượt mới)
              </button>
              <p className={HELPER}>Tạo lượt kế tiếp giữ nguyên chunk đã đạt — không nhân đôi submit.</p>
            </div>
            <p className={`${HELPER} max-w-md self-center`} data-testid="shot-review-controls-note">
              {controls.note_vi}
            </p>
          </div>

          {review.error && (
            <div className="mt-3 rounded bg-red-900/40 px-3 py-2" data-testid="shot-review-error">
              <p className="text-xs font-medium text-red-200">{review.error.title_vi}</p>
              <p className={HELPER}>{review.error.action_vi}</p>
            </div>
          )}

          {review.action?.error && (
            <div className="mt-3 rounded bg-amber-900/40 px-3 py-2" data-testid="shot-review-action-error">
              <p className="text-xs font-medium text-amber-200">{review.action.error.title_vi}</p>
              <p className={HELPER}>{review.action.error.action_vi}</p>
            </div>
          )}

          {review.action && !review.action.error && review.action.result && (
            <p className="mt-3 text-[11px] text-emerald-300" data-testid="shot-review-action-ok">
              {review.action.kind === "retry_shot"
                ? `Đã gửi yêu cầu chạy lại shot ${review.action.shotId} (1 lần cho 1 cú bấm).`
                : `Đã gửi thao tác ${review.action.kind} tới backend.`}
            </p>
          )}

          {!compact && (
            <div className="mt-3">
              <ShotList
                shots={review.shots}
                outputRefs={outputRefs}
                canRetryShot={Boolean(review.data) && review.data?.status !== "running"}
                busyShotId={busyShotId}
                onRetryShot={onRetryShot}
                onSelectShot={setActiveShotId}
                activeShotId={activeShotId}
              />
            </div>
          )}

          <div className="mt-3">
            <BeforeAfterSync
              beforeUrl={beforeUrl}
              afterUrl={afterUrl}
              fpsNum={review.data?.fps_num ?? null}
              fpsDen={review.data?.fps_den ?? null}
              frameCount={review.data?.frame_count ?? 0}
              markers={review.markers}
              seekToSeconds={seekToSeconds}
              shotWindow={shotWindow ? { start_sec: shotWindow.start_sec, end_sec: shotWindow.end_sec } : null}
              label={activeShot ? `Đồng bộ trước/sau — shot ${activeShot.shot_id}` : "Đồng bộ trước/sau theo time map"}
            />
          </div>

          <div className="mt-3">
            <QcMarkerList
              markers={review.markers}
              phase={review.markersPhase}
              errorText={review.markersError?.title_vi ?? null}
              activeMarkerId={activeMarkerId}
              onSeek={onSeekMarker}
            />
          </div>
        </>
      ) : (
        <p className="mt-3 rounded bg-gray-800 px-3 py-2 text-xs text-gray-300" data-testid="shot-review-empty">
          Chưa có run Full Apply để xem lại — hãy chạy Apply trước, rồi mở lại mục này.
        </p>
      )}
    </section>
  );
}
