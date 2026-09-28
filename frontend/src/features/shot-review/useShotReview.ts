"use client";

/**
 * MF-END-24 — useShotReview.
 *
 * Reads the REAL run status (poll while non-terminal), the REAL QC items +
 * their canonical navigation, and exposes the REAL run controls
 * (cancel/retry/resume/recompute-scoped-shot).  Every mutation goes through
 * a single-flight latch per intent, so one click can never issue two
 * requests.  All numbers rendered by the UI come from this data — nothing
 * is synthesised locally.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ShotReviewApiError,
  cancelRun,
  getQcNavigation,
  getRunStatus,
  listQcItems,
  recomputeScopedShot,
  resumeRun,
  retryRun,
  markerInputFrom,
  type QcItemRecord,
  type QcNavigationPayload,
  type RecomputePayload,
  type RunActionPayload,
  type RunStatusPayload,
} from "./shotReviewApi";
import {
  classifyReviewError,
  createSingleFlight,
  correctionAuthorityFromCheckpoint,
  groupChunksIntoShots,
  placeQcMarker,
  runProgress,
  scopedRetryPayload,
  type PlacedMarker,
  type ReviewErrorCopy,
  type ShotSummary,
} from "./shotReviewLogic";

export type ShotReviewPhase = "loading" | "ready" | "error" | "empty";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export interface UseShotReviewOpts {
  runId: string | null;
  projectId?: string | null;
  videoItemId?: string | null;
  workspaceId?: string;
  pollMs?: number;
  enabled?: boolean;
}

export interface ShotReviewActionState {
  kind: "cancel" | "retry" | "resume" | "retry_shot" | null;
  shotId?: string;
  result?: RunActionPayload | RecomputePayload;
  error?: ReviewErrorCopy;
  at: number;
}

export interface UseShotReviewReturn {
  phase: ShotReviewPhase;
  error: ReviewErrorCopy | null;
  data: RunStatusPayload | null;
  shots: ShotSummary[];
  progress: number | null;
  markers: PlacedMarker[];
  markersPhase: ShotReviewPhase;
  markersError: ReviewErrorCopy | null;
  action: ShotReviewActionState | null;
  isPolling: boolean;
  refresh: () => Promise<void>;
  refreshMarkers: () => Promise<void>;
  cancel: () => Promise<void>;
  retry: () => Promise<void>;
  resume: () => Promise<void>;
  retryShot: (shotId: string) => Promise<void>;
}

export function useShotReview(opts: UseShotReviewOpts): UseShotReviewReturn {
  const {
    runId,
    projectId = null,
    videoItemId = null,
    workspaceId = "default",
    pollMs = 1500,
    enabled = true,
  } = opts;

  const [phase, setPhase] = useState<ShotReviewPhase>(runId ? "loading" : "empty");
  const [error, setError] = useState<ReviewErrorCopy | null>(null);
  const [data, setData] = useState<RunStatusPayload | null>(null);
  const [markers, setMarkers] = useState<PlacedMarker[]>([]);
  const [markersPhase, setMarkersPhase] = useState<ShotReviewPhase>("empty");
  const [markersError, setMarkersError] = useState<ReviewErrorCopy | null>(null);
  const [action, setAction] = useState<ShotReviewActionState | null>(null);
  const [isPolling, setIsPolling] = useState(false);

  const mountedRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latchesRef = useRef({
    cancel: createSingleFlight(),
    retry: createSingleFlight(),
    resume: createSingleFlight(),
    retry_shot: createSingleFlight(),
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const fetchOnce = useCallback(async (): Promise<boolean> => {
    if (!runId || !enabled) {
      setPhase("empty");
      setData(null);
      setError(null);
      return false;
    }
    try {
      const result = await getRunStatus(runId, workspaceId, projectId ?? undefined);
      if (!mountedRef.current) return false;
      setData(result);
      setError(null);
      setPhase("ready");
      return !TERMINAL.has(result.status);
    } catch (err: unknown) {
      if (!mountedRef.current) return false;
      if (err instanceof ShotReviewApiError) {
        setError(classifyReviewError({ status: err.status, message: err.detailText() }));
      } else {
        setError(classifyReviewError({ message: err instanceof Error ? err.message : String(err) }));
      }
      setPhase("error");
      return false;
    }
  }, [runId, workspaceId, projectId, enabled]);

  useEffect(() => {
    let cancelled = false;
    const loop = async () => {
      const keepPolling = await fetchOnce();
      if (cancelled || !mountedRef.current) return;
      setIsPolling(keepPolling);
      if (keepPolling) {
        timerRef.current = setTimeout(loop, pollMs);
      }
    };
    void loop();
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      setIsPolling(false);
    };
  }, [fetchOnce, pollMs]);

  const refresh = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const keepPolling = await fetchOnce();
    if (mountedRef.current) {
      setIsPolling(keepPolling);
      if (keepPolling) {
        timerRef.current = setTimeout(async () => {
          const again = await fetchOnce();
          if (mountedRef.current) setIsPolling(again);
        }, pollMs);
      }
    }
  }, [fetchOnce, pollMs]);

  const fpsNum = data?.fps_num ?? null;
  const fpsDen = data?.fps_den ?? null;

  const refreshMarkers = useCallback(async () => {
    if (!projectId) {
      setMarkers([]);
      setMarkersPhase("empty");
      setMarkersError(null);
      return;
    }
    setMarkersPhase("loading");
    try {
      const list = await listQcItems(projectId, { videoItemId: videoItemId ?? undefined, limit: 50 });
      const placed: PlacedMarker[] = [];
      for (const item of list.items) {
        let nav: QcNavigationPayload | null = null;
        try {
          nav = await getQcNavigation(item.id);
        } catch {
          nav = null;
        }
        placed.push(placeQcMarker(markerInputFrom(item as QcItemRecord, nav), fpsNum, fpsDen));
      }
      if (!mountedRef.current) return;
      setMarkers(placed);
      setMarkersError(null);
      setMarkersPhase(placed.length === 0 ? "empty" : "ready");
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      if (err instanceof ShotReviewApiError) {
        setMarkersError(classifyReviewError({ status: err.status, message: err.detailText() }));
      } else {
        setMarkersError(classifyReviewError({ message: err instanceof Error ? err.message : String(err) }));
      }
      setMarkersPhase("error");
    }
  }, [projectId, videoItemId, fpsNum, fpsDen]);

  useEffect(() => {
    // Load through a microtask so the effect body never setStates synchronously;
    // re-placement uses the latest run fps, so it re-runs when fps arrives.
    queueMicrotask(() => {
      void refreshMarkers();
    });
  }, [refreshMarkers]);

  const runAction = useCallback(
    async (kind: "cancel" | "retry" | "resume", fn: () => Promise<RunActionPayload>) => {
      if (!runId) return;
      const latch = latchesRef.current[kind];
      try {
        const result = await latch.run(fn);
        if (!mountedRef.current) return;
        setAction({ kind, result, at: Date.now() });
        await refresh();
      } catch (err: unknown) {
        if (!mountedRef.current) return;
        const copy =
          err instanceof ShotReviewApiError
            ? classifyReviewError({ status: err.status, message: err.detailText() })
            : classifyReviewError({ message: err instanceof Error ? err.message : String(err) });
        setAction({ kind, error: copy, at: Date.now() });
      }
    },
    [runId, refresh],
  );

  const cancel = useCallback(async () => {
    if (!runId) return;
    await runAction("cancel", () => cancelRun(runId, workspaceId, projectId ?? undefined));
  }, [runId, runAction, workspaceId, projectId]);

  const retry = useCallback(async () => {
    if (!runId) return;
    await runAction("retry", () => retryRun(runId, workspaceId, projectId ?? undefined));
  }, [runId, runAction, workspaceId, projectId]);

  const resume = useCallback(async () => {
    if (!runId) return;
    await runAction("resume", () => resumeRun(runId, workspaceId, projectId ?? undefined));
  }, [runId, runAction, workspaceId, projectId]);

  const retryShot = useCallback(
    async (shotId: string) => {
      if (!runId || !data) return;
      const authority = correctionAuthorityFromCheckpoint(data.checkpoint);
      const payload = scopedRetryPayload(shotId, authority, data.revision ?? null);
      if (!payload) {
        if (!mountedRef.current) return;
        setAction({
          kind: "retry_shot",
          shotId,
          error: classifyReviewError({
            code: "scoped_retry_no_authority",
            message:
              "Chưa có correction authority đã áp dụng cho run này — không tạo correction_id tự phát để tránh render sai phạm vi.",
          }),
          at: Date.now(),
        });
        return;
      }
      try {
        const result = await latchesRef.current.retry_shot.run(() =>
          recomputeScopedShot(runId, payload, workspaceId, projectId ?? undefined),
        );
        if (!mountedRef.current) return;
        setAction({ kind: "retry_shot", shotId, result, at: Date.now() });
        await refresh();
      } catch (err: unknown) {
        if (!mountedRef.current) return;
        const copy =
          err instanceof ShotReviewApiError
            ? classifyReviewError({ status: err.status, message: err.detailText() })
            : classifyReviewError({ message: err instanceof Error ? err.message : String(err) });
        setAction({ kind: "retry_shot", shotId, error: copy, at: Date.now() });
      }
    },
    [runId, data, workspaceId, projectId, refresh],
  );

  const shots = useMemo(() => (data ? groupChunksIntoShots(data.chunks) : []), [data]);
  const progress = useMemo(() => (data ? runProgress(data.chunks) : null), [data]);

  return {
    phase,
    error,
    data,
    shots,
    progress,
    markers,
    markersPhase,
    markersError,
    action,
    isPolling,
    refresh,
    refreshMarkers,
    cancel,
    retry,
    resume,
    retryShot,
  };
}
