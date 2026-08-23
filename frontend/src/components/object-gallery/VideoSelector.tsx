"use client";

/**
 * Explicit project video selector (S08-T04-C1, finding E #5) for
 * multi-video projects. Lists the durable Video Items of the project
 * (S03 GET /api/v2/projects/{id}/videos) and switches the gallery view by
 * stable video_item_id — the chain/gallery state is per video.
 */

import { Film } from "lucide-react";
import type { ProjectVideoItem } from "@/lib/api";
import { shortId } from "./galleryUtils";

export interface VideoSelectorProps {
  videos: ProjectVideoItem[];
  currentVideoId: string | null;
  loading: boolean;
  error: string | null;
  onSelect: (videoItemId: string) => void;
}

export function VideoSelector({
  videos,
  currentVideoId,
  loading,
  error,
  onSelect,
}: VideoSelectorProps) {
  return (
    <section
      aria-label="Chọn video của dự án"
      className="rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="inline-flex items-center gap-2 font-display text-sm font-semibold text-[var(--text-primary)]">
          <Film aria-hidden="true" size={15} className="text-[var(--accent-300)]" />
          Video trong dự án
          <span className="rounded-full bg-[var(--surface-800)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-secondary)]">
            {videos.length}
          </span>
        </h2>
      </div>
      {loading && (
        <p className="mt-2 text-[11px] text-[var(--text-muted)]" aria-busy="true">
          Đang tải danh sách video…
        </p>
      )}
      {error && (
        <p className="mt-2 text-[11px] text-[var(--danger)]" role="alert">
          Không tải được danh sách video: {error}
        </p>
      )}
      {!loading && !error && videos.length === 0 && (
        <p className="mt-2 text-[11px] text-[var(--text-muted)]">
          Chưa có video nào trong dự án — hãy thêm video ở bước Nhập &amp; Phân tích.
        </p>
      )}
      {videos.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2" role="listbox" aria-label="Chọn video">
          {videos.map((video) => {
            const active = video.video_item_id === currentVideoId;
            return (
              <li key={video.video_item_id} role="option" aria-selected={active}>
                <button
                  type="button"
                  onClick={() => onSelect(video.video_item_id)}
                  aria-pressed={active}
                  className={`flex min-h-9 items-center gap-2 rounded-lg border px-3 text-xs font-medium transition-colors ${
                    active
                      ? "border-[var(--primary-500)] bg-[var(--primary-600)]/15 text-[var(--primary-300)]"
                      : "border-[var(--surface-700)] bg-[var(--surface-850)] text-[var(--text-secondary)] hover:bg-[var(--surface-800)]"
                  }`}
                >
                  <span className="max-w-40 truncate">
                    {video.title || `Video ${video.position + 1}`}
                  </span>
                  <span className="font-mono text-[10px] text-[var(--text-faint)]">
                    {shortId(video.video_item_id)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
        Chọn video để duyệt đối tượng của đúng video đó; dữ liệu mỗi video hoàn toàn tách biệt.
      </p>
    </section>
  );
}
