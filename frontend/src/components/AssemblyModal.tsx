"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type SceneDetail } from "@/lib/api";
import { useProjectStore } from "@/stores/project";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

const STATUS_LABEL: Record<SceneDetail["status"], string> = {
  approved: "🟢 Đã duyệt",
  draft: "🟡 Đang sửa",
  pending: "⚪ Chưa làm",
};

export function AssemblyModal({ isOpen, onClose }: Props) {
  const projectId = useProjectStore((s) => s.projectId);
  const [result, setResult] = useState<string | null>(null);

  const { data: scenes = [] } = useQuery({
    queryKey: ["scenes", projectId],
    queryFn: () => api.getSceneDetails(projectId!),
    enabled: !!projectId && isOpen,
  });

  const stitchMut = useMutation({
    mutationFn: () => api.stitchScenes(projectId!),
    onSuccess: (data) => {
      setResult(data.output_path);
    },
  });

  if (!isOpen) return null;

  const approvedCount = scenes.filter((s) => s.status === "approved").length;
  const allApproved = scenes.length > 0 && approvedCount === scenes.length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center
      bg-black/70 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-gray-900 border border-gray-700
        rounded-lg p-6 space-y-4">
        <h2 className="text-lg font-bold text-center">
          🎬 Tổng hợp ghép video
        </h2>

        {/* Scene list */}
        <div className="space-y-1 max-h-60 overflow-y-auto">
          {scenes.map((scene) => (
            <div
              key={scene.scene_id}
              className="flex items-center justify-between px-3 py-1.5
                bg-gray-800 rounded text-sm"
            >
              <span>Cảnh {scene.scene_id + 1}</span>
              <span className="text-xs">
                {STATUS_LABEL[scene.status]}
              </span>
            </div>
          ))}
        </div>

        <p className="text-xs text-gray-400 text-center">
          {approvedCount}/{scenes.length} cảnh đã duyệt
        </p>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-2 bg-gray-700 hover:bg-gray-600
              rounded text-sm transition-colors"
          >
            Đóng
          </button>
          <button
            onClick={() => stitchMut.mutate()}
            disabled={!allApproved || stitchMut.isPending}
            className="flex-1 py-2 bg-green-600 hover:bg-green-500
              disabled:bg-gray-700 disabled:text-gray-500
              rounded font-medium text-sm transition-colors"
          >
            {stitchMut.isPending
              ? "Đang ghép..."
              : "🎬 Đồng ý ghép Video hoàn chỉnh"}
          </button>
        </div>

        {/* Result */}
        {result && (
          <div className="p-3 bg-green-900/30 border border-green-700 rounded">
            <p className="text-sm text-green-300 text-center">
              ✅ Video đã ghép xong!
            </p>
            <p className="text-xs text-gray-400 text-center mt-1 break-all">
              {result}
            </p>
          </div>
        )}

        {stitchMut.isError && (
          <div className="p-3 bg-red-900/30 border border-red-700 rounded">
            <p className="text-sm text-red-300 text-center">
              ❌ Lỗi: {(stitchMut.error as Error).message}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
