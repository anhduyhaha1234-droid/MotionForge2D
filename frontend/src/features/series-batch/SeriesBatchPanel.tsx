"use client";

/**
 * MF-END-27 — panel batch series: xếp hai (hoặc nhiều) video cùng một bộ cast.
 *
 * Giao diện CHỈ gọi API batch đã có (seriesBatchApi); mọi nút đều có helper
 * text tiếng Việt ngay DƯỚI nút (text-gray-400, cỡ ≥11px) và không có tiến
 * trình giả (không random, không phần trăm tự chế).
 */

import { useCallback, useState } from "react";

import {
  batchStateLabel,
  canAdvance,
  errorText,
  leaseText,
  metricsText,
  outputText,
  videoStateLabel,
} from "./seriesBatchLogic";
import { seriesBatchApi, type SeriesBatchView } from "./seriesBatchApi";
import { ApiError } from "@/lib/api";

export interface SeriesBatchPanelProps {
  projectId: string;
  /** Hai video tối thiểu của cùng một bộ (series). */
  videos: Array<{ video_item_id: string; title: string }>;
  /** Payload export theo video — do màn hình export hiện có cung cấp. */
  exportPayloads: Record<string, Record<string, unknown>>;
  generation?: string;
}

function Helper({ children }: { children: string }) {
  return <p className="mt-1 text-[11px] leading-snug text-gray-400">{children}</p>;
}

function Button({
  label,
  helper,
  onClick,
  disabled,
  tone = "default",
}: {
  label: string;
  helper: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: "default" | "danger";
}) {
  const base =
    "rounded px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50";
  const colors =
    tone === "danger" ? "bg-red-700 hover:bg-red-600" : "bg-sky-700 hover:bg-sky-600";
  return (
    <div>
      <button type="button" className={`${base} ${colors}`} onClick={onClick} disabled={disabled}>
        {label}
      </button>
      <Helper>{helper}</Helper>
    </div>
  );
}

export function SeriesBatchPanel({
  projectId,
  videos,
  exportPayloads,
  generation = "1",
}: SeriesBatchPanelProps) {
  const [view, setView] = useState<SeriesBatchView | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const videoIds = videos.map((video) => video.video_item_id);

  const run = useCallback(
    async (action: () => Promise<SeriesBatchView | Record<string, unknown>>, noteText: string) => {
      setBusy(true);
      setNote(null);
      try {
        const result = await action();
        if (result && typeof result === "object" && "videos" in result) {
          setView(result as SeriesBatchView);
        }
        setNote(noteText);
      } catch (err) {
        const text =
          err instanceof ApiError
            ? err.detailText()
            : err instanceof Error
              ? err.message
              : String(err);
        setNote(`Lỗi: ${text}`);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const queue = () =>
    run(
      () =>
        seriesBatchApi.createBatch(projectId, {
          video_item_ids: videoIds,
          exports: exportPayloads,
          generation,
        }),
      "Đã xếp hàng — video thứ hai chờ lượt của video đầu.",
    );

  const refresh = () =>
    run(() => seriesBatchApi.getBatch(projectId, videoIds, generation), "Đã đọc lại hàng đợi.");

  const advance = () =>
    run(
      () =>
        seriesBatchApi.advanceBatch(projectId, {
          video_item_ids: videoIds,
          exports: exportPayloads,
          generation,
        }),
      "Đã mở video kế tiếp theo hàng đợi.",
    );

  const cancel = (videoItemId: string) =>
    run(
      () => seriesBatchApi.cancelVideo(projectId, videoIds, videoItemId, generation),
      `Đã yêu cầu huỷ ${videoItemId}; video khác không bị đụng tới.`,
    );

  return (
    <section className="rounded border border-gray-700 bg-gray-900 p-4 text-gray-200">
      <h2 className="text-base font-semibold text-white">Batch series — hai video cùng bộ nhân vật</h2>
      <p className="mt-1 text-[11px] leading-snug text-gray-400">
        Hàng đợi là hàng đợi job hiện có của app; batch chỉ xếp việc và giữ nguyên cast đã pin.
      </p>

      <div className="mt-3 flex flex-wrap gap-4">
        <Button
          label="Xếp hàng batch"
          helper="Chuẩn bị CPU cho mọi video trước, rồi chạy lần lượt từng video."
          onClick={queue}
          disabled={busy || videoIds.length < 2}
        />
        <Button
          label="Mở video kế tiếp"
          helper="Chỉ mở khi video trước đã kết thúc — tối đa một job nặng mỗi lúc."
          onClick={advance}
          disabled={busy || !canAdvance(view)}
        />
        <Button
          label="Tải lại trạng thái"
          helper="Đọc lại hàng đợi job thật sau restart; không xếp thêm việc."
          onClick={refresh}
          disabled={busy}
        />
      </div>

      {note ? <p className="mt-3 text-xs text-amber-300">{note}</p> : null}

      {view ? (
        <div className="mt-4 space-y-2">
          <p className="text-xs text-gray-400">
            {batchStateLabel(view.state)} · pack {view.pack_hash ? view.pack_hash.slice(0, 12) : "chưa có"}
            {" · "}
            {leaseText(view)}
          </p>
          <p className="text-xs text-gray-400">Đo lường: {metricsText(view.metrics)}</p>
          <ul className="divide-y divide-gray-800">
            {view.videos.map((row) => {
              const video = videos.find((item) => item.video_item_id === row.video_item_id);
              const rowError = errorText(row.error);
              return (
                <li key={row.video_item_id} className="py-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm text-white">
                        {video?.title ?? row.video_item_id} — {videoStateLabel(row.state)}
                      </p>
                      <p className="text-[11px] text-gray-400">{outputText(row.output)}</p>
                      {rowError ? <p className="text-[11px] text-red-400">{rowError}</p> : null}
                    </div>
                    <div>
                      <button
                        type="button"
                        className="rounded bg-red-700 px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
                        onClick={() => cancel(row.video_item_id)}
                        disabled={busy || row.state === "completed" || row.state === "cancelled"}
                      >
                        Huỷ video này
                      </button>
                      <Helper>Chỉ huỷ video này; video còn lại giữ nguyên.</Helper>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
