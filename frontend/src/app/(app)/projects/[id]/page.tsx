"use client";

import React, { useEffect, useState, use } from "react";
import Link from "next/link";

interface ProjectDetailData {
  id: string;
  name: string;
  description?: string;
  status: string;
  source_channel_id?: string;
  production_channel_id?: string;
  resume_step?: string;
  created_at: string;
  updated_at: string;
}

interface VideoItemData {
  id: string;
  order_index: number;
  title: string;
  status: string;
  duration_seconds?: number;
  created_at: string;
}

export default function ProjectDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const projectId = resolvedParams.id;

  const [project, setProject] = useState<ProjectDetailData | null>(null);
  const [videoItems, setVideoItems] = useState<VideoItemData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadProjectDetail() {
      try {
        setLoading(true);
        const res = await fetch(`/api/v2/projects/${projectId}`);
        if (res.ok) {
          const data = await res.json();
          setProject(data);
        } else {
          // Fallback mock detail for preview/dev mode
          setProject({
            id: projectId,
            name: `Dự án 2D ${projectId.slice(0, 8)}`,
            description: "Dự án chuyển đổi hoạt hình stickman 2D từ video nguồn",
            status: "draft",
            resume_step: "selection",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          });
        }

        const itemsRes = await fetch(`/api/v2/projects/${projectId}/videos`);
        if (itemsRes.ok) {
          const itemsData = await itemsRes.json();
          setVideoItems(itemsData.items || []);
        } else {
          setVideoItems([
            {
              id: "v-001",
              order_index: 1,
              title: "Video nguồn tập 1.mp4",
              status: "imported",
              duration_seconds: 45.2,
              created_at: new Date().toISOString(),
            },
          ]);
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to load project details");
      } finally {
        setLoading(false);
      }
    }
    loadProjectDetail();
  }, [projectId]);

  if (loading) {
    return (
      <div className="p-8 text-center text-zinc-400 max-w-5xl mx-auto space-y-4">
        <div className="h-8 w-48 bg-zinc-800 animate-pulse rounded mx-auto" />
        <div className="h-32 bg-zinc-900 animate-pulse rounded-xl" />
      </div>
    );
  }

  return (
    <div className="min-h-full bg-zinc-950 text-zinc-100 p-6 space-y-6 max-w-6xl mx-auto">
      {/* Top Breadcrumb & Actions */}
      <div className="flex items-center justify-between border-b border-zinc-800 pb-4">
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <Link href="/projects" className="hover:text-zinc-200 transition">
            &larr; Tất cả dự án
          </Link>
          <span>/</span>
          <span className="text-zinc-200 font-medium">{project?.name}</span>
        </div>
        <Link
          href={`/?project=${encodeURIComponent(projectId)}`}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition shadow-lg shadow-indigo-600/20"
          title="Tiếp tục quy trình xử lý video tại bước lưu tạm"
        >
          Tiếp tục xử lý ({project?.resume_step || "selection"}) &rarr;
        </Link>
      </div>

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-4 text-sm text-red-400">
          Lỗi: {error}
        </div>
      )}

      {/* Project Overview Card */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4 backdrop-blur-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h1 className="text-xl font-bold text-zinc-100">{project?.name}</h1>
            <p className="text-xs text-zinc-400 font-mono mt-0.5">ID: {project?.id}</p>
          </div>
          <span className="self-start sm:self-auto rounded-full bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-400 border border-indigo-500/20">
            Trạng thái: {project?.status}
          </span>
        </div>

        {project?.description && (
          <p className="text-sm text-zinc-300">{project.description}</p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 border-t border-zinc-800/80 pt-4 text-xs">
          <div>
            <span className="text-zinc-500 block">Kênh Nguồn (Source Channel)</span>
            <span className="text-zinc-200 font-medium">
              {project?.source_channel_id || "Chưa liên kết"}
            </span>
          </div>
          <div>
            <span className="text-zinc-500 block">Kênh Sản Xuất (Production Channel)</span>
            <span className="text-zinc-200 font-medium">
              {project?.production_channel_id || "Chưa liên kết"}
            </span>
          </div>
          <div>
            <span className="text-zinc-500 block">Bước làm việc tiếp theo</span>
            <span className="text-indigo-400 font-medium uppercase">
              {project?.resume_step || "Start"}
            </span>
          </div>
        </div>
      </div>

      {/* Video Items Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Danh Sách Video Items ({videoItems.length})</h2>
            <p className="text-xs text-zinc-400">Các đoạn video nguồn và dữ liệu trích xuất chuyển động trong dự án này</p>
          </div>
          <button
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-800 px-3.5 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-700 transition"
            title="Thêm tệp video nguồn mới vào dự án này"
          >
            + Thêm Video Item
          </button>
        </div>

        {videoItems.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-xs text-zinc-500">
            Chưa có Video Item nào trong dự án này.
          </div>
        ) : (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 divide-y divide-zinc-800/80">
            {videoItems.map((item) => (
              <div key={item.id} className="p-4 flex items-center justify-between gap-4 hover:bg-zinc-900/80 transition">
                <div className="flex items-center gap-3">
                  <span className="w-6 h-6 rounded-full bg-zinc-800 text-zinc-400 text-xs font-mono flex items-center justify-center">
                    #{item.order_index}
                  </span>
                  <div>
                    <h3 className="text-sm font-medium text-zinc-200">{item.title}</h3>
                    <span className="text-xs text-zinc-500">
                      Thời lượng: {item.duration_seconds ? `${item.duration_seconds}s` : "N/A"}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-3 text-xs">
                  <span className="rounded bg-zinc-800 px-2.5 py-1 text-zinc-300">
                    {item.status}
                  </span>
                  <button
                    className="text-indigo-400 hover:text-indigo-300 font-medium transition"
                    title="Mở trình biên tập xem trước chuyển động cho Video Item này"
                  >
                    Xem chi tiết &rarr;
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
