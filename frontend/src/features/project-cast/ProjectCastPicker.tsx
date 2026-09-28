"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState, useCallback } from "react";
import { api, ApiError, type PickerPackItem, type CompatibilityEvaluateResponse, type ProjectCastData } from "@/lib/api";
import { LibraryPicker } from "./LibraryPicker";
import { CompatibilityWarnings } from "./CompatibilityWarnings";
import { CastRecommendationPanel } from "@/features/reference-library";

interface ProjectCastPickerProps {
  projectId: string;
  objectRoleId: string;
  /** Controlled mapping id + revision for stale handling */
  mappingId?: string | null;
  currentRevision?: number | null;
  onSuccess?: (mapping: ProjectCastData) => void;
}

export function ProjectCastPicker({ projectId, objectRoleId, mappingId, currentRevision, onSuccess }: ProjectCastPickerProps) {
  const [selected, setSelected] = useState<PickerPackItem | null>(null);
  const [compat, setCompat] = useState<CompatibilityEvaluateResponse | null>(null);
  const [compatLoading, setCompatLoading] = useState(false);
  const [compatError, setCompatError] = useState<string | null>(null);
  const [submitPhase, setSubmitPhase] = useState<"idle" | "submitting" | "error" | "success">("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [staleInfo, setStaleInfo] = useState<{ current: number | null; pinned: string | null } | null>(null);
  const [pinnedVersionId, setPinnedVersionId] = useState<string | null>(null);
  const [pinnedRevision, setPinnedRevision] = useState<number | null>(currentRevision ?? null);
  const [pinnedMappingId, setPinnedMappingId] = useState<string | null>(null);
  const [pinnedLoading, setPinnedLoading] = useState(false);

  const fetchPinned = useCallback(async () => {
    setPinnedLoading(true);
    try {
      const res = await api.listProjectCastMappings(projectId, 50, 0);
      const found = res.mappings.find((m) => m.object_role_id === objectRoleId);
      if (found) {
        setPinnedVersionId(found.pack_version_id);
        setPinnedRevision(found.revision);
        setPinnedMappingId(found.id);
      } else {
        setPinnedVersionId(null);
        setPinnedRevision(null);
        setPinnedMappingId(null);
      }
    } catch {
      // ignore, stay null
    } finally {
      setPinnedLoading(false);
    }
  }, [projectId, objectRoleId]);

  useEffect(() => {
    void fetchPinned();
  }, [fetchPinned]);

  useEffect(() => {
    if (currentRevision !== undefined && currentRevision !== null) setPinnedRevision(currentRevision);
  }, [currentRevision]);

  const effectiveMappingId = mappingId ?? pinnedMappingId ?? null;
  const effectiveRevision = pinnedRevision ?? currentRevision ?? null;

  const evaluate = useCallback(
    async (pack: PickerPackItem) => {
      setCompatLoading(true);
      setCompatError(null);
      try {
        const r = await api.evaluateCastCompatibility({
          project_id: projectId,
          object_role_id: objectRoleId,
          pack_version_id: pack.id,
          expected_revision: effectiveRevision,
          mapping_id: effectiveMappingId,
        });
        setCompat(r);
        if (r.pinned_version_id) setPinnedVersionId(r.pinned_version_id);
        if (r.current_revision !== null && r.current_revision !== undefined) setPinnedRevision(r.current_revision);
        // stale revision handling from compat
        if (r.reasons.includes("stale_revision")) {
          setStaleInfo({ current: r.current_revision, pinned: r.pinned_version_id });
        } else {
          setStaleInfo(null);
        }
      } catch (err) {
        setCompatError(err instanceof ApiError ? err.detailText() || err.message : String(err));
      } finally {
        setCompatLoading(false);
      }
    },
    [projectId, objectRoleId, effectiveRevision, effectiveMappingId],
  );

  const handleSelect = (pack: PickerPackItem) => {
    setSelected(pack);
    setSubmitPhase("idle");
    setSubmitError(null);
    evaluate(pack);
  };

  const handleSubmit = async () => {
    if (!selected) return;
    // P1-A: fail-closed but fallback_supported (fallback_allowed=true, blocked=false) is allowed
    if (compat && !compat.compatible && !compat.fallback_allowed) {
      setSubmitPhase("error");
      setSubmitError("Không thể ghim — pack không tương thích (chính sách máy chủ, fail-closed).");
      return;
    }
    setSubmitPhase("submitting");
    setSubmitError(null);
    try {
      let result: ProjectCastData;
      if (effectiveMappingId) {
        // Update existing mapping (CAS)
        result = await api.updateProjectCastMapping(effectiveMappingId, {
          revision: effectiveRevision ?? 1,
          character_id: selected.character_id,
          pack_version_id: selected.id,
          fallback_acknowledged: !!compat?.fallback_allowed,
        });
      } else {
        result = await api.createProjectCastMapping({
          project_id: projectId,
          object_role_id: objectRoleId,
          character_id: selected.character_id,
          pack_version_id: selected.id,
          idempotency_key: `${projectId}:${objectRoleId}:${selected.id}`,
          fallback_acknowledged: !!compat?.fallback_allowed,
        });
      }
      setSubmitPhase("success");
      setPinnedVersionId(result.pack_version_id);
      setPinnedRevision(result.revision);
      setStaleInfo(null);
      onSuccess?.(result);
    } catch (err) {
      setSubmitPhase("error");
      if (err instanceof ApiError) {
        if (err.status === 409 && err.detailText().toLowerCase().includes("stale")) {
          setSubmitError(`Stale revision — phiên bản đã cũ. ${err.detailText()}`);
          setStaleInfo({ current: null, pinned: null });
          // Trigger re-evaluate to surface stale
          if (selected) evaluate(selected);
          // Also refetch pinned
          fetchPinned();
        } else if (err.status === 409) {
          setSubmitError(`Bị chặn (409): ${err.detailText()}`);
        } else {
          setSubmitError(err.detailText() || err.message);
        }
      } else {
        setSubmitError(String(err));
      }
    }
  };

  const canSubmit = !!selected && (compat?.compatible === true || compat?.fallback_allowed === true) && submitPhase !== "submitting";
  const showStaleRecovery = staleInfo || (compat?.reasons.includes("stale_revision") ?? false);

  return (
    <div className="flex flex-col gap-4" data-testid="project-cast-picker">
      {/* MF-END-10: gợi ý bộ từ kho + MỘT thao tác xác nhận (đọc-only cho tới khi xác nhận). */}
      <CastRecommendationPanel
        objectRoleId={objectRoleId}
        projectId={projectId}
        onConfirmed={() => {
          void fetchPinned();
        }}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <LibraryPicker pinnedVersionId={pinnedVersionId} selectedVersionId={selected?.id ?? null} onSelect={handleSelect} />

        <div className="flex flex-col gap-3">
          <CompatibilityWarnings result={compat} loading={compatLoading} error={compatError} onRetry={() => selected && evaluate(selected)} />

          {selected && (
            <div className="p-3 bg-gray-800 border border-gray-700 rounded" data-testid="selected-summary">
              <p className="text-sm text-gray-200">Đã chọn: {selected.character_name} — Version {selected.version}</p>
              <p className="text-[11px] text-gray-400 font-mono break-all">PackVersion ID: {selected.id}</p>
              <p className="text-[11px] text-gray-400">Character ID: {selected.character_id} — chỉ PackVersion ID mới được ghim (không chỉ character).</p>
            </div>
          )}

          {pinnedVersionId && (
            <div className="p-2 bg-amber-900/20 border border-amber-700 rounded" data-testid="pinned-summary">
              <p className="text-sm text-amber-200">Pinned hiện tại: {pinnedVersionId}</p>
              <p className="text-[11px] text-gray-400">Revision: {pinnedRevision ?? "?"} — cập nhật cần gửi đúng revision.</p>
            </div>
          )}
          {pinnedLoading && <p className="text-[11px] text-gray-400" data-testid="pinned-loading">Đang tải pinned...</p>}

          {showStaleRecovery && (
            <div className="flex flex-col gap-2 p-3 bg-orange-900/20 border border-orange-700 rounded" data-testid="stale-recovery">
              <p className="text-sm text-orange-300">Phiên bản đã cũ — mapping đã thay đổi.</p>
              <p className="text-[11px] text-gray-400">Tải lại pinned mới nhất và thử lại. Không gửi stale revision.</p>
              {staleInfo?.current !== null && staleInfo?.current !== undefined && <p className="text-[11px] text-gray-400">Current revision: {staleInfo.current}</p>}
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    fetchPinned();
                    if (selected) evaluate(selected);
                  }}
                  className="px-3 py-1.5 bg-orange-700 hover:bg-orange-600 text-white rounded text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                  data-testid="stale-reload"
                >
                  Tải lại
                </button>
                <span className="text-[11px] text-gray-400 self-center">Nhấn Tải lại để đồng bộ revision mới.</span>
              </div>
            </div>
          )}

          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            aria-disabled={!canSubmit}
            className={`px-4 py-2 rounded text-sm font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 ${canSubmit ? "bg-indigo-600 hover:bg-indigo-500 text-white" : "bg-gray-700 text-gray-400 cursor-not-allowed"}`}
            data-testid="cast-submit"
          >
            {compat?.fallback_allowed ? "Ghim bất chấp khác biệt" : effectiveMappingId ? "Cập nhật Ghim" : "Ghim Pack"}
          </button>
          <p className="text-[11px] text-gray-400">{compat?.fallback_allowed ? "Pack có cảnh báo nhưng fallback được phép — nhấn để ghim có chủ đích." : "Chỉ pack tương thích mới được ghim. Không tương thích → nút bị khóa (fail closed)."}</p>

          {submitPhase === "submitting" && <p className="text-sm text-gray-400" data-testid="submit-loading">Đang ghim...</p>}
          {submitPhase === "error" && (
            <div className="p-2 bg-red-900/20 border border-red-700 rounded" data-testid="submit-error">
              <p className="text-sm text-red-300">{submitError}</p>
              <p className="text-[11px] text-gray-400">Sửa lỗi và thử lại. Stale revision cần tải lại.</p>
              <button
                onClick={handleSubmit}
                className="mt-2 px-3 py-1.5 bg-red-700 hover:bg-red-600 text-white rounded text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
                data-testid="submit-retry"
              >
                Thử lại
              </button>
            </div>
          )}
          {submitPhase === "success" && (
            <div className="p-2 bg-emerald-900/20 border border-emerald-700 rounded" data-testid="submit-success">
              <p className="text-sm text-emerald-300">Đã ghim thành công.</p>
              <p className="text-[11px] text-gray-400">Mapping đã lưu với PackVersion ID chính xác.</p>
            </div>
          )}
        </div>
      </div>

      {/* Keyboard hint */}
      <p className="text-[11px] text-gray-400">Điều hướng bàn phím: Tab để chuyển focus, Enter/Space để chọn, Escape để đóng. Hỗ trợ desktop và 390px.</p>
    </div>
  );
}
