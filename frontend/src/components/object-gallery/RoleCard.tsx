"use client";

/**
 * Object Role card for the gallery (S08-T04).
 *
 * Displays REAL durable role data: name/kind/status, confidence summary
 * with the low-confidence threshold, confidence reasons + provenance,
 * scene coverage, the real bbox footprint, and the registered thumbnail /
 * mask artifact metadata (matched by candidate name from the completed
 * extraction job).  Every action requires explicit selection and is
 * confirmed in a dialog — low confidence is NEVER auto-confirmed.
 */

import {
  AlertTriangle,
  CheckCircle2,
  GitMerge,
  GitBranch,
  Layers,
  MoveHorizontal,
  PencilLine,
  Split,
  ImageOff,
  Trash2,
} from "lucide-react";
import type { ObjectRole, ObjectRoleKind, RoleMedia } from "@/lib/api";
import {
  BboxFootprint,
  ConfidenceBar,
  formatConfidence,
  isLowConfidence,
  isRemovalOnlyKind,
  kindLabel,
  MediaTile,
  reasonLabel,
  shortId,
  summarizeConfidence,
} from "./galleryUtils";

export const ROLE_STATUS_LABELS: Record<string, string> = {
  suggested: "Đề xuất",
  confirmed: "Đã xác nhận",
  superseded: "Đã thay thế",
};

export interface RoleCardProps {
  role: ObjectRole;
  /**
   * The NEWEST VALID media of the role (backend association-resolved) —
   * the stable role id is the ONLY identity authority; no name matching.
   */
  media: RoleMedia[];
  /** Backend grouping-policy review threshold (nullable until policy loads). */
  reviewThreshold: number | null;
  /** Backend-owned removal-only kinds (S08-A01) — ``source_overlay``.
   *  Roles of these kinds are shown removal-only and never offered as a
   *  replacement/Character Pack candidate. */
  removalOnlyKinds: ReadonlySet<ObjectRoleKind>;
  /** Merge selection state (manual curation). */
  isMergeSource: boolean;
  isMergeTarget: boolean;
  mergeDisabled: boolean;
  /** F2: true when this role is a different kind from the selected merge
   *  target — its "source" checkbox is disabled (kind-safe manual merge). */
  mergeSourceKindMismatch?: boolean;
  /** Split availability: original role ids merged into this target. */
  splitOriginals: string[];
  onToggleSource: (role: ObjectRole) => void;
  onSelectTarget: (role: ObjectRole) => void;
  onConfirm: (role: ObjectRole) => void;
  onSplit: (role: ObjectRole) => void;
  /** S08-T05: open the reassign-correction dialog for one occurrence. */
  onReassign?: (occurrenceId: string, role: ObjectRole) => void;
  /** S08-T05: open the candidate-edit correction dialog for this role. */
  onEdit?: (role: ObjectRole) => void;
  /** F4: dedicated "Sửa phân loại" (fix classification) action for a
   *  removal-only (source_overlay) role — reclassifies through the existing
   *  correction preview + confirm + CAS flow.  It is NOT a merge/confirm/
   *  reassign/replacement surface: the role is merely moved out of the
   *  removal-only kind when the user corrects a misclassification. */
  onReclassify?: (role: ObjectRole) => void;
  /** Disable correction actions while a correction is in flight. */
  correctionDisabled?: boolean;
  /** S07-T02: open cast picker for this role. */
  onCast?: (role: ObjectRole) => void;
}

