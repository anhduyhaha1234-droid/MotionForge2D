"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  cancelExport,
  exportStatus,
  getS12ExportErrorCopy,
  preflightExport,
  retryExport,
  submitExport,
  S12_EXPORT_REASON_COPY,
  type S12ExportAspectHandling,
  type S12ExportCheckpointPin,
  type S12ExportLockPin,
  type S12ExportPreflightBody,
  type S12ExportPreflightResponse,
  type S12ExportProfileId,
  type S12ExportRunStatus,
  type S12ExportRunStatusPayload,
  type S12ExportSubmitBody,
} from "@/lib/s12-export-api";
import { ExportEvidence } from "./ExportEvidence";
import { ExportProgress } from "./ExportProgress";

const HELPER = "text-[11px] leading-snug text-gray-400";

const FROZEN_PROFILES: ReadonlyArray<{
  id: S12ExportProfileId;
  label: string;
  detail: string;
}> = [
  { id: "master-4k-h264", label: "Master 4K · H.264", detail: "3840×2160 · h264" },
  { id: "master-4k-hevc", label: "Master 4K · HEVC", detail: "3840×2160 · hevc" },
  { id: "preview-1080p-h264", label: "Preview 1080p · H.264", detail: "1920×1080 · h264" },
];

const ACTIVE_STATUSES: ReadonlySet<S12ExportRunStatus> = new Set(["pending", "running", "verifying"]);

interface ExportPanelProps {
  projectId: string;
  videoItemId: string;
  workspaceId: string;
  initialRunId?: string | null;
}

