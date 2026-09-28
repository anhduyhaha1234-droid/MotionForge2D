"use client";

/**
 * MF-END-10 — Bảng gợi ý bộ cast cho MỘT vai trò của video.
 *
 * Hiển thị:
 *  - bộ đang ghim (pin thật đọc từ server, giữ nguyên sau khi reload);
 *  - gợi ý từ kho kèm LÝ DO (deterministic + AI khi có), xếp hạng rõ ràng;
 *  - series pin đã chốt (nếu có) — KHÔNG tự đổi khi kho cập nhật;
 *  - MỘT nút xác nhận duy nhất (thao tác ghi duy nhất của luồng).
 *
 * Endpoint: POST /api/v2/project-cast/recommendations (read-only)
 *           POST /api/v2/project-cast/recommendations/confirm (ghi có kiểm soát)
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, AlertTriangle, CheckCircle2, Loader2, Lock, Sparkles } from "lucide-react";
import { api, type ProjectCastData } from "@/lib/api";
import {
  confirmCast,
  getObjectRole,
  recommendCast,
  REFERENCE_VIEW_LABELS,
  type CastCandidate,
  type CastConfirmResult,
  type CastRecommendationResult,
  type RoleRecommendation,
} from "./referenceLibraryApi";
import {
  advisoryStatusLabel,
  httpErrorText,
  reasonLabel,
  selectionModeLabel,
} from "./reasonText";

interface CastRecommendationPanelProps {
  objectRoleId: string;
  /** Có sẵn từ nơi gọi; nếu thiếu sẽ tự resolve qua ObjectRole. */
  projectId?: string;
  videoItemId?: string;
  onConfirmed?: (mapping: CastConfirmResult["mapping"]) => void;
}

function candidateTitle(candidate: CastCandidate): string {
  return `${candidate.character_name} (${candidate.character_code}) · v${candidate.pack_version}`;
}

