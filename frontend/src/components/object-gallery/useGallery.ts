"use client";

/**
 * Object Gallery — bounded hooks (S08-T04-C1, finding E #8: the 1,611-line
 * panel is split into focused hooks + components).
 *
 * All data comes from the REAL T01/T02/T03/T05 APIs. The backend is the only
 * authority: current extraction via GET /extraction/current (source-generation
 * filtered — browser storage is never required), roles media via the durable
 * object_role_artifact associations (stable role ids only, never names),
 * thresholds via GET /grouping/policy (never hardcoded UI constants).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type AnalyzeChainState,
  type CorrectionRequestPayload,
  type ExtractionJob,
  type GroupingSuggestion,
  type ObjectRole,
} from "@/lib/api";

const POLL_INTERVAL_MS = 1500;
const ACTIVE_JOB_STATES = new Set(["queued", "running", "cancelling", "pending"]);
const ACTIVE_RECOMPUTE_STATES = new Set(["queued", "running", "cancelling", "pending"]);
export const ROLE_PAGE_SIZE = 16;

// ─── Backend grouping policy (thresholds/semantics) ───────────────────────

export function useGalleryPolicy() {
  return useQuery({
    queryKey: ["grouping-policy"],
    queryFn: () => api.getGroupingPolicy(),
    staleTime: 5 * 60_000,
    retry: 1,
  });
}

// ─── Canonical ObjectRole taxonomy (S08-A01) ──────────────────────────────

/** The canonical seven-kind ObjectRole taxonomy + removal-only policy
 *  (backend-authoritative; the ONLY place the frontend derives kinds from). */
export function useGalleryKinds() {
  return useQuery({
    queryKey: ["object-role-kinds"],
    queryFn: () => api.getObjectRoleKinds(),
    staleTime: 5 * 60_000,
    retry: 1,
  });
}

// ─── Analyze chain (project → current video + generation) ─────────────────

export function useGalleryChain(projectId: string | null) {
  const query = useQuery({
    queryKey: ["analyze-chain", projectId],
    queryFn: () => api.getAnalyzeChain(projectId as string),
    enabled: projectId !== null,
    retry: 1,
  });
  const chain: AnalyzeChainState | undefined = query.data;
  const chainCompleted = chain?.chain_status === "completed";
  return {
    ...query,
    chain,
    chainCompleted,
    videoItemId: chainCompleted ? (chain.video_item_id ?? null) : null,
    generation: chain?.generation ?? "1",
    sourceSha256: chain?.source_sha256 ?? null,
  };
}

// ─── Project videos (multi-video selector) ────────────────────────────────

export function useGalleryVideos(projectId: string | null) {
  return useQuery({
    queryKey: ["project-videos", projectId],
    queryFn: async () => {
      try {
        return await api.listProjectVideos(projectId as string);
      } catch (err) {
        // Legacy projects are NOT durable v2 projects: the v2 videos endpoint
        // 404s — that is an EMPTY video list (single chain video), not an error.
        if (err instanceof ApiError && err.status === 404) {
          return { project_id: projectId ?? "", workspace_id: "default", active_only: true, videos: [] };
        }
        throw err;
      }
    },
    enabled: projectId !== null,
    retry: 1,
  });
}

// ─── Current extraction (backend truth; no sessionStorage) ────────────────

export interface ExtractionState {
  /** null while not found (no completed extraction for this generation). */
  job: ExtractionJob | null;
  loading: boolean;
  error: string | null;
  phase: "idle" | "submitting" | "polling" | "terminal" | "not-found" | "error";
}

