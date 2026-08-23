"use client";

/**
 * Shared presentation helpers for the Object Gallery (S08-T04).
 *
 * Everything rendered here is derived from REAL backend data (T01/T02/T03
 * responses) — confidence numbers, reasons, bbox geometry, artifact
 * metadata. Nothing is invented or mocked.
 */

import type { ReactNode } from "react";
import type { ObjectOccurrence, ObjectRoleKind, RoleMedia } from "@/lib/api";
import { roleMediaContentUrl } from "@/lib/api";

/**
 * Canonical seven-kind ObjectRole taxonomy (S08-A01) — Vietnamese labels.
 *
 * The MACHINE kinds and the removal-only policy come from the backend
 * (GET /api/v2/object-intelligence/kinds — the single taxonomy authority);
 * this map renders them in Vietnamese ONLY for display.  Filter options are
 * derived from the backend response, never this map alone.
 */
export const KIND_LABELS: Record<ObjectRoleKind, string> = {
  character: "Nhân vật",
  prop: "Vật phẩm",
  background: "Bối cảnh",
  foreground: "Tiền cảnh",
  graphic: "Nội dung/đồ họa",
  source_overlay: "Lớp nguồn cần loại bỏ",
  other: "Khác",
};

export function kindLabel(kind: ObjectRoleKind): string {
  return KIND_LABELS[kind] ?? kind;
}

/**
 * True when the given kind is backend-owned removal-only (source_overlay):
 * it is shown as removal-only in the gallery and NEVER offered as a
 * replacement/Character Pack candidate (no merge source/target, no
 * confirm-as-official, no split/edit/reassign surfaces).
 */
export function isRemovalOnlyKind(
  kind: ObjectRoleKind,
  removalOnlyKinds: ReadonlySet<ObjectRoleKind>,
): boolean {
  return removalOnlyKinds.has(kind);
}

/**
 * Review thresholds come from the BACKEND grouping policy metadata
 * (T03-C1) — never duplicated hardcoded UI constants. Callers receive
 * `policy.review_threshold` via useGalleryPolicy() and pass it down.
 */

/** Known machine reason codes → Vietnamese labels (raw code kept as provenance). */
export const REASON_LABELS: Record<string, string> = {
  "same-normalized-name": "Cùng tên chuẩn hóa",
  "spatial-footprint-consistent-across-scenes": "Vùng xuất hiện nhất quán giữa các cảnh",
  "occurrences-temporally-disjoint-ambiguity": "Xuất hiện ở các thời điểm khác nhau — có thể mơ hồ",
  "deterministic-scene-layout": "Bố cục cảnh (bộ phát hiện)",
  "detector": "Bộ phát hiện",
  "model": "Mô hình",
};

export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason;
}

export function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function shortId(id: string, length = 8): string {
  return id.length <= length ? id : id.slice(0, length);
}

