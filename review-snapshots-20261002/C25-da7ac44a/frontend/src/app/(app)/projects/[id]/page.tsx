"use client";

/**
 * Project detail page (S08-H01 correction — finding F: production authority).
 *
 * Project/video identity comes ONLY from the durable backend + URL:
 *   - resolve: GET /api/v2/projects/{id} (durable SQLite) → fallback
 *     GET /api/projects/{id} (legacy filesystem) → honest NOT-FOUND on real
 *     404 from both, honest ERROR+retry on any network/server failure.
 *   - videos (durable): GET /api/v2/projects/{id}/videos (real `videos`
 *     payload).  videos (legacy): the analyze chain
 *     GET /api/projects/{id}/analyze is the only backend authority for the
 *     project's current video item.
 * NO fabricated rows, no mock projects, no silent-empty.  Navigation passes
 * the selection EXPLICITLY at click time via the URL query string:
 *   processing → /import-analyze?project=<id>
 *   gallery    → /object-gallery?project=<id>&video=<video_item_id>
 * Never an ambient-store read as the source of identity.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, FolderOpen, RefreshCw } from "lucide-react";
import {
  api,
  ApiError,
  buildJourneyStages,
  journeyCurrentIndex,
  journeyNextStage,
  type DurableProjectData,
  type JourneyStageView,
  type ProjectData,
  type ProjectVideoItem,
} from "@/lib/api";
import { listApprovals } from "@/features/demo";
import { ShotAnchorBoard } from "@/features/shot-anchors";
import { exportContext } from "@/lib/s12-export-api";
import { ReadinessPanel } from "@/components/readiness/ReadinessPanel";

type DetailPhase = "loading" | "error" | "not-found" | "ready";

/** localStorage pointers written by the /apply and /export routes. */
const STORAGE_APPLY_RUN = "s10:apply:lastRunId";
const STORAGE_APPLY_PROJECT = "s10:apply:lastProjectId";

/** Journey rail state — statuses/hrefs come from the pure journey mapping. */
interface JourneyState {
  loading: boolean;
  stages: JourneyStageView[];
  error: string | null;
  /** Video item the rail was computed against (null before import completed). */
  videoItemId: string | null;
}

function readExportPointer(
  projectId: string,
  videoItemId: string,
  workspaceId: string,
): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(
      `s12:export:${workspaceId}:${projectId}:${videoItemId}:run`,
    );
  } catch {
    return null;
  }
}

function readApplyPointer(projectId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    const storedProject = localStorage.getItem(STORAGE_APPLY_PROJECT);
    if (storedProject && storedProject !== projectId) return null;
    return localStorage.getItem(STORAGE_APPLY_RUN);
  } catch {
    return null;
  }
}

interface VideoRow {
  video_item_id: string;
  title: string;
  position: number;
  status: string;
  duration_ms: number | null;
}

interface ProjectView {
  id: string;
  name: string;
  status: string;
  description: string;
  resume_step: string | null;
  source_channel_id: string | null;
  production_channel_id: string | null;
}

interface DetailState {
  phase: DetailPhase;
  error: string | null;
  project: ProjectView | null;
  videos: VideoRow[];
  videosError: string | null;
  loadingVideos: boolean;
}

const STATUS_LABELS: Record<string, string> = {
  // durable v2 (S03)
  draft: "Nháp",
  generating: "Đang xử lý",
  needs_review: "Cần xem lại",
  ready: "Sẵn sàng",
  archived: "Đã lưu trữ",
  // legacy filesystem
  in_progress: "Đang thực hiện",
  ready_to_stitch: "Sẵn sàng ghép",
  completed: "Hoàn tất",
};

const STATUS_STYLES: Record<string, string> = {
  ready: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  completed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  needs_review: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  generating: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20 animate-pulse",
  in_progress: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20 animate-pulse",
  archived: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

function statusClass(status: string): string {
  return STATUS_STYLES[status] ?? "bg-indigo-500/10 text-indigo-400 border-indigo-500/20";
}

function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return "N/A";
  return `${(ms / 1000).toFixed(1)} giây`;
}

