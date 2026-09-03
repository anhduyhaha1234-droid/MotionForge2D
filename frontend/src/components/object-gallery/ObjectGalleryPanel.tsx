"use client";

/**
 * Object Gallery panel (S08-T04 + correction round C1, finding E).
 *
 * A SLIM orchestrator over the bounded hooks/components in ./useGallery.ts,
 * ./VideoSelector.tsx and ./RoleSummaryCard.tsx:
 *
 *   - The backend is the ONLY authority: current extraction via
 *     GET /extraction/current (source-generation filtered — no
 *     sessionStorage), role media via durable object_role_artifact
 *     associations (stable role ids, never names), review thresholds via
 *     GET /grouping/policy (never hardcoded 0.65/0.5).
 *   - Roles are paginated (infinite load); heavy occurrence detail is
 *     fetched lazily on expand (GET /roles/{id}).
 *   - Explicit project video selector for multi-video projects.
 *   - All UX states preserved: loading, empty, error+retry, extraction
 *     progress, partial media, low confidence (policy threshold, never
 *     auto-confirmed), stale conflict (409 → banner + refetch), success
 *     feedback, correction recompute tracking, 390px no-overflow.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Boxes,
  ClipboardList,
  FolderOpen,
  GitMerge,
  Loader2,
  RefreshCw,
  ScanSearch,
  Sparkles,
  X,
} from "lucide-react";
import {
  api,
  type CorrectionRequestPayload,
  type ExtractionJob,
  type GroupingSuggestion,
  type ObjectRole,
  type ObjectRoleKind,
} from "@/lib/api";
import { ConfirmDialog } from "./ConfirmDialog";
import { ProjectCastPicker } from "@/features/project-cast";
import { CorrectionScope, RecomputeStrip } from "./CorrectionScope";
import { RoleCard } from "./RoleCard";
import { RoleSummaryCard } from "./RoleSummaryCard";
import { SuggestionCard } from "./SuggestionCard";
import { VideoSelector } from "./VideoSelector";
import {
  ROLE_PAGE_SIZE,
  useCorrectionPreview,
  useGalleryChain,
  useGalleryCorrections,
  useGalleryExtraction,
  useGalleryGrouping,
  useGalleryKinds,
  useGalleryPolicy,
  useGalleryRolesPaged,
  useGalleryVideos,
  useRoleDetail,
  useStableRoleNames,
} from "./useGallery";
import {
  formatConfidence,
  kindLabel,
  shortId,
  StatusRegion,
} from "./galleryUtils";

const JOB_STATUS_LABELS: Record<string, string> = {
  queued: "Đang chờ",
  running: "Đang phát hiện",
  cancelling: "Đang hủy",
  cancelled: "Đã hủy",
  completed: "Hoàn tất",
  failed: "Thất bại",
  pending: "Đang chờ",
};

const OPERATION_TYPE_LABELS: Record<string, string> = {
  merge: "Gộp",
  split: "Tách",
  confirm: "Xác nhận",
};

type MergeDraft =
  | { kind: "suggestion"; suggestion: GroupingSuggestion }
  | { kind: "manual"; targetRoleId: string; sourceRoleIds: string[] };

export interface ObjectGalleryPanelProps {
  projectId: string | null;
  /** Explicitly selected video (multi-video projects); null = chain default. */
  videoParam: string | null;
  onVideoChange: (videoItemId: string) => void;
}