export function useGalleryExtraction(
  projectId: string | null,
  videoItemId: string | null,
  generation: string,
  sourceSha256: string | null,
  onCompletedRefresh: (videoItemId: string) => void,
) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ExtractionState>({
    job: null,
    loading: false,
    error: null,
    phase: "idle",
  });
  const pollingTimer = useRef<number | null>(null);
  const completedRef = useRef(false);
  const [lastVideoKey, setLastVideoKey] = useState<string | null>(null);
  // Reset to the loading state when the video/generation changes — adjusted
  // during render (the sanctioned pattern; no setState-in-effect).
  if (videoItemId && lastVideoKey !== `${videoItemId}@${generation}`) {
    setLastVideoKey(`${videoItemId}@${generation}`);
    setState({ job: null, loading: true, error: null, phase: "idle" });
  }

  // Restore from the BACKEND (source-generation filtered): a fresh browser
  // with empty sessionStorage lands on the same truth.
  useEffect(() => {
    if (!videoItemId) return;
    let cancelled = false;
    completedRef.current = false;
    api
      .getCurrentExtraction(videoItemId, generation)
      .then((job) => {
        if (cancelled) return;
        setState({ job, loading: false, error: null, phase: "terminal" });
      })
      .catch((err) => {
        if (cancelled) return;
        const is404 = err instanceof ApiError && err.status === 404;
        setState({
          job: null,
          loading: false,
          error: is404 ? null : err instanceof Error ? err.message : "Lỗi khi đọc trạng thái phát hiện.",
          phase: is404 ? "not-found" : "error",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [videoItemId, generation]);

  // Poll an active job with REAL durable progress.
  useEffect(() => {
    if (state.phase !== "polling") return;
    const jobId = state.job?.job_id ?? "";
    if (!jobId) return;
    pollingTimer.current = window.setInterval(() => {
      api
        .getExtractionJob(jobId)
        .then((job) => {
          setState((prev) => {
            if (prev.phase !== "polling" || prev.job?.job_id !== jobId) return prev;
            if (job.status === "completed") {
              if (!completedRef.current && videoItemId) {
                completedRef.current = true;
                onCompletedRefresh(videoItemId);
              }
              return { job, loading: false, error: null, phase: "terminal" };
            }
            if (job.status === "failed" || job.status === "cancelled") {
              return {
                job,
                loading: false,
                error: job.error ?? `Công việc kết thúc với trạng thái ${job.status}`,
                phase: "error",
              };
            }
            return { ...prev, job };
          });
        })
        .catch(() => {
          /* transient read failure — keep polling */
        });
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollingTimer.current) window.clearInterval(pollingTimer.current);
    };
  }, [state.phase, state.job?.job_id, videoItemId, onCompletedRefresh]);

  const submit = useCallback(async () => {
    if (!projectId || !videoItemId) return;
    completedRef.current = false;
    setState({ job: null, loading: false, error: null, phase: "submitting" });
    try {
      const result = await api.submitObjectExtraction({
        projectId,
        videoItemId,
        generation,
        sourceSha256,
      });
      const job = await api.getExtractionJob(result.job_id);
      setState({ job, loading: false, error: null, phase: "polling" });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `Không thể bắt đầu phát hiện (${err.status}): ${err.detailText()}`
          : err instanceof Error
            ? err.message
            : "Không thể bắt đầu phát hiện.";
      setState({ job: null, loading: false, error: message, phase: "error" });
    }
  }, [projectId, videoItemId, generation, sourceSha256]);

  // Invalidate lists on completion (extraction finished) — the CURRENT
  // generation slice (finding C2 #5: keys embed videoItemId + generation).
  useEffect(() => {
    if (state.phase !== "terminal" || !videoItemId || !state.job) return;
    if (state.job.status !== "completed") return;
    if (completedRef.current) return;
    completedRef.current = true;
    onCompletedRefresh(videoItemId);
    void queryClient.invalidateQueries({ queryKey: ["object-roles", videoItemId, generation] });
    void queryClient.invalidateQueries({ queryKey: ["grouping-suggestions", videoItemId, generation] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase, state.job?.status, videoItemId, generation]);

  return { ...state, submit };
}

// ─── Paged role summaries + lazy detail ───────────────────────────────────

export function useGalleryRolesPaged(videoItemId: string | null, generation: string | null) {
  const queryClient = useQueryClient();
  const [pages, setPages] = useState<ObjectRole[][]>([]);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hydratedKey, setHydratedKey] = useState<string | null>(null);
  const [lastDataKey, setLastDataKey] = useState<string | null>(null);
  // Reset when the video OR generation changes — adjusted during render.
  // The React Query KEY embeds videoItemId + generation (finding C2 #5), so a
  // generation switch is a NEW cache slice; the old slice is invalidated below.
  const videoKey = `${videoItemId ?? "__none__"}@${generation ?? "__gen__"}`;
  if (hydratedKey !== null && hydratedKey !== videoKey) {
    setHydratedKey(videoKey);
    setLastDataKey(null);
    setPages([]);
    setTotal(0);
  }

  const reset = useCallback(() => {
    setPages([]);
    setTotal(0);
    setLastDataKey(null);
  }, []);

  // First page — the query key carries videoItemId + generation.
  const firstQuery = useQuery({
    queryKey: ["object-roles", videoItemId, generation, 0],
    queryFn: () =>
      api.listObjectRoles(videoItemId as string, { limit: ROLE_PAGE_SIZE, offset: 0 }),
    enabled: videoItemId !== null,
    retry: false,
    staleTime: 30_000,
  });

  // Hydrate whenever the FIRST-page payload actually changes (initial load,
  // post-extraction invalidation, manual refresh) — adjusted during render.
  // S08-T05-C2: the signature includes ROLE STATE (revision/status/occurrence
  // count/media source jobs), not just the id set — corrections keep the same
  // role ids but change their state, and the gallery must reflect it.
  const dataKey = firstQuery.data
    ? `${firstQuery.data.total}:${firstQuery.data.offset}:${firstQuery.data.roles
        .map(
          (r) =>
            `${r.id}:${r.revision}:${r.status}:${r.occurrences.length}:${
              (r.media ?? []).map((m) => m.source_job_id).join("|")
            }`,
        )
        .join(",")}`
    : null;
  if (firstQuery.data && dataKey !== null && lastDataKey !== dataKey && !firstQuery.isFetching) {
    setLastDataKey(dataKey);
    setPages([firstQuery.data.roles]);
    setTotal(firstQuery.data.total);
  }

  const loadMore = useCallback(async () => {
    if (!videoItemId) return;
    const offset = pages.reduce((n, p) => n + p.length, 0);
    if (offset >= total) return;
    setLoadingMore(true);
    try {
      const data = await api.listObjectRoles(videoItemId, {
        limit: ROLE_PAGE_SIZE,
        offset,
      });
      setPages((prev) => [...prev, data.roles]);
      setTotal(data.total);
    } finally {
      setLoadingMore(false);
    }
  }, [videoItemId, pages, total]);

  const refresh = useCallback(() => {
    reset();
    void queryClient.invalidateQueries({ queryKey: ["object-roles", videoItemId, generation] });
  }, [queryClient, reset, videoItemId, generation]);

  const allRoles = useMemo(() => pages.flat(), [pages]);
  const hasMore = allRoles.length < total;
  const roleNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const role of allRoles) map.set(role.id, role.name);
    return map;
  }, [allRoles]);

  return {
    loading: firstQuery.isLoading,
    error: firstQuery.error,
    refetch: () => void firstQuery.refetch(),
    pages,
    allRoles,
    total,
    hasMore,
    loadingMore,
    loadMore,
    refresh,
    roleNames,
    /** Backend-authoritative current source generation (T01-C2). */
    currentGeneration: firstQuery.data?.current_generation ?? null,
  };
}

/** Lazy authoritative detail of one role (fetch on expand).
 *  RQ key embeds videoItemId generation scope (finding C2 #5). */
export function useRoleDetail(roleId: string | null, generation: string | null) {
  return useQuery({
    queryKey: ["object-role-detail", roleId, generation],
    queryFn: () => api.getObjectRole(roleId as string),
    enabled: roleId !== null,
    retry: false,
  });
}

// ─── Grouping (suggestions + curation) ────────────────────────────────────

export function useGalleryGrouping(
  videoItemId: string | null,
  generation: string,
  onNotice: (message: string) => void,
  onConflict: (message: string) => void,
) {
  const queryClient = useQueryClient();

  const suggestionsQuery = useQuery({
    queryKey: ["grouping-suggestions", videoItemId, generation],
    queryFn: () => api.listGroupingSuggestions(videoItemId as string, "pending"),
    enabled: videoItemId !== null,
    retry: false,
  });
  const operationsQuery = useQuery({
    queryKey: ["grouping-operations", videoItemId, generation],
    queryFn: () => api.listGroupingOperations(videoItemId as string),
    enabled: videoItemId !== null,
    retry: false,
  });

  const refreshAll = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["object-roles", videoItemId, generation] });
    void queryClient.invalidateQueries({ queryKey: ["object-role-detail"] });
    void queryClient.invalidateQueries({ queryKey: ["grouping-suggestions", videoItemId, generation] });
    void queryClient.invalidateQueries({ queryKey: ["grouping-operations", videoItemId, generation] });
  }, [queryClient, videoItemId, generation]);

  const handleError = useCallback(
    (error: Error) => {
      if (error instanceof ApiError && error.status === 409) {
        onConflict(
          "Dữ liệu đã thay đổi ở nơi khác (xung đột phiên bản). Đã tải lại trạng thái mới nhất — hãy kiểm tra lại trước khi thao tác tiếp.",
        );
        refreshAll();
        return;
      }
      onConflict(
        error instanceof ApiError
          ? `Lỗi ${error.status}: ${error.detailText()}`
          : error instanceof Error
            ? error.message
            : "Thao tác thất bại.",
      );
    },
    [onConflict, refreshAll],
  );

  const generateMutation = useMutation({
    mutationFn: () =>
      api.generateGroupingSuggestions(videoItemId as string, generation, crypto.randomUUID()),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["grouping-suggestions", videoItemId, generation] });
      onNotice(
        `Đã tạo ${result.created_count} gợi ý mới (lặp lại ${result.replayed_count}, thay thế ${result.superseded_count}). Tất cả gợi ý đều chờ bạn duyệt.`,
      );
    },
    onError: handleError,
  });

  const dismissMutation = useMutation({
    mutationFn: (suggestion: GroupingSuggestion) =>
      api.dismissSuggestion(suggestion.id, suggestion.revision),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["grouping-suggestions", videoItemId, generation] });
      onNotice("Đã từ chối gợi ý gộp (các vai trò vẫn giữ riêng biệt).");
    },
    onError: handleError,
  });

  /** Explicit durable confirm of one role (CAS + audit + idempotent replay). */
  const confirmMutation = useMutation({
    mutationFn: (role: ObjectRole) =>
      api.confirmObjectRole(role.id, videoItemId as string, role.revision, crypto.randomUUID()),
    onSuccess: (result) => {
      refreshAll();
      onNotice(`Đã xác nhận vai trò "${result.role.name}" (lịch sử thao tác đã ghi).`);
    },
    onError: handleError,
  });

  const splitOriginalsByRole = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const op of operationsQuery.data?.operations ?? []) {
      if (op.operation_type !== "merge") continue;
      const existing = map.get(op.target_role_id) ?? [];
      map.set(op.target_role_id, [...existing, ...op.source_role_ids]);
    }
    return map;
  }, [operationsQuery.data]);

  return {
    suggestionsQuery,
    operationsQuery,
    operations: operationsQuery.data?.operations ?? [],
    refreshAll,
    generateMutation,
    dismissMutation,
    confirmMutation,
    splitOriginalsByRole,
    /** Backend-authoritative current source generation (T03-C2). */
    currentGeneration: suggestionsQuery.data?.current_generation ?? null,
  };
}

