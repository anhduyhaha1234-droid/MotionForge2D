"use client";

/**
 * S11-T04D — Review item detail: canonical location + evidence + the T04A
 * navigation action + correction entry.
 *
 * - navigate (frame/object kinds) → REAL frontend deep link into the Object
 *   Gallery with the canonical anchors (?frame=&role=) — G13; the gallery
 *   opens exactly at the failing frame/role, never the full timeline.
 * - navigate (other kinds)    → the registered API target shown read-only
 *   (honest endpoint, no invented screen).
 * - explain (Decision E)      → stable code + Vietnamese reason VERBATIM,
 *   NO dead link.
 * - Correction entry only exists when the item carries the structured
 *   occurrence anchor (T04B V1 scope) — otherwise the out-of-scope note.
 * - A live recompute (RecomputeStateData) renders as a NON-blocking
 *   role="status" strip; navigation stays enabled the whole time.
 */

import { AlertTriangle, ArrowLeft, CheckCircle2, Loader2, MapPin } from "lucide-react";
import Link from "next/link";
import type { QcItemData, QcNavigationData } from "@/lib/api";
import { qcReasonLabel } from "./ReviewQueueList";
import { SeverityBadge } from "./ReviewQueueStates";

export interface CorrectionProgressInfo {
  status: string;
  progress: number | null;
  error: string | null;
}

export interface ReviewItemDetailProps {
  projectId: string;
  projectName: string;
  item: QcItemData;
  navigation: QcNavigationData | null;
  navLoading: boolean;
  navError: string | null;
  /** Non-blocking recompute outcome of the item's correction (if any). */
  correction: CorrectionProgressInfo | null;
  /** Structured occurrence anchor present → the V1 targeted correction exists. */
  canCorrect: boolean;
  onOpenCorrection: () => void;
  onRetryNav: () => void;
  onBack: () => void;
}

function LocationCell({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="min-w-0">
      <span className="block text-[11px] text-gray-400">{label}</span>
      <span className="block truncate font-mono text-xs text-zinc-200">
        {value ?? "—"}
      </span>
    </div>
  );
}

