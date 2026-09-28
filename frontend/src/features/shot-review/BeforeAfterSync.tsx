"use client";

/**
 * MF-END-24 — BeforeAfterSync.
 *
 * Two REAL <video> elements (source + rendered output) frame-locked by
 * currentTime, plus a timeline that shows the run's time map (frame ⇄
 * seconds from the run's real fps) with the QC marker ticks placed by the
 * caller.  Nothing plays on its own and no frame is synthesised: a missing
 * media URL renders a typed note instead of an empty player.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { PlacedMarker } from "./shotReviewLogic";

const HELPER = "text-[11px] leading-snug text-gray-400";

export interface BeforeAfterSyncProps {
  beforeUrl?: string | null;
  afterUrl?: string | null;
  fpsNum: number | null;
  fpsDen: number | null;
  frameCount: number;
  markers?: PlacedMarker[];
  /** When set, both videos seek to this time (QC marker navigation). */
  seekToSeconds?: number | null;
  /** Shot window on the run timeline (seconds), from the real chunk range. */
  shotWindow?: { start_sec: number; end_sec: number } | null;
  label?: string;
}

function absolute(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  const base = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888").replace(/\/+$/, "");
  return url.startsWith("/") ? `${base}${url}` : `${base}/${url}`;
}

export function BeforeAfterSync({
  beforeUrl,
  afterUrl,
  fpsNum,
  fpsDen,
  frameCount,
  markers = [],
  seekToSeconds = null,
  shotWindow = null,
  label = "Đồng bộ trước/sau theo time map",
}: BeforeAfterSyncProps) {
  const [playing, setPlaying] = useState(false);
  const [currentSec, setCurrentSec] = useState(0);
  const beforeRef = useRef<HTMLVideoElement | null>(null);
  const afterRef = useRef<HTMLVideoElement | null>(null);

  const fps = fpsNum && fpsDen && fpsNum > 0 && fpsDen > 0 ? fpsNum / fpsDen : null;
  const totalSec = fps ? frameCount / fps : null;

  const currentFrame = fps ? Math.floor(currentSec * fps) : null;

  const syncFrom = useCallback((source: HTMLVideoElement | null) => {
    const other = source === beforeRef.current ? afterRef.current : beforeRef.current;
    if (!source || !other) return;
    if (Math.abs(source.currentTime - other.currentTime) > 0.15) {
      other.currentTime = source.currentTime;
    }
    setCurrentSec(source.currentTime);
  }, []);

  useEffect(() => {
    const before = beforeRef.current;
    const after = afterRef.current;
    if (!before || !after) return;
    const onBefore = () => syncFrom(before);
    const onAfter = () => syncFrom(after);
    const onSeeked = () => setCurrentSec(before.currentTime);
    before.addEventListener("timeupdate", onBefore);
    after.addEventListener("timeupdate", onAfter);
    before.addEventListener("seeked", onSeeked);
    after.addEventListener("seeked", onSeeked);
    return () => {
      before.removeEventListener("timeupdate", onBefore);
      after.removeEventListener("timeupdate", onAfter);
      before.removeEventListener("seeked", onSeeked);
      after.removeEventListener("seeked", onSeeked);
    };
  }, [syncFrom]);

  // QC marker navigation: seek BOTH videos to the marker's canonical time.
  useEffect(() => {
    if (seekToSeconds === null) return;
    const seconds = seekToSeconds;
    for (const el of [beforeRef.current, afterRef.current]) {
      if (el) el.currentTime = seconds;
    }
    queueMicrotask(() => setCurrentSec(seconds));
  }, [seekToSeconds]);

  const togglePlay = useCallback(() => {
    const before = beforeRef.current;
    const after = afterRef.current;
    if (!before || !after) return;
    if (playing) {
      before.pause();
      after.pause();
      setPlaying(false);
    } else {
      after.currentTime = before.currentTime;
      void before.play();
      void after.play();
      setPlaying(true);
    }
  }, [playing]);

  const stepFrame = useCallback(
    (delta: number) => {
      if (fps === null) return;
      const before = beforeRef.current;
      const after = afterRef.current;
      if (!before || !after) return;
      const next = Math.max(0, before.currentTime + delta / fps);
      before.currentTime = next;
      after.currentTime = next;
      setCurrentSec(next);
    },
    [fps],
  );

  const missing: string[] = [];
  if (!beforeUrl) missing.push("video nguồn");
  if (!afterUrl) missing.push("video kết quả render");

  return (
    <section className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="shot-review-sync">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-100">{label}</h3>
          <p className={HELPER}>
            Hai video được khoá cùng thời điểm theo time map thật của run; QC marker nhảy đúng frame đã đánh dấu.
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={togglePlay}
              disabled={missing.length > 0}
              className="rounded bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-400"
              data-testid="shot-review-play"
            >
              {playing ? "Tạm dừng phát" : "Phát cả hai"}
            </button>
            <p className={HELPER}>Phát đồng thời nguồn và kết quả, giữ đúng khung hình.</p>
          </div>
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={() => stepFrame(-1)}
              disabled={fps === null}
              className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700 disabled:cursor-not-allowed disabled:text-gray-500"
              data-testid="shot-review-step-back"
            >
              Lùi 1 frame
            </button>
            <p className={HELPER}>Xem khung ngay trước để đối chiếu chuyển động.</p>
          </div>
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={() => stepFrame(1)}
              disabled={fps === null}
              className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700 disabled:cursor-not-allowed disabled:text-gray-500"
              data-testid="shot-review-step-forward"
            >
              Tiến 1 frame
            </button>
            <p className={HELPER}>Xem khung ngay sau để kiểm tra khớp chuyển động.</p>
          </div>
        </div>
      </div>

      {missing.length > 0 && (
        <p className="mt-3 rounded bg-gray-800 px-3 py-2 text-xs text-amber-300" data-testid="shot-review-sync-missing">
          Chưa có {missing.join(" và ")} để phát — UI không tự tạo media giả. Hãy hoàn tất render/export rồi mở lại.
        </p>
      )}

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <figure>
          <figcaption className="mb-1 text-xs text-gray-300">Nguồn (before)</figcaption>
          {beforeUrl ? (
            <video
              ref={beforeRef}
              src={absolute(beforeUrl)}
              muted
              playsInline
              preload="metadata"
              className="w-full rounded bg-black"
              data-testid="shot-review-before"
            />
          ) : (
            <div className="flex h-40 items-center justify-center rounded border border-dashed border-gray-700 text-xs text-gray-400">
              Không có URL nguồn
            </div>
          )}
        </figure>
        <figure>
          <figcaption className="mb-1 text-xs text-gray-300">Kết quả render (after)</figcaption>
          {afterUrl ? (
            <video
              ref={afterRef}
              src={absolute(afterUrl)}
              playsInline
              preload="metadata"
              className="w-full rounded bg-black"
              data-testid="shot-review-after"
            />
          ) : (
            <div className="flex h-40 items-center justify-center rounded border border-dashed border-gray-700 text-xs text-gray-400">
              Không có URL kết quả
            </div>
          )}
        </figure>
      </div>

      <div className="mt-3" data-testid="shot-review-timeline">
        <div className="flex items-center justify-between text-[11px] text-gray-400">
          <span>
            Frame hiện tại: <span className="font-mono text-gray-200">{currentFrame ?? "—"}</span>
            {fps !== null && <> · fps {fps.toFixed(3)}</>}
          </span>
          <span>
            {fps !== null && totalSec !== null ? `Tổng ${frameCount} frame ≈ ${totalSec.toFixed(2)}s` : "Chưa có fps của run"}
          </span>
        </div>
        <div className="relative mt-1 h-3 w-full overflow-hidden rounded bg-gray-800">
          {shotWindow && totalSec ? (
            <div
              className="absolute h-full bg-indigo-900/70"
              style={{
                left: `${Math.min(100, (shotWindow.start_sec / totalSec) * 100)}%`,
                width: `${Math.max(0.5, ((shotWindow.end_sec - shotWindow.start_sec) / totalSec) * 100)}%`,
              }}
              data-testid="shot-review-shot-window"
            />
          ) : null}
          {fps !== null &&
            totalSec &&
            markers.map((m) =>
              m.status === "ok" && m.seconds !== null ? (
                <div
                  key={m.qc_item_id}
                  title={`${m.reason_code} @ ${m.frame !== null ? `frame ${m.frame}` : `${m.seconds.toFixed(3)}s`}`}
                  className={`absolute top-0 h-full w-0.5 ${m.severity === "blocker" ? "bg-red-500" : "bg-amber-400"}`}
                  style={{ left: `${Math.min(100, (m.seconds / totalSec) * 100)}%` }}
                  data-testid={`shot-review-marker-${m.qc_item_id}`}
                />
              ) : null,
            )}
          {fps !== null && totalSec ? (
            <div
              className="absolute top-0 h-full w-0.5 bg-white"
              style={{ left: `${Math.min(100, (currentSec / totalSec) * 100)}%` }}
            />
          ) : null}
        </div>
        <p className={HELPER}>
          Vạch trắng = vị trí phát hiện tại; vạch đỏ/vàng = QC marker theo frame thật (đỏ = blocker).
        </p>
      </div>
    </section>
  );
}
