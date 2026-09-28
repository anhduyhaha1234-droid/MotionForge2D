"use client";

/**
 * S10-T04B — /apply route (Project Shell Apply flow).
 *
 * Vietnamese Project Shell flow exposes Demo-approved Apply, progress,
 * cancel/retry/resume and structural evidence truthfully.
 *
 * Data truth: all numbers come from GET /api/v2/full-apply/{run_id} and
 * POST /api/v2/full-apply/{run_id}/structural-compare — no synthetic
 * local completion.  Persist last run_id to localStorage + URL so reload
 * keeps truth.
 *
 * Dark theme: every button has VN helper text directly below (text-gray-400, 11px+).
 * Responsive: flex-wrap, no horizontal overflow at 390px.
 */

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError, buildExportHref, buildReviewHref } from "@/lib/api";
import { ApplyCard } from "@/features/apply/ApplyCard";
import { ApplyProgress } from "@/features/apply/ApplyProgress";
import { ApplyEvidenceLinks, type StructuralEvidenceView } from "@/features/apply/ApplyEvidenceLinks";
import { useApplyStatus } from "@/features/apply/useApplyStatus";

const HELPER = "text-[11px] leading-snug text-gray-400";
const STORAGE_RUN_ID = "s10:apply:lastRunId";
const STORAGE_PROJECT_ID = "s10:apply:lastProjectId";

function readStorage(): { runId: string | null; projectId: string | null } {
  if (typeof window === "undefined") return { runId: null, projectId: null };
  try {
    return {
      runId: localStorage.getItem(STORAGE_RUN_ID),
      projectId: localStorage.getItem(STORAGE_PROJECT_ID),
    };
  } catch {
    return { runId: null, projectId: null };
  }
}

function writeStorage(runId: string | null, projectId: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (runId) localStorage.setItem(STORAGE_RUN_ID, runId);
    else localStorage.removeItem(STORAGE_RUN_ID);
    if (projectId) localStorage.setItem(STORAGE_PROJECT_ID, projectId);
    else localStorage.removeItem(STORAGE_PROJECT_ID);
  } catch {
    // ignore
  }
}

export default function ApplyPage() {
  return (
    <Suspense fallback={<div className="min-h-full p-4 sm:p-6" aria-busy="true" />}>
      <ApplyRoute />
    </Suspense>
  );
}

