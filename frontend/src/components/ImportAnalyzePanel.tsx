"use client";

/**
 * Import/Analyze UI — S05-C01 (approved-pipeline orchestration).
 *
 * Wired to the REAL approved durable chain T02→T03→T04 (no legacy /ingest):
 *   - submit  : POST /api/projects/{id}/analyze          (api.analyzeProject)
 *   - state   : GET  /api/projects/{id}/analyze          (api.getAnalyzeChain)
 *   - retry   : POST /api/projects/{id}/analyze/retry    (api.retryAnalyzeChain)
 *   - cancel  : POST /api/projects/{id}/analyze/cancel   (api.cancelAnalyzeChain)
 *
 *   The cancel target is resolved by the BACKEND at cancel time (atomic
 *   chain-cancel API, S05-C04-R3) — never from this component's polled
 *   chain snapshot — so a click during an import→proxy→scene transition
 *   still cancels the currently active durable step.
 *
 * Rules enforced here:
 *   - ALL progress/state come from the backend-owned chain state (real
 *     durable Job rows + real checkpoints). No fake timers, no synthetic
 *     progress, no mocked job state. The overall progress is the backend's
 *     `chain.progress` (mean of real per-step progresses); ETA is DERIVED
 *     from real progress deltas over wall-clock and always labelled
 *     "ước tính".
 *   - After every mutation (submit/cancel/retry) the panel REFETCHES the
 *     chain so UI state matches the backend. Duplicate retries reuse the
 *     backend-created successor (never a 500 IdempotencyKeyInUse without a
 *     path).
 *   - Refresh/restart rehydrates the chain from GET /analyze (backend-owned
 *     per project — no client-side job id persistence, no duplicate
 *     submission).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Boxes } from "lucide-react";
import {
  api,
  ApiError,
  type AnalyzeChainState,
  type ChainStepInfo,
  type ChainStepName,
} from "@/lib/api";
import {
  GENERIC_ACTION,
  JOB_STATE_LABEL,
  matchPreflightError,
  type PreflightErrorInfo,
} from "@/lib/preflightErrors";

const POLL_INTERVAL_MS = 1000;
const ACTIVE_JOB_STATES = new Set(["pending", "queued", "running", "cancelling"]);
const ACTIVE_CHAIN_STATUSES = new Set(["running"]);

export interface ImportAnalyzePanelProps {
  /** Legacy project id the approved chain runs against. */
  projectId: string;
  /** Optional callback when the chain reaches a terminal state. */
  onTerminal?: (chain: AnalyzeChainState) => void;
}

interface ChainSample {
  at: number;
  progress: number;
}

type Phase = "idle" | "submitting" | "polling" | "terminal" | "resume-check";

interface PanelState {
  phase: Phase;
  chain: AnalyzeChainState | null;
  /** Error to show for the CURRENT action (submit/cancel/retry). */
  actionError: string | null;
  /** Elapsed wall-clock ms since the chain first became active. */
  elapsedMs: number;
  /** Derived ETA seconds from REAL chain progress deltas (null until estimable). */
  etaSeconds: number | null;
  submitError: string | null;
}

function initialState(): PanelState {
  return {
    phase: "resume-check",
    chain: null,
    actionError: null,
    elapsedMs: 0,
    etaSeconds: null,
    submitError: null,
  };
}

const STEP_ORDER: ChainStepName[] = ["import", "proxy", "scene_detect"];

const CHAIN_STEP_LABEL: Record<ChainStepName, string> = {
  import: "1. Nhập nguồn (import)",
  proxy: "2. Tạo proxy",
  scene_detect: "3. Phát hiện cảnh",
};

const CHAIN_STATUS_LABEL: Record<string, string> = {
  idle: "Chưa có công việc",
  running: "Đang xử lý",
  completed: "Hoàn tất",
  failed: "Thất bại",
  cancelled: "Đã hủy",
};