function NavSection({
  projectId,
  item,
  navigation,
  navLoading,
  navError,
  onRetryNav,
}: {
  projectId: string;
  item: QcItemData;
  navigation: QcNavigationData | null;
  navLoading: boolean;
  navError: string | null;
  onRetryNav: () => void;
}) {
  if (navLoading) {
    return (
      <div
        role="status"
        aria-busy="true"
        className="flex items-center gap-2 text-xs text-gray-400"
      >
        <Loader2 aria-hidden="true" size={13} className="animate-spin" />
        Đang xác định vị trí lỗi từ máy chủ…
      </div>
    );
  }
  if (navError) {
    return (
      <div role="alert" data-testid="nav-error" className="space-y-2 text-xs text-red-300">
        <p>Không xác định được vị trí lỗi: {navError}</p>
        <button
          type="button"
          onClick={onRetryNav}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-zinc-800 px-3 py-1.5 text-zinc-200 hover:bg-zinc-700"
        >
          Thử lại
        </button>
        <p className="text-[11px] text-gray-400">Xác định lại vị trí từ máy chủ.</p>
      </div>
    );
  }
  if (!navigation) return null;

  const loc = navigation.canonical_location;
  const video = item.video_item_id;

  if (navigation.action.kind === "explain") {
    return (
      <div data-testid="nav-explain" className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
        <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-300">
          <AlertTriangle aria-hidden="true" size={14} />
          Không thể mở vị trí cụ thể (ngoài phạm vi rerun V1)
        </p>
        <p className="text-xs leading-relaxed text-zinc-300">
          {navigation.action.reason ?? "Không có lý do từ máy chủ."}
        </p>
        {navigation.action.code && (
          <p className="font-mono text-[11px] text-gray-400">
            Mã: {navigation.action.code}
          </p>
        )}
      </div>
    );
  }

  // navigate — frame/object kinds get a REAL gallery deep link with the
  // canonical anchors; other kinds show the registered API target read-only.
  const kind = navigation.layer_ref_type;
  const roleId = loc.object_role_id ?? (typeof item.evidence?.object_role_id === "string" ? item.evidence.object_role_id : null);
  const frame = loc.frame_index;
  const href =
    kind === "frame" && frame !== null
      ? `/object-gallery?project=${encodeURIComponent(projectId)}&video=${encodeURIComponent(video)}&frame=${frame}${roleId ? `&role=${encodeURIComponent(roleId)}` : ""}`
      : kind === "object"
        ? `/object-gallery?project=${encodeURIComponent(projectId)}&video=${encodeURIComponent(video)}${roleId ? `&role=${encodeURIComponent(roleId)}` : ""}`
        : null;

  if (href) {
    return (
      <div className="space-y-2">
        <div className="flex flex-col items-start gap-1">
          <Link
            href={href}
            data-testid="nav-deeplink"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-500"
          >
            <MapPin aria-hidden="true" size={15} />
            Mở tại vị trí lỗi
          </Link>
          <p className="text-[11px] text-gray-400">
            Mở thẳng đúng vị trí trong Thư viện đối tượng — không qua timeline.
          </p>
        </div>
        {frame !== null && (
          <p data-testid="detail-frame-index" className="font-mono text-[11px] text-gray-400">
            frame {frame}
            {loc.scene_id !== null ? ` · scene ${loc.scene_id}` : ""}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
      <p className="text-xs font-semibold text-zinc-200">Đích API đã đăng ký (T04A)</p>
      <p className="break-all font-mono text-[11px] text-gray-400">
        {navigation.action.target ?? navigation.action.endpoint ?? "—"}
      </p>
      <p className="text-[11px] text-gray-400">
        Loại issue này không có màn hình chuyên biệt — xem trực tiếp tại endpoint API thật.
      </p>
    </div>
  );
}

export function ReviewItemDetail({
  projectId,
  projectName,
  item,
  navigation,
  navLoading,
  navError,
  correction,
  canCorrect,
  onOpenCorrection,
  onRetryNav,
  onBack,
}: ReviewItemDetailProps) {
  const loc = navigation?.canonical_location;
  const evidenceJson = JSON.stringify(item.evidence ?? {}, null, 2);
  const correctionActive =
    correction && ["pending", "queued", "running", "cancelling"].includes(correction.status);

  return (
    <div data-testid="qc-detail" className="mt-2 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800 pb-3">
        <div className="flex flex-col items-start gap-1">
          <button
            type="button"
            data-testid="detail-back"
            onClick={onBack}
            className="inline-flex min-h-10 items-center gap-1.5 text-xs text-gray-400 transition hover:text-zinc-200"
          >
            <ArrowLeft aria-hidden="true" size={14} />
            Về danh sách
          </button>
          <p className="text-[11px] text-gray-400">Quay lại hàng đợi QC của {projectName}.</p>
        </div>
        <div className="flex flex-col items-start gap-1">
          <div className="flex items-center gap-2">
            <SeverityBadge severity={item.severity} testid="detail-severity" />
            <span className="rounded bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-300">
              {item.status}
            </span>
          </div>
          <p className="text-[11px] text-gray-400">
            Trạng thái issue trên máy chủ (open/đã ghi nhận/đã xử lý).
          </p>
        </div>
      </div>

      <div>
        <h3 className="text-base font-semibold text-zinc-100">
          {qcReasonLabel(item.reason_code)}
        </h3>
        <p className="mt-0.5 text-xs text-gray-400">
          {item.detector} (rev {item.detector_revision}) · độ chắc{" "}
          {Math.round(item.confidence * 100)}% · {item.category}
        </p>
      </div>

      {/* Canonical location — STRUCTURED-only (T04A). */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
        <p className="mb-2 text-xs font-semibold text-zinc-200">
          Vị trí chuẩn (canonical location)
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <LocationCell label="Scene" value={loc?.scene_id !== null && loc?.scene_id !== undefined ? String(loc.scene_id) : null} />
          <LocationCell label="Frame" value={loc?.frame_index !== null && loc?.frame_index !== undefined ? String(loc.frame_index) : null} />
          <LocationCell label="Timecode (ms)" value={loc?.timecode_ms !== null && loc?.timecode_ms !== undefined ? String(loc.timecode_ms) : null} />
          <LocationCell label="Object role" value={loc?.object_role_id ?? null} />
          <LocationCell label="Segment row" value={loc?.segment_row_id ?? null} />
          <LocationCell label="Segment logical" value={loc?.segment_logical_id ?? null} />
        </div>
      </div>

      {/* Evidence payload (real backend bytes). */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
        <p className="mb-2 text-xs font-semibold text-zinc-200">Bằng chứng (evidence)</p>
        <pre
          data-testid="qc-evidence"
          className="max-h-48 overflow-auto rounded-lg bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-zinc-300"
        >
          {evidenceJson}
        </pre>
      </div>

      {/* Navigation action (T04A). */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
        <p className="mb-2 text-xs font-semibold text-zinc-200">Đi tới vị trí lỗi</p>
        <NavSection
          projectId={projectId}
          item={item}
          navigation={navigation}
          navLoading={navLoading}
          navError={navError}
          onRetryNav={onRetryNav}
        />
      </div>

      {/* Correction entry (two-phase, T04B scope) OR Decision-E note. */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
        <p className="mb-2 text-xs font-semibold text-zinc-200">Correction có chọn lọc</p>
        {canCorrect ? (
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              data-testid="correction-open"
              onClick={onOpenCorrection}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-500"
            >
              Tạo correction
            </button>
            <p className="text-[11px] text-gray-400">
              Xem trước phạm vi ảnh hưởng rồi xác nhận — chỉ sửa đúng vùng lỗi.
            </p>
          </div>
        ) : (
          <p data-testid="correction-out-of-scope" className="text-xs leading-relaxed text-zinc-300">
            Issue này không có correction targeted trong phạm vi rerun V1 (cần anchor
            occurrence có cấu trúc trong evidence). Không tự đoán — hãy chạy lại kiểm tra
            trên dữ liệu mới.
          </p>
        )}

        {correction && (
          <div
            data-testid="correction-progress"
            role="status"
            className={`mt-3 flex items-center gap-2 rounded-lg border p-3 text-xs ${
              correctionActive
                ? "border-indigo-500/30 bg-indigo-500/10 text-indigo-300"
                : correction.status === "failed" || correction.status === "cancelled"
                  ? "border-red-500/30 bg-red-500/10 text-red-300"
                  : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
            }`}
          >
            {correctionActive ? (
              <>
                <Loader2 aria-hidden="true" size={14} className="animate-spin" />
                Đang tính lại dữ liệu dẫn xuất:{" "}
                {Math.round((correction.progress ?? 0) * 100)}% — điều hướng vẫn mở.
              </>
            ) : correction.status === "failed" || correction.status === "cancelled" ? (
              <>
                <AlertTriangle aria-hidden="true" size={14} />
                Tính toán lại {correction.status}: {correction.error ?? ""}
              </>
            ) : (
              <>
                <CheckCircle2 aria-hidden="true" size={14} />
                Đã áp dụng thành công — dữ liệu dẫn xuất đã cập nhật.
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}