// ─── S08-T05 correction flow (preview / confirm / retry / poll) ───────────

export function useCorrectionPreview(payload: CorrectionRequestPayload | null) {
  const payloadKey = payload ? JSON.stringify(payload) : null;
  const query = useQuery({
    queryKey: ["correction-preview", payloadKey],
    queryFn: () => api.previewCorrection(payload as CorrectionRequestPayload),
    enabled: payloadKey !== null,
    retry: false,
    staleTime: 15_000,
  });
  if (payloadKey === null) return { impact: null, loading: false, error: null };
  const error =
    query.isError && query.error instanceof ApiError
      ? `Lỗi ${query.error.status}: ${query.error.detailText()}`
      : query.isError && query.error instanceof Error
        ? query.error.message
        : null;
  return { impact: query.data ?? null, loading: query.isLoading, error };
}

export interface CorrectionTrack {
  correctionId: string;
  recompute: { recompute_needed: boolean; job_id: string | null; status: string | null; progress: number | null; error: string | null } | null;
}

export function useGalleryCorrections(
  videoItemId: string | null,
  generation: string | null,
  refreshAll: () => void,
  onNotice: (message: string) => void,
  onConflict: (message: string) => void,
) {
  const queryClient = useQueryClient();
  const [track, setTrack] = useState<CorrectionTrack | null>(null);

  const handleError = useCallback(
    (error: Error) => {
      if (error instanceof ApiError && error.status === 409) {
        onConflict(
          "Dữ liệu đã thay đổi ở nơi khác (xung đột phiên bản). Đã tải lại trạng thái mới nhất — hãy kiểm tra lại trước khi thao tác tiếp.",
        );
        refreshAll();
        return;
      }
      onConflict(
        error instanceof ApiError
          ? `Lỗi ${error.status}: ${error.detailText()}`
          : error instanceof Error
            ? error.message
            : "Thao tác thất bại.",
      );
    },
    [onConflict, refreshAll],
  );

  const applyMutation = useMutation({
    mutationFn: async (req: { payload: CorrectionRequestPayload; successNotice: string }) => {
      const idempotencyKey = crypto.randomUUID();
      const created = await api.createCorrection({
        ...req.payload,
        idempotency_key: idempotencyKey,
      });
      const correction = await api.confirmCorrection(
        created.correction.id,
        created.correction.revision,
      );
      return { correction, successNotice: req.successNotice };
    },
    onSuccess: ({ correction, successNotice }) => {
      setTrack({ correctionId: correction.id, recompute: correction.recompute });
      refreshAll();
      if (videoItemId) {
        void queryClient.invalidateQueries({ queryKey: ["object-roles", videoItemId, generation] });
      }
      onNotice(successNotice);
    },
    onError: handleError,
  });

  const retryMutation = useMutation({
    mutationFn: (correctionId: string) => api.retryCorrectionRecompute(correctionId),
    onSuccess: (correction) => {
      setTrack({ correctionId: correction.id, recompute: correction.recompute });
      onNotice("Đã tạo công việc tính toán lại kế nhiệm — đang chạy.");
    },
    onError: handleError,
  });

  // Poll the durable recompute job until its honest terminal outcome.
  useEffect(() => {
    if (!track || !track.recompute) return;
    const status = track.recompute.status ?? "";
    if (!ACTIVE_RECOMPUTE_STATES.has(status)) return;
    const id = track.correctionId;
    const timer = window.setInterval(() => {
      api
        .getCorrection(id)
        .then((correction) => {
          setTrack((prev) =>
            prev && prev.correctionId === id
              ? { correctionId: id, recompute: correction.recompute }
              : prev,
          );
          const state = correction.recompute?.status ?? "";
          if (state === "completed") {
            refreshAll();
            if (videoItemId) {
              void queryClient.invalidateQueries({ queryKey: ["object-roles", videoItemId, generation] });
            }
            onNotice("Đã hoàn tất tính toán lại cho các vai trò bị ảnh hưởng.");
          } else if (state === "failed") {
            onConflict(
              `Tính toán lại thất bại: ${correction.recompute?.error ?? "lỗi không xác định"} — chỉnh sửa đã được áp dụng; hãy thử lại tính toán.`,
            );
          } else if (state === "cancelled") {
            onNotice("Công việc tính toán lại đã bị hủy — chỉnh sửa vẫn được giữ.");
          }
        })
        .catch(() => {
          /* transient read failure — keep polling */
        });
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track?.correctionId, track?.recompute?.status, refreshAll, videoItemId]);

  return { track, setTrack, applyMutation, retryMutation, ACTIVE_RECOMPUTE_STATES };
}

/** Stable-role-id lookup map for display names (never an identity authority). */
export function useStableRoleNames(roles: ObjectRole[]): Map<string, string> {
  return useMemo(() => {
    const map = new Map<string, string>();
    for (const role of roles) map.set(role.id, role.name);
    return map;
  }, [roles]);
}

export { ACTIVE_JOB_STATES, POLL_INTERVAL_MS };
