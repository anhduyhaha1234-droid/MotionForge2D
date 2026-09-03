"use client";

/**
 * S10-T04B-C3 (C6A) — ApplyCard
 *
 * Disabled Apply with an explicit VN reason until a current Demo
 * approval/checkpoint exists.  Shows approval selection, its hash +
 * verification, and the guarded Apply button with VN helper text.
 * Dark theme: VN helper under every button, text-gray-400 >= 11px.
 *
 * C6A server-derived authority contract:
 * - The UI NEVER derives scene/mapping/routes/region from the approval
 *   snapshot or any fixture — those are server-side render authority.
 * - Apply is enabled ONLY from the v2 eligibility truth of
 *   GET /api/v2/s09-approvals/{id}/full-apply-authority:
 *   verified === true && eligibility.full_apply_executable === true.
 * - v1 checkpoint → truthful REAPPROVAL_REQUIRED reason (422).
 * - unsupported route / stale / tampered / incomplete authority → the real
 *   server reason is shown (never a generic "Failed to fetch").
 * - Submit body is the minimal public identity/CAS contract — no client
 *   scene_manifest/mapping/approved_checkpoint/structural_lock_manifest.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { listApprovals, listDurableProjects, listProjectVideos, listReskinConfigs, type ApprovalCheckpointOut, type ProjectInfo, type VideoItemInfo, type ReskinConfigInfo } from "@/features/demo";

const HELPER = "text-[11px] leading-snug text-gray-400";
const STORAGE_RUN_ID = "s10:apply:lastRunId";

export interface ApplyCardSelection {
  projectId: string;
  videoItemId: string;
  checkpointId: string;
  checkpointHash: string;
  checkpointRevision: number;
}

export interface FullApplyEligibilityView {
  full_apply_executable: boolean;
  reasons: string[];
  unsupported_routes: string[];
}

interface AuthorityState {
  checkpointId: string | null;
  phase: "idle" | "loading" | "ready" | "error";
  status: number | null;
  verified: boolean | null;
  eligibility: FullApplyEligibilityView | null;
  error: string | null;
}

const AUTHORITY_IDLE: AuthorityState = { checkpointId: null, phase: "idle", status: null, verified: null, eligibility: null, error: null };
const AUTHORITY_LOADING: AuthorityState = { checkpointId: null, phase: "loading", status: null, verified: null, eligibility: null, error: null };

interface ApplyCardProps {
  onApplySuccess?: (runId: string, projectId: string) => void;
  onSelectionChange?: (sel: ApplyCardSelection | null, disabledReason: string | null) => void;
  /** Deep-link project selection (from the /apply?project= URL) — wins over
   *  the first listed project so the Project Detail entry reaches the right
   *  selection truthfully. */
  initialProjectId?: string | null;
}

function errText(err: unknown): string {
  if (err instanceof ApiError) return err.detailText() || `API ${err.status}`;
  return err instanceof Error ? err.message : String(err);
}

function checkpointLabel(cp: ApprovalCheckpointOut): string {
  const schema = (cp.snapshot?.schema as string | undefined) ?? "";
  const tag = schema === "s09.approval/v2" ? "v2" : schema === "s09.approval/v1" ? "v1" : "?";
  return `${cp.id.slice(0, 8)}… · ${tag} · hash ${cp.checkpoint_hash.slice(0, 8)}… · rev ${cp.reskin_config_revision}`;
}