export default function ProjectDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolved = use(params);
  const id = resolved.id;

  const [state, setState] = useState<DetailState>({
    phase: "loading",
    error: null,
    project: null,
    videos: [],
    videosError: null,
    loadingVideos: false,
  });

  const [journey, setJourney] = useState<JourneyState>({
    loading: true,
    stages: [],
    error: null,
    videoItemId: null,
  });

  /** Anchor readiness reported by the real shot-anchors board (G2 gate). */
  const [anchorGate, setAnchorGate] = useState<{ ready: boolean; message: string }>({
    ready: false,
    message: "Đang đọc trạng thái anchor từ máy chủ…",
  });

  /**
   * Journey rail — every input is a REAL backend read (analyze chain, cast
   * mappings, demo approvals, apply run status, export context).  A failed
   * read stays null so the pure mapping fails closed (blocked + missing
   * sentence) instead of opening a step whose dependencies are unknown.
   */
  const loadJourney = useCallback(
    async (projectId: string, videoItemId: string | null) => {
      setJourney({ loading: true, stages: [], error: null, videoItemId: null });
      try {
        const chainP = api
          .getAnalyzeChain(projectId)
          .catch(() => null);
        const castP = api
          .listProjectCastMappings(projectId)
          .then((r) => r.total)
          .catch(() => null);
        const approvalP = listApprovals({ projectId })
          .then((r) => r.total)
          .catch(() => null);
        const applyPointer = readApplyPointer(projectId);
        const applyP = applyPointer
          ? api
              .getS10FullApplyStatus(applyPointer, "default", projectId)
              .then((r) => ({ runId: applyPointer, status: r.status }))
              .catch(() => ({ runId: applyPointer, status: null }))
          : Promise.resolve({ runId: null, status: null });
        const exportPointer =
          videoItemId !== null
            ? readExportPointer(projectId, videoItemId, "default")
            : null;
        const contextP =
          videoItemId !== null
            ? exportContext(projectId, videoItemId).catch(() => null)
            : Promise.resolve(null);

        const [chain, castCount, approvalCount, apply, context] = await Promise.all([
          chainP,
          castP,
          approvalP,
          applyP,
          contextP,
        ]);

        const chainVideoItemId =
          chain && typeof chain.video_item_id === "string" ? chain.video_item_id : null;
        const resolvedVideo = videoItemId ?? chainVideoItemId;

        const stages = buildJourneyStages({
          projectId,
          workspaceId: "default",
          videoItemId: resolvedVideo,
          analyzeChainStatus: chain ? chain.chain_status : null,
          castMappingCount: castCount,
          approvalCount,
          applyRunId: apply.runId,
          applyRunStatus: apply.status,
          fullApplyRunId: context ? context.full_apply_run_id : null,
          exportRunId: exportPointer ?? (context?.current_run?.run_id ?? null),
        });
        setJourney({ loading: false, stages, error: null, videoItemId: resolvedVideo });
      } catch (err) {
        setJourney({
          loading: false,
          stages: [],
          error: err instanceof Error ? err.message : "Không thể tính hành trình.",
          videoItemId: null,
        });
      }
    },
    [],
  );

  const load = useCallback(async () => {
    setState({
      phase: "loading",
      error: null,
      project: null,
      videos: [],
      videosError: null,
      loadingVideos: false,
    });
    setJourney({ loading: true, stages: [], error: null, videoItemId: null });
    try {
      // 1) Resolve identity from the durable backend first, legacy second.
      let durable: DurableProjectData | null = null;
      let legacy: ProjectData | null = null;
      try {
        durable = await api.getDurableProject(id);
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err;
      }
      if (!durable) {
        try {
          legacy = await api.getProject(id);
        } catch (err) {
          if (!(err instanceof ApiError && err.status === 404)) throw err;
        }
      }
      if (!durable && !legacy) {
        setState({
          phase: "not-found",
          error: null,
          project: null,
          videos: [],
          videosError: null,
          loadingVideos: false,
        });
        return;
      }

      const view: ProjectView = durable
        ? {
            id: durable.project_id,
            name: durable.name,
            status: durable.status,
            description: durable.description ?? "",
            resume_step: durable.resume_step,
            source_channel_id: durable.source_channel_id,
            production_channel_id: durable.production_channel_id,
          }
        : {
            id,
            name: legacy?.name || "Dự án",
            status: legacy?.task_status ?? "draft",
            description: "",
            resume_step: null,
            source_channel_id: null,
            production_channel_id: null,
          };

      // 2) Videos from the matching real contract (never fabricated).
      let videos: VideoRow[] = [];
      setState((prev) => ({ ...prev, phase: "ready", project: view, loadingVideos: true }));
      try {
        if (durable) {
          const list = await api.listProjectVideos(durable.project_id);
          videos = list.videos
            .map((v: ProjectVideoItem) => ({
              video_item_id: v.video_item_id,
              title: v.title,
              position: v.position,
              status: v.status,
              duration_ms: v.duration_ms ?? null,
            }))
            .sort((a, b) => a.position - b.position);
        } else {
          // Legacy project: the analyze chain is the ONLY backend authority
          // for video identity here (v2 videos 404 for legacy ids).
          const chain = await api.getAnalyzeChain(id);
          if (chain.video_item_id) {
            videos = [
              {
                video_item_id: chain.video_item_id,
                title: chain.source_name ?? "Video đã phân tích",
                position: 0,
                status: chain.chain_status,
                duration_ms: null,
              },
            ];
          }
        }
        setState((prev) => ({ ...prev, videos, videosError: null, loadingVideos: false }));
        // Journey rail: real per-project reads over the resolved video item.
        void loadJourney(
          durable ? durable.project_id : id,
          videos.length > 0 ? videos[0].video_item_id : null,
        );
      } catch (err) {
        setState((prev) => ({
          ...prev,
          videosError:
            err instanceof Error ? err.message : "Không thể tải danh sách video.",
          loadingVideos: false,
        }));
      }
    } catch (err) {
      setState({
        phase: "error",
        error:
          err instanceof ApiError
            ? `Lỗi ${err.status}: ${err.detailText()}`
            : err instanceof Error
              ? err.message
              : "Lỗi kết nối máy chủ.",
        project: null,
        videos: [],
        videosError: null,
        loadingVideos: false,
      });
    }
  }, [id, loadJourney]);

  useEffect(() => {
    void load();
  }, [load]);

  // ── Rendering ────────────────────────────────────────────────────────────

  if (state.phase === "loading") {
    return (
      <div className="p-8 text-center text-zinc-400 max-w-5xl mx-auto space-y-4" aria-busy="true">
        <div className="h-8 w-48 bg-zinc-800 animate-pulse rounded mx-auto" />
        <div className="h-32 bg-zinc-900 animate-pulse rounded-xl" />
        <div className="mx-auto h-4 w-64 bg-zinc-900 animate-pulse rounded" />
      </div>
    );
  }

  if (state.phase === "error") {
    return (
      <div className="min-h-full bg-zinc-950 text-zinc-100 p-6 max-w-2xl mx-auto">
        <div className="rounded-xl border border-red-500/30 bg-zinc-900/60 p-8 text-center space-y-4">
          <AlertTriangle aria-hidden="true" size={32} className="mx-auto text-red-400" />
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Không thể tải dự án</h1>
            <p className="mt-2 text-sm text-zinc-400">
              Không kết nối được máy chủ hoặc máy chủ báo lỗi khi đọc dự án{" "}
              <span className="font-mono text-xs">{id}</span>.
            </p>
            <p
              role="alert"
              className="mt-2 rounded bg-red-500/10 border border-red-500/20 px-3 py-2 text-xs text-red-300 font-mono break-all"
            >
              {state.error}
            </p>
          </div>
          <div className="flex flex-col items-center gap-1">
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex items-center gap-2 rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-600 transition"
            >
              <RefreshCw aria-hidden="true" size={15} />
              Thử lại
            </button>
            <p className="text-[11px] text-zinc-500">Tải lại thông tin dự án từ máy chủ.</p>
          </div>
          <Link href="/projects" className="inline-block text-sm text-indigo-400 hover:text-indigo-300">
            ← Về danh sách dự án
          </Link>
        </div>
      </div>
    );
  }

  if (state.phase === "not-found" || !state.project) {
    return (
      <div className="min-h-full bg-zinc-950 text-zinc-100 p-6 max-w-2xl mx-auto">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-8 text-center space-y-4">
          <FolderOpen aria-hidden="true" size={32} className="mx-auto text-zinc-500" />
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Không tìm thấy dự án</h1>
            <p className="mt-2 text-sm text-zinc-400">
              Máy chủ không có dự án{" "}
              <span className="font-mono text-xs text-zinc-300">{id}</span> (đã kiểm tra cả
              workspace bền vững và dự án trên đĩa). Mã dự án có thể đã bị xóa hoặc sai.
            </p>
          </div>
          <Link
            href="/projects"
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 transition"
          >
            ← Về danh sách dự án
          </Link>
          <p className="text-[11px] text-zinc-500">
            Danh sách dự án luôn được lấy thật từ máy chủ — không có dữ liệu mẫu ở đây.
          </p>
        </div>
      </div>
    );
  }

  const project = state.project;
  const nextStage = journeyNextStage(journey.stages);
  const currentIndex = journeyCurrentIndex(journey.stages);
  const applyStage = journey.stages.find((s) => s.key === "apply") ?? null;
  const exportStage = journey.stages.find((s) => s.key === "export") ?? null;
  const stageChip: Record<string, string> = {
    done: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    current: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
    blocked: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  };
  const stageChipLabel: Record<string, string> = {
    done: "Đã xong",
    current: "Bước hiện tại",
    blocked: "Bị chặn",
  };
  return (
    <div className="min-h-full bg-zinc-950 text-zinc-100 p-4 sm:p-6 space-y-6 max-w-6xl mx-auto overflow-x-hidden">
      {/* Top Breadcrumb & Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 pb-4">
        <div className="flex items-center gap-2 text-sm text-zinc-400 min-w-0">
          <Link href="/projects" className="hover:text-zinc-200 transition shrink-0">
            &larr; Tất cả dự án
          </Link>
          <span aria-hidden="true">/</span>
          <span className="text-zinc-200 font-medium truncate">{project.name}</span>
        </div>
        <Link
          href={`/import-analyze?project=${encodeURIComponent(project.id)}`}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition shadow-lg shadow-indigo-600/20"
          title="Tiếp tục quy trình xử lý video (Nhập & Phân tích) cho dự án này"
        >
          Tiếp tục xử lý ({project.resume_step || "start"}) &rarr;
        </Link>
      </div>

      {/* Project Overview Card */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4 backdrop-blur-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-zinc-100 truncate">{project.name}</h1>
            <p className="text-xs text-zinc-400 font-mono mt-0.5">ID: {project.id}</p>
          </div>
          <span
            className={`self-start sm:self-auto rounded-full px-3 py-1 text-xs font-medium border ${statusClass(project.status)}`}
          >
            Trạng thái: {statusLabel(project.status)}
          </span>
        </div>

        {project.description && <p className="text-sm text-zinc-300">{project.description}</p>}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 border-t border-zinc-800/80 pt-4 text-xs">
          <div className="min-w-0">
            <span className="text-zinc-500 block">Kênh Nguồn (Source Channel)</span>
            <span className="text-zinc-200 font-medium break-all">
              {project.source_channel_id || "Chưa liên kết"}
            </span>
          </div>
          <div className="min-w-0">
            <span className="text-zinc-500 block">Kênh Sản Xuất (Production Channel)</span>
            <span className="text-zinc-200 font-medium break-all">
              {project.production_channel_id || "Chưa liên kết"}
            </span>
          </div>
          <div className="min-w-0">
            <span className="text-zinc-500 block">Bước làm việc tiếp theo</span>
            <span className="text-indigo-400 font-medium uppercase">
              {project.resume_step || "Start"}
            </span>
          </div>
        </div>
      </div>

      {/* Journey rail — import → cast → demo → apply → review → export (MF-END-25) */}
      <section
        data-testid="project-journey"
        aria-label="Hành trình sản xuất"
        className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Hành trình sản xuất</h2>
            <p className="text-xs text-zinc-400">
              Sáu bước thật từ nhập nguồn tới xuất video. Trạng thái đọc từ máy chủ; bước
              thiếu điều kiện sẽ bị khóa kèm lý do cụ thể.
            </p>
          </div>
          {!journey.loading && journey.stages.length > 0 && (
            <span className="text-[11px] text-gray-400" data-testid="journey-position">
              Bước {currentIndex + 1}/{journey.stages.length}
            </span>
          )}
        </div>

        {journey.loading ? (
          <div className="space-y-2" aria-busy="true" data-testid="journey-loading">
            <div className="h-20 animate-pulse rounded-lg bg-zinc-800" />
            <p className="text-[11px] text-gray-400">
              Đang đọc trạng thái hành trình từ máy chủ…
            </p>
          </div>
        ) : journey.error ? (
          <div role="alert" className="space-y-2" data-testid="journey-error">
            <p className="text-sm text-red-300">Không thể tính hành trình: {journey.error}</p>
            <p className="text-[11px] text-gray-400">
              Tải lại trang để đọc lại trạng thái thật từ máy chủ.
            </p>
          </div>
        ) : (
          <>
            <ol
              className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3"
              data-testid="journey-stages"
              aria-label="Các bước của hành trình sản xuất"
            >
              {journey.stages.map((stage, index) => (
                <li
                  key={stage.key}
                  data-testid={`journey-stage-${stage.key}`}
                  className={`space-y-1 rounded-lg border p-3 ${
                    stage.status === "blocked"
                      ? "border-amber-500/30 bg-amber-500/5"
                      : "border-zinc-800 bg-zinc-950/40"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-zinc-200">
                      {index + 1}. {stage.label}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${stageChip[stage.status]}`}
                    >
                      {stageChipLabel[stage.status]}
                    </span>
                  </div>
                  <p className="text-[11px] leading-snug text-gray-400">{stage.helper}</p>
                  {stage.href ? (
                    <Link
                      href={stage.href}
                      data-testid={`journey-open-${stage.key}`}
                      className="inline-flex min-h-8 items-center rounded border border-zinc-700 bg-zinc-900 px-3 text-xs font-medium text-zinc-100 transition hover:bg-zinc-800"
                    >
                      Mở bước này →
                    </Link>
                  ) : (
                    <p
                      className="text-[11px] font-medium text-amber-300"
                      data-testid={`journey-missing-${stage.key}`}
                    >
                      {stage.missing}
                    </p>
                  )}
                </li>
              ))}
            </ol>
            {nextStage && (
              <div className="flex flex-col items-start gap-1">
                <Link
                  href={nextStage.href as string}
                  data-testid="journey-next"
                  className="inline-flex min-h-9 items-center rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-500"
                >
                  Tiếp tục: {nextStage.label} →
                </Link>
                <p className="text-[11px] text-gray-400">{nextStage.helper}</p>
              </div>
            )}
          </>
        )}
      </section>

      {/* Anchors theo shot (G2) — bước dựng anchor thật, đúng project/video này (MF-END-25 C25) */}
      {journey.videoItemId ? (
        <ShotAnchorBoard
          projectId={project.id}
          videoItemId={journey.videoItemId}
          onCoverageChange={(ready, message) => {
            setAnchorGate({ ready, message });
          }}
        />
      ) : (
        <section
          data-testid="shot-anchor-board"
          aria-label="Anchors theo shot (G2)"
          className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/60 p-6"
        >
          <h2 className="text-lg font-semibold text-zinc-100">Anchors theo shot (G2)</h2>
          <p className="text-xs text-zinc-400">
            Chưa có video item đã phân tích cho dự án này — chạy bước Nhập &amp; Phân tích trước khi
            dựng anchor.
          </p>
        </section>
      )}

      {/* Video Items Section */}
      <div className="space-y-4 min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">
              Danh Sách Video Items ({state.loadingVideos ? "…" : state.videos.length})
            </h2>
            <p className="text-xs text-zinc-400">
              Các đoạn video nguồn và dữ liệu trích xuất chuyển động trong dự án này (lấy thật từ
              máy chủ).
            </p>
          </div>
          <div className="flex flex-col items-start gap-1">
                      {/* S11-T04D additive: review-queue entry (level-2, G14 — no new top nav). */}
                      <Link
                        href={`/projects/${encodeURIComponent(project.id)}/review`}
                        data-testid="project-go-review"
                        className="inline-flex min-h-9 items-center rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-1.5 text-xs font-semibold text-zinc-100 hover:bg-zinc-800"
                      >
                        Hàng đợi QC (Review)
                      </Link>
                      <p className="text-[11px] text-gray-400">
                        Xem các issue kiểm tra chất lượng — mở thẳng vị trí lỗi.
                      </p>
                    </div>
                    <div className="flex flex-col items-start gap-1">
                      {applyStage?.href ? (
                        <Link
                          href={applyStage.href}
                          className="inline-flex min-h-9 items-center rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
                          data-testid="project-go-apply"
                        >
                          Áp dụng toàn bộ video (Full Apply) →
                        </Link>
                      ) : (
                        <button
                          type="button"
                          disabled
                          aria-disabled="true"
                          title={applyStage?.missing ?? "Chưa đủ điều kiện để Apply"}
                          className="inline-flex min-h-9 cursor-not-allowed items-center rounded-lg bg-zinc-800 px-4 py-1.5 text-xs font-semibold text-zinc-500"
                          data-testid="project-go-apply"
                        >
                          Áp dụng toàn bộ video (Full Apply)
                        </button>
                      )}
                      <p className="text-[11px] text-gray-400">
                        {applyStage?.href
                          ? "Mở luồng Apply — checkpoint duyệt Demo đã có."
                          : (applyStage?.missing ?? "Đang đọc điều kiện Apply từ máy chủ…")}
                      </p>
                      <p className="text-[11px] text-gray-400" data-testid="journey-anchor-gate">
                        Anchor (G2): {anchorGate.message}
                      </p>
                    </div>
                    <div className="flex flex-col items-start gap-1">
                      {exportStage?.href ? (
                        <Link
                          href={exportStage.href}
                          className="inline-flex min-h-9 items-center rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-1.5 text-xs font-semibold text-zinc-100 hover:bg-zinc-800"
                          data-testid="project-go-export"
                        >
                          Xuất video (Export) →
                        </Link>
                      ) : (
                        <button
                          type="button"
                          disabled
                          aria-disabled="true"
                          title={exportStage?.missing ?? "Chưa đủ điều kiện để xuất video"}
                          className="inline-flex min-h-9 cursor-not-allowed items-center rounded-lg bg-zinc-800 px-4 py-1.5 text-xs font-semibold text-zinc-500"
                          data-testid="project-go-export"
                        >
                          Xuất video (Export)
                        </button>
                      )}
                      <p className="text-[11px] text-gray-400">
                        {exportStage?.href
                          ? "Mở luồng Export — xuất MP4 từ lượt Apply đã hoàn tất."
                          : (exportStage?.missing ?? "Đang đọc điều kiện Export từ máy chủ…")}
                      </p>
                    </div>
        </div>

        {state.loadingVideos ? (
          <div className="space-y-2" aria-busy="true">
            <div className="h-16 animate-pulse rounded-lg bg-zinc-900" />
          </div>
        ) : state.videosError ? (
          <div className="rounded-xl border border-red-500/30 bg-zinc-900/60 p-6 text-center space-y-3">
            <p role="alert" className="text-sm text-red-300">
              Không thể tải danh sách video: {state.videosError}
            </p>
            <div className="flex flex-col items-center gap-1">
              <button
                type="button"
                onClick={() => void load()}
                className="inline-flex items-center gap-2 rounded-lg bg-zinc-800 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-700 transition"
              >
                <RefreshCw aria-hidden="true" size={15} />
                Thử lại
              </button>
              <p className="text-[11px] text-zinc-500">Tải lại thông tin dự án và video từ máy chủ.</p>
            </div>
          </div>
        ) : state.videos.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-xs text-zinc-500">
            Chưa có Video Item nào trong dự án này. Hãy vào{" "}
            <Link
              href={`/import-analyze?project=${encodeURIComponent(project.id)}`}
              className="text-indigo-400 hover:text-indigo-300"
            >
              Nhập &amp; Phân tích
            </Link>{" "}
            để thêm video nguồn.
          </div>
        ) : (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 divide-y divide-zinc-800/80 min-w-0">
            {state.videos.map((item) => (
              <div
                key={item.video_item_id}
                className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-zinc-900/80 transition"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="w-6 h-6 rounded-full bg-zinc-800 text-zinc-400 text-xs font-mono flex items-center justify-center shrink-0">
                    #{item.position + 1}
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-sm font-medium text-zinc-200 truncate">{item.title}</h3>
                    <span className="text-xs text-zinc-500">
                      Thời lượng: {formatDuration(item.duration_ms)} · mã video:{" "}
                      <span className="font-mono">{item.video_item_id.slice(0, 8)}</span>
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-3 text-xs shrink-0">
                  <span className="rounded bg-zinc-800 px-2.5 py-1 text-zinc-300">
                    {statusLabel(item.status)}
                  </span>
                  <Link
                    href={`/object-gallery?project=${encodeURIComponent(project.id)}&video=${encodeURIComponent(item.video_item_id)}`}
                    className="text-indigo-400 hover:text-indigo-300 font-medium transition"
                    title="Mở Thư viện đối tượng cho Video Item này (chọn chuyển qua URL)"
                  >
                    Xem chi tiết &rarr;
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* S11-T05B additive: readiness block (T05A payload, GET-only). */}
      <ReadinessPanel projectId={project.id} />
    </div>
  );
}