export function RoleCard({
  role,
  media,
  reviewThreshold,
  removalOnlyKinds,
  isMergeSource,
  isMergeTarget,
  mergeDisabled,
  mergeSourceKindMismatch = false,
  splitOriginals,
  onToggleSource,
  onSelectTarget,
  onConfirm,
  onSplit,
  onReassign,
  onEdit,
  onReclassify,
  correctionDisabled = false,
  onCast,
}: RoleCardProps) {
  const summary = summarizeConfidence(role.occurrences);
  const low = reviewThreshold !== null && isLowConfidence(summary.min, reviewThreshold);
  const sceneIds = new Set(role.occurrences.map((o) => o.scene_id));
  const reasons = Array.from(
    new Set(role.occurrences.flatMap((o) => o.reasons)),
  ).slice(0, 4);
  const provenance = role.occurrences.find((o) => o.algorithm) ?? null;
  const superseded = role.status === "superseded";
  // S08-A01: backend-owned removal-only role (source_overlay) — shown as
  // removal-only and NEVER offered as a replacement/Character Pack candidate.
  const removalOnly = isRemovalOnlyKind(role.kind, removalOnlyKinds);

  const statusBadge =
    role.status === "confirmed" ? (
      <span className="inline-flex items-center gap-1 rounded-full bg-[var(--success-strong)]/20 px-2.5 py-1 text-xs font-medium text-[var(--success)]">
        <CheckCircle2 aria-hidden="true" size={12} />
        {ROLE_STATUS_LABELS.confirmed}
      </span>
    ) : role.status === "superseded" ? (
      <span className="rounded-full bg-[var(--surface-800)] px-2.5 py-1 text-xs font-medium text-[var(--text-faint)]">
        {ROLE_STATUS_LABELS.superseded}
      </span>
    ) : (
      <span className="rounded-full bg-[var(--surface-800)] px-2.5 py-1 text-xs font-medium text-[var(--accent-300)]">
        {ROLE_STATUS_LABELS.suggested}
      </span>
    );

  return (
    <article
      data-testid="role-detail"
      aria-label={`Vai trò ${role.name}`}
      className={`rounded-xl border bg-[var(--surface-900)] p-4 ${
        isMergeTarget
          ? "border-[var(--primary-500)] ring-1 ring-[var(--primary-500)]"
          : isMergeSource
            ? "border-[var(--accent-500)] ring-1 ring-[var(--accent-500)]"
            : "border-[var(--surface-800)]"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h3 className="truncate font-display text-base font-semibold text-[var(--text-primary)]">
            {role.name}
          </h3>
          <span className="rounded-full bg-[var(--surface-800)] px-2 py-0.5 text-[11px] text-[var(--text-muted)]">
            {kindLabel(role.kind)}
          </span>
          {removalOnly && (
            <span
              data-testid="removal-only-badge"
              className="inline-flex items-center gap-1 rounded-full bg-[var(--danger)]/15 px-2.5 py-1 text-[11px] font-semibold text-[var(--danger)]"
            >
              <Trash2 aria-hidden="true" size={12} />
              Chỉ loại bỏ (lớp nguồn)
            </span>
          )}
          {statusBadge}
          {low && !superseded && (
            <span className="inline-flex items-center gap-1 rounded-full bg-[var(--warning)]/15 px-2.5 py-1 text-xs font-medium text-[var(--warning)]">
              <AlertTriangle aria-hidden="true" size={12} />
              Độ tin cậy thấp
            </span>
          )}
        </div>
        <p className="font-mono text-[10px] text-[var(--text-faint)]">
          rev {role.revision} · {shortId(role.id)}
        </p>
      </div>

      <div className="mt-3 grid gap-4 md:grid-cols-2">
        {/* Left: confidence + evidence */}
        <div className="space-y-3">
          <div>
            <div className="mb-1 flex items-center justify-between text-[11px] text-[var(--text-muted)]">
              <span>Độ tin cậy trung bình</span>
              <span>
                {formatConfidence(summary.average)} · thấp nhất {formatConfidence(summary.min)}
              </span>
            </div>
            <ConfidenceBar value={summary.average} threshold={reviewThreshold} />
            {low && !superseded && (
              <p className="mt-1 text-[11px] text-[var(--warning)]">
                Dưới ngưỡng duyệt {formatConfidence(reviewThreshold)} (chính sách gộp từ máy chủ) —
                hệ thống chưa chắc các vùng này thuộc cùng một đối tượng. Vai trò này không bao
                giờ được tự động xác nhận.
              </p>
            )}
          </div>

          {reasons.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                Lý do tin cậy
              </p>
              <ul className="mt-1 space-y-0.5">
                {reasons.map((reason) => (
                  <li key={reason} className="text-xs text-[var(--text-secondary)]">
                    {reasonLabel(reason)}
                    <span className="ml-1 font-mono text-[10px] text-[var(--text-faint)]">
                      ({reason})
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {provenance && (
            <div className="rounded-lg bg-[var(--surface-850)] px-3 py-2 text-[11px] text-[var(--text-muted)]">
              Nguồn: {provenance.confidence_source} · thuật toán {provenance.algorithm} v
              {provenance.algorithm_version}
            </div>
          )}

          <div className="flex flex-wrap gap-2 text-[11px] text-[var(--text-secondary)]">
            <span className="inline-flex items-center gap-1 rounded-full bg-[var(--surface-850)] px-2 py-1">
              <Layers aria-hidden="true" size={12} className="text-[var(--info)]" />
              {role.occurrences.length} khung hình
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-[var(--surface-850)] px-2 py-1">
              <span aria-hidden="true" className="inline-block size-2 rounded-full bg-[var(--info)]" />
              {sceneIds.size} cảnh
            </span>
            {role.occurrences.length > 0 && (
              <span className="rounded-full bg-[var(--surface-850)] px-2 py-1">
                {role.occurrences[0].frame_index}–{role.occurrences[role.occurrences.length - 1].frame_index} khung
              </span>
            )}
          </div>
        </div>

        {/* Right: footprint + artifacts */}
        <div className="space-y-3">
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
              Phủ sóng cảnh (bằng chứng)
            </p>
            <BboxFootprint occurrences={role.occurrences} />
          </div>

          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
              Ảnh mẫu &amp; mặt nạ
            </p>
            {media.length > 0 ? (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {media.map((item) => (
                  <MediaTile key={item.association_id} media={item} />
                ))}
              </div>
            ) : (
              /* The role's media is association-managed (stable role id only) —
                 never a name-matched fallback. When the newest-valid set is
                 empty (evidence moved by a correction) we say so honestly;
                 older associations stay auditable on the backend. */
              <div
                className="flex items-center gap-2 rounded-lg border border-dashed border-[var(--surface-700)] bg-black/20 px-3 py-2 text-[11px] text-[var(--text-faint)]"
                data-testid="no-current-media"
              >
                <ImageOff aria-hidden="true" size={14} />
                {superseded
                  ? "Vai trò đã thay thế — ảnh mẫu thuộc vai trò đích."
                  : "Không có ảnh mẫu hiện tại cho vai trò này (bằng chứng đã được chuyển đi sau chỉnh sửa). Ảnh cũ vẫn được lưu để truy vết."}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* S08-T05: per-occurrence evidence with targeted reassignment.
          S08-A01: removal-only roles (source_overlay) are never a
          reassignment surface — they are not replaceable output. */}
      {!superseded && role.occurrences.length > 0 && (
        <div className="mt-4 rounded-lg bg-[var(--surface-850)] p-3">
          {!removalOnly && (
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
              Bằng chứng theo cảnh — chuyển sang vai trò khác nếu gán nhầm
            </p>
          )}
          <ul className="mt-2 space-y-1.5">
            {role.occurrences.map((occ) => (
              <li
                key={occ.id}
                className="flex flex-wrap items-center gap-2 rounded-md bg-black/20 px-2 py-1.5 text-[11px] text-[var(--text-muted)]"
              >
                <span className="font-mono text-[10px] text-[var(--text-faint)]">
                  cảnh {occ.scene_id.slice(0, 8)}
                </span>
                <span>khung {occ.frame_index}</span>
                <span>
                  khung vùng {occ.bbox.x},{occ.bbox.y} {occ.bbox.width}×{occ.bbox.height}
                </span>
                <span>độ tin cậy {Math.round(occ.confidence * 100)}%</span>
                {onReassign && !removalOnly && (
                  <button
                    type="button"
                    onClick={() => onReassign(occ.id, role)}
                    disabled={correctionDisabled}
                    className="ml-auto inline-flex min-h-7 items-center gap-1 rounded-md bg-[var(--surface-800)] px-2 text-[11px] font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <MoveHorizontal aria-hidden="true" size={12} />
                    Chuyển vai trò
                  </button>
                )}
              </li>
            ))}
          </ul>
          {!removalOnly ? (
            <p className="mt-1.5 text-[11px] leading-snug text-[var(--text-muted)]">
              “Chuyển vai trò” mở báo cáo phạm vi ảnh hưởng trước khi xác nhận; chỉ bằng chứng
              này và các phần dẫn xuất liên quan được tính lại.
            </p>
          ) : (
            <p className="mt-1.5 text-[11px] leading-snug text-[var(--text-danger)]">
              Lớp nguồn được đánh dấu chỉ để loại bỏ — không dùng làm đối tượng thay thế, không
              gộp/tách/xác nhận thành nhân vật hoặc gói thay thế.
            </p>
          )}
        </div>
      )}

      {/* S08-A01: removal-only explanatory strip — no curation surface. */}
      {!superseded && removalOnly && (
        <div
          data-testid="removal-only-note"
          className="mt-4 flex items-start gap-2 rounded-lg border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-[11px] leading-snug text-[var(--text-secondary)]"
        >
          <Trash2 aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-[var(--danger)]" />
          <div className="min-w-0 space-y-2">
            <p>
              Đây là lớp nguồn (watermark/logo) cần loại bỏ khi dựng lại: hệ thống không gộp,
              không đề xuất gộp, không xác nhận thành đối tượng thay thế, và không thay thế bằng
              gói tài nguyên (Character Pack).
            </p>
            {/* F4: dedicated fix-classification action — goes through the
                existing correction preview + confirm + CAS flow (candidate_edit
                with role_kind).  It is NOT a merge/confirm/reassign surface. */}
            {onReclassify && (
              <div className="flex flex-col items-start gap-1 pt-1">
                <button
                  type="button"
                  onClick={() => onReclassify(role)}
                  disabled={correctionDisabled}
                  data-testid="reclassify-source-overlay"
                  className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--surface-800)] px-3 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <PencilLine aria-hidden="true" size={14} />
                  Sửa phân loại (sai loại?)
                </button>
                <p className="text-[11px] text-[var(--text-muted)]">
                  Nếu hệ thống gán sai loại, sửa lại phân loại của lớp này qua luồng chỉnh sửa có
                  báo phạm vi ảnh hưởng và xác nhận (CAS) — lớp rời khỏi trạng thái “chỉ loại bỏ”.
                  Không dùng thao tác này để gộp/xác nhận/thay thế.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Actions — every button has an explicit Vietnamese helper line.
          S08-A01: removal-only roles expose NO curation actions. */}
      {!superseded && !removalOnly && (
        <div className="mt-4 flex flex-wrap items-start gap-x-5 gap-y-3 border-t border-[var(--surface-800)] pt-3">
          <label className="flex min-h-9 cursor-pointer items-center gap-2 text-xs text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={isMergeSource}
              disabled={mergeDisabled || mergeSourceKindMismatch}
              onChange={() => onToggleSource(role)}
              aria-disabled={mergeDisabled || mergeSourceKindMismatch}
              title={
                mergeSourceKindMismatch
                  ? "Chỉ gộp được vai trò cùng loại với vai trò đích (gộp an toàn theo loại)."
                  : undefined
              }
              className="size-4 accent-[var(--accent-500)] disabled:cursor-not-allowed"
            />
            Nguồn gộp
            {mergeSourceKindMismatch ? (
              <span className="text-[11px] text-[var(--text-faint)]">
                (khác loại với đích — chỉ gộp cùng loại)
              </span>
            ) : null}
          </label>
          <label className="flex min-h-9 cursor-pointer items-center gap-2 text-xs text-[var(--text-secondary)]">
            <input
              type="radio"
              name="merge-target"
              checked={isMergeTarget}
              disabled={mergeDisabled}
              onChange={() => onSelectTarget(role)}
              className="size-4 accent-[var(--primary-500)] disabled:cursor-not-allowed"
            />
            Vai trò đích
          </label>

          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={() => onConfirm(role)}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--success-strong)]/30 px-3 text-xs font-semibold text-[var(--success)] transition-colors hover:bg-[var(--success-strong)]/45"
            >
              <CheckCircle2 aria-hidden="true" size={14} />
              Xác nhận vai trò
            </button>
            <p className="text-[11px] leading-snug text-[var(--text-muted)]">
              Chuyển vai trò này thành dữ liệu chính thức (có lịch sử thao tác).
            </p>
          </div>

          {onEdit && (
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => onEdit(role)}
                disabled={correctionDisabled}
                className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--surface-800)] px-3 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <PencilLine aria-hidden="true" size={14} />
                Sửa tên/loại
              </button>
              <p className="text-[11px] leading-snug text-[var(--text-muted)]">
                Sửa tên hoặc loại đối tượng — báo phạm vi ảnh hưởng trước khi áp dụng.
              </p>
            </div>
          )}

          {splitOriginals.length > 0 && (
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => onSplit(role)}
                className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--surface-800)] px-3 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)]"
              >
                <Split aria-hidden="true" size={14} />
                Tách vai trò đã gộp
              </button>
              <p className="text-[11px] leading-snug text-[var(--text-muted)]">
                Tách lại {splitOriginals.length} vai trò gốc đã gộp vào vai trò này.
              </p>
            </div>
          )}
          {onCast && (
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => onCast(role)}
                data-testid="cast-pin-button"
                className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--primary-600)] px-3 text-xs font-semibold text-white transition-colors hover:bg-[var(--primary-700)] focus:outline-none focus:ring-2 focus:ring-[var(--primary-500)]"
              >
                Ghim nhân vật
              </button>
              <p className="text-[11px] leading-snug text-gray-400">
                Chọn pack để ghim cho vai trò này — chỉ pack đã xuất bản mới hiện.
              </p>
            </div>
          )}
        </div>
      )}

      {isMergeSource && (
        <p className="mt-2 text-[11px] text-[var(--accent-300)]">
          <GitMerge aria-hidden="true" className="mr-1 inline" size={12} />
          Đang chọn làm nguồn gộp — bằng chứng sẽ chuyển sang vai trò đích khi bạn xác nhận gộp.
        </p>
      )}
      {isMergeTarget && (
        <p className="mt-2 text-[11px] text-[var(--primary-300)]">
          <GitBranch aria-hidden="true" className="mr-1 inline" size={12} />
          Vai trò đích của thao tác gộp — giữ tên và bằng chứng sau khi gộp.
        </p>
      )}
    </article>
  );
}