export function ApplyCard({ onApplySuccess, onSelectionChange, initialProjectId }: ApplyCardProps) {
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [videos, setVideos] = useState<VideoItemInfo[]>([]);
  const [configs, setConfigs] = useState<ReskinConfigInfo[]>([]);
  const [checkpoints, setCheckpoints] = useState<ApprovalCheckpointOut[]>([]);
  const [projectId, setProjectId] = useState<string>(initialProjectId ?? "");
  const [videoId, setVideoId] = useState<string>("");
  const [checkpointId, setCheckpointId] = useState<string>("");
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [authority, setAuthority] = useState<AuthorityState>(AUTHORITY_IDLE);
  const [lastRunId, setLastRunId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      return localStorage.getItem(STORAGE_RUN_ID);
    } catch {
      return null;
    }
  });

  const selectedCheckpoint = useMemo(() => checkpoints.find((c) => c.id === checkpointId) ?? null, [checkpoints, checkpointId]);
  const selectedConfig = useMemo(() => configs.find((c) => c.id === selectedCheckpoint?.reskin_config_id) ?? configs[0] ?? null, [configs, selectedCheckpoint]);

  // ── v2 eligibility truth (server-derived, per selected checkpoint) ──────
  // The fetch is started from an effect, but every state WRITE happens in an
  // async callback (never synchronously in the effect body); the effective
  // authority for the CURRENT checkpoint is derived during render so a stale
  // response for a previously selected checkpoint can never leak.
  const authorityReqId = selectedCheckpoint?.id ?? null;
  const authoritySeq = useRef(0);
  useEffect(() => {
    if (!authorityReqId) return;
    const seq = ++authoritySeq.current;
    let cancelled = false;
    api
      .getFullApplyAuthority(authorityReqId, "default")
      .then((res) => {
        if (cancelled || seq !== authoritySeq.current) return;
        setAuthority({
          checkpointId: authorityReqId,
          phase: "ready",
          status: 200,
          verified: Boolean(res.verified),
          eligibility: (res.eligibility ?? { full_apply_executable: false, reasons: [], unsupported_routes: [] }) as FullApplyEligibilityView,
          error: null,
        });
      })
      .catch((err: unknown) => {
        if (cancelled || seq !== authoritySeq.current) return;
        const status = err instanceof ApiError ? err.status : null;
        setAuthority({
          checkpointId: authorityReqId,
          phase: "error",
          status,
          verified: null,
          eligibility: null,
          error: err instanceof ApiError ? err.detailText() || `API ${err.status}` : err instanceof Error ? err.message : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [authorityReqId]);

  const effectiveAuthority: AuthorityState = useMemo(() => {
    if (!authorityReqId) return AUTHORITY_IDLE;
    if (authority.checkpointId !== authorityReqId) return { ...AUTHORITY_LOADING, checkpointId: authorityReqId };
    return authority;
  }, [authority, authorityReqId]);

  // Truthful reason for an unusable authority — v1/tampered/unsupported/
  // incomplete all map to the real server state (never a generic error).
  const authorityDisabledReason: string | null = useMemo(() => {
    if (!selectedCheckpoint) return null;
    if (effectiveAuthority.phase === "idle") return "Chưa kiểm tra quyền Apply của checkpoint.";
    if (effectiveAuthority.phase === "loading")
      return "Đang kiểm tra quyền Apply từ backend (full-apply-authority) — chờ xác minh checkpoint…";
    if (effectiveAuthority.phase === "error") {
      if (effectiveAuthority.status === 422)
        return "Checkpoint là bản duyệt cũ (v1) — cần duyệt lại (reapproval) để tạo checkpoint v2 trước khi Apply (REAPPROVAL_REQUIRED).";
      if (effectiveAuthority.status === 404) return "Không tìm thấy checkpoint trên backend — nạp lại danh sách để đồng bộ.";
      if (effectiveAuthority.status === 500)
        return "Checkpoint không vượt kiểm tra hash (bị thay đổi/hỏng) — không thể Apply với dữ liệu không tin cậy.";
      return effectiveAuthority.error ? `Backend không xác minh được checkpoint: ${effectiveAuthority.error}` : "Backend không xác minh được checkpoint.";
    }
    // ready
    if (effectiveAuthority.verified !== true)
      return "Checkpoint không vượt kiểm tra hash (bị thay đổi/hỏng) — không thể Apply với dữ liệu không tin cậy.";
    const elig = effectiveAuthority.eligibility;
    if (!elig || elig.full_apply_executable !== true) {
      const reasons = elig?.reasons?.length ? elig.reasons.join("; ") : "authority không đầy đủ";
      return `Backend không cho phép Apply với checkpoint này: ${reasons}`;
    }
    return null;
  }, [selectedCheckpoint, effectiveAuthority]);

  const disabledReason: string | null = useMemo(() => {
    if (phase === "loading") return "Đang tải danh sách approval — chờ dữ liệu từ backend.";
    if (projects.length === 0) return "Chưa có project nào — hãy tạo project và chạy Demo trước khi Apply.";
    if (videos.length === 0) return "Project chưa có video — nhập video và phân tích trước khi Apply.";
    if (checkpoints.length === 0) return "Chưa có checkpoint duyệt (approval) nào cho project này — hãy duyệt Demo trước khi Apply.";
    if (!checkpointId || !selectedCheckpoint) return "Chưa chọn checkpoint duyệt — chọn một checkpoint để Apply.";
    if (selectedCheckpoint.project_id !== projectId) return "Checkpoint không thuộc project đã chọn — chọn lại checkpoint của đúng project này.";
    if (!videoId) return "Chưa chọn video — chọn video thuộc project này để Apply.";
    return null;
  }, [phase, projects.length, videos.length, checkpoints.length, checkpointId, selectedCheckpoint, projectId, videoId]);

  const selection: ApplyCardSelection | null = useMemo(() => {
    if (!selectedCheckpoint || !projectId || !videoId) return null;
    if (disabledReason || authorityDisabledReason) return null;
    return {
      projectId,
      videoItemId: videoId,
      checkpointId: selectedCheckpoint.id,
      checkpointHash: selectedCheckpoint.checkpoint_hash,
      checkpointRevision: selectedCheckpoint.reskin_config_revision,
    };
  }, [selectedCheckpoint, projectId, videoId, disabledReason, authorityDisabledReason]);

  const effectiveDisabledReason: string | null = useMemo(() => {
    if (disabledReason) return disabledReason;
    if (authorityDisabledReason) return authorityDisabledReason;
    return null;
  }, [disabledReason, authorityDisabledReason]);
  const effectiveIsDisabled = effectiveDisabledReason !== null || applying;

  useEffect(() => {
    onSelectionChange?.(selection, effectiveDisabledReason);
  }, [selection, effectiveDisabledReason, onSelectionChange]);

  const loadProjects = useCallback(async () => {
    setPhase("loading");
    setError(null);
    try {
      const doc = await listDurableProjects();
      setProjects(doc.projects);
      const first = doc.projects[0];
      if (!first) {
        setPhase("ready");
        return;
      }
      // Deep-link project (from /apply?project=) wins when present in the
      // durable list; otherwise default to the first project.
      const target =
        initialProjectId && doc.projects.some((p) => p.project_id === initialProjectId)
          ? initialProjectId
          : first.project_id;
      setProjectId(target);
      const vdoc = await listProjectVideos(target);
      setVideos(vdoc.videos);
      const firstVideo = vdoc.videos[0];
      if (firstVideo) {
        setVideoId(firstVideo.video_item_id);
        const [cfgDoc, cpDoc] = await Promise.all([listReskinConfigs(target), listApprovals({ projectId: target })]);
        setConfigs(cfgDoc.configs);
        setCheckpoints(cpDoc.items);
        if (checkpointId) {
          const still = cpDoc.items.find((c) => c.id === checkpointId);
          if (!still) setCheckpointId("");
        }
      }
      setPhase("ready");
    } catch (err: unknown) {
      setError(errText(err));
      setPhase("error");
    }
  }, [checkpointId, initialProjectId]);

  const loadedRef = useRef(false);
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    void loadProjects();
  }, [loadProjects]);

  const onProjectChange = useCallback(async (nextPid: string) => {
    setProjectId(nextPid);
    setCheckpointId("");
    setAuthority(AUTHORITY_IDLE);
    try {
      const vdoc = await listProjectVideos(nextPid);
      setVideos(vdoc.videos);
      const firstVideo = vdoc.videos[0];
      setVideoId(firstVideo?.video_item_id ?? "");
      const [cfgDoc, cpDoc] = await Promise.all([listReskinConfigs(nextPid), listApprovals({ projectId: nextPid })]);
      setConfigs(cfgDoc.configs);
      setCheckpoints(cpDoc.items);
    } catch (err: unknown) {
      setError(errText(err));
    }
  }, []);

  const onApply = useCallback(async () => {
    if (!selection || effectiveIsDisabled) return;
    setApplying(true);
    setApplyError(null);
    try {
      // Minimal public identity/CAS contract — the server derives the plan
      // and render authority exclusively from the frozen v2 checkpoint.
      const res = await api.submitS10FullApply(selection.projectId, {
        video_item_id: selection.videoItemId,
        apply_checkpoint_id: selection.checkpointId,
        expected_checkpoint_hash: selection.checkpointHash,
        expected_checkpoint_revision: selection.checkpointRevision,
        chunk_frames: 25,
        overlap_frames: 4,
      });
      try {
        localStorage.setItem(STORAGE_RUN_ID, res.run_id);
      } catch {
        // ignore
      }
      setLastRunId(res.run_id);
      onApplySuccess?.(res.run_id, selection.projectId);
    } catch (err: unknown) {
      // Server truth: 422 REAPPROVAL_REQUIRED / authority mismatch, 409
      // conflict, 404, 500 — every detail is rendered, never "Failed to fetch".
      setApplyError(errText(err));
    } finally {
      setApplying(false);
    }
  }, [selection, effectiveIsDisabled, onApplySuccess]);

  return (
    <section className="rounded border border-gray-700 bg-gray-900/60 p-4" data-testid="apply-card" aria-label="Áp dụng Full Video">
      <h2 className="text-sm font-semibold text-gray-100">Áp dụng Full Video (Full Apply)</h2>
      <p className={HELPER}>Chỉ hoạt động sau khi có checkpoint duyệt Demo hiện hành — mọi trường hợp thiếu đều hiển thị lý do tiếng Việt rõ ràng.</p>

      {phase === "loading" && (
        <div className="mt-3 rounded border border-gray-700 p-3" aria-busy="true" data-testid="apply-card-loading">
          <p className="text-sm text-gray-300">Đang tải project / video / checkpoint duyệt…</p>
          <p className={HELPER}>Dữ liệu đọc trực tiếp từ API backend.</p>
        </div>
      )}

      {phase === "error" && error && (
        <div className="mt-3 rounded border border-red-700 bg-red-900/20 p-3" role="alert" data-testid="apply-card-error">
          <p className="text-sm text-red-300">{error}</p>
          <div className="mt-2 flex flex-col items-start gap-1">
            <button type="button" onClick={() => void loadProjects()} className="rounded bg-red-700 px-3 py-1.5 text-xs text-white hover:bg-red-600" data-testid="apply-card-error-retry">
              Thử lại
            </button>
            <p className={HELPER}>Tải lại danh sách project và checkpoint duyệt từ backend.</p>
          </div>
        </div>
      )}

      {phase !== "loading" && (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="apply-project" className="text-xs text-gray-300">
              Project
            </label>
            <select
              id="apply-project"
              value={projectId}
              onChange={(e) => void onProjectChange(e.target.value)}
              className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              data-testid="apply-project-select"
            >
              {projects.length === 0 && <option value="">(không có project)</option>}
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.name}
                </option>
              ))}
            </select>
            <p className={HELPER}>Project chứa checkpoint duyệt cần áp dụng toàn bộ video.</p>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="apply-video" className="text-xs text-gray-300">
              Video item
            </label>
            <select
              id="apply-video"
              value={videoId}
              onChange={(e) => setVideoId(e.target.value)}
              className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              data-testid="apply-video-select"
            >
              {videos.length === 0 && <option value="">(không có video)</option>}
              {videos.map((v) => (
                <option key={v.video_item_id} value={v.video_item_id}>
                  {v.title || v.video_item_id}
                </option>
              ))}
            </select>
            <p className={HELPER}>Video cần áp dụng Full Apply.</p>
          </div>
        </div>
      )}

      {checkpoints.length > 0 && phase !== "loading" && (
        <div className="mt-3 flex flex-col gap-1">
          <label htmlFor="apply-checkpoint-select" className="text-xs text-gray-300">
            Checkpoint duyệt
          </label>
          <select
            id="apply-checkpoint-select"
            value={checkpointId}
            onChange={(e) => setCheckpointId(e.target.value)}
            className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            data-testid="apply-checkpoint-select"
          >
            <option value="">— Chọn checkpoint duyệt —</option>
            {checkpoints.map((cp) => (
              <option key={cp.id} value={cp.id}>
                {checkpointLabel(cp)}
              </option>
            ))}
          </select>
          <p className={HELPER}>Checkpoint được duyệt từ backend — chọn đúng bản duyệt để Apply.</p>
        </div>
      )}

      {selectedCheckpoint && (
        <div className="mt-3 rounded border border-indigo-800/50 bg-indigo-900/10 p-3" data-testid="apply-checkpoint">
          <p className="text-xs font-medium text-indigo-200">Checkpoint duyệt hiện hành</p>
          <p className="mt-1 break-all font-mono text-xs text-gray-300" data-testid="apply-checkpoint-id">
            {selectedCheckpoint.id}
          </p>
          <p className="mt-1 break-all font-mono text-[11px] text-gray-400" data-testid="apply-checkpoint-hash">
            hash {selectedCheckpoint.checkpoint_hash.slice(0, 16)}… · revision {selectedCheckpoint.reskin_config_revision} ·{" "}
            {(selectedCheckpoint.snapshot?.schema as string | undefined) ?? "schema?"}
            {checkpoints.length > 1 ? ` · ${checkpoints.length} checkpoints trong project` : " · duy nhất trong project"}
          </p>
          {selectedConfig && (
            <p className={`mt-1 ${HELPER}`} data-testid="apply-checkpoint-pack">
              Pack: {selectedConfig.pack_version_id.slice(0, 8)}… · config {selectedConfig.id.slice(0, 8)}…
            </p>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-col items-start gap-1">
        <button
          type="button"
          onClick={() => void onApply()}
          disabled={effectiveIsDisabled}
          aria-disabled={effectiveIsDisabled}
          className={`inline-flex min-h-10 items-center rounded px-5 py-2 text-sm font-semibold ${effectiveIsDisabled ? "cursor-not-allowed bg-gray-700 text-gray-400" : "bg-indigo-600 text-white hover:bg-indigo-500"}`}
          data-testid="apply-submit"
        >
          {applying ? "Đang gửi…" : "Áp dụng toàn bộ video"}
        </button>
        <p className={HELPER} data-testid="apply-submit-helper">
          {effectiveIsDisabled
            ? effectiveDisabledReason
            : "Gửi yêu cầu Full Apply theo checkpoint v2 — backend tự dựng plan từ authority đã đóng băng và trả về run_id để theo dõi tiến độ."}
        </p>
        {applyError && (
          <p role="alert" className="mt-1 text-xs text-red-300" data-testid="apply-submit-error">
            {applyError}
          </p>
        )}
      </div>

      {lastRunId && (
        <div className="mt-3 rounded bg-gray-800 px-3 py-2" data-testid="apply-last-run">
          <p className="text-xs text-gray-300">
            Lần Apply gần nhất: <span className="font-mono">{lastRunId}</span>
          </p>
          <p className={HELPER}>Lưu cục bộ — reload trang vẫn hiện và tiếp tục theo dõi đúng run_id này.</p>
        </div>
      )}

      <div className="mt-3 flex flex-col items-start gap-1">
        <button type="button" onClick={() => void loadProjects()} className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700" data-testid="apply-reload">
          Nạp lại
        </button>
        <p className={HELPER}>Tải lại dữ liệu approval/checkpoint mới nhất từ backend.</p>
      </div>
    </section>
  );
}