function stepStatusLabel(status: string): string {
  if (status === "not_created") return "Chưa tạo";
  return JOB_STATE_LABEL[status] ?? status;
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatEta(sec: number): string {
  if (sec <= 0) return "—";
  if (sec < 60) return `≈ ${Math.ceil(sec)} giây`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `≈ ${m} phút ${s} giây`;
}

/** The chain is active while any step Job is active or the backend says running. */
function isChainActive(chain: AnalyzeChainState | null): boolean {
  if (!chain) return false;
  if (ACTIVE_CHAIN_STATUSES.has(chain.chain_status)) return true;
  return STEP_ORDER.some((name) => {
    const step = chain.steps[name];
    return step !== undefined && ACTIVE_JOB_STATES.has(step.status);
  });
}

function isChainTerminal(chain: AnalyzeChainState | null): boolean {
  if (!chain) return false;
  return (
    chain.chain_status === "completed" ||
    chain.chain_status === "failed" ||
    chain.chain_status === "cancelled"
  );
}

/** The first failed/cancelled step (what a retry will replace). */
function firstRetryableStep(chain: AnalyzeChainState | null): ChainStepInfo | null {
  if (!chain) return null;
  for (const name of STEP_ORDER) {
    const step = chain.steps[name];
    if (step !== undefined && (step.status === "failed" || step.status === "cancelled")) {
      return step;
    }
  }
  return null;
}

export function ImportAnalyzePanel({ projectId, onTerminal }: ImportAnalyzePanelProps) {
  const router = useRouter();
  const [state, setState] = useState<PanelState>(initialState);
  const samplesRef = useRef<ChainSample[]>([]);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [clientHint, setClientHint] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const chain = state.chain;
  const active = isChainActive(chain);

  // ── Polling loop (real backend chain state, 1s interval while active) ────
  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const adoptChain = useCallback(
    (next: AnalyzeChainState) => {
      const at = Date.now();
      setState((prev) => {
        const wasActive = isChainActive(prev.chain);
        const nowActive = isChainActive(next);
        let elapsedMs = prev.elapsedMs;
        if (nowActive) {
          elapsedMs = wasActive ? prev.elapsedMs : 0;
        } else {
          elapsedMs = 0;
        }
        // Derive ETA from REAL chain progress deltas over wall-clock (§7.3).
        let etaSeconds: number | null = null;
        if (nowActive && next.progress > 0) {
          const samples = [...samplesRef.current, { at, progress: next.progress }].slice(-6);
          samplesRef.current = samples;
          if (samples.length >= 2) {
            const first = samples[0];
            const last = samples[samples.length - 1];
            const dP = last.progress - first.progress;
            const dT = (last.at - first.at) / 1000;
            if (dP > 0 && dT > 1) {
              const rate = dP / dT;
              etaSeconds = (100 - last.progress) / rate;
            }
          }
        } else if (!nowActive) {
          samplesRef.current = [];
        }
        return {
          ...prev,
          chain: next,
          phase: nowActive ? "polling" : "terminal",
          elapsedMs,
          etaSeconds,
        };
      });
      if (!isChainActive(next)) {
        stopPolling();
        onTerminal?.(next);
      }
    },
    [onTerminal, stopPolling],
  );

  const refetchChain = useCallback(async () => {
    try {
      const next = await api.getAnalyzeChain(projectId);
      adoptChain(next);
    } catch {
      // transient poll failure — keep showing last known state
    }
  }, [projectId, adoptChain]);

  // Poll loop effect: runs while the chain is active.
  useEffect(() => {
    if (state.phase !== "polling" || !active) return;
    pollTimerRef.current = setInterval(() => {
      void refetchChain();
    }, POLL_INTERVAL_MS);
    return stopPolling;
  }, [state.phase, active, refetchChain, stopPolling]);

  // Elapsed clock while active (real wall-clock, derived from polls).
  useEffect(() => {
    if (state.phase !== "polling" || !active) return;
    const t = setInterval(() => {
      setState((prev) =>
        prev.phase === "polling" && isChainActive(prev.chain)
          ? { ...prev, elapsedMs: prev.elapsedMs + 250 }
          : prev,
      );
    }, 250);
    return () => clearInterval(t);
  }, [state.phase, active]);

  // ── Resume after refresh/restart (backend-owned chain, no duplicate submit) ──
  useEffect(() => {
    let cancelled = false;
    async function resume() {
      try {
        const next = await api.getAnalyzeChain(projectId);
        if (cancelled) return;
        if (next.chain_status === "idle") {
          // Backend has no chain for this project yet — the empty dropzone.
          setState((prev) => ({ ...prev, chain: null, phase: "idle" }));
        } else if (isChainActive(next) || isChainTerminal(next)) {
          adoptChain(next);
        } else {
          setState((prev) => ({ ...prev, chain: next, phase: "idle" }));
        }
      } catch (err) {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          phase: "idle",
          submitError: err instanceof Error ? err.message : null,
        }));
      }
    }
    void resume();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // ── File selection (client-side hint only; backend probe is truth) ──
  const handleFileSelect = useCallback((f: File | null) => {
    if (!f) return;
    setFile(f);
    setClientHint(null);
    const lower = f.name.toLowerCase();
    if (!lower.endsWith(".mp4")) {
      setClientHint(
        "Chỉ hỗ trợ MP4 (H.264/HEVC + AAC). Hệ thống sẽ kiểm tra lại khi phân tích; nếu không hợp lệ bạn sẽ thấy lý do cụ thể.",
      );
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const files = e.dataTransfer.files;
      if (files && files.length > 0) handleFileSelect(files[0]);
    },
    [handleFileSelect],
  );

  // ── Submit: upload → ONE analyze submission (creates the approved chain) ──
  const handleSubmit = useCallback(async () => {
    if (!file) return;
    setState((prev) => ({
      ...prev,
      phase: "submitting",
      submitError: null,
      actionError: null,
    }));
    try {
      // 1. Upload the source video via the approved upload endpoint.
      await api.uploadVideo(projectId, file);
      // 2. ONE submission drives T02→T03→T04 (backend-owned chain).
      const chainState = await api.analyzeProject(projectId, file.name);
      samplesRef.current = [];
      adoptChain(chainState);
    } catch (err) {
      setState((prev) => ({
        ...prev,
        phase: "idle",
        submitError:
          err instanceof Error ? err.message : "Không thể khởi chạy phân tích.",
      }));
    }
  }, [file, projectId, adoptChain]);

  // ── Cancel the chain's ACTIVE step (atomic backend resolution) ────────
  const handleCancel = useCallback(async () => {
    // S05-C04-R3 (Codex finding 1): the backend resolves the currently
    // active durable job AT CANCEL TIME via POST /analyze/cancel — never
    // this component's polled snapshot. A click during an
    // import→proxy→scene transition therefore still cancels the active
    // step; the backend fails honestly (400) only when the chain has
    // genuinely completed/terminated, and the refetch below shows that
    // truth.
    setState((prev) => ({ ...prev, actionError: null }));
    try {
      const res = await api.cancelAnalyzeChain(projectId);
      if (res.status === "cancel_requested") {
        // Refetch immediately — UI must show the backend's cancelling state.
        void refetchChain();
      }
    } catch (err) {
      setState((prev) => ({
        ...prev,
        actionError:
          err instanceof ApiError && err.status === 400
            ? "Chuỗi đã kết thúc — không còn bước nào để hủy (trạng thái thật được làm mới)."
            : err instanceof Error
              ? err.message
              : "Không thể hủy công việc.",
      }));
      // Terminal/transitional chain → refetch so UI matches the backend.
      void refetchChain();
    }
  }, [projectId, refetchChain]);

  // ── Retry the failed/cancelled step via a successor Job (§8.5) + refetch ──
  const handleRetry = useCallback(async () => {
    setState((prev) => ({
      ...prev,
      phase: "submitting",
      actionError: null,
    }));
    try {
      const chainState = await api.retryAnalyzeChain(projectId);
      samplesRef.current = [];
      adoptChain(chainState);
    } catch (err) {
      setState((prev) => ({
        ...prev,
        phase: "terminal",
        actionError:
          err instanceof Error ? err.message : "Không thể thử lại công việc.",
      }));
      void refetchChain();
    }
  }, [projectId, adoptChain, refetchChain]);

  // ── Derived UI ──────────────────────────────────────────────────────────
  const failedStep = chain
    ? STEP_ORDER.map((name) => chain.steps[name]).find(
        (s): s is ChainStepInfo => s !== undefined && s.status === "failed",
      ) ?? null
    : null;
  const preflight: PreflightErrorInfo | null = failedStep
    ? matchPreflightError(failedStep.error_code) ??
      matchPreflightError(failedStep.error) ??
      matchPreflightError(failedStep.message)
    : null;
  const showError =
    (state.submitError ?? state.actionError) ||
    (failedStep && failedStep.error ? failedStep.error : null);

  const cancelDisabled = !active;
  const cancelDisabledReason = !chain
    ? null
    : !active
      ? "Không có bước nào đang chạy (không thể hủy công việc đã kết thúc)."
      : chain.steps[chain.active_step ?? "import"]?.status === "cancelling"
        ? "Đã yêu cầu hủy — hệ thống đang dừng công việc."
        : null;
  const retryableStep = firstRetryableStep(chain);
  const retryVisible = retryableStep !== null;
  const retryDisabled = state.phase === "submitting";
  const retryDisabledReason = retryDisabled
    ? "Đang gửi yêu cầu lên hệ thống..."
    : null;

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      {/* Heading — one dominant action per screen */}
      <div className="space-y-2">
        <h1 className="font-display text-2xl font-semibold text-[var(--text-primary)]">
          Nhập &amp; Phân tích video
        </h1>
        <p className="text-sm text-[var(--text-muted)]">
          Tải video lên; hệ thống chạy chuỗi xử lý đã được duyệt: nhập nguồn → tạo
          proxy → phát hiện cảnh. Bạn có thể hủy, thử lại hoặc tiếp tục sau khi tải
          lại trang.
        </p>
      </div>

      {/* Resume-check skeleton (initial loading matches the resulting layout) */}
      {state.phase === "resume-check" && (
        <div className="space-y-4" role="status" aria-label="Đang khôi phục công việc">
          <div className="h-24 animate-pulse rounded-xl bg-[var(--surface-800)]" />
          <div className="h-4 w-2/3 animate-pulse rounded bg-[var(--surface-800)]" />
        </div>
      )}

      {/* File dropzone (empty state — no chain yet) */}
      {(state.phase === "idle" || state.phase === "submitting") && !chain && (
        <section
          aria-label="Chọn tệp video nguồn"
          className="space-y-4 rounded-2xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-6 shadow-panel"
        >
          <div
            role="button"
            tabIndex={0}
            aria-label="Chọn tệp video nguồn"
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-10 text-center transition-colors ${
              isDragging
                ? "border-[var(--primary-500)] bg-[color-mix(in_srgb,var(--primary-600)_15%,transparent)]"
                : file
                  ? "border-[var(--success)]/50 bg-[color-mix(in_srgb,var(--success)_8%,transparent)]"
                  : "border-[var(--surface-700)] hover:border-[var(--primary-500)]"
            }`}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".mp4,video/mp4"
              className="sr-only"
              onChange={(e) => handleFileSelect(e.target.files?.[0] ?? null)}
              aria-label="Chọn tệp video MP4"
            />
            <span aria-hidden="true" className="text-3xl">🎬</span>
            {file ? (
              <>
                <p className="text-sm font-medium text-[var(--text-primary)]">{file.name}</p>
                <p className="text-xs text-[var(--text-muted)]">
                  {(file.size / 1024 / 1024).toFixed(1)} MB — nhấn để chọn tệp khác
                </p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-[var(--text-primary)]">
                  Kéo thả tệp video MP4 vào đây
                </p>
                <p className="text-xs text-[var(--text-muted)]">
                  hoặc nhấn để chọn tệp từ máy tính
                </p>
              </>
            )}
          </div>
          {clientHint && (
            <p role="status" className="text-[11px] text-[var(--warning)]">
              ⚠️ {clientHint}
            </p>
          )}
          <div className="flex flex-col items-start gap-2">
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!file || state.phase === "submitting"}
              className="rounded-lg bg-[var(--primary-600)] px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--primary-700)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {state.phase === "submitting" ? "Đang khởi chạy..." : "Phân tích video"}
            </button>
            <p className="text-[11px] text-[var(--text-muted)]">
              {!file
                ? "Chọn tệp video MP4 trước — nút sẽ được bật sau khi bạn chọn tệp."
                : "Một lần gửi sẽ chạy đủ 3 bước: nhập nguồn, tạo proxy, phát hiện cảnh (tiến trình thật từ hệ thống)."}
            </p>
          </div>
        </section>
      )}

      {/* Chain panel: real backend-owned chain state */}
      {chain && (
        <section
          aria-label="Trạng thái chuỗi phân tích"
          className="space-y-4 rounded-2xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-6 shadow-panel"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span
                role="status"
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  chain.chain_status === "completed"
                    ? "bg-[color-mix(in_srgb,var(--success)_15%,transparent)] text-[var(--success)]"
                    : chain.chain_status === "failed"
                      ? "bg-[color-mix(in_srgb,var(--danger)_15%,transparent)] text-[var(--danger)]"
                      : chain.chain_status === "cancelled"
                        ? "bg-[color-mix(in_srgb,var(--text-muted)_15%,transparent)] text-[var(--text-muted)]"
                        : "bg-[color-mix(in_srgb,var(--primary-500)_15%,transparent)] text-[var(--primary-300)]"
                }`}
              >
                {CHAIN_STATUS_LABEL[chain.chain_status] ?? chain.chain_status}
              </span>
              {chain.source_name && (
                <span className="text-xs text-[var(--text-faint)]">{chain.source_name}</span>
              )}
            </div>
            {active && (
              <span className="text-xs text-[var(--text-muted)]">
                Đã chạy {formatElapsed(state.elapsedMs)}
              </span>
            )}
          </div>

          {/* Overall progress — backend-computed mean of REAL step progresses */}
          <div
            role="progressbar"
            aria-valuenow={Math.round(chain.progress)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Tiến trình phân tích: ${Math.round(chain.progress)} phần trăm`}
            className="h-3 w-full overflow-hidden rounded-full bg-[var(--surface-800)]"
          >
            <div
              className={`h-full rounded-full transition-[width] duration-500 ${
                chain.chain_status === "failed"
                  ? "bg-[var(--danger)]"
                  : chain.chain_status === "cancelled"
                    ? "bg-[var(--text-faint)]"
                    : "bg-gradient-to-r from-[var(--primary-500)] to-[var(--accent-500)]"
              }`}
              style={{ width: `${Math.max(0, Math.min(100, chain.progress))}%` }}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span role="status" className="text-[var(--text-secondary)]">
              {active
                ? chain.active_step
                  ? `Đang chạy bước: ${CHAIN_STEP_LABEL[chain.active_step]}`
                  : "Đang xử lý..."
                : (CHAIN_STATUS_LABEL[chain.chain_status] ?? chain.chain_status)}
            </span>
            <span className="text-[var(--text-muted)]">{Math.round(chain.progress)}%</span>
          </div>

          {/* Derived ETA — always labelled as an estimate */}
          {active && state.etaSeconds !== null && (
            <p role="status" className="text-[11px] text-[var(--text-muted)]">
              Ước tính còn lại: {formatEta(state.etaSeconds)} (tính từ tốc độ tiến trình thật)
            </p>
          )}
          {active && state.etaSeconds === null && (
            <p role="status" className="text-[11px] text-[var(--text-muted)]">
              Ước tính sẽ hiện sau khi hệ thống thu thập đủ mẫu tiến trình.
            </p>
          )}

          {/* Per-step real state — one row per approved job, real progress */}
          <ol className="space-y-3" aria-label="Các bước của chuỗi phân tích">
            {STEP_ORDER.map((name) => {
              const step = chain.steps[name];
              if (!step) return null;
              const stepActive = ACTIVE_JOB_STATES.has(step.status);
              const stepFailed = step.status === "failed";
              const stepCancelled = step.status === "cancelled";
              const stepCompleted = step.status === "completed";
              return (
                <li
                  key={name}
                  className={`rounded-xl border p-4 ${
                    stepActive
                      ? "border-[var(--primary-500)]/50 bg-[color-mix(in_srgb,var(--primary-600)_8%,transparent)]"
                      : stepFailed
                        ? "border-[var(--danger)]/40 bg-[color-mix(in_srgb,var(--danger)_6%,transparent)]"
                        : stepCompleted
                          ? "border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_6%,transparent)]"
                          : stepCancelled
                            ? "border-[var(--surface-700)] bg-[var(--surface-950)]"
                            : "border-[var(--surface-700)] bg-[var(--surface-950)]"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-[var(--text-primary)]">
                      {CHAIN_STEP_LABEL[name]}
                    </p>
                    <span className="flex items-center gap-2">
                      {step.job_id && (
                        <span className="text-[11px] text-[var(--text-faint)]">
                          #{step.job_id.slice(0, 8)}
                        </span>
                      )}
                      <span
                        role="status"
                        className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          stepCompleted
                            ? "bg-[color-mix(in_srgb,var(--success)_15%,transparent)] text-[var(--success)]"
                            : stepFailed
                              ? "bg-[color-mix(in_srgb,var(--danger)_15%,transparent)] text-[var(--danger)]"
                              : stepCancelled || step.status === "not_created"
                                ? "bg-[color-mix(in_srgb,var(--text-muted)_15%,transparent)] text-[var(--text-muted)]"
                                : "bg-[color-mix(in_srgb,var(--primary-500)_15%,transparent)] text-[var(--primary-300)]"
                        }`}
                      >
                        {stepStatusLabel(step.status)}
                      </span>
                    </span>
                  </div>
                  {step.status !== "not_created" && (
                    <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-[var(--surface-800)]">
                      <div
                        className={`h-full rounded-full transition-[width] duration-500 ${
                          stepFailed
                            ? "bg-[var(--danger)]"
                            : stepCancelled
                              ? "bg-[var(--text-faint)]"
                              : "bg-gradient-to-r from-[var(--primary-500)] to-[var(--accent-500)]"
                        }`}
                        style={{ width: `${Math.max(0, Math.min(100, step.progress))}%` }}
                      />
                    </div>
                  )}
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                    {step.message || stepStatusLabel(step.status)}
                    {step.status !== "not_created" && ` · ${Math.round(step.progress)}%`}
                  </p>
                </li>
              );
            })}
          </ol>

          {/* Actionable preflight error rendering (approved taxonomy) */}
          {failedStep && preflight && (
            <div
              role="alert"
              className="space-y-1 rounded-xl border border-[var(--danger)]/40 bg-[color-mix(in_srgb,var(--danger)_8%,transparent)] p-4"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--danger)]">
                {preflight.severity === "warning" ? "Cảnh báo" : "Không thể import"} ·{" "}
                {preflight.code}
              </p>
              <p className="text-sm text-[var(--text-primary)]">{preflight.action}</p>
              {failedStep.error && (
                <p className="text-[11px] text-[var(--text-faint)]">
                  Chi tiết: {failedStep.error}
                </p>
              )}
            </div>
          )}
          {failedStep && !preflight && (
            <div
              role="alert"
              className="space-y-1 rounded-xl border border-[var(--danger)]/40 bg-[color-mix(in_srgb,var(--danger)_8%,transparent)] p-4"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--danger)]">
                Không thể import
              </p>
              <p className="text-sm text-[var(--text-primary)]">
                {GENERIC_ACTION.action}{" "}
                {failedStep.error ? `(Chi tiết: ${failedStep.error})` : ""}
              </p>
            </div>
          )}

          {/* Submit/cancel/retry action errors */}
          {(state.actionError || state.submitError) && (
            <p role="alert" className="text-xs text-[var(--danger)]">
              {state.actionError ?? state.submitError}
            </p>
          )}

          {/* Actions — cancel the active step, retry via successor, refetch after mutation */}
          <div className="flex flex-wrap items-center gap-4 pt-1">
            <button
              type="button"
              onClick={() => void handleCancel()}
              disabled={cancelDisabled}
              className="rounded-lg border border-[var(--surface-700)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-800)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              Hủy công việc
            </button>
            <p className="text-[11px] text-[var(--text-muted)]">
              {cancelDisabledReason ??
                "Yêu cầu hệ thống dừng bước đang chạy; trạng thái thật sẽ được làm mới từ máy chủ."}
            </p>

            {retryVisible && (
              <>
                <button
                  type="button"
                  onClick={() => void handleRetry()}
                  disabled={retryDisabled}
                  className="rounded-lg bg-[var(--primary-600)] px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--primary-700)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {state.phase === "submitting" ? "Đang gửi..." : "Thử lại bước thất bại"}
                </button>
                <p className="text-[11px] text-[var(--text-muted)]">
                  {retryDisabledReason ??
                    "Hệ thống tạo công việc kế tiếp (successor) cho bước thất bại/đã hủy; gửi lặp sẽ dùng lại công việc đã tạo."}
                </p>
              </>
            )}
          </div>
        </section>
      )}

      {/* Success state — real completion evidence + next action */}
      {chain?.chain_status === "completed" && (
        <section
          role="status"
          aria-label="Phân tích hoàn tất"
          className="space-y-3 rounded-2xl border border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_8%,transparent)] p-6"
        >
          <p className="text-base font-semibold text-[var(--success)]">
            ✅ Phân tích video hoàn tất
          </p>
          <p className="text-sm text-[var(--text-secondary)]">
            Cả 3 bước đã hoàn tất: nhập nguồn, tạo proxy và phát hiện cảnh
            {chain.scenes_count !== null ? ` (${chain.scenes_count} cảnh được phát hiện)` : ""}.
            Bạn có thể tiếp tục sang bước chọn đối tượng.
          </p>
          <p className="text-[11px] text-[var(--text-faint)]">
            Nguồn: {chain.source_name ?? "—"} · Proxy: {chain.proxy_artifact_id?.slice(0, 8) ?? "—"}{" "}
            · Tiến trình thật {Math.round(chain.progress)}%
          </p>
          {chain.video_item_id && (
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() =>
                  router.push(
                    `/object-gallery?project=${encodeURIComponent(projectId)}&video=${encodeURIComponent(chain.video_item_id!)}`,
                  )
                }
                className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[var(--primary-600)] px-4 text-sm font-semibold text-white transition-colors hover:bg-[var(--primary-700)]"
              >
                <Boxes aria-hidden="true" size={16} />
                Xem thư viện đối tượng
              </button>
              <p className="text-[11px] text-[var(--text-muted)]">
                Mở Thư viện đối tượng cho video vừa phân tích — mã video được truyền tường minh qua địa chỉ.
              </p>
            </div>
          )}
          <div className="flex flex-col items-start gap-1">
            <Link
              href={`/projects/${encodeURIComponent(projectId)}`}
              data-testid="import-go-project"
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--surface-700)] px-4 text-sm font-semibold text-[var(--text-primary)] transition-colors hover:bg-[var(--surface-800)]"
            >
              Về dự án (hành trình sản xuất)
            </Link>
            <p className="text-[11px] text-[var(--text-muted)]">
              Mở trang dự án — hành trình đọc trạng thái thật và chỉ mở bước kế khi đủ điều kiện.
            </p>
          </div>
        </section>
      )}

      {/* showError fallback (non-chain errors) */}
      {showError && !chain && (
        <p role="alert" className="text-xs text-[var(--danger)]">
          {showError}
        </p>
      )}
    </div>
  );
}
