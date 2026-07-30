"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type ProjectData } from "@/lib/api";
import { useProjectStore } from "@/stores/project";

export function ScreenA() {
  const { projectId, setProjectId, setProject, setScreen } = useProjectStore();
  const [projectName, setProjectName] = useState("MotionForge Project");
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string>("");

  // Create project
  const createMut = useMutation({
    mutationFn: () => api.createProject(projectName),
    onSuccess: (data) => setProjectId(data.project_id),
  });

  // Upload video
  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      if (!projectId) throw new Error("No project");
      setUploadStatus("Đang tải video lên...");
      return api.uploadVideo(projectId, file);
    },
    onSuccess: () => setUploadStatus("Video đã tải lên"),
  });

  // Ingest
  const ingestMut = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error("No project");
      setUploadStatus("Đang phân tích video...");
      return api.triggerIngest(projectId);
    },
    onSuccess: (data) => {
      setUploadStatus(`Phân tích hoàn tất (job: ${data.job_id})`);
      // Poll for completion then load project
      pollJob(data.job_id);
    },
  });

  const pollJob = async (jobId: string) => {
    const maxAttempts = 60;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const job = await api.getJob(jobId);
        if (job.status === "completed") {
          setUploadStatus("Hoàn tất!");
          // Load project data
          if (projectId) {
            const proj = await api.getProject(projectId);
            setProject(proj);
            setScreen("selection");
          }
          return;
        }
        if (job.status === "failed") {
          setUploadStatus(`Lỗi: ${job.message}`);
          return;
        }
        setUploadStatus(`${job.message} (${Math.round(job.progress)}%)`);
      } catch {
        // continue polling
      }
    }
  };

  const handleStart = useCallback(async () => {
    if (!videoFile) return;
    createMut.mutate(undefined, {
      onSuccess: () => {
        // Need to wait for projectId to be set
        setTimeout(() => {
          uploadMut.mutate(videoFile, {
            onSuccess: () => ingestMut.mutate(),
          });
        }, 100);
      },
    });
  }, [videoFile]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="w-full max-w-lg p-8 space-y-6">
        <h1 className="text-2xl font-bold text-center">
          MotionForge 2D
        </h1>
        <p className="text-gray-400 text-center">
          Tách và thay thế vật thể trong video hoạt hình 2D
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-gray-300 mb-1">
              Tên dự án
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-gray-100"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-300 mb-1">
              Video MP4
            </label>
            <input
              type="file"
              accept=".mp4,video/mp4"
              onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-gray-100 file:mr-4 file:py-1 file:px-3 file:rounded file:border-0 file:bg-blue-600 file:text-white"
            />
          </div>

          <button
            onClick={handleStart}
            disabled={!videoFile || createMut.isPending || uploadMut.isPending || ingestMut.isPending}
            className="w-full py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 rounded font-medium transition-colors"
          >
            {uploadStatus || "Bắt đầu"}
          </button>

          {uploadStatus && (
            <p className="text-sm text-gray-400 text-center">
              {uploadStatus}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