export function ObjectGalleryPanel({ projectId, videoParam, onVideoChange }: ObjectGalleryPanelProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  // ── Backend policy (thresholds/semantics — never hardcoded) ────────────
  const policyQuery = useGalleryPolicy();
  const reviewThreshold = policyQuery.data?.review_threshold ?? null;
  const calibrationVersion = policyQuery.data?.calibration_version ?? "1";
  const policySemantics = policyQuery.data?.confidence_semantics ?? [];

  // ── Canonical seven-kind taxonomy (S08-A01) ────────────────────────────
  const kindsQuery = useGalleryKinds();
  const canonicalKindData = useMemo(
    () => kindsQuery.data?.kinds ?? [],
    [kindsQuery.data],
  );
  // Backend-owned removal-only kinds (source_overlay).  Before the kinds
  // endpoint resolves we fall back to the canonical single member
  // (source_overlay) — the display policy mirrors the backend authority.
  const removalOnlyKinds = useMemo(() => {
    if (kindsQuery.data) {
      return new Set<ObjectRoleKind>(
        canonicalKindData.filter((k) => k.removal_only).map((k) => k.name),
      );
    }
    return new Set<ObjectRoleKind>(["source_overlay"]);
  }, [kindsQuery.data, canonicalKindData]);
  const [kindFilter, setKindFilter] = useState<ObjectRoleKind | "all">("all");

  // Chain + videos (project context) ────────────────────────────────────
  const chainHook = useGalleryChain(projectId);
  const { chain, chainCompleted, generation, sourceSha256 } = chainHook;
  const videosQuery = useGalleryVideos(projectId);
  const videos = useMemo(() => videosQuery.data?.videos ?? [], [videosQuery.data]);
  const chainVideoId = chainHook.videoItemId;
  // The selector always shows an explicit per-video surface: the durable v2
  // items when available, plus the chain's CURRENT video as a fallback entry
  // (legacy projects own exactly the analyzed video).
  const selectorVideos = useMemo(() => {
    let list = videos;
    const hasCurrent = list.some((v) => v.video_item_id === chainVideoId);
    if (chainVideoId && !hasCurrent) {
      list = [
        ...list,
        {
          video_item_id: chainVideoId,
          project_id: projectId ?? "",
          workspace_id: "default",
          title: "Video hiện tại (đã phân tích)",
          position: list.length,
          status: "active",
          source_artifact_id: null,
          duration_ms: null,
          width: null,
          height: null,
          fps_num: null,
          fps_den: null,
          archived_at: null,
          created_at: "",
          updated_at: "",
          revision: 1,
        },
      ];
    }
    return list;
  }, [videos, chainVideoId, projectId]);
  // Selected video: the explicit `?video=` stable id wins whenever present
  // (the selector + URL drive per-video review; legacy projects can enumerate
  // only their current chain video, so old video ids arrive via explicit
  // selection — the backend resolves them, or the gallery shows the honest
  // empty state). The chain's current video is the default otherwise.
  const videoItemId = videoParam ? videoParam : chainVideoId;
  const generationForVideo =
    videoParam && videoParam !== chainVideoId ? undefined : generation;

  // ── Banners ─────────────────────────────────────────────────────────────
  const [conflict, setConflict] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const onNotice = useCallback((message: string) => setNotice(message), []);
  const onConflict = useCallback((message: string) => setConflict(message), []);

  // ── Extraction (backend truth; no sessionStorage) ───────────────────────
  const refreshLists = useCallback(
    (vid: string) => {
      void queryClient.invalidateQueries({ queryKey: ["object-roles", vid] });
      void queryClient.invalidateQueries({ queryKey: ["grouping-suggestions", vid] });
      void queryClient.invalidateQueries({ queryKey: ["grouping-operations", vid] });
    },
    [queryClient],
  );
  const extraction = useGalleryExtraction(
    projectId,
    videoItemId,
    generationForVideo ?? "1",
    sourceSha256,
    refreshLists,
  );

  // ── Roles (paginated summaries + lazy detail) ───────────────────────────
  // C2: all cache slices key on videoItemId + generation (finding C2 #5); the
  // gallery consumes the backend-authoritative CURRENT generation.  The
  // S08-A01 seven-kind filter is applied CLIENT-SIDE over the loaded pages
  // (grouping/merge surfaces keep the full active-role list unfiltered).
  const roles = useGalleryRolesPaged(videoItemId, generationForVideo ?? "1");
  const [expandedRoleId, setExpandedRoleId] = useState<string | null>(null);
    const detailQuery = useRoleDetail(expandedRoleId, generationForVideo ?? "1");
    const expandedRole = detailQuery.data ?? null;

    // ── S11-T04D additive: review-queue deep link (?frame=&role=) ──────────
        // When the review page navigates here with canonical anchors, expand the
        // exact role (and load more pages only if the anchor isn't on page 1).
        // Purely additive — no other gallery behavior changes.  window access is
        // confined to useEffect (client-only — safe during SSR/prerender).
        const deepLinkRef = useRef<{ frame: string | null; role: string | null } | null>(null);
            const deepLinkExpandedRef = useRef(false);
            const deepLinkLoadMoreRef = useRef(false);
            const {
              loading: rolesLoading,
              allRoles: rolesAll,
              hasMore: rolesHasMore,
              loadingMore: rolesLoadingMore,
              loadMore: rolesLoadMore,
            } = roles;
            useEffect(() => {
              if (deepLinkRef.current === null) {
                const params = new URLSearchParams(window.location.search);
                deepLinkRef.current = { frame: params.get("frame"), role: params.get("role") };
              }
              const target = deepLinkRef.current;
              if (!target || !target.role || rolesLoading) return;
              const found = rolesAll.find((r) => r.id === target.role);
              if (found && !deepLinkExpandedRef.current) {
                deepLinkExpandedRef.current = true;
                setExpandedRoleId(target.role);
                requestAnimationFrame(() => {
                  document
                    .querySelector('[data-testid="role-detail"]')
                    ?.scrollIntoView({ behavior: "smooth", block: "center" });
                });
              } else if (!found && rolesHasMore && !rolesLoadingMore && !deepLinkLoadMoreRef.current) {
                deepLinkLoadMoreRef.current = true;
                void rolesLoadMore();
              }
            }, [rolesLoading, rolesAll, rolesHasMore, rolesLoadingMore, rolesLoadMore]);
  const allRoles = roles.allRoles;
  const roleNames = useStableRoleNames(allRoles);
  const activeRoles = useMemo(
    () => allRoles.filter((r) => r.status !== "superseded"),
    [allRoles],
  );
  const supersededRoles = useMemo(
    () => allRoles.filter((r) => r.status === "superseded"),
    [allRoles],
  );
  // S08-A01: client-side seven-kind filter for the role card list only
  // (grouping/merge surfaces keep the full active-role list).
  const visibleActiveRoles = useMemo(
    () =>
      kindFilter === "all"
        ? activeRoles
        : activeRoles.filter((r) => r.kind === kindFilter),
    [activeRoles, kindFilter],
  );

  // ── Grouping ────────────────────────────────────────────────────────────
  const grouping = useGalleryGrouping(videoItemId, generationForVideo ?? "1", onNotice, onConflict);
  const {
    suggestionsQuery,
    operations,
    generateMutation,
    dismissMutation,
    confirmMutation,
    splitOriginalsByRole,
    refreshAll,
  } = grouping;
  const allRolesForGrouping = allRoles;

  // C2: the gallery VERIFIES the backend-authoritative CURRENT generation from
  // the roles/suggestions responses (T01-C2/T03-C2); it drives the header and
  // every mutation payload (generation is passed/asserted server-side too).
  const authoritativeGeneration =
    roles.currentGeneration ?? grouping.currentGeneration ?? generationForVideo ?? "1";

  // C2 (finding #6): when the video/source-generation changes, INVALIDATE the
  // previous cache slices so no stale generation/data breadcrumb survives.
  const cacheKey = `${videoItemId ?? "__vid__"}@${generationForVideo ?? "__gen__"}`;
  const lastCacheKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (lastCacheKeyRef.current !== null && lastCacheKeyRef.current !== cacheKey) {
      const [, prevVid, prevGen] = lastCacheKeyRef.current.split("@");
      if (prevVid && prevGen) {
        void queryClient.removeQueries({ queryKey: ["object-roles", prevVid, prevGen] });
        void queryClient.removeQueries({ queryKey: ["grouping-suggestions", prevVid, prevGen] });
        void queryClient.removeQueries({ queryKey: ["grouping-operations", prevVid, prevGen] });
        // Role details are per (roleId, generation) — a full prefixed sweep is
        // the simplest honest invalidation on a source/video switch.
        void queryClient.removeQueries({ queryKey: ["object-role-detail"] });
      }
    }
    lastCacheKeyRef.current = cacheKey;
  }, [cacheKey, queryClient]);

  // ── Merge selection (stable role ids; F2 kind-safe) ────────────────────
  const [mergeTargetId, setMergeTargetId] = useState<string | null>(null);
  const [mergeSourceIds, setMergeSourceIds] = useState<string[]>([]);
  // F2: only roles whose kind equals the current target's kind may be merge
  // sources.  Changing the target clears incompatible source selections.
  const mergeTargetKind = useMemo(() => {
    if (!mergeTargetId) return null;
    return allRolesForGrouping.find((r) => r.id === mergeTargetId)?.kind ?? null;
  }, [mergeTargetId, allRolesForGrouping]);
  const toggleSource = useCallback(
    (role: ObjectRole) => {
      // A source must share the current target's kind (manual merge is
      // kind-homogeneous — F2).  Selecting an incompatible role is ignored.
      if (mergeTargetKind !== null && role.kind !== mergeTargetKind) return;
      setMergeSourceIds((prev) => {
        if (prev.includes(role.id)) return prev.filter((id) => id !== role.id);
        if (mergeTargetId === role.id) setMergeTargetId(null);
        return [...prev, role.id];
      });
    },
    [mergeTargetKind, mergeTargetId],
  );
  const selectTarget = useCallback(
    (role: ObjectRole) => {
      setMergeTargetId(role.id);
      // Changing the target clears any incompatible source selections (F2):
      // only roles whose kind equals the NEW target's kind may stay selected.
      setMergeSourceIds((prev) =>
        prev.filter((id) => {
          if (id === role.id) return false;
          const source = allRolesForGrouping.find((r) => r.id === id);
          return source !== undefined && source.kind === role.kind;
        }),
      );
    },
    // stable: allRolesForGrouping is the full active-role list (id->kind)
    [allRolesForGrouping],
  );
  const clearSelection = useCallback(() => {
    setMergeTargetId(null);
    setMergeSourceIds([]);
  }, []);

  // ── Dialog states ───────────────────────────────────────────────────────
  const [confirmRole, setConfirmRole] = useState<ObjectRole | null>(null);
  const [mergeDraft, setMergeDraft] = useState<MergeDraft | null>(null);
  const [dismissSuggestion, setDismissSuggestion] = useState<GroupingSuggestion | null>(null);
  const [splitRole, setSplitRole] = useState<ObjectRole | null>(null);
  const [splitOriginalId, setSplitOriginalId] = useState<string | null>(null);
  const [reassignDraft, setReassignDraft] = useState<{
    occurrenceId: string;
    sourceRole: ObjectRole;
  } | null>(null);
  const [reassignTargetId, setReassignTargetId] = useState<string | null>(null);
  const [editRole, setEditRole] = useState<ObjectRole | null>(null);
  const [editName, setEditName] = useState("");
  const [editKind, setEditKind] = useState("character");

  // ── Correction payload builders (shared by preview + confirm) ───────────
  const mergePayload = useCallback(
    (draft: MergeDraft): CorrectionRequestPayload | null => {
      if (!projectId || !videoItemId) return null;
      const rolesById = new Map(allRolesForGrouping.map((r) => [r.id, r]));
      if (draft.kind === "suggestion") {
        const targetId = mergeTargetId ?? draft.suggestion.target_role_id ?? draft.suggestion.role_ids[0];
        const sources = draft.suggestion.role_ids.filter((id) => id !== targetId);
        const target = rolesById.get(targetId);
        if (!target || sources.length === 0) return null;
        return {
          kind: "merge",
          project_id: projectId,
          video_item_id: videoItemId,
          generation: authoritativeGeneration,
          target_role_id: targetId,
          target_revision: target.revision,
          source_role_ids: sources,
          suggestion_id: draft.suggestion.id,
        };
      }
      const target = rolesById.get(draft.targetRoleId);
      if (!target || draft.sourceRoleIds.length === 0) return null;
      return {
        kind: "merge",
        project_id: projectId,
        video_item_id: videoItemId,
        generation: authoritativeGeneration,
        target_role_id: draft.targetRoleId,
        target_revision: target.revision,
        source_role_ids: draft.sourceRoleIds,
      };
    },
    [allRolesForGrouping, mergeTargetId, projectId, videoItemId, authoritativeGeneration],
  );

  const splitPayload = useCallback(
    (role: ObjectRole, originalRoleId: string | null): CorrectionRequestPayload | null => {
      if (!projectId || !videoItemId || !originalRoleId) return null;
      return {
        kind: "split",
        project_id: projectId,
        video_item_id: videoItemId,
        generation: authoritativeGeneration,
        target_role_id: role.id,
        target_revision: role.revision,
        original_role_id: originalRoleId,
      };
    },
    [projectId, videoItemId, authoritativeGeneration],
  );

  const reassignPayload = useCallback((): CorrectionRequestPayload | null => {
    if (!projectId || !videoItemId || !reassignDraft || !reassignTargetId) return null;
    const occurrence = reassignDraft.sourceRole.occurrences.find(
      (o) => o.id === reassignDraft.occurrenceId,
    );
    if (!occurrence) return null;
    return {
      kind: "reassign",
      project_id: projectId,
      video_item_id: videoItemId,
      generation: authoritativeGeneration,
      occurrence_id: occurrence.id,
      occurrence_revision: occurrence.revision,
      source_role_id: reassignDraft.sourceRole.id,
      target_role_id: reassignTargetId,
    };
  }, [projectId, videoItemId, authoritativeGeneration, reassignDraft, reassignTargetId]);

  const editPayload = useCallback((): CorrectionRequestPayload | null => {
    if (!projectId || !videoItemId || !editRole) return null;
    const nameChanged = editName.trim() !== "" && editName.trim() !== editRole.name;
    const kindChanged = editKind !== editRole.kind;
    if (!nameChanged && !kindChanged) return null;
    return {
      kind: "candidate_edit",
      project_id: projectId,
      video_item_id: videoItemId,
      generation: authoritativeGeneration,
      target: "role",
      role_id: editRole.id,
      role_revision: editRole.revision,
      ...(nameChanged ? { name: editName.trim() } : {}),
      ...(kindChanged ? { role_kind: editKind } : {}),
    };
  }, [projectId, videoItemId, authoritativeGeneration, editRole, editName, editKind]);

  const mergePreview = useCorrectionPreview(mergeDraft ? mergePayload(mergeDraft) : null);
  const splitPreview = useCorrectionPreview(splitRole ? splitPayload(splitRole, splitOriginalId) : null);
  const reassignPreview = useCorrectionPreview(reassignDraft ? reassignPayload() : null);
  const editPreview = useCorrectionPreview(editRole ? editPayload() : null);

  // ── Corrections (apply + retry + recompute poll) ────────────────────────
  const corrections = useGalleryCorrections(videoItemId, authoritativeGeneration, refreshAll, onNotice, onConflict);

  const mergeSuccessNotice = useCallback(
    (draft: MergeDraft): string => {
      const targetId =
        draft.kind === "suggestion"
          ? (mergeTargetId ?? draft.suggestion.target_role_id ?? draft.suggestion.role_ids[0])
          : draft.targetRoleId;
      const sources =
        draft.kind === "suggestion"
          ? draft.suggestion.role_ids.filter((id) => id !== targetId)
          : draft.sourceRoleIds;
      const targetName = roleNames.get(targetId) ?? "vai trò đích";
      return `Đã gộp ${sources.length} vai trò vào "${targetName}". Các vai trò nguồn chuyển thành đã thay thế.`;
    },
    [mergeTargetId, roleNames],
  );

  const confirmMutationForDialog = confirmMutation;
  void confirmMutationForDialog;

  // ── Render: project picker ──────────────────────────────────────────────
  if (projectId === null) {
    return <ProjectPicker onPick={(pid) => router.replace(`/object-gallery?project=${encodeURIComponent(pid)}`)} />;
  }

  // ── Chain gates ─────────────────────────────────────────────────────────
  if (chainHook.isLoading) {
    return (
      <div className="space-y-4" aria-busy="true">
        <h1 className="font-display text-2xl font-semibold text-[var(--text-primary)]">Thư viện đối tượng</h1>
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }
  if (chainHook.isError || !chain) {
    return (
      <ErrorPanel
        title="Không đọc được trạng thái phân tích"
        message="Không thể lấy thông tin dự án từ máy chủ."
        onRetry={() => void chainHook.refetch()}
      />
    );
  }
  if (!chainCompleted || !chainVideoId) {
    return (
      <div className="mx-auto w-full max-w-2xl space-y-4">
        <h1 className="font-display text-2xl font-semibold text-[var(--text-primary)]">Thư viện đối tượng</h1>
        <section
          aria-label="Cần phân tích trước"
          className="space-y-4 rounded-2xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-6 shadow-panel"
        >
          <div className="flex items-start gap-3">
            <AlertCircle aria-hidden="true" size={20} className="mt-0.5 shrink-0 text-[var(--warning)]" />
            <div className="space-y-1">
              <h2 className="font-display text-base font-semibold text-[var(--text-primary)]">
                Dự án chưa sẵn sàng để duyệt đối tượng
              </h2>
              <p className="text-sm text-[var(--text-secondary)]">
                Trạng thái phân tích hiện tại: <strong>{chain.chain_status}</strong> ({chain.progress}%).
                Cần hoàn tất bước Nhập &amp; Phân tích trước khi phát hiện và duyệt đối tượng.
              </p>
            </div>
          </div>
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={() => router.push(`/import-analyze?project=${encodeURIComponent(projectId)}`)}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[var(--primary-600)] px-4 text-sm font-semibold text-white transition-colors hover:bg-[var(--primary-700)]"
            >
              <ScanSearch aria-hidden="true" size={16} />
              Mở bước Nhập &amp; Phân tích
            </button>
            <p className="text-[11px] text-[var(--text-muted)]">
              Quay lại màn hình phân tích để theo dõi hoặc chạy lại chuỗi công việc.
            </p>
          </div>
        </section>
      </div>
    );
  }

  const extractionActive =
    extraction.phase === "polling" || extraction.phase === "submitting";
  const hasRoles = allRoles.length > 0;

  return (
    <div className="space-y-6">
      <StatusRegion>
        {notice ?? ""}
        {conflict ?? ""}
        {extraction.job
          ? `Công việc phát hiện đối tượng: ${JOB_STATUS_LABELS[extraction.job.status] ?? extraction.job.status}`
          : ""}
      </StatusRegion>

      {/* Header */}
      <div className="space-y-2">
        <h1 className="font-display text-2xl font-semibold text-[var(--text-primary)]">Thư viện đối tượng</h1>
        <p className="text-sm text-[var(--text-muted)]">
          Duyệt các đối tượng của video qua các cảnh, xem độ tin cậy và bằng chứng, rồi xác nhận
          hoặc gộp/tách chúng. Thế hệ nguồn hiện tại (máy chủ): <strong>{authoritativeGeneration}</strong>
          {chain.scenes_count != null ? ` · ${chain.scenes_count} cảnh đã phát hiện` : ""}
          {sourceSha256 ? ` · SHA-256 ${shortId(sourceSha256, 12)}…` : ""}
        </p>
        {policyQuery.data && (
          <p className="text-[11px] text-[var(--text-muted)]">
            Ngưỡng duyệt gộp: {formatConfidence(policyQuery.data.review_threshold)} · hiệu chuẩn{" "}
            {policyQuery.data.calibration_version} (chính sách từ máy chủ —{" "}
            {policyQuery.data.algorithm} v{policyQuery.data.algorithm_version}).
          </p>
        )}
      </div>

      {/* Video selector (multi-video projects) */}
      {videoItemId && (
        <VideoSelector
          videos={selectorVideos}
          currentVideoId={videoItemId}
          loading={videosQuery.isLoading}
          error={videosQuery.isError ? "Không tải được danh sách video." : null}
          onSelect={(vid) => onVideoChange(vid)}
        />
      )}

      {/* Conflict / notice banners */}
      {conflict && (
        <div
          role="alert"
          className="flex items-start justify-between gap-3 rounded-xl border border-[var(--danger)]/50 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]"
        >
          <p>{conflict}</p>
          <button
            type="button"
            onClick={() => setConflict(null)}
            aria-label="Đóng thông báo xung đột"
            className="flex min-h-8 min-w-8 items-center justify-center rounded-lg text-[var(--danger)] hover:bg-[var(--danger)]/15"
          >
            <X aria-hidden="true" size={15} />
          </button>
        </div>
      )}
      {notice && (
        <div
          role="status"
          className="flex items-start justify-between gap-3 rounded-xl border border-[var(--success-strong)]/50 bg-[var(--success-strong)]/10 px-4 py-3 text-sm text-[var(--success)]"
        >
          <p>{notice}</p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Đóng thông báo"
            className="flex min-h-8 min-w-8 items-center justify-center rounded-lg text-[var(--success)] hover:bg-[var(--success-strong)]/20"
          >
            <X aria-hidden="true" size={15} />
          </button>
        </div>
      )}

      {/* Correction recompute strip */}
      <RecomputeStrip
        correctionId={corrections.track?.correctionId ?? ""}
        recompute={corrections.track?.recompute ?? null}
        onRetry={() => {
          if (corrections.track) corrections.retryMutation.mutate(corrections.track.correctionId);
        }}
        busy={corrections.retryMutation.isPending}
      />

      {/* Extraction job strip (real progress) */}
      <ExtractionStrip
        job={extraction.job}
        phase={extraction.phase}
        error={extraction.error}
        onRetry={() => void extraction.submit()}
      />

      {/* Main gallery */}
      {roles.loading && !hasRoles ? (
        <div className="space-y-4" aria-busy="true">
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <Loader2 aria-hidden="true" size={15} className="animate-spin" />
            Đang tải các vai trò đối tượng…
          </div>
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : roles.error ? (
        <ErrorPanel
          title="Không tải được danh sách đối tượng"
          message={roles.error instanceof Error ? roles.error.message : "Lỗi không xác định từ máy chủ."}
          onRetry={roles.refetch}
        />
      ) : !hasRoles && !extractionActive ? (
        /* Empty state — no roles and no running extraction */
        <section
          aria-label="Chưa có đối tượng"
          className="space-y-4 rounded-2xl border border-dashed border-[var(--surface-700)] bg-[var(--surface-900)] p-6 text-center"
        >
          <Boxes aria-hidden="true" size={32} className="mx-auto text-[var(--text-faint)]" />
          <div className="space-y-1">
            <h2 className="font-display text-base font-semibold text-[var(--text-primary)]">
              Chưa có đối tượng nào
            </h2>
            <p className="mx-auto max-w-md text-sm text-[var(--text-muted)]">
              Hệ thống chưa phát hiện đối tượng nào cho video này. Bắt đầu một lần phát hiện:
              hệ thống sẽ tạo các vai trò đề xuất kèm ảnh mẫu, mặt nạ, độ tin cậy và bằng chứng
              tại từng cảnh. Mọi vai trò đều cần bạn xác nhận thủ công.
            </p>
          </div>
          <div className="flex flex-col items-center gap-1">
            <button
              type="button"
              onClick={() => void extraction.submit()}
              className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[var(--primary-600)] px-5 text-sm font-semibold text-white transition-colors hover:bg-[var(--primary-700)]"
            >
              <ScanSearch aria-hidden="true" size={16} />
              Phát hiện đối tượng
            </button>
            <p className="text-[11px] text-[var(--text-muted)]">
              Chạy phát hiện đối tượng trên toàn video (công việc nền, có thể đóng trang và quay lại).
            </p>
          </div>
        </section>
      ) : (
        <div className="space-y-6">
          {/* Toolbar */}
          <div className="flex flex-wrap items-start gap-3">
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => generateMutation.mutate()}
                disabled={generateMutation.isPending || !hasRoles}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[var(--surface-800)] px-4 text-sm font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Sparkles aria-hidden="true" size={15} className="text-[var(--accent-300)]" />
                {generateMutation.isPending ? "Đang tạo gợi ý…" : "Tạo gợi ý gộp"}
              </button>
              <p className="text-[11px] text-[var(--text-muted)]">
                So sánh các vai trò trên toàn video; kết quả luôn là gợi ý chờ bạn duyệt.
              </p>
            </div>
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={refreshAll}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[var(--surface-850)] px-4 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-800)]"
              >
                <RefreshCw aria-hidden="true" size={15} />
                Làm mới dữ liệu
              </button>
              <p className="text-[11px] text-[var(--text-muted)]">
                Tải lại vai trò, gợi ý và lịch sử thao tác từ máy chủ.
              </p>
            </div>
          </div>

          {/* Policy semantics (backend-authoritative) */}
          {policySemantics.length > 0 && (
            <details className="rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-4">
              <summary className="cursor-pointer text-sm font-medium text-[var(--text-secondary)]">
                Ý nghĩa các mức độ tin cậy (chính sách gộp từ máy chủ)
              </summary>
              <ul className="mt-2 list-inside list-disc space-y-1 text-xs text-[var(--text-muted)]">
                {policySemantics.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          )}

          {/* Merge action bar (explicit selection) */}
          {mergeTargetId && mergeSourceIds.length > 0 && (
            <div
              role="status"
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--primary-500)]/50 bg-[var(--primary-600)]/10 px-4 py-3"
            >
              <p className="text-sm text-[var(--text-primary)]">
                Đã chọn <strong>{mergeSourceIds.length}</strong> vai trò nguồn để gộp vào vai trò
                đích đã chọn.
              </p>
              <div className="flex flex-wrap items-start gap-3">
                <div className="flex flex-col items-start gap-1">
                  <button
                    type="button"
                    onClick={() => setMergeDraft({ kind: "manual", targetRoleId: mergeTargetId, sourceRoleIds: mergeSourceIds })}
                    className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--primary-600)] px-3 text-xs font-semibold text-white transition-colors hover:bg-[var(--primary-700)]"
                  >
                    <GitMerge aria-hidden="true" size={14} />
                    Gộp các vai trò đã chọn
                  </button>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    Mở hộp thoại xác nhận trước khi gộp.
                  </p>
                </div>
                <div className="flex flex-col items-start gap-1">
                  <button
                    type="button"
                    onClick={clearSelection}
                    className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--surface-800)] px-3 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)]"
                  >
                    <X aria-hidden="true" size={14} />
                    Hủy chọn
                  </button>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    Bỏ chọn toàn bộ vai trò nguồn và đích.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Suggestions */}
          {suggestionsQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]" aria-busy="true">
              <Loader2 aria-hidden="true" size={15} className="animate-spin" />
              Đang tải gợi ý gộp…
            </div>
          ) : suggestionsQuery.isError ? (
            <ErrorPanel
              title="Không tải được gợi ý gộp"
              message={suggestionsQuery.error instanceof Error ? suggestionsQuery.error.message : "Lỗi không xác định."}
              onRetry={() => void suggestionsQuery.refetch()}
            />
          ) : (suggestionsQuery.data?.suggestions.length ?? 0) > 0 ? (
            <section aria-label="Gợi ý gộp đang chờ duyệt" className="space-y-3">
              <h2 className="font-display text-sm font-semibold text-[var(--text-secondary)]">
                Gợi ý gộp đang chờ duyệt ({suggestionsQuery.data?.suggestions.length ?? 0})
              </h2>
              {(suggestionsQuery.data?.suggestions ?? []).map((suggestion) => (
                <SuggestionCard
                  key={suggestion.id}
                  suggestion={suggestion}
                  roles={allRolesForGrouping}
                  reviewThreshold={reviewThreshold}
                  calibrationVersion={calibrationVersion}
                  onMerge={(s) => {
                    setMergeDraft({ kind: "suggestion", suggestion: s });
                    setMergeTargetId(s.target_role_id ?? s.role_ids[0]);
                  }}
                  onDismiss={(s) => setDismissSuggestion(s)}
                  busy={corrections.applyMutation.isPending || dismissMutation.isPending}
                />
              ))}
            </section>
          ) : null}

          {/* S08-A01: seven-kind filter bar (backend taxonomy). */}
          <section
            aria-label="Lọc theo loại đối tượng"
            className="space-y-2 rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-3"
          >
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
              Lọc theo loại đối tượng
            </p>
            <div className="flex flex-wrap items-center gap-1.5" data-testid="kind-filter-bar">
              <button
                type="button"
                onClick={() => setKindFilter("all")}
                aria-pressed={kindFilter === "all"}
                className={`min-h-7 rounded-full px-2.5 py-0.5 text-[11px] font-semibold transition-colors ${
                  kindFilter === "all"
                    ? "bg-[var(--primary-600)] text-white"
                    : "bg-[var(--surface-800)] text-[var(--text-secondary)] hover:bg-[var(--surface-700)]"
                }`}
              >
                Tất cả
              </button>
              {canonicalKindData.map((k) => {
                const active = kindFilter === k.name;
                return (
                  <button
                    key={k.name}
                    type="button"
                    onClick={() => setKindFilter(active ? "all" : k.name)}
                    aria-pressed={active}
                    data-kind={k.name}
                    data-removal-only={k.removal_only ? "true" : "false"}
                    className={`min-h-7 rounded-full px-2.5 py-0.5 text-[11px] font-semibold transition-colors ${
                      active
                        ? "bg-[var(--primary-600)] text-white"
                        : k.removal_only
                          ? "bg-[var(--danger)]/10 text-[var(--danger)] hover:bg-[var(--danger)]/20"
                          : "bg-[var(--surface-800)] text-[var(--text-secondary)] hover:bg-[var(--surface-700)]"
                    }`}
                  >
                    {kindLabel(k.name)}
                  </button>
                );
              })}
            </div>
            {kindsQuery.isLoading && (
              <p className="text-[11px] text-[var(--text-faint)]" aria-busy="true">
                Đang tải danh sách loại đối tượng từ máy chủ…
              </p>
            )}
            {kindsQuery.isError && (
              <p className="text-[11px] text-[var(--danger)]" role="alert">
                Không tải được danh sách loại đối tượng từ máy chủ — vẫn hiển thị tất cả vai trò.
              </p>
            )}
          </section>

          {/* Roles — paginated summaries + lazy detail on expand */}
          <section aria-label="Vai trò của video" className="space-y-3">
            <h2 className="font-display text-sm font-semibold text-[var(--text-secondary)]">
              Vai trò của video ({visibleActiveRoles.length}/{roles.total}
              {kindFilter !== "all" ? ` · lọc ${kindLabel(kindFilter)}` : ""})
            </h2>
            {visibleActiveRoles.length === 0 ? (
              <p className="rounded-xl border border-dashed border-[var(--surface-700)] px-4 py-3 text-sm text-[var(--text-muted)]">
                {kindFilter !== "all"
                  ? `Không có vai trò nào thuộc loại “${kindLabel(kindFilter)}” trong danh sách đã tải. Chọn “Tất cả” để xem toàn bộ.`
                  : "Không có vai trò đề xuất nào. Xác nhận hoặc gộp để tiến tới bước tiếp theo."}
              </p>
            ) : (
              <>
                {visibleActiveRoles.map((role) => {
                  const expanded = expandedRoleId === role.id;
                  return (
                    <div key={role.id} className="space-y-2">
                      <RoleSummaryCard
                        role={role}
                        reviewThreshold={reviewThreshold}
                        removalOnlyKinds={removalOnlyKinds}
                        expanded={expanded}
                        onExpand={(r) => setExpandedRoleId(expanded ? null : r.id)}
                      />
                      {expanded &&
                        (detailQuery.isLoading ? (
                          <SkeletonCard />
                        ) : detailQuery.isError ? (
                          <ErrorPanel
                            title="Không tải được chi tiết vai trò"
                            message={detailQuery.error instanceof Error ? detailQuery.error.message : "Lỗi không xác định."}
                            onRetry={() => void detailQuery.refetch()}
                          />
                        ) : expandedRole ? (
                          <>
                            <RoleCard
                            role={expandedRole}
                            media={expandedRole.media ?? []}
                            reviewThreshold={reviewThreshold}
                            removalOnlyKinds={removalOnlyKinds}
                            isMergeSource={mergeSourceIds.includes(expandedRole.id)}
                            isMergeTarget={mergeTargetId === expandedRole.id}
                            mergeDisabled={corrections.applyMutation.isPending}
                            mergeSourceKindMismatch={
                              mergeTargetId !== null &&
                              mergeTargetId !== expandedRole.id &&
                              mergeTargetKind !== null &&
                              expandedRole.kind !== mergeTargetKind
                            }
                            splitOriginals={splitOriginalsByRole.get(expandedRole.id) ?? []}
                            onToggleSource={toggleSource}
                            onSelectTarget={selectTarget}
                            onConfirm={setConfirmRole}
                            onSplit={(r) => {
                              setSplitRole(r);
                              setSplitOriginalId(splitOriginalsByRole.get(r.id)?.[0] ?? null);
                            }}
                            onReassign={(occurrenceId, r) => {
                              setReassignDraft({ occurrenceId, sourceRole: r });
                              setReassignTargetId(null);
                            }}
                            onEdit={(r) => {
                              setEditRole(r);
                              setEditName(r.name);
                              setEditKind(r.kind);
                            }}
                            onReclassify={(r) => {
                              // F4: dedicated fix-classification action —
                              // reuses the candidate-edit correction dialog
                              // (kind change via the existing preview+confirm
                              // + CAS flow).  Not a merge/confirm/reassign.
                              setEditRole(r);
                              setEditName(r.name);
                              setEditKind(r.kind);
                            }}
                            correctionDisabled={corrections.applyMutation.isPending}
                            onCast={() => {}}
                          />
                          {projectId && (
                            <div className="mt-4 rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-4">
                              <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Ghim nhân vật cho vai trò</h3>
                              <p className="mb-3 text-[11px] text-gray-400">
                                Chọn pack đã xuất bản để ghim cho vai trò này. Chỉ pack tương thích mới được ghim (fail-closed).
                              </p>
                              <ProjectCastPicker
                                key={expandedRole.id}
                                projectId={projectId}
                                objectRoleId={expandedRole.id}
                                onSuccess={() => {
                                  // Reload authoritative mapping after success
                                  void queryClient.invalidateQueries({ queryKey: ["object-roles", videoItemId] });
                                  setNotice(`Đã ghim pack cho vai trò "${expandedRole.name}"`);
                                }}
                              />
                            </div>
                          )}
                          </>
                        ) : null)}
                    </div>
                  );
                })}
                {roles.hasMore && (
                  <div className="flex flex-col items-start gap-1 pt-1">
                    <button
                      type="button"
                      onClick={() => void roles.loadMore()}
                      disabled={roles.loadingMore}
                      className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[var(--surface-800)] px-4 text-sm font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {roles.loadingMore ? (
                        <Loader2 aria-hidden="true" size={15} className="animate-spin" />
                      ) : (
                        <RefreshCw aria-hidden="true" size={15} />
                      )}
                      Tải thêm vai trò
                    </button>
                    <p className="text-[11px] text-[var(--text-muted)]">
                      Đã hiển thị {allRoles.length}/{roles.total} — tải tiếp theo từng trang
                      ({ROLE_PAGE_SIZE}/trang).
                    </p>
                  </div>
                )}
              </>
            )}
          </section>

          {/* Superseded (traceable) */}
          {supersededRoles.length > 0 && (
            <details className="rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-4">
              <summary className="cursor-pointer text-sm font-medium text-[var(--text-secondary)]">
                Vai trò đã thay thế ({supersededRoles.length}) — vẫn giữ để truy vết
              </summary>
              <ul className="mt-3 space-y-1.5">
                {supersededRoles.map((role) => (
                  <li key={role.id} className="flex flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
                    <span className="text-[var(--text-secondary)]">{role.name}</span>
                    <span className="font-mono text-[10px] text-[var(--text-faint)]">{shortId(role.id)}</span>
                    {role.supersedes_role_id && (
                      <span className="font-mono text-[10px] text-[var(--text-faint)]">
                        → gộp vào {shortId(role.supersedes_role_id)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {/* Operations audit */}
          {operations.length > 0 && (
            <section aria-label="Lịch sử thao tác" className="rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-4">
              <h2 className="inline-flex items-center gap-2 font-display text-sm font-semibold text-[var(--text-secondary)]">
                <ClipboardList aria-hidden="true" size={15} />
                Lịch sử thao tác ({operations.length})
              </h2>
              <ul className="mt-3 space-y-2">
                {operations.map((op) => (
                  <li key={op.id} className="flex flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
                    <span className="rounded-full bg-[var(--surface-800)] px-2 py-0.5 font-medium text-[var(--accent-300)]">
                      {OPERATION_TYPE_LABELS[op.operation_type] ?? op.operation_type}
                    </span>
                    <span className="text-[var(--text-secondary)]">
                      {op.operation_type === "merge"
                        ? `${op.source_role_ids.length} nguồn → đích ${shortId(op.target_role_id)}`
                        : op.operation_type === "split"
                          ? `tạo ${op.created_role_ids.length} vai trò từ ${shortId(op.target_role_id)}`
                          : `vai trò ${shortId(op.target_role_id)}`}
                    </span>
                    <span className="font-mono text-[10px] text-[var(--text-faint)]">
                      {new Date(op.created_at).toLocaleString("vi-VN")} · rev {op.revision_after}
                    </span>
                    {op.note && <span className="italic text-[var(--text-faint)]">“{op.note}”</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {/* ── Dialogs (all explicit confirmations) ──────────────────────────── */}

      <ConfirmDialog
        open={confirmRole !== null}
        title={confirmRole ? `Xác nhận vai trò "${confirmRole.name}"?` : ""}
        confirmLabel="Xác nhận vai trò"
        busy={confirmMutation.isPending}
        onConfirm={() => {
          if (confirmRole) confirmMutation.mutate(confirmRole);
          setConfirmRole(null);
        }}
        onClose={() => {
          if (!confirmMutation.isPending) setConfirmRole(null);
        }}
      >
        {confirmRole && (
          <div className="space-y-2">
            <p>
              Vai trò <strong>{confirmRole.name}</strong> sẽ chuyển sang trạng thái{" "}
              <strong>Đã xác nhận</strong> và trở thành dữ liệu chính thức (có lịch sử thao tác
              lưu vĩnh viễn).
            </p>
            {lowConfidenceFor(confirmRole, reviewThreshold) && (
              <p className="flex items-start gap-1.5 text-xs text-[var(--warning)]">
                <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
                Vai trò này có độ tin cậy dưới ngưỡng duyệt{" "}
                {formatConfidence(reviewThreshold ?? 0)} (chính sách gộp từ máy chủ).
                Hệ thống không bao giờ tự xác nhận — bạn đang xác nhận thủ công sau khi kiểm tra
                bằng chứng.
              </p>
            )}
          </div>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={mergeDraft !== null}
        title="Gộp các vai trò?"
        confirmLabel="Gộp vai trò"
        busy={corrections.applyMutation.isPending || mergePreview.loading}
        onConfirm={() => {
          if (mergeDraft) {
            const payload = mergePayload(mergeDraft);
            if (payload) {
              corrections.applyMutation.mutate({
                payload,
                successNotice: mergeSuccessNotice(mergeDraft),
              });
            }
          }
          setMergeDraft(null);
          clearSelection();
        }}
        onClose={() => {
          if (!corrections.applyMutation.isPending) setMergeDraft(null);
        }}
      >
        {mergeDraft && (
          <div className="space-y-3">
            <MergeDraftBody draft={mergeDraft} roles={allRolesForGrouping} reviewThreshold={reviewThreshold} />
            <CorrectionScope
              impact={mergePreview.impact}
              loading={mergePreview.loading}
              error={mergePreview.error}
              roleNames={roleNames}
            />
          </div>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={dismissSuggestion !== null}
        title="Từ chối gợi ý gộp?"
        confirmLabel="Từ chối gợi ý"
        danger
        busy={dismissMutation.isPending}
        onConfirm={() => {
          if (dismissSuggestion) dismissMutation.mutate(dismissSuggestion);
          setDismissSuggestion(null);
        }}
        onClose={() => {
          if (!dismissMutation.isPending) setDismissSuggestion(null);
        }}
      >
        <p>
          Gợi ý này sẽ chuyển thành <strong>đã từ chối</strong> và không còn hiển thị trong
          danh sách chờ duyệt. Các vai trò vẫn giữ nguyên, hoàn toàn riêng biệt.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={splitRole !== null}
        title={splitRole ? `Tách vai trò đã gộp "${splitRole.name}"?` : ""}
        confirmLabel="Tách vai trò"
        busy={corrections.applyMutation.isPending || splitPreview.loading}
        onConfirm={() => {
          if (splitRole && splitOriginalId) {
            const payload = splitPayload(splitRole, splitOriginalId);
            if (payload) {
              corrections.applyMutation.mutate({
                payload,
                successNotice: "Đã tách vai trò (bằng chứng được chuyển lại nguyên vẹn; phạm vi ảnh hưởng đã được tính lại).",
              });
            }
          }
          setSplitRole(null);
          setSplitOriginalId(null);
        }}
        onClose={() => {
          if (!corrections.applyMutation.isPending) {
            setSplitRole(null);
            setSplitOriginalId(null);
          }
        }}
      >
        {splitRole && (
          <div className="space-y-3">
            <SplitDialogBody
              role={splitRole}
              originals={splitOriginalsByRole.get(splitRole.id) ?? []}
              roles={allRolesForGrouping}
              selected={splitOriginalId}
              onSelect={setSplitOriginalId}
            />
            <CorrectionScope
              impact={splitPreview.impact}
              loading={splitPreview.loading}
              error={splitPreview.error}
              roleNames={roleNames}
            />
          </div>
        )}
      </ConfirmDialog>

      {/* S08-T05: reassign-correction dialog */}
      <ConfirmDialog
        open={reassignDraft !== null}
        title="Chuyển bằng chứng sang vai trò khác?"
        confirmLabel="Chuyển vai trò"
        busy={corrections.applyMutation.isPending || reassignPreview.loading}
        disabled={reassignTargetId === null}
        onConfirm={() => {
          if (reassignDraft && reassignTargetId) {
            const payload = reassignPayload();
            if (payload) {
              const targetName = roleNames.get(reassignTargetId) ?? "vai trò đích";
              corrections.applyMutation.mutate({
                payload,
                successNotice: `Đã chuyển 1 bằng chứng sang vai trò "${targetName}".`,
              });
            }
          }
          setReassignDraft(null);
          setReassignTargetId(null);
        }}
        onClose={() => {
          if (!corrections.applyMutation.isPending) {
            setReassignDraft(null);
            setReassignTargetId(null);
          }
        }}
      >
        {reassignDraft && (
          <div className="space-y-3">
            <p className="text-sm text-[var(--text-secondary)]">
              Bằng chứng (khung hình) của vai trò <strong>{reassignDraft.sourceRole.name}</strong>{" "}
              sẽ được gán cho một vai trò khác. Nội dung bằng chứng (khung vùng, độ tin cậy, lý do)
              giữ nguyên.
            </p>
            <div role="radiogroup" aria-label="Chọn vai trò đích" className="space-y-1.5">
              {activeRoles
                .filter((r) => r.id !== reassignDraft.sourceRole.id)
                .map((role) => (
                  <label
                    key={role.id}
                    className="flex min-h-9 cursor-pointer items-center gap-2 rounded-lg bg-[var(--surface-850)] px-3 text-xs text-[var(--text-secondary)]"
                  >
                    <input
                      type="radio"
                      name="reassign-target"
                      checked={reassignTargetId === role.id}
                      onChange={() => setReassignTargetId(role.id)}
                      className="size-4 accent-[var(--primary-500)]"
                    />
                    {role.name}
                    <span className="ml-auto font-mono text-[10px] text-[var(--text-faint)]">
                      {shortId(role.id)}
                    </span>
                  </label>
                ))}
            </div>
            <p className="text-[11px] text-[var(--text-muted)]">
              Chọn vai trò đích để xem phạm vi ảnh hưởng, sau đó bấm “Chuyển vai trò”.
            </p>
            <CorrectionScope
              impact={reassignPreview.impact}
              loading={reassignPreview.loading}
              error={reassignPreview.error}
              roleNames={roleNames}
            />
          </div>
        )}
      </ConfirmDialog>

      {/* S08-T05: candidate-edit correction dialog */}
      <ConfirmDialog
        open={editRole !== null}
        title={editRole ? `Sửa vai trò "${editRole.name}"?` : ""}
        confirmLabel="Lưu chỉnh sửa"
        busy={corrections.applyMutation.isPending || editPreview.loading}
        onConfirm={() => {
          if (editRole) {
            const payload = editPayload();
            if (payload) {
              corrections.applyMutation.mutate({
                payload,
                successNotice: `Đã cập nhật vai trò "${editName.trim() || editRole.name}" (phạm vi ảnh hưởng đã được tính lại).`,
              });
            }
          }
          setEditRole(null);
          setEditName("");
          setEditKind("character");
        }}
        onClose={() => {
          if (!corrections.applyMutation.isPending) {
            setEditRole(null);
            setEditName("");
            setEditKind("character");
          }
        }}
      >
        {editRole && (
          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                Tên vai trò
              </span>
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                maxLength={240}
                className="w-full rounded-lg border border-[var(--surface-700)] bg-black/30 px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--primary-500)]"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                Loại đối tượng
              </span>
              <select
                value={editKind}
                onChange={(e) => setEditKind(e.target.value as ObjectRoleKind)}
                className="w-full rounded-lg border border-[var(--surface-700)] bg-black/30 px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--primary-500)]"
              >
                {canonicalKindData.length === 0
                  ? // Kinds endpoint not loaded yet — keep the current value.
                    [
                      <option key={editRole.kind} value={editRole.kind}>
                        {kindLabel(editRole.kind)}
                      </option>,
                    ]
                  : canonicalKindData.map((k) => (
                      <option key={k.name} value={k.name}>
                        {kindLabel(k.name)}
                        {k.removal_only ? " — chỉ loại bỏ" : ""}
                      </option>
                    ))}
              </select>
            </label>
            {!editPayload() && (
              <p className="text-xs text-[var(--warning)]">Hãy thay đổi ít nhất tên hoặc loại trước khi lưu.</p>
            )}
            <CorrectionScope
              impact={editPreview.impact}
              loading={editPreview.loading}
              error={editPreview.error}
              roleNames={roleNames}
            />
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}

function lowConfidenceFor(role: ObjectRole, reviewThreshold: number | null): boolean {
  if (reviewThreshold === null) return false;
  if (role.occurrences.length === 0) return true;
  return Math.min(...role.occurrences.map((o) => o.confidence)) < reviewThreshold;
}

// ── Small presentational pieces ───────────────────────────────────────────

function ProjectPicker({ onPick }: { onPick: (projectId: string) => void }) {
  const projectsQuery = useQuery({
    queryKey: ["all-projects"],
    queryFn: () => api.listAllProjects(),
    enabled: true,
    retry: 1,
  });
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <div className="space-y-2">
        <h1 className="font-display text-2xl font-semibold text-[var(--text-primary)]">
          Thư viện đối tượng
        </h1>
        <p className="text-sm text-[var(--text-muted)]">
          Chọn một dự án đã phân tích để duyệt các đối tượng được phát hiện, xem độ tin cậy
          và xác nhận hoặc gộp/tách chúng.
        </p>
      </div>
      <section
        aria-label="Chọn dự án"
        className="rounded-2xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-5 shadow-panel"
      >
        <h2 className="font-display text-sm font-semibold text-[var(--text-secondary)]">
          Dự án có sẵn
        </h2>
        {projectsQuery.isLoading && (
          <div className="mt-3 space-y-2" aria-busy="true">
            <div className="h-14 animate-pulse rounded-lg bg-[var(--surface-800)]" />
            <div className="h-14 animate-pulse rounded-lg bg-[var(--surface-800)]" />
          </div>
        )}
        {projectsQuery.isError && (
          <ErrorPanel
            title="Không tải được danh sách dự án"
            message="Kiểm tra kết nối tới máy chủ rồi thử lại."
            onRetry={() => void projectsQuery.refetch()}
          />
        )}
        {projectsQuery.data && projectsQuery.data.length === 0 && (
          <p className="mt-3 text-sm text-[var(--text-muted)]">
            Chưa có dự án nào. Hãy tạo dự án và phân tích video trước.
          </p>
        )}
        <ul className="mt-3 space-y-2">
          {(projectsQuery.data ?? []).map((project) => (
            <li key={project.project_id}>
              <button
                type="button"
                onClick={() => onPick(project.project_id)}
                className="flex min-h-12 w-full items-center justify-between gap-3 rounded-lg border border-[var(--surface-700)] bg-[var(--surface-850)] px-4 text-left text-sm text-[var(--text-primary)] transition-colors hover:border-[var(--primary-500)]"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <FolderOpen aria-hidden="true" size={16} className="shrink-0 text-[var(--info)]" />
                  <span className="truncate">{project.name}</span>
                </span>
                <ArrowRight aria-hidden="true" size={16} className="shrink-0 text-[var(--text-muted)]" />
              </button>
              <p className="mt-0.5 px-1 text-[11px] text-[var(--text-muted)]">
                Mở thư viện đối tượng của dự án này.
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div
      aria-hidden="true"
      className="animate-pulse rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-4"
    >
      <div className="h-5 w-1/3 rounded bg-[var(--surface-800)]" />
      <div className="mt-3 h-2.5 w-full rounded bg-[var(--surface-800)]" />
      <div className="mt-2 h-2.5 w-2/3 rounded bg-[var(--surface-800)]" />
      <div className="mt-4 h-20 w-full rounded bg-[var(--surface-850)]" />
    </div>
  );
}

function ExtractionStrip({
  job,
  phase,
  error,
  onRetry,
}: {
  job: ExtractionJob | null;
  phase: string;
  error: string | null;
  onRetry: () => void;
}) {
  if (!job) return null;
  const active = phase === "polling" || phase === "submitting";
  return (
    <section
      aria-label="Công việc phát hiện đối tượng"
      className="rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="inline-flex items-center gap-2 font-display text-sm font-semibold text-[var(--text-primary)]">
          <ScanSearch aria-hidden="true" size={16} className="text-[var(--accent-300)]" />
          Phát hiện đối tượng
          <span className="rounded-full bg-[var(--surface-800)] px-2 py-0.5 text-[11px] font-medium text-[var(--accent-300)]">
            {JOB_STATUS_LABELS[job.status] ?? job.status}
          </span>
        </h2>
        <p className="font-mono text-[10px] text-[var(--text-faint)]">
          {shortId(job.job_id)} · {job.provider} · v{job.extractor_version} · thế hệ {job.generation}
        </p>
      </div>
      {active && (
        <div className="mt-3">
          <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--surface-800)]">
            <div
              className="h-full rounded-full bg-[var(--accent-400)] transition-all"
              style={{ width: `${Math.max(0, Math.min(100, Math.round(job.progress)))}%` }}
            />
          </div>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            {Math.round(job.progress)}% · {job.message || "Đang xử lý…"}
          </p>
        </div>
      )}
      {job.status === "completed" && job.candidates.length > 0 && (
        <div className="mt-3 grid gap-2 text-[11px] text-[var(--text-muted)] sm:grid-cols-3">
          <p>
            Ứng viên: <strong className="text-[var(--text-secondary)]">{job.candidates.length}</strong>
          </p>
          <p>
            Ảnh mẫu/mặt nạ:{" "}
            <strong className="text-[var(--text-secondary)]">
              {job.candidates.reduce((n, c) => n + c.artifacts.length, 0)}
            </strong>
          </p>
          <p>
            Nguồn: <strong className="text-[var(--text-secondary)]">{job.provider}</strong> · v
            {job.extractor_version}
          </p>
        </div>
      )}
      {phase === "error" && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p className="text-xs text-[var(--danger)]" role="alert">
            {error}
          </p>
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--surface-800)] px-3 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)]"
            >
              <RefreshCw aria-hidden="true" size={13} />
              Thử lại phát hiện
            </button>
            <p className="text-[11px] text-[var(--text-muted)]">
              Gửi lại công việc phát hiện; hệ thống không tạo bản sao trùng lặp.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}

function ErrorPanel({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <section
      aria-label={title}
      role="alert"
      className="space-y-3 rounded-2xl border border-[var(--danger)]/40 bg-[var(--surface-900)] p-5"
    >
      <div className="flex items-start gap-3">
        <AlertCircle aria-hidden="true" size={18} className="mt-0.5 shrink-0 text-[var(--danger)]" />
        <div className="space-y-1">
          <h2 className="font-display text-sm font-semibold text-[var(--text-primary)]">{title}</h2>
          <p className="text-xs text-[var(--text-secondary)]">{message}</p>
        </div>
      </div>
      <div className="flex flex-col items-start gap-1">
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--surface-800)] px-3 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)]"
        >
          <RefreshCw aria-hidden="true" size={13} />
          Thử lại
        </button>
        <p className="text-[11px] text-[var(--text-muted)]">
          Tải lại dữ liệu từ máy chủ; dữ liệu đã lưu không bị ảnh hưởng.
        </p>
      </div>
    </section>
  );
}

function MergeDraftBody({
  draft,
  roles,
  reviewThreshold,
}: {
  draft: MergeDraft;
  roles: ObjectRole[];
  reviewThreshold: number | null;
}) {
  const rolesById = new Map(roles.map((r) => [r.id, r]));
  const nameOf = (id: string) => rolesById.get(id)?.name ?? shortId(id);

  if (draft.kind === "suggestion") {
    const targetId = draft.suggestion.target_role_id ?? draft.suggestion.role_ids[0];
    const sources = draft.suggestion.role_ids.filter((id) => id !== targetId);
    return (
      <div className="space-y-2">
        <p>
          Gộp <strong>{sources.map(nameOf).join(", ")}</strong> vào vai trò đích{" "}
          <strong>{nameOf(targetId)}</strong>.
        </p>
        <p className="text-xs text-[var(--text-muted)]">
          Độ tin cậy gợi ý: {formatConfidence(draft.suggestion.confidence)}. Các vai trò nguồn
          chuyển thành <em>đã thay thế</em>; bằng chứng (khung hình, độ tin cậy, lý do) được
          chuyển nguyên vẹn sang vai trò đích. Thao tác được ghi vào lịch sử.
        </p>
        <p className="text-xs text-[var(--warning)]">
          <AlertTriangle aria-hidden="true" className="mr-1 inline" size={13} />
          {reviewThreshold !== null && draft.suggestion.confidence < reviewThreshold ? (
            "Đây là gợi ý dưới ngưỡng duyệt — chỉ gộp nếu bạn đã kiểm tra bằng chứng thực tế."
          ) : (
            "Hãy kiểm tra bằng chứng tại từng cảnh trước khi gộp."
          )}
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p>
        Gộp <strong>{draft.sourceRoleIds.map(nameOf).join(", ")}</strong> vào vai trò đích{" "}
        <strong>{nameOf(draft.targetRoleId)}</strong> (thao tác thủ công).
      </p>
      <p className="text-xs text-[var(--text-muted)]">
        Các vai trò nguồn chuyển thành <em>đã thay thế</em>; bằng chứng được chuyển nguyên vẹn.
        Thao tác được ghi vào lịch sử và có thể tách lại sau đó.
      </p>
    </div>
  );
}

function SplitDialogBody({
  role,
  originals,
  roles,
  selected,
  onSelect,
}: {
  role: ObjectRole;
  originals: string[];
  roles: ObjectRole[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const rolesById = new Map(roles.map((r) => [r.id, r]));
  const nameOf = (id: string) => rolesById.get(id)?.name ?? shortId(id);
  return (
    <div className="space-y-2">
      <p>
        Tách một vai trò gốc đã gộp vào <strong>{role.name}</strong> ra thành vai trò độc lập.
        Vai trò tách ra sẽ ở trạng thái <em>đề xuất</em> — cần xác nhận thủ công sau đó.
      </p>
      <div role="radiogroup" aria-label="Chọn vai trò gốc để tách" className="space-y-1.5">
        {originals.map((id) => (
          <label key={id} className="flex min-h-9 cursor-pointer items-center gap-2 rounded-lg bg-[var(--surface-850)] px-3 text-xs text-[var(--text-secondary)]">
            <input
              type="radio"
              name="split-original"
              checked={selected === id}
              onChange={() => onSelect(id)}
              className="size-4 accent-[var(--primary-500)]"
            />
            {nameOf(id)}
            <span className="ml-auto font-mono text-[10px] text-[var(--text-faint)]">{shortId(id)}</span>
          </label>
        ))}
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        Chọn vai trò gốc cần tách, sau đó bấm “Tách vai trò” để xác nhận.
      </p>
    </div>
  );
}

/** Export used by E2E. */
export { JOB_STATUS_LABELS };