export function formatTimeMs(timeMs: number): string {
  const totalSec = Math.floor(timeMs / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface RoleConfidenceSummary {
  average: number;
  min: number;
}

export function summarizeConfidence(occurrences: ObjectOccurrence[]): RoleConfidenceSummary {
  if (occurrences.length === 0) return { average: 0, min: 0 };
  const values = occurrences.map((o) => o.confidence);
  const min = Math.min(...values);
  const average = values.reduce((a, b) => a + b, 0) / values.length;
  return { average, min };
}

/** Backend-policy-driven low-confidence flag (review_threshold from policy). */
export function isLowConfidence(minConfidence: number, reviewThreshold: number): boolean {
  return minConfidence < reviewThreshold;
}

/**
 * REAL spatial footprint of a role's occurrences: every occurrence bbox is
 * drawn normalized into one 160×90 viewBox (scale by the role's own max
 * extent). This is a truthful geometric visualization of the detection
 * evidence — consistent footprints are exactly what the grouping reasons
 * describe — never a fabricated thumbnail.
 */
export function BboxFootprint({ occurrences }: { occurrences: ObjectOccurrence[] }) {
  if (occurrences.length === 0) {
    return (
      <div className="flex h-20 items-center justify-center rounded-md border border-dashed border-[var(--surface-700)] bg-black/30 text-[11px] text-[var(--text-faint)]">
        Không có bằng chứng khung hình
      </div>
    );
  }
  const maxX = Math.max(...occurrences.map((o) => o.bbox.x + o.bbox.width), 1);
  const maxY = Math.max(...occurrences.map((o) => o.bbox.y + o.bbox.height), 1);
  const viewW = 160;
  const viewH = 90;
  const colors = [
    "var(--primary-400)",
    "var(--accent-400)",
    "var(--success)",
    "var(--warning)",
    "var(--info)",
    "var(--danger)",
  ];
  return (
    <div>
      <svg
        viewBox={`0 0 ${viewW} ${viewH}`}
        role="img"
        aria-label="Bản đồ vùng xuất hiện của đối tượng qua các cảnh (chuẩn hóa theo vai trò)"
        className="h-auto w-full rounded-md border border-[var(--surface-700)] bg-black/40"
      >
        <rect x="0" y="0" width={viewW} height={viewH} fill="transparent" />
        {occurrences.map((occ, index) => {
          const x = (occ.bbox.x / maxX) * viewW;
          const y = (occ.bbox.y / maxY) * viewH;
          const w = (occ.bbox.width / maxX) * viewW;
          const h = (occ.bbox.height / maxY) * viewH;
          const color = colors[index % colors.length];
          return (
            <g key={occ.id}>
              <rect
                x={x}
                y={y}
                width={Math.max(2, w)}
                height={Math.max(2, h)}
                fill="none"
                stroke={color}
                strokeWidth={1.5}
              />
              <circle cx={x + w / 2} cy={y + h / 2} r={1.5} fill={color} />
            </g>
          );
        })}
      </svg>
      <ul className="mt-1.5 space-y-0.5">
        {occurrences.map((occ, index) => (
          <li key={occ.id} className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
            <span
              aria-hidden="true"
              className="inline-block size-2 shrink-0 rounded-full"
              style={{ backgroundColor: colors[index % colors.length] }}
            />
            <span className="truncate">
              Cảnh {shortId(occ.scene_id)} · khung {occ.frame_index} · {formatTimeMs(occ.time_ms)} ·{" "}
              {formatConfidence(occ.confidence)}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[10px] leading-snug text-[var(--text-faint)]">
        Vị trí khung phát hiện thật từ dữ liệu API, chuẩn hóa theo vùng lớn nhất của vai trò.
      </p>
    </div>
  );
}

/** Purpose codes → Vietnamese labels. */
export const ARTIFACT_PURPOSE_LABELS: Record<string, string> = {
  thumbnail: "Ảnh mẫu",
  mask: "Mặt nạ",
  result: "Kết quả",
};

/**
 * Honest artifact tile — REAL bytes preview via the contained content
 * endpoint (T02-C1): ETag=SHA-256, nosniff, 404/409 fail-closed. The
 * decoded dimensions are asserted in E2E (naturalWidth/naturalHeight).
 */
export function MediaTile({ media }: { media: RoleMedia }) {
  const purposeLabel = ARTIFACT_PURPOSE_LABELS[media.purpose] ?? media.purpose;
  const regenerated = media.relative_path.includes("/recompute/");
  return (
    <div className="rounded-lg border border-[var(--surface-700)] bg-[var(--surface-850)] p-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold text-[var(--text-secondary)]">{purposeLabel}</p>
        <span className="rounded-full bg-[var(--surface-800)] px-1.5 py-0.5 text-[10px] text-[var(--success)]">
          {media.mime_type ?? "—"}
        </span>
      </div>
      {/* Real byte preview via the contained endpoint (no mock data). */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={roleMediaContentUrl(media)}
        alt={`${purposeLabel} hiện tại`}
        loading="lazy"
        data-testid={`media-${media.purpose}`}
        className="mt-2 aspect-square w-full rounded-md border border-[var(--surface-800)] bg-black/30 object-contain"
      />
      <p className="mt-1 text-[10px] text-[var(--text-muted)]">
        {media.width && media.height ? `${media.width}×${media.height}` : "Chưa rõ kích thước"} ·{" "}
        {formatBytes(media.size_bytes)}
        {regenerated ? (
          <span
            data-testid="media-regenerated"
            className="ml-1 rounded-full bg-[var(--accent-300)]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[var(--accent-300)]"
          >
            đã tính lại sau chỉnh sửa
          </span>
        ) : null}
      </p>
      <p className="truncate font-mono text-[10px] text-[var(--text-faint)]" title={media.sha256}>
        SHA-256 {shortId(media.sha256, 12)}… · nguồn {media.source_job_id.slice(0, 8)}
      </p>
    </div>
  );
}

/** Confidence bar with the policy review-threshold line (null until policy loads). */
export function ConfidenceBar({ value, threshold }: { value: number; threshold: number | null }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  const low = threshold !== null && value < threshold;
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--surface-800)]">
        <div
          className={`h-full rounded-full ${low ? "bg-[var(--warning)]" : "bg-[var(--success)]"}`}
          style={{ width: `${pct}%` }}
        />
        {threshold !== null && (
          <div
            className="absolute inset-y-0 w-px bg-[var(--text-faint)]"
            style={{ left: `${Math.round(threshold * 100)}%` }}
            title={`Ngưỡng duyệt ${formatConfidence(threshold)} (chính sách gộp)`}
          />
        )}
      </div>
      <span className={`w-10 shrink-0 text-right font-mono text-[11px] ${low ? "text-[var(--warning)]" : "text-[var(--success)]"}`}>
        {pct}%
      </span>
    </div>
  );
}

/** Small status live-region helper for non-urgent updates (a11y baseline). */
export function StatusRegion({ children }: { children: ReactNode }) {
  return (
    <p role="status" aria-live="polite" className="sr-only">
      {children}
    </p>
  );
}