interface CheckedPins {
  checkpoint: S12ExportCheckpointPin;
  lock: S12ExportLockPin;
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

function parseInteger(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function parsePositiveNumber(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function parseChunkConfig(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

function errorCopy(error: unknown): string {
  const copy = getS12ExportErrorCopy(error);
  return `${copy.message} ${copy.action}`;
}

function reasonText(reason: S12ExportPreflightResponse["reasons"][number]): string {
  return S12_EXPORT_REASON_COPY[reason].message;
}

function clearOrDash(value: string): string {
  return value.trim() || "—";
}

export function ExportPanel({ projectId, videoItemId, workspaceId, initialRunId }: ExportPanelProps) {
  const [profileId, setProfileId] = useState<S12ExportProfileId>("master-4k-h264");
  const [aspectHandling, setAspectHandling] = useState<S12ExportAspectHandling>("passthrough");
  const [checkpointId, setCheckpointId] = useState("");
  const [checkpointHash, setCheckpointHash] = useState("");
  const [checkpointRevision, setCheckpointRevision] = useState("");
  const [manifestId, setManifestId] = useState("");
  const [manifestHash, setManifestHash] = useState("");
  const [sourceGeneration, setSourceGeneration] = useState("");

  const [preflight, setPreflight] = useState<S12ExportPreflightResponse | null>(null);
  const [checkedPins, setCheckedPins] = useState<CheckedPins | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);

  const [planId, setPlanId] = useState("");
  const [planHash, setPlanHash] = useState("");
  const [frameCount, setFrameCount] = useState("");
  const [fps, setFps] = useState("30");
  const [sourcePath, setSourcePath] = useState("");
  const [chunkDir, setChunkDir] = useState("");
  const [scratchDir, setScratchDir] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [chunkConfig, setChunkConfig] = useState('{"chunk_frames": 120}');
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [runId, setRunId] = useState<string | null>(initialRunId ?? null);
  const [runStatus, setRunStatus] = useState<S12ExportRunStatusPayload | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<"cancel" | "retry" | null>(null);

  const invalidatePreflight = useCallback(() => {
    setPreflight(null);
    setCheckedPins(null);
    setSubmitError(null);
  }, []);

  const handlePreflight = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPreflightError(null);
    setSubmitError(null);

    const revision = parseInteger(checkpointRevision);
    if (revision === null) {
      setPreflightError("Checkpoint revision phải là số nguyên không âm.");
      return;
    }
    if (!checkpointId.trim() || !checkpointHash.trim() || !manifestId.trim() || !manifestHash.trim() || !sourceGeneration.trim()) {
      setPreflightError("Cần nhập đủ checkpoint pin và lock pin trước khi chạy preflight.");
      return;
    }

    const body: S12ExportPreflightBody = {
      video_item_id: videoItemId,
      profile_id: profileId,
      aspect_handling: aspectHandling,
      checkpoint: {
        checkpoint_id: checkpointId.trim(),
        checkpoint_hash: checkpointHash.trim(),
        checkpoint_revision: revision,
      },
      lock: {
        manifest_id: manifestId.trim(),
        manifest_hash: manifestHash.trim(),
        source_generation: sourceGeneration.trim(),
      },
    };

    setPreflightBusy(true);
    try {
      const result = await preflightExport(projectId, body);
      setPreflight(result);
      setCheckedPins(result.eligible ? { checkpoint: body.checkpoint, lock: body.lock } : null);
    } catch (error: unknown) {
      setPreflight(null);
      setCheckedPins(null);
      setPreflightError(errorCopy(error));
    } finally {
      setPreflightBusy(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitError(null);
    if (!preflight?.eligible || !checkedPins) {
      setSubmitError("Chỉ được submit sau khi preflight trả eligible và các pin đã được kiểm tra.");
      return;
    }

    const parsedFrameCount = parseInteger(frameCount);
    const parsedFps = parsePositiveNumber(fps);
    const parsedChunkConfig = parseChunkConfig(chunkConfig);
    if (parsedFrameCount === null || parsedFrameCount <= 0) {
      setSubmitError("frame_count phải là số nguyên dương.");
      return;
    }
    if (parsedFps === null) {
      setSubmitError("fps phải là một số dương.");
      return;
    }
    if (!parsedChunkConfig) {
      setSubmitError("chunk_config phải là một JSON object hợp lệ.");
      return;
    }
    if (!planId.trim() || !planHash.trim() || !sourcePath.trim() || !chunkDir.trim() || !scratchDir.trim() || !outputPath.trim()) {
      setSubmitError("Cần nhập đủ plan, frame/fps và các path export.");
      return;
    }

    const body: S12ExportSubmitBody = {
      project_id: projectId,
      video_item_id: videoItemId,
      checkpoint_id: checkedPins.checkpoint.checkpoint_id,
      checkpoint_hash: checkedPins.checkpoint.checkpoint_hash,
      checkpoint_revision: checkedPins.checkpoint.checkpoint_revision,
      manifest_id: checkedPins.lock.manifest_id,
      manifest_hash: checkedPins.lock.manifest_hash,
      manifest_generation: checkedPins.lock.source_generation,
      profile_id: preflight.profile.profile_id,
      plan_id: planId.trim(),
      plan_hash: planHash.trim(),
      frame_count: parsedFrameCount,
      chunk_config: parsedChunkConfig,
      source_path: sourcePath.trim(),
      fps: parsedFps,
      chunk_dir: chunkDir.trim(),
      scratch_dir: scratchDir.trim(),
      output_path: outputPath.trim(),
    };

    setSubmitBusy(true);
    try {
      const result = await submitExport(body, workspaceId);
      setRunStatus(null);
      setStatusError(null);
      setRunId(result.run_id);
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
    } catch (error: unknown) {
      setStatusError(errorCopy(error));
    } finally {
      setActionBusy(null);
    }
  };

  const canSubmit = Boolean(preflight?.eligible && checkedPins && !preflightBusy && !submitBusy);
  const canCancel = Boolean(runStatus && ACTIVE_STATUSES.has(runStatus.status));
  const canRetry = Boolean(runStatus && (runStatus.status === "failed" || runStatus.status === "cancelled"));

  return (
    <section className="min-w-0 w-full space-y-4 overflow-hidden text-gray-100" data-testid="export-panel">
      <header className="min-w-0">
        <h1 className="text-base font-semibold">Export video</h1>
        <p className={HELPER}>Project <span className="break-all font-mono">{projectId}</span> · video <span className="break-all font-mono">{videoItemId}</span> · workspace <span className="break-all font-mono">{workspaceId}</span></p>
      </header>

      <form onSubmit={(event) => void handlePreflight(event)} className="min-w-0 rounded border border-gray-700 bg-gray-900/40 p-3 sm:p-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-gray-100">1. Preflight export</h2>
          <p className={HELPER}>Kiểm tra readiness, source và các pin trước khi cho phép submit.</p>
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
              {FROZEN_PROFILES.map((profile) => <option key={profile.id} value={profile.id}>{profile.label} · {profile.detail}</option>)}
            </select>
            <span className={HELPER}>Chỉ dùng 1 trong 3 profile đã đóng băng của export contract.</span>
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
            <span className={HELPER}>Chính sách aspect được gửi nguyên dạng cho backend preflight.</span>
          </label>
        </div>

        <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <fieldset className="min-w-0 rounded border border-gray-800 p-3">
            <legend className="px-1 text-xs font-medium text-gray-300">Checkpoint lock pin</legend>
            <div className="space-y-2">
              <label className="block min-w-0 text-xs text-gray-400">checkpoint_id<input value={checkpointId} onChange={(event) => { setCheckpointId(event.target.value); invalidatePreflight(); }} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 text-xs text-gray-100" /></label>
              <label className="block min-w-0 text-xs text-gray-400">checkpoint_hash<input value={checkpointHash} onChange={(event) => { setCheckpointHash(event.target.value); invalidatePreflight(); }} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 font-mono text-xs text-gray-100" /></label>
              <label className="block min-w-0 text-xs text-gray-400">checkpoint_revision<input inputMode="numeric" value={checkpointRevision} onChange={(event) => { setCheckpointRevision(event.target.value); invalidatePreflight(); }} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 text-xs text-gray-100" /></label>
            </div>
            <p className={`mt-2 ${HELPER}`}>Pin đúng id, hash và revision; sửa pin sẽ làm mất kết quả preflight cũ.</p>
          </fieldset>
          <fieldset className="min-w-0 rounded border border-gray-800 p-3">
            <legend className="px-1 text-xs font-medium text-gray-300">Structural-lock manifest</legend>
            <div className="space-y-2">
              <label className="block min-w-0 text-xs text-gray-400">manifest_id<input value={manifestId} onChange={(event) => { setManifestId(event.target.value); invalidatePreflight(); }} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 text-xs text-gray-100" /></label>
              <label className="block min-w-0 text-xs text-gray-400">manifest_hash<input value={manifestHash} onChange={(event) => { setManifestHash(event.target.value); invalidatePreflight(); }} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 font-mono text-xs text-gray-100" /></label>
              <label className="block min-w-0 text-xs text-gray-400">source_generation<input value={sourceGeneration} onChange={(event) => { setSourceGeneration(event.target.value); invalidatePreflight(); }} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 text-xs text-gray-100" /></label>
            </div>
            <p className={`mt-2 ${HELPER}`}>Lock pin phải cùng video/project và được backend xác nhận.</p>
          </fieldset>
        </div>

        <div className="mt-4 flex flex-col items-start gap-1">
          <button
            type="submit"
            disabled={preflightBusy}
            className={`min-h-10 rounded px-4 py-2 text-sm font-semibold ${preflightBusy ? "cursor-not-allowed bg-gray-700 text-gray-400" : "bg-indigo-600 text-white hover:bg-indigo-500"}`}
            data-testid="export-preflight"
          >
            {preflightBusy ? "Đang preflight…" : "Chạy preflight"}
          </button>
          <p className={HELPER}>Gửi các profile/aspect/pin hiện tại lên backend để lấy eligible, estimate và checks.</p>
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
            {checkedPins && (
              <p className={`mt-3 ${HELPER}`} data-testid="export-checked-pins">
                Đã giữ nguyên pin được check cho submit: checkpoint <span className="break-all font-mono">{checkedPins.checkpoint.checkpoint_id}</span> · manifest <span className="break-all font-mono">{checkedPins.lock.manifest_id}</span>.
              </p>
            )}
          </div>
        )}
      </form>

      <form onSubmit={(event) => void handleSubmit(event)} className="min-w-0 rounded border border-gray-700 bg-gray-900/40 p-3 sm:p-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-gray-100">2. Submit export</h2>
          <p className={HELPER}>Submit dùng đúng các pin đã checked ở preflight và các tham số render do bạn cung cấp.</p>
        </div>
        <div className="mt-3 rounded bg-gray-800 px-3 py-2">
          <p className="break-words text-xs text-gray-300">{checkedPins ? "Pins đã checked và sẽ được reuse khi submit." : "Chưa có pins checked; submit đang bị khóa."}</p>
          {checkedPins && <p className={HELPER}>checkpoint {clearOrDash(checkedPins.checkpoint.checkpoint_id)} · manifest {clearOrDash(checkedPins.lock.manifest_id)}</p>}
        </div>

        <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block min-w-0 text-xs text-gray-400">plan_id<input value={planId} onChange={(event) => setPlanId(event.target.value)} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 text-xs text-gray-100" /></label>
          <label className="block min-w-0 text-xs text-gray-400">plan_hash<input value={planHash} onChange={(event) => setPlanHash(event.target.value)} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 font-mono text-xs text-gray-100" /></label>
          <label className="block min-w-0 text-xs text-gray-400">frame_count<input inputMode="numeric" value={frameCount} onChange={(event) => setFrameCount(event.target.value)} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 text-xs text-gray-100" /></label>
          <label className="block min-w-0 text-xs text-gray-400">fps<input inputMode="decimal" value={fps} onChange={(event) => setFps(event.target.value)} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 text-xs text-gray-100" /></label>
        </div>
        <div className="mt-3 grid min-w-0 grid-cols-1 gap-3">
          <label className="block min-w-0 text-xs text-gray-400">source_path<input value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 font-mono text-xs text-gray-100" /></label>
          <label className="block min-w-0 text-xs text-gray-400">chunk_dir<input value={chunkDir} onChange={(event) => setChunkDir(event.target.value)} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 font-mono text-xs text-gray-100" /></label>
          <label className="block min-w-0 text-xs text-gray-400">scratch_dir<input value={scratchDir} onChange={(event) => setScratchDir(event.target.value)} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 font-mono text-xs text-gray-100" /></label>
          <label className="block min-w-0 text-xs text-gray-400">output_path<input value={outputPath} onChange={(event) => setOutputPath(event.target.value)} className="mt-1 min-w-0 w-full rounded border border-gray-600 bg-gray-800 px-2 py-2 font-mono text-xs text-gray-100" /></label>
          <label className="block min-w-0 text-xs text-gray-400">chunk_config · JSON object<textarea value={chunkConfig} onChange={(event) => setChunkConfig(event.target.value)} rows={3} spellCheck={false} className="mt-1 min-w-0 w-full resize-y rounded border border-gray-600 bg-gray-800 px-2 py-2 font-mono text-xs text-gray-100" /></label>
        </div>
        <div className="mt-4 flex flex-col items-start gap-1">
          <button
            type="submit"
            disabled={!canSubmit}
            className={`min-h-10 rounded px-4 py-2 text-sm font-semibold ${canSubmit ? "bg-emerald-600 text-white hover:bg-emerald-500" : "cursor-not-allowed bg-gray-700 text-gray-400"}`}
            data-testid="export-submit"
          >
            {submitBusy ? "Đang submit…" : "Submit export"}
          </button>
          <p className={HELPER}>{canSubmit ? "Gửi export với pins checked, plan, frame_count, fps, paths và chunk_config hiện tại." : "Cần preflight eligible và đủ trường submit hợp lệ trước khi gửi."}</p>
        </div>
        {submitError && <p className="mt-2 break-words text-xs text-red-300" role="alert">{submitError}</p>}
      </form>

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

      {runStatus?.status === "completed" && <ExportEvidence data={runStatus} />}
    </section>
  );
}
