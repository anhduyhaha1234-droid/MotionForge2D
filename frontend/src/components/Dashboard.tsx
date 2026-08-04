"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";

export interface ProjectSummary {
  id: string;
  name: string;
  description?: string;
  status: "draft" | "generating" | "needs_review" | "ready" | "archived";
  source_channel_id?: string;
  production_channel_id?: string;
  source_channel_name?: string;
  production_channel_name?: string;
  video_count?: number;
  active_jobs_count?: number;
  last_activity_at?: string;
}

export interface ActiveJobSummary {
  id: string;
  job_type: string;
  state: string;
  progress: number;
  attempt: number;
  max_attempts: number;
  created_at: string;
}

export function Dashboard() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeJobs, setActiveJobs] = useState<ActiveJobSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [showLegacy, setShowLegacy] = useState<boolean>(false);

  useEffect(() => {
    async function loadDashboard() {
      try {
        setLoading(true);
        const res = await fetch("/api/v2/projects");
        if (res.ok) {
          const data = await res.json();
          setProjects(data.projects || []);
        } else {
          // Fallback demo projects if v2 server is starting up
          setProjects([]);
        }

        const jobsRes = await fetch("/api/v2/jobs?state=running");
        if (jobsRes.ok) {
          const jobsData = await jobsRes.json();
          setActiveJobs(jobsData.jobs || []);
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to load dashboard data");
      } finally {
        setLoading(false);
      }
    }
    loadDashboard();
  }, []);

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

  return (
    <div className="min-h-full bg-zinc-950 text-zinc-100 p-6 space-y-8 max-w-7xl mx-auto">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-800 pb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-100">
            Bảng Điều Khiển MotionForge 2D
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Tổng quan dự án, tiến trình trích xuất chuyển động và kênh xuất bản tự động.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/channels"
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-800 px-3.5 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-700 transition focus:outline-none focus:ring-2 focus:ring-indigo-500"
            title="Tạo kênh nguồn hoặc kênh sản xuất mới cho dự án"
          >
            <svg className="w-4 h-4 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Quản lý Kênh
          </Link>
          <Link
            href="/projects"
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 transition shadow-lg shadow-indigo-600/20 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            title="Khởi tạo dự án 2D mới và cấu hình nguồn video"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            + Tạo Dự Án Mới
          </Link>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-4 text-sm text-red-400">
          Lỗi tải dữ liệu: {error}
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Tổng Dự Án</span>
            <span className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
            </span>
          </div>
          <p className="text-3xl font-bold text-zinc-100 mt-2">{loading ? "..." : projects.length}</p>
          <span className="text-xs text-zinc-500 mt-1 block">Đang hoạt động trong workspace</span>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Tiến Trình Đang Chạy</span>
            <span className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </span>
          </div>
          <p className="text-3xl font-bold text-zinc-100 mt-2">{loading ? "..." : activeJobs.length}</p>
          <span className="text-xs text-zinc-500 mt-1 block">Job trích xuất/thay thế nền</span>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Kênh Sản Xuất</span>
            <span className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </span>
          </div>
          <p className="text-3xl font-bold text-zinc-100 mt-2">Active</p>
          <span className="text-xs text-zinc-500 mt-1 block">Kênh xuất bản đã kết nối</span>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Thư Viện Nhân Vật</span>
            <span className="p-2 rounded-lg bg-purple-500/10 text-purple-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </span>
          </div>
          <p className="text-3xl font-bold text-zinc-100 mt-2">v2 Ready</p>
          <span className="text-xs text-zinc-500 mt-1 block">Pack nhân vật 6-pose hoàn chỉnh</span>
        </div>
      </div>

      {/* Active Jobs Section */}
      {activeJobs.length > 0 && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
              Tiến Trình Đang Xử Lý Tự Động ({activeJobs.length})
            </h2>
          </div>
          <div className="space-y-3">
            {activeJobs.map((job) => (
              <div key={job.id} className="rounded-lg border border-zinc-800/80 bg-zinc-950 p-4 space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium text-zinc-200">{job.job_type}</span>
                  <span className="text-xs text-zinc-400">Thử lại {job.attempt}/{job.max_attempts}</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
                  <div className="bg-cyan-500 h-2 rounded-full transition-all duration-300" style={{ width: `${job.progress}%` }} />
                </div>
                <div className="flex justify-between text-xs text-zinc-500">
                  <span>Trạng thái: {job.state}</span>
                  <span>{Math.round(job.progress)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Projects List Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Dự Án Gần Đây</h2>
            <p className="text-xs text-zinc-400">Danh sách các dự án animation 2D hiện có</p>
          </div>
          <Link href="/projects" className="text-xs text-indigo-400 hover:text-indigo-300 transition">
            Xem tất cả dự án &rarr;
          </Link>
        </div>

        {loading ? (
          <div className="py-12 text-center text-sm text-zinc-500">Đang tải danh sách dự án...</div>
        ) : projects.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 p-12 text-center space-y-3">
            <div className="mx-auto w-12 h-12 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-400">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
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
                key={p.id}
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
                  <div className="flex flex-wrap gap-2 text-xs">
                    {p.source_channel_name && (
                      <span className="rounded bg-zinc-800 px-2 py-0.5 text-zinc-300 border border-zinc-700">
                        Nguồn: {p.source_channel_name}
                      </span>
                    )}
                    {p.production_channel_name && (
                      <span className="rounded bg-zinc-800 px-2 py-0.5 text-zinc-300 border border-zinc-700">
                        Sản xuất: {p.production_channel_name}
                      </span>
                    )}
                  </div>
                </div>

                <div className="border-t border-zinc-800/80 pt-4 mt-4 flex items-center justify-between text-xs text-zinc-500">
                  <span>{p.video_count || 0} video items</span>
                  <Link
                    href={`/projects/${p.id}`}
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

      {/* Collapsible Legacy Panel */}
      <div className="border-t border-zinc-800 pt-6">
        <button
          onClick={() => setShowLegacy(!showLegacy)}
          className="text-xs text-zinc-500 hover:text-zinc-400 transition flex items-center gap-1.5 focus:outline-none"
        >
          <span>{showLegacy ? "▲ Ẩn Quy Trình Cũ (Legacy Step Workflow)" : "▼ Hiện Quy Trình Cũ (Legacy Step Workflow)"}</span>
        </button>
        {showLegacy && (
          <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950 p-4">
            <p className="text-xs text-zinc-500 mb-2">Quy trình từng bước truyền thống (Screen A-D)</p>
          </div>
        )}
      </div>
    </div>
  );
}
