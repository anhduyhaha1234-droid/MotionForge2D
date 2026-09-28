"use client";

/**
 * MF-END-24 — QcMarkerList.
 *
 * One row per QC item of the reviewed video.  The frame/role shown comes
 * from the item's canonical navigation (qc-navigation), never from the
 * evidence blob guessed client-side; an item without a canonical location
 * renders the typed refusal text instead of a fabricated frame.
 */

import type { PlacedMarker } from "./shotReviewLogic";

const HELPER = "text-[11px] leading-snug text-gray-400";

export interface QcMarkerListProps {
  markers: PlacedMarker[];
  phase: "loading" | "ready" | "error" | "empty";
  errorText?: string | null;
  onSeek?: (seconds: number, markerId: string) => void;
  activeMarkerId?: string | null;
}

function severityClass(severity: string): string {
  if (severity === "blocker") return "bg-red-900/60 text-red-200";
  if (severity === "warning") return "bg-amber-900/60 text-amber-200";
  return "bg-gray-700 text-gray-200";
}

export function QcMarkerList({ markers, phase, errorText, onSeek, activeMarkerId }: QcMarkerListProps) {
  return (
    <section className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="shot-review-markers">
      <div>
        <h3 className="text-sm font-semibold text-gray-100">QC marker của video</h3>
        <p className={HELPER}>
          Mỗi marker trỏ đúng frame + role lấy từ qc-navigation; bấm “Xem đúng frame” để tua cả hai video.
        </p>
      </div>

      {phase === "loading" && <p className="mt-3 text-xs text-gray-400">Đang tải QC item…</p>}

      {phase === "error" && (
        <p className="mt-3 rounded bg-red-900/40 px-3 py-2 text-xs text-red-200" data-testid="shot-review-markers-error">
          Không tải được QC item: {errorText ?? "lỗi không rõ"} — dùng nút Làm mới để thử lại.
        </p>
      )}

      {phase === "empty" && (
        <p className="mt-3 text-xs text-gray-400" data-testid="shot-review-markers-empty">
          Chưa có QC item nào cho video này — chạy QC (check-run) rồi quay lại; UI không tự sinh marker.
        </p>
      )}

      {phase === "ready" && (
        <ul className="mt-3 space-y-2">
          {markers.map((m) => (
            <li
              key={m.qc_item_id}
              className={`rounded bg-gray-800 px-3 py-2 ${activeMarkerId === m.qc_item_id ? "ring-1 ring-indigo-400" : ""}`}
              data-testid={`shot-review-marker-row-${m.qc_item_id}`}
            >
              <div className="flex flex-wrap items-center gap-2 text-xs text-gray-200">
                <span className={`rounded px-1.5 py-0.5 text-[11px] ${severityClass(m.severity)}`}>{m.severity}</span>
                <span className="font-mono">{m.reason_code}</span>
                {m.status === "ok" ? (
                  <>
                    <span>
                      frame <span className="font-mono text-gray-100">{m.frame ?? "—"}</span>
                      {m.seconds !== null && <> · {m.seconds.toFixed(3)}s</>}
                    </span>
                    {m.role_id && (
                      <span>
                        role <span className="font-mono text-gray-100">{m.role_id}</span>
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-amber-300">{m.reason_vi}</span>
                )}
              </div>
              {m.status === "ok" && m.seconds !== null && onSeek && (
                <div className="mt-2 flex flex-col items-start gap-1">
                  <button
                    type="button"
                    onClick={() => onSeek(m.seconds as number, m.qc_item_id)}
                    className="rounded bg-gray-700 px-2 py-1 text-[11px] text-gray-100 hover:bg-gray-600"
                    data-testid={`shot-review-marker-seek-${m.qc_item_id}`}
                  >
                    {m.frame !== null ? `Xem đúng frame ${m.frame}` : `Tua tới ${m.seconds.toFixed(3)}s`}
                  </button>
                  <p className={HELPER}>Tua hai video tới đúng vị trí canonical của marker này.</p>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