export function CastRecommendationPanel({
  objectRoleId,
  projectId,
  videoItemId,
  onConfirmed,
}: CastRecommendationPanelProps) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState<CastConfirmResult | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);

  const roleQuery = useQuery({
    queryKey: ["object-role", objectRoleId],
    queryFn: () => getObjectRole(objectRoleId),
    enabled: videoItemId == null,
  });

  const effectiveVideoItemId = videoItemId ?? roleQuery.data?.video_item_id ?? null;
  const effectiveProjectId = projectId ?? roleQuery.data?.project_id ?? null;

  const pinnedQuery = useQuery({
    queryKey: ["project-cast-mappings", effectiveProjectId, objectRoleId],
    queryFn: () => api.listProjectCastMappings(effectiveProjectId as string, 50, 0),
    enabled: effectiveProjectId != null,
    select: (data) => data.mappings.find((m) => m.object_role_id === objectRoleId) ?? null,
  });

  const planQuery = useQuery({
    queryKey: ["cast-recommendation", effectiveVideoItemId],
    queryFn: () => recommendCast({ video_item_id: effectiveVideoItemId as string }),
    enabled: effectiveVideoItemId != null,
  });

  const role: RoleRecommendation | null = useMemo(() => {
    const plan: CastRecommendationResult | undefined = planQuery.data;
    if (!plan) return null;
    const named = plan.roles.find((item) => item.object_role_id === objectRoleId);
    return named ?? (plan.roles.length === 1 ? plan.roles[0] : null);
  }, [planQuery.data, objectRoleId]);

  // Server đã chọn sẵn một ứng viên (series pin/metadata) → chọn trước cho
  // người dùng, nhưng KHÔNG tự xác nhận: xác nhận luôn là hành động có chủ đích.
  const effectiveSelectedId = selectedId ?? role?.selected_pack_version_id ?? null;

  const selected: CastCandidate | null = useMemo(() => {
    if (!role || effectiveSelectedId == null) return null;
    return role.candidates.find((c) => c.pack_version_id === effectiveSelectedId) ?? null;
  }, [role, effectiveSelectedId]);

  const pinned: ProjectCastData | null = pinnedQuery.data ?? null;

  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!role || !selected || effectiveVideoItemId == null) {
        throw new Error("Chưa có lựa chọn để xác nhận.");
      }
      const isSeries = selected.source === "series_snapshot";
      const trace = {
        role_key: role.role_key,
        selection_mode: (isSeries
          ? "series_pin"
          : role.selection_mode === "none" || role.selection_mode === "series_pin"
            ? "manual"
            : role.selection_mode) as "series_pin" | "advisory" | "metadata" | "manual",
        selected_pack_version_id: selected.pack_version_id,
        required_views: role.required_views,
        required_capabilities: role.required_capabilities,
        style_version: role.style_version,
        series_snapshot_id: isSeries
          ? (selected.snapshot_id ?? role.series_pin?.snapshot_id ?? null)
          : null,
        series_snapshot_index: isSeries
          ? (selected.snapshot_index ?? role.series_pin?.snapshot_index ?? null)
          : null,
        series_entries_sha256: isSeries ? (role.series_pin?.entries_sha256 ?? null) : null,
      };
      return confirmCast({
        video_item_id: effectiveVideoItemId,
        object_role_id: objectRoleId,
        character_id: selected.character_id,
        pack_version_id: selected.pack_version_id,
        idempotency_key: `${effectiveVideoItemId}:${objectRoleId}:${selected.pack_version_id}`,
        expected_revision:
          pinned != null && pinned.pack_version_id !== selected.pack_version_id
            ? pinned.revision
            : undefined,
        recommendation: trace,
      });
    },
    onSuccess: async (data) => {
      setErrorText(null);
      setResult(data);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["project-cast-mappings"] }),
        queryClient.invalidateQueries({ queryKey: ["cast-recommendation"] }),
      ]);
      onConfirmed?.(data.mapping);
    },
    onError: (error: unknown) => {
      const withStatus = error as { status?: number };
      setErrorText(
        typeof withStatus.status === "number"
          ? httpErrorText(withStatus.status, (error as Error).message)
          : String(error),
      );
    },
  });

  const loading = (videoItemId == null && roleQuery.isLoading) || planQuery.isLoading;

  return (
    <section
      className="flex flex-col gap-3 rounded-lg border border-[var(--surface-800)] bg-[var(--surface-900)] p-4"
      data-testid="cast-recommendation-panel"
      aria-label="Gợi ý bộ cast từ kho"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
          Gợi ý bộ từ kho
        </h3>
        <span className="flex items-center gap-1 text-[11px] text-[var(--text-muted)]">
          <Sparkles aria-hidden="true" size={12} />
          Chỉ đọc gợi ý — chỉ đổi bộ khi bạn xác nhận
        </span>
      </div>

      {/* Bộ đang ghim (đọc từ server — giữ nguyên khi tải lại trang) */}
      <div className="rounded border border-[var(--surface-700)] bg-[var(--surface-850)] p-3" data-testid="pinned-set">
        {pinnedQuery.isLoading ? (
          <p className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <Loader2 aria-hidden="true" size={14} className="animate-spin" />
            Đang kiểm tra bộ đang ghim…
          </p>
        ) : pinned ? (
          <>
            <p className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
              <Lock aria-hidden="true" size={13} className="text-[var(--warning)]" />
              Đang ghim: {pinned.pack_version_id}
            </p>
            <p className="mt-1 text-[11px] text-gray-400">
              Revision {pinned.revision} · nhân vật {pinned.character_id}. Bộ đã ghim không tự
              đổi khi kho cập nhật pack mới.
            </p>
          </>
        ) : (
          <>
            <p className="text-sm text-[var(--text-secondary)]">
              Vai trò này chưa được ghim bộ nào.
            </p>
            <p className="mt-1 text-[11px] text-gray-400">
              Chọn một gợi ý bên dưới rồi xác nhận để ghim bộ cho vai trò.
            </p>
          </>
        )}
      </div>

      {loading && (
        <p className="flex items-center gap-2 text-sm text-[var(--text-secondary)]" data-testid="recommend-loading">
          <Loader2 aria-hidden="true" size={14} className="animate-spin" />
          Đang tải gợi ý từ kho…
        </p>
      )}

      {planQuery.isError && (
        <div className="rounded border border-red-700 bg-red-900/20 p-3" data-testid="recommend-error">
          <p className="flex items-center gap-2 text-sm text-red-300">
            <AlertCircle aria-hidden="true" size={14} />
            Không tải được gợi ý bộ cast.
          </p>
          <button
            type="button"
            onClick={() => planQuery.refetch()}
            className="mt-2 min-h-9 rounded bg-gray-700 px-3 text-sm text-gray-100 hover:bg-gray-600"
            data-testid="recommend-retry"
          >
            Thử lại
          </button>
          <p className="mt-1 text-[11px] text-gray-400">
            Nhấn Thử lại để tải lại danh sách gợi ý (không thay đổi ghim hiện có).
          </p>
        </div>
      )}

      {role && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
            <span>Vai trò {role.role_key}</span>
            <span>·</span>
            <span>Lựa chọn hiện tại: {selectionModeLabel(role.selection_mode)}</span>
            <span>·</span>
            <span>AI: {advisoryStatusLabel(role.advisory.status)}</span>
          </div>

          {role.series_pin && (
            <div className="rounded border border-amber-700 bg-amber-900/20 p-3" data-testid="series-pin">
              <p className="text-sm text-amber-200">
                Bộ series đã chốt (snapshot #{role.series_pin.snapshot_index})
              </p>
              <p className="mt-1 break-all font-mono text-[10px] text-gray-400">
                {role.series_pin.snapshot_id} · {role.series_pin.entries_sha256.slice(0, 16)}…
              </p>
              <p className="mt-1 text-[11px] text-gray-400">
                {role.series_pin.live_ok
                  ? "Bộ này còn nguyên trong kho — video mới của series dùng lại đúng bộ/phong cách."
                  : "Bộ đã chốt không còn khớp kho hiện tại — cần chốt lại trước khi tạo thêm."}
              </p>
              {!role.series_pin.live_ok && role.series_pin.problems.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {role.series_pin.problems.map((problem, index) => (
                    <li key={index} className="text-[11px] text-amber-200">
                      {problem}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {role.candidates.length === 0 ? (
            <div className="rounded border border-dashed border-[var(--surface-700)] p-4 text-center" data-testid="recommend-empty">
              <p className="text-sm text-[var(--text-secondary)]">
                Kho chưa có bộ nào phù hợp cho vai trò này.
              </p>
              <p className="mt-1 text-[11px] text-gray-400">
                Hãy tạo/hoàn thiện pack trong Thư viện nhân vật rồi quay lại.
              </p>
            </div>
          ) : (
            <ul className="flex flex-col gap-2" data-testid="candidate-list">
              {role.candidates.map((candidate) => {
                const isSelected = selectedId === candidate.pack_version_id;
                const isPinned = pinned?.pack_version_id === candidate.pack_version_id;
                return (
                  <li key={candidate.pack_version_id}>
                    <button
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => {
                        setSelectedId(candidate.pack_version_id);
                        setResult(null);
                        setErrorText(null);
                      }}
                      className={`w-full rounded border p-3 text-left transition-colors ${
                        isSelected
                          ? "border-[var(--primary-400)] bg-[var(--surface-850)]"
                          : "border-[var(--surface-700)] bg-[var(--surface-850)]/60 hover:bg-[var(--surface-850)]"
                      }`}
                      data-testid={`candidate-${candidate.pack_version_id}`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-sm font-medium text-[var(--text-primary)]">
                          {candidateTitle(candidate)}
                        </span>
                        <span className="flex items-center gap-1">
                          {isPinned && (
                            <span className="rounded bg-amber-900/30 px-2 py-0.5 text-[11px] text-amber-300">
                              Đang ghim
                            </span>
                          )}
                          {candidate.source === "series_snapshot" && (
                            <span className="rounded bg-[var(--primary-700)]/25 px-2 py-0.5 text-[11px] text-[var(--primary-300)]">
                              Thuộc series
                            </span>
                          )}
                          <span className="rounded bg-[var(--surface-800)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)]">
                            Hạng {candidate.rank}
                          </span>
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-gray-400">
                        View có sẵn:{" "}
                        {candidate.available_views.length > 0
                          ? candidate.available_views
                              .map((view) => REFERENCE_VIEW_LABELS[view] ?? view)
                              .join(", ")
                          : "chưa có"}
                        {candidate.missing_views.length > 0 && (
                          <>
                            {" — thiếu: "}
                            {candidate.missing_views
                              .map((view) => REFERENCE_VIEW_LABELS[view] ?? view)
                              .join(", ")}
                          </>
                        )}
                      </p>
                      {candidate.reasons.length > 0 && (
                        <ul className="mt-1 list-disc pl-4">
                          {candidate.reasons.map((reason, index) => (
                            <li key={index} className="text-[11px] text-gray-400">
                              {reasonLabel(reason.code)}
                              {reason.detail ? ` — ${reason.detail}` : ""}
                            </li>
                          ))}
                        </ul>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {role.generation.required && (
            <div className="rounded border border-[var(--surface-700)] bg-[var(--surface-850)] p-3" data-testid="generation-plan">
              <p className="text-sm text-[var(--text-secondary)]">
                Cần tạo thêm {role.generation.views.length} view:{" "}
                {role.generation.views.map((view) => REFERENCE_VIEW_LABELS[view] ?? view).join(", ")}
              </p>
              <p className="mt-1 text-[11px] text-gray-400">
                {role.generation.note} · chi phí dự kiến {role.generation.estimated_cost_units}{" "}
                {role.generation.unit}
              </p>
            </div>
          )}

          <div className="flex flex-col gap-1">
            <button
              type="button"
              disabled={selected == null || confirmMutation.isPending}
              onClick={() => confirmMutation.mutate()}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-[var(--primary-600)] px-4 text-sm font-medium text-white hover:bg-[var(--primary-500)] disabled:cursor-not-allowed disabled:opacity-45"
              data-testid="cast-confirm"
            >
              {confirmMutation.isPending ? "Đang xác nhận…" : "Xác nhận ghim bộ đã chọn"}
            </button>
            <p className="text-[11px] text-gray-400">
              Một thao tác duy nhất: ghim đúng PackVersion của bộ đang chọn cho vai trò này. Đổi bộ
              về sau cần xác nhận lại.
            </p>
          </div>

          {confirmMutation.isPending && (
            <p className="text-sm text-gray-400" data-testid="confirm-pending">
              Đang ghim bộ… vui lòng chờ.
            </p>
          )}

          {errorText && (
            <p role="alert" className="flex items-start gap-2 text-sm text-[var(--danger)]" data-testid="confirm-error">
              <AlertCircle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
              {errorText}
            </p>
          )}

          {result && (
            <div className="rounded border border-emerald-700 bg-emerald-900/20 p-3" data-testid="confirm-success">
              <p className="flex items-center gap-2 text-sm text-emerald-300">
                <CheckCircle2 aria-hidden="true" size={14} />
                {result.replayed
                  ? "Bộ này đã được ghim trước đó — xác nhận lặp lại không tạo thêm bản ghi."
                  : "Đã ghim bộ cho vai trò."}
              </p>
              <p className="mt-1 text-[11px] text-gray-400">
                Nguồn kiểm chứng: {result.trace.verified_source === "series_pin" ? "bộ series đã chốt" : "ứng viên trong kho"}
                {" · "}PackVersion {result.mapping.pack_version_id}
              </p>
              {result.warnings.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {result.warnings.map((warning, index) => (
                    <li key={index} className="flex items-start gap-1.5 text-[11px] text-amber-200">
                      <AlertTriangle aria-hidden="true" size={12} className="mt-0.5 shrink-0" />
                      <span>{warning.detail}{warning.action ? ` — ${warning.action}` : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
              {result.missing_views.length > 0 && (
                <p className="mt-2 text-[11px] text-gray-400">
                  Thiếu view:{" "}
                  {result.missing_views.map((view) => REFERENCE_VIEW_LABELS[view] ?? view).join(", ")}
                  {" — tạo ở bảng view tham chiếu của pack rồi render."}
                </p>
              )}
            </div>
          )}
        </>
      )}

      <p className="text-[11px] text-gray-400">
        Gợi ý không làm thay đổi ghim hiện tại. Chỉ nút “Xác nhận ghim bộ đã chọn” mới ghi vào bộ
        đang dùng của video.
      </p>
    </section>
  );
}
