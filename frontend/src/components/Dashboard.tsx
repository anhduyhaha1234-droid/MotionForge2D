"use client";

/**
 * Home dashboard (S08-H01 correction — finding F: production authority).
 *
 * The project list comes ONLY from the durable backend (GET /api/v2/projects,
 * SQLite) — no demo rows, no silent-empty, no localStorage as truth.  Any API
 * failure renders an honest error banner with a working retry.
 *
 * Note: there is NO backend endpoint that lists active jobs (only
 * GET /api/jobs/{job_id} + POST cancel exist), so the "Tiến trình đang xử lý"
 * card shows an explicit, honest unavailable note instead of a fabricated
 * count.  Job progress is visible per project via the Import & Analyze screen.
 */

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, RefreshCw } from "lucide-react";
import { api, type DurableProjectData } from "@/lib/api";

const statusBadge = (status: string) => {
  switch (status) {
    case "ready":
      return <span className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-400 border border-emerald-500/20">Sẵn sàng</span>;
    case "needs_review":
      return <span className="rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-400 border border-amber-500/20">Cần xem lại</span>;
    case "generating":
      return <span className="rounded-full bg-cyan-500/10 px-2.5 py-0.5 text-xs font-medium text-cyan-400 border border-cyan-500/20 animate-pulse">Đang xử lý</span>;
    case "archived":
      return <span className="rounded-full bg-zinc-500/10 px-2.5 py-0.5 text-xs font-medium text-zinc-400 border border-zinc-500/20">Đã lưu trữ</span>;
    default:
      return <span className="rounded-full bg-indigo-500/10 px-2.5 py-0.5 text-xs font-medium text-indigo-400 border border-indigo-500/20">Bản nháp</span>;
  }
};

export function Dashboard() {
  const query = useQuery({
    queryKey: ["dashboard-projects"],
    queryFn: () => api.listDurableProjects(true),
    retry: 1,
  });
  const projects = useMemo<DurableProjectData[]>(
    () => query.data?.projects ?? [],
    [query.data],
  );

  return (
    <div className="min-h-full bg-zinc-950 text-zinc-100 p-6 space-y-8 max-w-7xl mx-auto overflow-x-hidden">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-800 pb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-100">
            Bảng Điều Khiển MotionForge 2D
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Tổng quan dự án và kênh xuất bản. Tất cả dữ liệu lấy thật từ máy chủ.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/channels"
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-800 px-3.5 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-700 transition focus:outline-none focus:ring-2 focus:ring-indigo-500"
            title="Tạo kênh nguồn hoặc kênh sản xuất mới cho dự án"
          >
            Quản lý Kênh
          </Link>
          <Link
            href="/projects"
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 transition shadow-lg shadow-indigo-600/20 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            title="Khởi tạo dự án 2D mới và cấu hình nguồn video"
          >
            + Tạo Dự Án Mới
          </Link>
        </div>
      </div>

      {/* Honest API error — never fabricated data */}
      {query.isError && (
        <div
          role="alert"
          className="rounded-lg bg-red-500/10 border border-red-500/20 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
        >
          <div className="space-y-1">
            <p className="flex items-center gap-2 text-sm font-medium text-red-300">
              <AlertCircle aria-hidden="true" size={16} />
              Không thể tải danh sách dự án từ máy chủ
            </p>
            <p className="text-xs text-red-400/80 break-all">
              {query.error instanceof Error ? query.error.message : "Lỗi kết nối máy chủ."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-600 transition"
          >
            <RefreshCw aria-hidden="true" size={15} />
            Thử lại
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Tổng Dự Án</span>
            <span className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400">▦</span>
          </div>
          <p className="text-3xl font-bold text-zinc-100 mt-2">
            {query.isLoading ? "…" : query.isError ? "—" : projects.length}
          </p>
          <span className="text-xs text-zinc-500 mt-1 block">Đang hoạt động trong workspace</span>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Tiến Trình Đang Xử Lý</span>
            <span className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">⚙</span>
          </div>
          <p className="text-3xl font-bold text-zinc-100 mt-2">—</p>
          <span className="text-xs text-zinc-500 mt-1 block">
            Không có API liệt kê job — xem tiến trình thật trong từng dự án
          </span>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Kênh Sản Xuất</span>
            <span className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400">◉</span>
          </div>
          <p className="text-3xl font-bold text-zinc-100 mt-2">—</p>
          <span className="text-xs text-zinc-500 mt-1 block">
            Mở trang Kênh để xem kênh đã kết nối
          </span>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Thư Viện Nhân Vật</span>
            <span className="p-2 rounded-lg bg-purple-500/10 text-purple-400">◈</span>
          </div>
          <p className="text-3xl font-bold text-zinc-100 mt-2">—</p>
          <span className="text-xs text-zinc-500 mt-1 block">
            Mở trang Thư viện nhân vật để xem pack
          </span>
        </div>
      </div>

      {/* Projects List Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Dự Án</h2>
            <p className="text-xs text-zinc-400">Danh sách dự án 2D hiện có (workspace bền vững)</p>
          </div>
          <Link href="/projects" className="text-xs text-indigo-400 hover:text-indigo-300 transition">
            Xem tất cả dự án &rarr;
          </Link>
        </div>

        {query.isLoading ? (
          <div className="py-12 text-center text-sm text-zinc-500" aria-busy="true">
            Đang tải danh sách dự án...
          </div>
        ) : !query.isError && projects.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 p-12 text-center space-y-3">
            <div className="mx-auto w-12 h-12 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-400">▦</div>
            <h3 className="text-sm font-medium text-zinc-200">Chưa có dự án nào</h3>
            <p className="text-xs text-zinc-500 max-w-sm mx-auto">
              Bắt đầu bằng cách tạo dự án mới hoặc nhập video nguồn để trích xuất chuyển động 2D.
            </p>
            <Link
              href="/projects"
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-500 transition"
            >
              + Tạo Dự Án Mới Ngay
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((p) => (
              <div
                key={p.project_id}
                className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 flex flex-col justify-between hover:border-zinc-700 transition group"
              >
                <div className="space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-zinc-100 group-hover:text-indigo-400 transition line-clamp-1">
                      {p.name}
                    </h3>
                    {statusBadge(p.status)}
                  </div>
                  {p.description && (
                    <p className="text-xs text-zinc-400 line-clamp-2">{p.description}</p>
                  )}
                  <p className="font-mono text-[10px] text-zinc-500 break-all">{p.project_id}</p>
                  <div className="flex flex-wrap gap-2 text-xs">
                    {p.source_channel_id && (
                      <span className="rounded bg-zinc-800 px-2 py-0.5 text-zinc-300 border border-zinc-700">
                        Nguồn: {p.source_channel_id.slice(0, 8)}
                      </span>
                    )}
                    {p.production_channel_id && (
                      <span className="rounded bg-zinc-800 px-2 py-0.5 text-zinc-300 border border-zinc-700">
                        Sản xuất: {p.production_channel_id.slice(0, 8)}
                      </span>
                    )}
                  </div>
                </div>

                <div className="border-t border-zinc-800/80 pt-4 mt-4 flex items-center justify-between text-xs text-zinc-500">
                  <span>Workspace bền vững</span>
                  <Link
                    href={`/projects/${p.project_id}`}
                    className="font-medium text-indigo-400 hover:text-indigo-300 transition flex items-center gap-1"
                  >
                    Chi tiết &rarr;
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
