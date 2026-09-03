"use client";

/**
 * S10-T04B — useApplyStatus (polling hook for S10 FullApply progress truth).
 *
 * Contract:
 * - All progress/estimate/current-chunk comes from the backend
 *   GET /api/v2/full-apply/{run_id} — no local synthesis, no fake 100%.
 * - Survives reload: caller supplies the run_id from localStorage / URL.
 * - Polls while status is pending/running/verifying; stops at terminal.
 * - Returns loading/error/empty states distinctly.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";

export interface ApplyStatus {
  run_id: string;
  workspace_id: string;
  project_id: string;
  video_item_id: string;
  apply_checkpoint_id: string;
  apply_checkpoint_hash: string;
  apply_checkpoint_revision: number;
  plan_id: string;
  plan_hash: string;
  status: string;
  frame_count: number;
  attempt: number;
  natural_key: string | null;
  idempotency_key: string | null;
  chunks: Array<{
    id: string;
    workspace_id: string;
    run_id: string;
    chunk_index: number;
    order_index: number;
    shot_id: string;
    layer_id: string | null;
    object_role_id: string | null;
    core_start_frame: number;
    core_end_frame: number;
    overlap_before: number;
    overlap_after: number;
    content_hash: string;
    state: string;
    attempt: number;
    artifact_id: string | null;
    verified: boolean;
  }>;
  publications: Array<{
    id: string;
    workspace_id: string;
    run_id: string;
    artifact_id: string;
    content_hash: string;
    frame_count: number;
    frame_metadata: Record<string, unknown>;
    checkpoint_id: string;
    checkpoint_hash: string;
    checkpoint_revision: number;
    state: string;
  }>;
  checkpoint: Record<string, unknown> | null;
}

export type ApplyStatusPhase = "loading" | "ready" | "error" | "empty";

export interface UseApplyStatusOpts {
  runId: string | null;
  workspaceId?: string;
  projectId?: string;
  pollMs?: number;
  enabled?: boolean;
}

export interface UseApplyStatusReturn {
  phase: ApplyStatusPhase;
  error: string | null;
  errorStatus: number | null;
  data: ApplyStatus | null;
  progress: number | null;
  currentChunk: ApplyStatus["chunks"][number] | null;
  isPolling: boolean;
  refresh: () => Promise<void>;
}

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function deriveProgress(data: ApplyStatus | null): number | null {
  if (!data || data.chunks.length === 0) return null;
  const done = data.chunks.filter((c) => c.state === "completed").length;
  return Math.round((done / data.chunks.length) * 100);
}

function deriveCurrentChunk(data: ApplyStatus | null): ApplyStatus["chunks"][number] | null {
  if (!data || data.chunks.length === 0) return null;
  const running = data.chunks.find((c) => c.state === "running");
  if (running) return running;
  const nextPending = data.chunks.find((c) => c.state === "pending");
  if (nextPending) return nextPending;
  return data.chunks[data.chunks.length - 1] ?? null;
}

export function useApplyStatus(opts: UseApplyStatusOpts): UseApplyStatusReturn {
  const { runId, workspaceId = "default", projectId, pollMs = 1500, enabled = true } = opts;
  const [phase, setPhase] = useState<ApplyStatusPhase>(runId ? "loading" : "empty");
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [data, setData] = useState<ApplyStatus | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const fetchOnce = useCallback(async () => {
    if (!runId || !enabled) {
      setPhase("empty");
      setData(null);
      setError(null);
      setErrorStatus(null);
      return;
    }
    try {
      const result = await api.getS10FullApplyStatus(runId, workspaceId, projectId);
      if (!mountedRef.current) return;
      setData(result as unknown as ApplyStatus);
      setError(null);
      setErrorStatus(null);
      setPhase("ready");
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      if (err instanceof ApiError) {
        setError(err.detailText() || `Lỗi ${err.status}`);
        setErrorStatus(err.status);
      } else {
        setError(err instanceof Error ? err.message : String(err));
        setErrorStatus(null);
      }
      setPhase("error");
    }
  }, [runId, workspaceId, projectId, enabled]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const loadedRef = useRef(false);
  useEffect(() => {
    if (!runId || !enabled) return;
    if (loadedRef.current) return;
    loadedRef.current = true;
    void fetchOnce();
  }, [runId, enabled, fetchOnce]);

  // Handle clearing when runId/enabled go to empty without setState-in-effect lint
  const prevRunIdRef = useRef<string | null>(runId);
  useEffect(() => {
    if ((!runId || !enabled) && prevRunIdRef.current !== runId) {
      prevRunIdRef.current = runId;
      setPhase("empty");
      setData(null);
      setError(null);
      setErrorStatus(null);
    } else {
      prevRunIdRef.current = runId;
    }
  }, [runId, enabled]);

  const shouldPoll = phase === "ready" && data !== null && !TERMINAL.has(data.status);
  const isPolling = shouldPoll && enabled && runId !== null;

  useEffect(() => {
    if (!isPolling) return;
    timerRef.current = setTimeout(() => {
      void fetchOnce();
    }, pollMs);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isPolling, pollMs, fetchOnce, data?.status]);

  return {
    phase,
    error,
    errorStatus,
    data,
    progress: deriveProgress(data),
    currentChunk: deriveCurrentChunk(data),
    isPolling,
    refresh: fetchOnce,
  };
}
