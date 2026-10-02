"use client";

/**
 * S12-T05 — /export route (Export UI).
 *
 * Vietnamese Export flow: preflight → submit → poll status →
 * cancel/retry → result/evidence. All business state refetched from the
 * S12 API; localStorage + URL keep only run/project/video pointers so a
 * refresh or restart resumes from durable truth.
 *
 * Dark theme: every button has VN helper text directly below
 * (text-gray-400, 11px+). Responsive: flex-wrap, no overflow at 390px.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  listDurableProjects,
  listProjectVideos,
  type ProjectInfo,
  type VideoItemInfo,
} from "@/features/demo";
import { ExportPanel } from "@/components/export/ExportPanel";

const STORAGE_LAST_SCOPE = "s12:export:lastScope";

interface LastScope {
  project: string;
  video: string;
  workspace: string;
}

function readLastScope(): LastScope | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_LAST_SCOPE);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LastScope>;
    if (!parsed.project || !parsed.video) return null;
    return {
      project: parsed.project,
      video: parsed.video,
      workspace: parsed.workspace ?? "default",
    };
  } catch {
    return null;
  }
}

function writeLastScope(scope: LastScope) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_LAST_SCOPE, JSON.stringify(scope));
  } catch {
    // ignore
  }
}

function scopedStorageKey(workspaceId: string, projectId: string, videoItemId: string): string {
  return `s12:export:${workspaceId}:${projectId}:${videoItemId}:run`;
}

function readStorage(workspaceId: string, projectId: string, videoItemId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(scopedStorageKey(workspaceId, projectId, videoItemId));
  } catch {
    return null;
  }
}

function writeStorage(runId: string | null, workspaceId: string, projectId: string, videoItemId: string) {
  if (typeof window === "undefined") return;
  try {
    const key = scopedStorageKey(workspaceId, projectId, videoItemId);
    if (runId) localStorage.setItem(key, runId);
    else localStorage.removeItem(key);
  } catch {
    // ignore
  }
}

export default function ExportPage() {
  return (
    <Suspense fallback={<div className="min-h-full p-4 sm:p-6" aria-busy="true" />}>
      <ExportRoute />
    </Suspense>
  );
}

function ExportRoute() {
  const params = useSearchParams();
  const router = useRouter();

  // Scope resolution: URL wins; a bare reload falls back to the last scope
  // this browser used (pointer only — every number still comes from the API).
  const [lastScope] = useState<LastScope | null>(() => readLastScope());
  const projectId = params.get("project") ?? lastScope?.project ?? "";
  const videoItemId = params.get("video") ?? lastScope?.video ?? "";
  const workspaceId = params.get("workspace") ?? lastScope?.workspace ?? "default";
  const initialRunId = params.get("run") ?? (projectId && videoItemId ? readStorage(workspaceId, projectId, videoItemId) : null);
  const scopeKey = `${workspaceId}:${projectId}:${videoItemId}`;

  useEffect(() => {
    if (initialRunId && projectId && videoItemId) writeStorage(initialRunId, workspaceId, projectId, videoItemId);
  }, [initialRunId, workspaceId, projectId, videoItemId]);

  useEffect(() => {
    if (projectId && videoItemId) {
      writeLastScope({ project: projectId, video: videoItemId, workspace: workspaceId });
    }
  }, [projectId, videoItemId, workspaceId]);

  const updateRunPointer = useCallback((runId: string) => {
    writeStorage(runId, workspaceId, projectId, videoItemId);
    const next = new URLSearchParams(params.toString());
    next.set("project", projectId);
    next.set("video", videoItemId);
    next.set("workspace", workspaceId);
    next.set("run", runId);
    router.replace(`/export?${next.toString()}`, { scroll: false });
  }, [params, router, workspaceId, projectId, videoItemId]);

  if (!projectId || !videoItemId) {
    return (
      <ExportScopePicker
        onPick={(project, video) =>
          router.replace(
            `/export?project=${encodeURIComponent(project)}&video=${encodeURIComponent(video)}&workspace=${encodeURIComponent(workspaceId)}`,
            { scroll: false },
          )
        }
      />
    );
  }

  return (
    <div className="min-h-full p-4 sm:p-6">
      <h1 data-testid="export-title" className="sr-only">Export video</h1>
      <ExportPanel key={scopeKey} projectId={projectId} videoItemId={videoItemId} workspaceId={workspaceId} initialRunId={initialRunId} onRunPointerChange={updateRunPointer} />
    </div>
  );
}

/** Pick project + video from the REAL durable listings (no manual URL/API). */
function ExportScopePicker({ onPick }: { onPick: (projectId: string, videoItemId: string) => void }) {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [videos, setVideos] = useState<VideoItemInfo[]>([]);
  const [projectId, setProjectId] = useState("");
  const [videoItemId, setVideoItemId] = useState("");
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [videosLoading, setVideosLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    setPhase("loading");
    setError(null);
    try {
      const res = await listDurableProjects();
      setProjects(res.projects);
      setPhase("ready");
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Không thể tải danh sách dự án.");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadProjects();
    });
  }, [loadProjects]);

  const loadVideos = useCallback(async (pid: string) => {
    setVideosLoading(true);
    setVideos([]);
    setVideoItemId("");
    setError(null);
    try {
      const res = await listProjectVideos(pid);
      setVideos(res.videos);
    } catch (err) {
      // UI-created projects are legacy-shelled first: `/api/v2/projects/{id}`
      // is uuid-constrained and 404s for those ids, while the analyze chain is
      // the REAL authority for the project's current video item.  Falling back
      // keeps the journey usable without seeding anything.
      if (err instanceof ApiError && err.status === 404) {
        try {
          const chain = await api.getAnalyzeChain(pid);
          if (chain.video_item_id) {
            setVideos([
              {
                video_item_id: chain.video_item_id,
                title: chain.source_name ?? "Video đã phân tích",
                status: chain.chain_status,
              },
            ]);
            return;
          }
        } catch {
          // fall through to the typed empty state below
        }
      }
      setError(err instanceof Error ? err.message : "Không thể tải danh sách video.");
    } finally {
      setVideosLoading(false);
    }
  }, []);

  const canOpen = projectId !== "" && videoItemId !== "";

  return (
    <div className="min-h-full p-4 sm:p-6">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
        <header className="flex flex-col gap-1">
          <h1 data-testid="export-title" className="text-base font-semibold text-gray-100">
            Export video
          </h1>
          <p className="text-xs leading-snug text-gray-400" data-testid="export-empty">
            Chưa có project/video trên địa chỉ. Chọn từ danh sách thật bên dưới — không cần
            nhập tay hay gọi API ngoài giao diện.
          </p>
        </header>

        {phase === "loading" && (
          <div className="rounded border border-gray-700 p-4" aria-busy="true" data-testid="export-picker-loading">
            <p className="text-sm text-gray-300">Đang tải danh sách dự án từ máy chủ…</p>
          </div>
        )}

        {phase === "error" && (
          <div role="alert" className="rounded border border-red-700 bg-red-900/20 p-4" data-testid="export-picker-error">
            <p className="text-sm text-red-300">{error}</p>
            <div className="mt-2 flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => void loadProjects()}
                className="rounded bg-red-700 px-3 py-1.5 text-xs text-white hover:bg-red-600"
                data-testid="export-picker-retry"
              >
                Thử lại
              </button>
              <p className="text-[11px] text-gray-400">Tải lại danh sách dự án thật từ backend.</p>
            </div>
          </div>
        )}

        {phase === "ready" && (
          <div className="space-y-4 rounded border border-gray-700 bg-gray-900/40 p-4">
            <div className="flex flex-col items-start gap-1">
              <label htmlFor="export-picker-project" className="text-xs font-medium text-gray-200">
                Dự án
              </label>
              <select
                id="export-picker-project"
                data-testid="export-picker-project"
                value={projectId}
                onChange={(e) => {
                  const pid = e.target.value;
                  setProjectId(pid);
                  if (pid) void loadVideos(pid);
                }}
                className="min-h-9 w-full rounded border border-gray-700 bg-gray-900 px-3 text-sm text-gray-100"
              >
                <option value="">— Chọn dự án —</option>
                {projects.map((p) => (
                  <option key={p.project_id} value={p.project_id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-gray-400">Danh sách đọc thật từ GET /api/v2/projects.</p>
            </div>

            <div className="flex flex-col items-start gap-1">
              <label htmlFor="export-picker-video" className="text-xs font-medium text-gray-200">
                Video trong dự án
              </label>
              <select
                id="export-picker-video"
                data-testid="export-picker-video"
                value={videoItemId}
                onChange={(e) => setVideoItemId(e.target.value)}
                disabled={!projectId || videosLoading}
                className="min-h-9 w-full rounded border border-gray-700 bg-gray-900 px-3 text-sm text-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <option value="">{videosLoading ? "Đang tải…" : "— Chọn video —"}</option>
                {videos.map((v) => (
                  <option key={v.video_item_id} value={v.video_item_id}>
                    {v.title}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-gray-400">Chọn video để Export đúng phạm vi (project + video).</p>
            </div>

            {projectId && !videosLoading && videos.length === 0 && (
              <p className="text-xs text-amber-300" data-testid="export-picker-no-videos">
                Dự án này chưa có video item — hãy nhập &amp; phân tích nguồn trước.
              </p>
            )}

            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                disabled={!canOpen}
                onClick={() => onPick(projectId, videoItemId)}
                className={`min-h-9 rounded px-4 py-1.5 text-xs font-medium ${
                  canOpen
                    ? "bg-cyan-700 text-white hover:bg-cyan-600"
                    : "cursor-not-allowed bg-gray-700 text-gray-400"
                }`}
                data-testid="export-picker-open"
              >
                Mở Export cho video này →
              </button>
              <p className="text-[11px] text-gray-400">
                {canOpen
                  ? "Địa chỉ sẽ mang đúng project/video — mọi số liệu lấy từ backend."
                  : "Chọn dự án và video trước khi mở Export."}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