function ApplyRoute() {
  const searchParams = useSearchParams();

  const urlRunId = searchParams.get("run_id");
  const urlProject = searchParams.get("project");

  const [runId, setRunId] = useState<string | null>(() => urlRunId ?? readStorage().runId);
  const [projectIdForStatus, setProjectIdForStatus] = useState<string | null>(() => urlProject ?? readStorage().projectId);
  const [evidence, setEvidence] = useState<StructuralEvidenceView | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  // URL search-params are the source of truth for deep-links and browser
  // navigation. When they change (back/forward, manual URL edit, share link),
  // adjust state during render — React's documented derived-state pattern —
  // instead of calling setState inside an effect (no cascading renders, no
  // suppressed lint rules). A missing param keeps the current selection (persist).
  const [prevUrlRunId, setPrevUrlRunId] = useState<string | null>(urlRunId);
  const [prevUrlProject, setPrevUrlProject] = useState<string | null>(urlProject);
  if (urlRunId !== prevUrlRunId || urlProject !== prevUrlProject) {
    setPrevUrlRunId(urlRunId);
    setPrevUrlProject(urlProject);
    if (urlRunId) setRunId(urlRunId);
    if (urlProject) setProjectIdForStatus(urlProject);
  }

  // Mirror the current selection to localStorage so a bare reload (no URL
  // params) restores the last run. Storage write only — never setState,
  // never rewrites the URL (back/forward must not fight a replace loop).
  useEffect(() => {
    writeStorage(runId, projectIdForStatus);
  }, [runId, projectIdForStatus]);

  const status = useApplyStatus({ runId, projectId: projectIdForStatus ?? undefined });

  const canCancel = status.data?.status === "pending" || status.data?.status === "running" || status.data?.status === "verifying";
  const canRetry = status.data?.status === "failed" || status.data?.status === "cancelled";
  const canResume = status.data?.status === "failed" || status.data?.status === "pending" || status.data?.status === "running" || status.data?.status === "verifying";
  const isTerminalCompleted = status.data?.status === "completed";

  // User actions own the URL: when a new run is created/selected the handler
  // writes run_id/project into the URL explicitly (no effect-driven replace,
  // so back/forward never fights a replace loop). window.history.replaceState
  // is the documented Next.js (App Router) shallow-routing primitive and it
  // integrates with the router: useSearchParams picks up the change on the
  // SAME tick — a synchronous URL update immune to the async router.replace
  // transition race observed with the 1500ms status poller (retry URL stale).
  const syncUrlToRun = useCallback(
    (nextRunId: string, nextProjectId: string | null) => {
      if (!nextRunId) return;
      const params = new URLSearchParams(searchParams.toString());
      params.set("run_id", nextRunId);
      if (nextProjectId) params.set("project", nextProjectId);
      else params.delete("project");
      const url = `/apply?${params.toString()}`;
      window.history.replaceState(window.history.state, "", url);
    },
    [searchParams],
  );

  const doCancel = useCallback(async () => {
    if (!runId) return;
    setActionBusy("cancel");
    setActionError(null);
    try {
      await api.cancelS10FullApply(runId, "default", projectIdForStatus ?? undefined);
      await status.refresh();
    } catch (err: unknown) {
      setActionError(err instanceof ApiError ? err.detailText() || `Lỗi ${err.status}` : err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  }, [runId, projectIdForStatus, status]);

  const doRetry = useCallback(async () => {
    if (!runId) return;
    setActionBusy("retry");
    setActionError(null);
    try {
      const res = await api.retryS10FullApply(runId, "default", projectIdForStatus ?? undefined);
      setRunId(res.run_id);
      setProjectIdForStatus(projectIdForStatus);
      syncUrlToRun(res.run_id, projectIdForStatus);
      setEvidence(null);
      setEvidenceError(null);
    } catch (err: unknown) {
      setActionError(err instanceof ApiError ? err.detailText() || `Lỗi ${err.status}` : err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  }, [runId, projectIdForStatus, syncUrlToRun]);

  const doResume = useCallback(async () => {
    if (!runId) return;
    setActionBusy("resume");
    setActionError(null);
    try {
      await api.resumeS10FullApply(runId, "default", projectIdForStatus ?? undefined);
      await status.refresh();
    } catch (err: unknown) {
      setActionError(err instanceof ApiError ? err.detailText() || `Lỗi ${err.status}` : err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  }, [runId, projectIdForStatus, status]);

  const fetchEvidence = useCallback(async () => {
    if (!runId || !status.data) return;
    setEvidenceLoading(true);
    setEvidenceError(null);
    try {
      // Structural gate is server-derived: client sends only run identity as intent;
      // every metric/cut/shot/annotation is computed server-side from the pinned
      // publication + StructuralLockManifest + stored evidence (hash-bound).
      // The body is an empty hint (extra=allow) — server ignores all metrics.
      const body: Record<string, unknown> = {};
      const res = await api.structuralCompareS10(runId, body, "default", projectIdForStatus ?? undefined);
      setEvidence(res as unknown as StructuralEvidenceView);
    } catch (err: unknown) {
      setEvidenceError(err instanceof ApiError ? err.detailText() || `Lỗi ${err.status}` : err instanceof Error ? err.message : String(err));
    } finally {
      setEvidenceLoading(false);
    }
  }, [runId, projectIdForStatus, status.data]);

  const handleApplySuccess = useCallback(
    (newRunId: string, pid: string) => {
      setRunId(newRunId);
      setProjectIdForStatus(pid);
      syncUrlToRun(newRunId, pid);
      setEvidence(null);
      setEvidenceError(null);
      setActionError(null);
    },
    [syncUrlToRun],
  );

  const staleNotice = useMemo(() => {
    if (status.errorStatus === 409) return "Xung đột (409) — checkpoint đã cũ hoặc truyền nhầm revision/hash. Hãy nạp lại và chọn checkpoint mới nhất.";
    if (status.errorStatus === 404) return "Không tìm thấy run — mã run_id hoặc project không khớp.";
    if (status.errorStatus === 422)
      return "Yêu cầu bị từ chối (422) — checkpoint cần duyệt lại (REAPPROVAL_REQUIRED) hoặc authority không hợp lệ. Hãy nạp lại và chọn checkpoint v2 mới nhất.";
    if (status.errorStatus && status.errorStatus >= 500)
      return `Lỗi máy chủ (${status.errorStatus}) — kiểm tra lại checkpoint/authority; xem chi tiết bên dưới.`;
    return null;
  }, [status.errorStatus]);

  return (
    <div className="min-h-full p-4 sm:p-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <header className="flex flex-col gap-1">
          <h1 className="text-lg font-semibold text-gray-100" data-testid="apply-page-title">
            Áp dụng toàn bộ video
          </h1>
          <p className={HELPER}>Luồng Apply sau khi duyệt Demo — tiến độ và bằng chứng lấy trực tiếp từ backend.</p>
          {runId && (
            <p className="break-all font-mono text-xs text-gray-400" data-testid="apply-page-run-id">
              run_id hiện tại: {runId} · project {projectIdForStatus ?? "—"}
            </p>
          )}
        </header>

        <ApplyCard onApplySuccess={handleApplySuccess} initialProjectId={urlProject} />

        {/* ── Status / progress (backend truth, survives reload) ───────── */}
        {status.phase === "loading" && (
          <div className="rounded border border-gray-700 p-4" aria-busy="true" data-testid="apply-status-loading">
            <p className="text-sm text-gray-300">Đang tải trạng thái Apply từ backend…</p>
            <p className={HELPER}>Đọc GET /api/v2/full-apply/{"{run_id}"} — không dùng dữ liệu giả.</p>
          </div>
        )}

        {status.phase === "error" && (
          <div className="rounded border border-red-700 bg-red-900/20 p-4" role="alert" data-testid="apply-status-error">
            <p className="text-sm text-red-300">{status.error}</p>
            {staleNotice && <p className="mt-1 text-xs text-amber-300">{staleNotice}</p>}
            <div className="mt-2 flex flex-col items-start gap-1">
              <button type="button" onClick={() => void status.refresh()} className="rounded bg-red-700 px-3 py-1.5 text-xs text-white hover:bg-red-600" data-testid="apply-status-retry">
                Thử lại
              </button>
              <p className={HELPER}>Tải lại trạng thái run hiện tại từ backend.</p>
            </div>
          </div>
        )}

        {status.phase === "empty" && !runId && (
          <div className="rounded border border-dashed border-gray-700 p-6 text-center" data-testid="apply-empty">
            <p className="text-sm text-gray-400">Chưa có lần Apply nào — hãy tạo một lần Apply ở trên.</p>
            <p className={HELPER}>Sau khi Apply, tiến trình và bằng chứng sẽ tự cập nhật từ backend.</p>
          </div>
        )}

        {(status.phase === "ready" || (status.phase === "error" && status.data)) && status.data && (
          <ApplyProgress data={status.data} progress={status.progress} currentChunk={status.currentChunk} isPolling={status.isPolling} onRefresh={() => void status.refresh()} />
        )}

        {/* ── Actions: cancel / retry / resume (backend truth, survive reload) ─ */}
        {status.data && (
          <div className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="apply-actions">
            <h3 className="text-sm font-medium text-gray-100">Điều khiển Apply</h3>
            <p className={HELPER}>Mọi hành động gọi API thật — hủy/hủy chỉ ảnh hưởng đúng run hiện tại.</p>
            <div className="mt-3 flex flex-wrap gap-4">
              <div className="flex flex-col items-start gap-1">
                <button
                  type="button"
                  onClick={() => void doCancel()}
                  disabled={!canCancel || !!actionBusy}
                  className={`min-h-9 rounded px-4 py-1.5 text-xs font-medium ${!canCancel || !!actionBusy ? "cursor-not-allowed bg-gray-700 text-gray-400" : "bg-red-700 text-white hover:bg-red-600"}`}
                  data-testid="apply-cancel"
                >
                  {actionBusy === "cancel" ? "Đang hủy…" : "Hủy Apply"}
                </button>
                <p className={HELPER}>Hủy job đang chạy — không tạo publication giả sau khi hủy.</p>
              </div>
              <div className="flex flex-col items-start gap-1">
                <button
                  type="button"
                  onClick={() => void doRetry()}
                  disabled={!canRetry || !!actionBusy}
                  className={`min-h-9 rounded px-4 py-1.5 text-xs font-medium ${!canRetry || !!actionBusy ? "cursor-not-allowed bg-gray-700 text-gray-400" : "bg-amber-700 text-white hover:bg-amber-600"}`}
                  data-testid="apply-retry"
                >
                  {actionBusy === "retry" ? "Đang thử lại…" : "Thử lại (retry)"}
                </button>
                <p className={HELPER}>Tạo lineage mới từ run đã hủy/thất bại — không dùng lại artifact cũ.</p>
              </div>
              <div className="flex flex-col items-start gap-1">
                <button
                  type="button"
                  onClick={() => void doResume()}
                  disabled={!canResume || !!actionBusy}
                  className={`min-h-9 rounded px-4 py-1.5 text-xs font-medium ${!canResume || !!actionBusy ? "cursor-not-allowed bg-gray-700 text-gray-400" : "bg-indigo-600 text-white hover:bg-indigo-500"}`}
                  data-testid="apply-resume"
                >
                  {actionBusy === "resume" ? "Đang tiếp tục…" : "Tiếp tục (resume)"}
                </button>
                <p className={HELPER}>Tiếp tục từ checkpoint bền vững — tái sử dụng chunk đã xác minh, không render lại.</p>
              </div>
            </div>
            {actionError && (
              <p role="alert" className="mt-2 text-xs text-red-300" data-testid="apply-action-error">
                {actionError}
              </p>
            )}
            {staleNotice && (
              <p className="mt-2 text-xs text-amber-300" data-testid="apply-conflict-notice">
                {staleNotice}
              </p>
            )}
            <div className="mt-3 flex flex-col items-start gap-1">
              <button type="button" onClick={() => void status.refresh()} className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700" data-testid="apply-actions-refresh">
                Làm mới trạng thái
              </button>
              <p className={HELPER}>Tải lại trạng thái mới nhất từ backend (hiển thị lỗi/conflict nếu có).</p>
            </div>
          </div>
        )}

        {/* ── Structural evidence gate ───────────────────────────────── */}
        {status.data && (
          <div className="space-y-2">
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => void fetchEvidence()}
                disabled={!isTerminalCompleted || evidenceLoading}
                className={`min-h-9 rounded px-4 py-1.5 text-xs font-medium ${!isTerminalCompleted || evidenceLoading ? "cursor-not-allowed bg-gray-700 text-gray-400" : "bg-cyan-700 text-white hover:bg-cyan-600"}`}
                data-testid="apply-compare-btn"
              >
                {evidenceLoading ? "Đang kiểm tra…" : "Kiểm tra cấu trúc (structural-compare)"}
              </button>
              <p className={HELPER}>
                {isTerminalCompleted ? "Gọi POST structural-compare cho run đã hoàn tất — hiển thị lý do role/layer/segment nếu thất bại." : "Chỉ kiểm tra sau khi Apply hoàn tất (status completed)."}
              </p>
            </div>
            <ApplyEvidenceLinks
              evidence={evidence}
              loading={evidenceLoading}
              error={evidenceError}
              onRetry={() => void fetchEvidence()}
              reviewHref={evidence?.passed && evidence?.status === "REVIEW_REQUIRED" ? `/projects/${encodeURIComponent(projectIdForStatus ?? "")}` : undefined}
            />
          </div>
        )}

        {/* ── Empty evidence when no run yet ─────────────────────────── */}
        {!status.data && !evidence && !evidenceLoading && !evidenceError && runId && (
          <div className="rounded border border-gray-700 p-3" data-testid="apply-no-evidence-yet">
            <p className="text-xs text-gray-400">Chưa có bằng chứng — tạo và hoàn tất một lần Apply trước.</p>
          </div>
        )}

        {/* ── Next steps after a completed run (journey context) ─────── */}
        {status.data && (
          <div className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="apply-next-steps">
            <h3 className="text-sm font-medium text-gray-100">Bước kế tiếp</h3>
            <p className={HELPER}>
              Hành trình dùng đúng project/video của run hiện tại — không cần nhập tay.
            </p>
            {isTerminalCompleted ? (
              <div className="mt-3 flex flex-wrap gap-4">
                <div className="flex flex-col items-start gap-1">
                  <Link
                    href={buildExportHref(
                      status.data.project_id,
                      status.data.video_item_id,
                      "default",
                      status.data.run_id,
                    )}
                    data-testid="apply-go-export"
                    className="inline-flex min-h-9 items-center rounded bg-cyan-700 px-4 py-1.5 text-xs font-medium text-white hover:bg-cyan-600"
                  >
                    Xuất video (Export) →
                  </Link>
                  <p className={HELPER}>Mở luồng Export cho đúng project/video của run này.</p>
                </div>
                <div className="flex flex-col items-start gap-1">
                  <Link
                    href={buildReviewHref(status.data.project_id)}
                    data-testid="apply-go-review"
                    className="inline-flex min-h-9 items-center rounded border border-gray-700 bg-gray-800 px-4 py-1.5 text-xs font-medium text-gray-200 hover:bg-gray-700"
                  >
                    Duyệt QC (hàng đợi) →
                  </Link>
                  <p className={HELPER}>Xem issue kiểm tra chất lượng và vị trí lỗi của dự án.</p>
                </div>
                <div className="flex flex-col items-start gap-1">
                  <Link
                    href={`/projects/${encodeURIComponent(status.data.project_id)}`}
                    data-testid="apply-go-project"
                    className="inline-flex min-h-9 items-center rounded border border-gray-700 bg-gray-800 px-4 py-1.5 text-xs font-medium text-gray-200 hover:bg-gray-700"
                  >
                    Về dự án (hành trình) →
                  </Link>
                  <p className={HELPER}>Xem lại toàn bộ hành trình sản xuất của dự án.</p>
                </div>
              </div>
            ) : (
              <p className="mt-2 text-xs text-amber-300" data-testid="apply-next-blocked">
                Chưa mở Export/Duyệt QC: cần run ở trạng thái completed (hiện tại:{" "}
                {status.data.status}).
              </p>
            )}
          </div>
        )}

        <footer className="rounded border border-gray-800 p-3">
          <p className={HELPER}>Giao diện hỗ trợ mobile 390px, dark theme, mọi trạng thái loading/empty/error/stale/conflict đều có thông báo rõ ràng.</p>
          <p className="mt-1 font-mono text-[11px] text-gray-400">S10-T04B — nguồn duy nhất là backend API (GET /api/v2/full-apply/… + POST structural-compare).</p>
        </footer>
      </div>
    </div>
  );
}
