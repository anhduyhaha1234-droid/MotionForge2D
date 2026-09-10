"use client";

import { useCallback, useEffect, useState } from "react";
import {
  cancelExport,
  exportContext,
  exportStatus,
  getS12ExportErrorCopy,
  preflightExport,
  retryExport,
  submitExport,
  S12_EXPORT_REASON_COPY,
  type S12ExportAspectHandling,
  type S12ExportContextResponse,
  type S12ExportPreflightBody,
  type S12ExportPreflightResponse,
  type S12ExportProfileId,
  type S12ExportRunStatus,
  type S12ExportRunStatusPayload,
} from "@/lib/s12-export-api";
import { ExportEvidence } from "./ExportEvidence";
import { ExportProgress } from "./ExportProgress";

const HELPER = "text-[11px] leading-snug text-gray-400";

const ACTIVE_STATUSES: ReadonlySet<S12ExportRunStatus> = new Set(["pending", "running", "verifying"]);

interface ExportPanelProps {
  projectId: string;
  videoItemId: string;
  workspaceId: string;
  initialRunId?: string | null;
  onRunPointerChange?: (runId: string) => void;
}

function formatEstimate(bytes: number | null): string {
  if (bytes === null) return "Chưa có estimate";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = "B";
  for (const nextUnit of units) {
    value /= 1024;
    unit = nextUnit;
    if (value < 1024 || nextUnit === "TB") break;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${unit}`;
}

function errorCopy(error: unknown): string {
  const copy = getS12ExportErrorCopy(error);
  return `${copy.message} ${copy.action}`;
}

function reasonText(reason: S12ExportPreflightResponse["reasons"][number]): string {
  return S12_EXPORT_REASON_COPY[reason].message;
}

export function ExportPanel({ projectId, videoItemId, workspaceId, initialRunId, onRunPointerChange }: ExportPanelProps) {
  const [profileId, setProfileId] = useState<S12ExportProfileId>("master-4k-h264");
  const [aspectHandling, setAspectHandling] = useState<S12ExportAspectHandling>("passthrough");
  const [context, setContext] = useState<S12ExportContextResponse | null>(null);
  const [contextLoading, setContextLoading] = useState(true);
  const [contextError, setContextError] = useState<string | null>(null);
  const [pointerHydrated, setPointerHydrated] = useState(Boolean(initialRunId));
  const [preflight, setPreflight] = useState<S12ExportPreflightResponse | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [runId, setRunId] = useState<string | null>(initialRunId ?? null);
  const [runStatus, setRunStatus] = useState<S12ExportRunStatusPayload | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<"cancel" | "retry" | null>(null);

  const invalidatePreflight = useCallback(() => {
    setPreflight(null);
    setSubmitError(null);
  }, []);

  const loadContext = useCallback(async () => {
    setContextLoading(true);
    setContextError(null);
    try {
      const result = await exportContext(projectId, videoItemId);
      setContext(result);
      if (!pointerHydrated && result.current_run) {
        setRunId(result.current_run.run_id);
        setPointerHydrated(true);
        onRunPointerChange?.(result.current_run.run_id);
      }
      if (result.profiles.some((profile) => profile.profile_id === profileId && !profile.supported)) {
        const firstSupported = result.profiles.find((profile) => profile.supported);
        if (firstSupported) setProfileId(firstSupported.profile_id);
      }
    } catch (error: unknown) {
      setContext(null);
      setContextError(errorCopy(error));
    } finally {
      setContextLoading(false);
    }
  }, [projectId, videoItemId, profileId, pointerHydrated, onRunPointerChange]);

  // The loader synchronizes this client view with server-owned export context.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadContext(); }, [loadContext]);

  const handlePreflight = async () => {
    setPreflightError(null);
    setSubmitError(null);
    if (!context?.checkpoint || !context.lock) {
      setPreflightError("Backend chưa cung cấp đủ authority cho video này; export bị khóa.");
      return;
    }
    const body: S12ExportPreflightBody = {
      video_item_id: videoItemId,
      profile_id: profileId,
      aspect_handling: aspectHandling,
      checkpoint: context.checkpoint,
      lock: context.lock,
    };
    setPreflightBusy(true);
    try {
      setPreflight(await preflightExport(projectId, body));
    } catch (error: unknown) {
      setPreflight(null);
      setPreflightError(errorCopy(error));
    } finally {
      setPreflightBusy(false);
    }
  };

  const handleSubmit = async () => {
    setSubmitError(null);
    if (!preflight?.eligible || !context?.plan || !context.checkpoint || !context.lock) {
      setSubmitError("Chỉ được submit sau khi preflight eligible và backend còn giữ context hiện hành.");
      return;
    }
    const body = {
      project_id: projectId,
      video_item_id: videoItemId,
      checkpoint_id: context.checkpoint.checkpoint_id,
      checkpoint_hash: context.checkpoint.checkpoint_hash,
      checkpoint_revision: context.checkpoint.checkpoint_revision,
      manifest_id: context.lock.manifest_id,
      manifest_hash: context.lock.manifest_hash,
      manifest_generation: context.lock.source_generation,
      profile_id: preflight.profile.profile_id,
      plan_id: context.plan.plan_id,
      plan_hash: context.plan.plan_hash,
      frame_count: context.plan.frame_count,
      context_revision: context.context_revision,
    };

    setSubmitBusy(true);
    try {
      const result = await submitExport(body, workspaceId);
      setRunStatus(null);
      setStatusError(null);
      setRunId(result.run_id);
      onRunPointerChange?.(result.run_id);
      await loadContext();
    } catch (error: unknown) {
      setSubmitError(errorCopy(error));
    } finally {
      setSubmitBusy(false);
    }
  };

  const fetchStatus = useCallback(async (targetRunId: string): Promise<S12ExportRunStatusPayload | null> => {
    try {
      const result = await exportStatus(targetRunId, workspaceId, projectId);
      setRunStatus(result);
      setStatusError(null);
      return result;
    } catch (error: unknown) {
      setStatusError(errorCopy(error));
      return null;
    }
  }, [projectId, workspaceId]);

  useEffect(() => {
    if (!runId) return;

    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      if (disposed) return;
      setStatusLoading(true);
      const result = await fetchStatus(runId);
      if (disposed) return;
      setStatusLoading(false);
      if (!result || ACTIVE_STATUSES.has(result.status)) {
        timer = setTimeout(() => void poll(), 2000);
      }
    };

    void poll();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
    };
  }, [fetchStatus, runId]);

  const handleCancel = async () => {
    if (!runId || !runStatus || !ACTIVE_STATUSES.has(runStatus.status) || actionBusy !== null) return;
    setActionBusy("cancel");
    setStatusError(null);
    try {
      await cancelExport(runId, workspaceId, projectId);
      await fetchStatus(runId);
    } catch (error: unknown) {
      setStatusError(errorCopy(error));
    } finally {
      setActionBusy(null);
    }
  };

  const handleRetry = async () => {
    if (!runStatus || (runStatus.status !== "failed" && runStatus.status !== "cancelled") || actionBusy !== null) return;
    setActionBusy("retry");
    setStatusError(null);
    try {
      const result = await retryExport(runStatus.run_id, workspaceId, projectId);
      setRunStatus(null);
      setRunId(result.run_id);
      onRunPointerChange?.(result.run_id);
      await loadContext();
    } catch (error: unknown) {
      setStatusError(errorCopy(error));
    } finally {
      setActionBusy(null);
    }
  };

  const canSubmit = Boolean(preflight?.eligible && context?.plan && !preflightBusy && !submitBusy);
  const canCancel = Boolean(runStatus && ACTIVE_STATUSES.has(runStatus.status));
  const canRetry = Boolean(runStatus && (runStatus.status === "failed" || runStatus.status === "cancelled"));

  return (
    <section className="min-w-0 w-full space-y-4 overflow-hidden text-gray-100" data-testid="export-panel">
      <header className="min-w-0">
        <h1 className="text-base font-semibold">Export video</h1>
        <p className={HELPER}>Project <span className="break-all font-mono">{projectId}</span> · video <span className="break-all font-mono">{videoItemId}</span> · workspace <span className="break-all font-mono">{workspaceId}</span></p>
      </header>

      <section className="min-w-0 rounded border border-gray-700 bg-gray-900/40 p-3 sm:p-4" data-testid="export-context">
        <h2 className="text-sm font-semibold text-gray-100">Project/video context</h2>
        {contextLoading && <p className="mt-2 text-xs text-gray-300" aria-busy="true">Đang tải context server…</p>}
        {contextError && <p className="mt-2 break-words text-xs text-red-300" role="alert">{contextError}</p>}
        {context && <><p className="mt-2 break-words text-xs text-gray-300">{context.project_name ?? projectId} · {context.video_title ?? videoItemId} · {context.video_width ?? "?"}×{context.video_height ?? "?"} · {context.video_status ?? "unknown"}</p>{context.reasons.length > 0 && <ul className="mt-2 space-y-1" data-testid="export-context-reasons">{context.reasons.map((reason) => <li key={reason} className="break-words text-xs text-red-300"><span className="font-mono">{reason}</span> · {reasonText(reason)}</li>)}</ul>}</>}
        <p className={HELPER}>Authority pins, plan, timing, capability and server paths never come from typed UI fields.</p>
      </section>

      <section className="min-w-0 rounded border border-gray-700 bg-gray-900/40 p-3 sm:p-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-gray-100">1. Preflight export</h2>
          <p className={HELPER}>Kiểm tra readiness, source và pins do backend cung cấp.</p>
        </div>

        <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex min-w-0 flex-col gap-1 text-xs text-gray-300">
            Profile cố định
            <select
              value={profileId}
              onChange={(event) => { setProfileId(event.target.value as S12ExportProfileId); invalidatePreflight(); }}
              className="min-w-0 rounded border border-gray-600 bg-gray-800 px-2 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              data-testid="export-profile"
            >
              {(context?.profiles ?? []).map((profile) => <option key={profile.profile_id} value={profile.profile_id} disabled={!profile.supported}>{profile.profile_id} · {profile.width}×{profile.height} · {profile.codec}{profile.supported ? "" : " · unavailable"}</option>)}
            </select>
            <span className={HELPER}>Chỉ chọn profile được capability probe server báo hỗ trợ.</span>
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-xs text-gray-300">
            Aspect handling
            <select
              value={aspectHandling}
              onChange={(event) => { setAspectHandling(event.target.value as S12ExportAspectHandling); invalidatePreflight(); }}
              className="min-w-0 rounded border border-gray-600 bg-gray-800 px-2 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              data-testid="export-aspect"
            >
              <option value="passthrough">Passthrough</option>
              <option value="letterbox">Letterbox</option>
              <option value="fail_closed">Fail closed</option>
            </select>
            <span className={HELPER}>Không stretch/crop âm thầm; letterbox giữ hình học.</span>
          </label>
        </div>

        <p className="mt-4 break-words rounded bg-gray-800 px-3 py-2 text-xs text-gray-300" data-testid="export-server-authority">Authority pins and the render plan are resolved by the server for this project/video.</p>

        <div className="mt-4 flex flex-col items-start gap-1">
          <button
            type="button"
            onClick={() => void handlePreflight()}
            disabled={preflightBusy || contextLoading || !context?.checkpoint || !context.lock}
            className={`min-h-10 rounded px-4 py-2 text-sm font-semibold ${preflightBusy ? "cursor-not-allowed bg-gray-700 text-gray-400" : "bg-indigo-600 text-white hover:bg-indigo-500"}`}
            data-testid="export-preflight"
          >
            {preflightBusy ? "Đang preflight…" : "Chạy preflight"}
          </button>
          <p className={HELPER}>Backend trả eligible, estimate, reasons và checks.</p>
        </div>
        {preflightError && <p className="mt-2 break-words text-xs text-red-300" role="alert">{preflightError}</p>}

        {preflight && (
          <div className="mt-4 min-w-0 rounded border border-gray-800 bg-gray-950/40 p-3" data-testid="export-preflight-result">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="text-xs font-semibold text-gray-200">Kết quả preflight</h3>
                <p className={HELPER}>Contract {preflight.contract_version} · readiness policy {preflight.readiness_policy}</p>
              </div>
              <span className={`rounded px-2 py-1 text-xs font-medium ${preflight.eligible ? "bg-emerald-900/30 text-emerald-300" : "bg-red-900/30 text-red-300"}`}>
                {preflight.eligible ? "ELIGIBLE" : "BLOCKED"}
              </span>
            </div>
            <div className="mt-3 grid min-w-0 grid-cols-1 gap-2 text-xs sm:grid-cols-2">
              <p className="min-w-0 break-words rounded bg-gray-800 px-3 py-2">Source kind: <span className="font-medium text-gray-100">{preflight.source_kind}</span> · {preflight.source_width ?? "?"}×{preflight.source_height ?? "?"}</p>
              <p className="min-w-0 break-words rounded bg-gray-800 px-3 py-2">Estimate: <span className="font-medium text-gray-100">{formatEstimate(preflight.estimate_bytes)}</span></p>
              <p className="min-w-0 break-words rounded bg-gray-800 px-3 py-2">Readiness: <span className="font-medium text-gray-100">{preflight.readiness_status}</span></p>
              <p className="min-w-0 break-words rounded bg-gray-800 px-3 py-2">Basis: {preflight.estimate_basis}</p>
            </div>
            <div className="mt-3 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="min-w-0">
                <p className="text-xs font-medium text-gray-300">Reasons</p>
                {preflight.reasons.length === 0 ? <p className={HELPER}>Backend không trả reason code.</p> : <ul className="mt-1 space-y-1">{preflight.reasons.map((reason) => <li key={reason} className="break-words text-xs text-gray-300"><span className="font-mono text-gray-400">{reason}</span> · {reasonText(reason)}</li>)}</ul>}
              </div>
              <div className="min-w-0">
                <p className="text-xs font-medium text-gray-300">Checks</p>
                <ul className="mt-1 space-y-1">{preflight.checks.length === 0 ? <li className={HELPER}>Backend không trả check.</li> : preflight.checks.map((check) => <li key={`${check.name}-${check.reason}`} className="break-words text-xs text-gray-300"><span className={check.passed ? "text-emerald-300" : "text-red-300"}>{check.passed ? "PASS" : "FAIL"}</span> · {check.name} · {check.detail}</li>)}</ul>
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="min-w-0 rounded border border-gray-700 bg-gray-900/40 p-3 sm:p-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-gray-100">2. Submit export</h2>
          <p className={HELPER}>Submit dùng context hiện hành do backend sở hữu; không cần nhập hash, frame/fps hoặc filesystem path.</p>
        </div>
        <div className="mt-3 rounded bg-gray-800 px-3 py-2"><p className="break-words text-xs text-gray-300">{context?.plan ? `Server plan ${context.plan.plan_id.slice(0, 12)}… · ${context.plan.frame_count} frames` : "Chưa có plan authority"}</p><p className={HELPER}>Các đường dẫn source/chunk/scratch/output do backend tự dẫn xuất.</p></div>

        <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <p className="break-words text-xs text-gray-400">Plan, frame count and fps are resolved from the current backend Full Apply authority.</p>
        </div>
        <div className="mt-3 grid min-w-0 grid-cols-1 gap-3">
          <p className="break-words text-xs text-gray-400">Source, chunk, scratch and output paths are derived under the managed root by the backend.</p>
        </div>
        <div className="mt-4 flex flex-col items-start gap-1">
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!canSubmit}
            className={`min-h-10 rounded px-4 py-2 text-sm font-semibold ${canSubmit ? "bg-emerald-600 text-white hover:bg-emerald-500" : "cursor-not-allowed bg-gray-700 text-gray-400"}`}
            data-testid="export-submit"
          >
            {submitBusy ? "Đang submit…" : "Submit export"}
          </button>
          <p className={HELPER}>{canSubmit ? "Gửi export sau khi preflight eligible." : "Cần context authority và preflight eligible."}</p>
        </div>
        {submitError && <p className="mt-2 break-words text-xs text-red-300" role="alert">{submitError}</p>}
      </section>

      {runId && (
        <p data-testid="export-run-id" className="mt-3 break-all font-mono text-[11px] text-gray-400">
          run {runId}
        </p>
      )}

      {runId && (
        <ExportProgress
          runId={runId}
          data={runStatus}
          loading={statusLoading}
          error={statusError}
          actionBusy={actionBusy}
          canCancel={canCancel}
          canRetry={canRetry}
          onCancel={() => void handleCancel()}
          onRetry={() => void handleRetry()}
        />
      )}

      {runStatus?.status === "completed" && (
        <ExportEvidence data={runStatus} workspaceId={workspaceId} projectId={projectId} />
      )}
    </section>
  );
}
