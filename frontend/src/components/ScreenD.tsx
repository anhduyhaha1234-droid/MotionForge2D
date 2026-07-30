"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProjectStore } from "@/stores/project";

export function ScreenD() {
  const {
    projectId,
    activeObject,
    replacement,
    setReplacement,
    resetReplacement,
    setScreen,
  } = useProjectStore();
  const objectId = activeObject?.object_id;
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // Upload replacement PNG
  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      if (!projectId || !objectId) throw new Error("No project/object");
      const result = await api.uploadReplacement(projectId, objectId, file);
      setReplacement({ mode: "static_asset", asset_path: result.asset_path });
      return result;
    },
  });

  // Update settings
  const settingsMut = useMutation({
    mutationFn: async () => {
      if (!projectId || !objectId) throw new Error("No project/object");
      return api.updateReplacementSettings(projectId, objectId, {
        mode: replacement.mode,
        asset_path: replacement.asset_path,
        anchor: replacement.anchor,
        offset: replacement.offset,
        scale: replacement.scale,
        rotation_offset_deg: replacement.rotation_offset_deg,
        opacity: replacement.opacity,
        fit_mode: replacement.fit_mode,
      });
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800">
        <h2 className="text-sm font-medium">Thay thế vật thể</h2>
        <button
          onClick={() => setScreen("review")}
          className="text-xs text-gray-400 hover:text-gray-200"
        >
          ← Quay lại kết quả
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: Original + Replacement preview */}
        <div className="w-64 bg-gray-900 border-r border-gray-800 p-4 space-y-4">
          <div>
            <h3 className="text-xs text-gray-500 uppercase mb-2">
              Object gốc
            </h3>
            <div className="aspect-square bg-gray-800 rounded flex items-center justify-center text-gray-600 text-xs">
              {/* Thumbnail from gallery */}
              <div
                className="w-full h-full rounded"
                style={{
                  backgroundImage:
                    "linear-gradient(45deg, #333 25%, transparent 25%), linear-gradient(-45deg, #333 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #333 75%), linear-gradient(-45deg, transparent 75%, #333 75%)",
                  backgroundSize: "12px 12px",
                  backgroundPosition: "0 0, 0 6px, 6px -6px, -6px 0px",
                }}
              >
                {projectId && objectId && (
                  <img
                    src={`http://localhost:8000/api/projects/${projectId}/objects/${objectId}/thumbnail`}
                    alt="Object thumbnail"
                    className="w-full h-full object-contain"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = "none";
                    }}
                  />
                )}
              </div>
            </div>
          </div>

          <div>
            <h3 className="text-xs text-gray-500 uppercase mb-2">
              Ảnh thay thế
            </h3>
            <input
              type="file"
              accept=".png,image/png"
              onChange={handleFileChange}
              className="w-full text-xs text-gray-400 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:bg-blue-600 file:text-white file:text-xs"
            />
            {replacement.asset_path && (
              <div className="mt-2 aspect-square bg-gray-800 rounded overflow-hidden">
                <div
                  className="w-full h-full"
                  style={{
                    backgroundImage:
                      "linear-gradient(45deg, #333 25%, transparent 25%), linear-gradient(-45deg, #333 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #333 75%), linear-gradient(-45deg, transparent 75%, #333 75%)",
                    backgroundSize: "12px 12px",
                    backgroundPosition: "0 0, 0 6px, 6px -6px, -6px 0px",
                  }}
                >
                  <img
                    src={`http://localhost:8000${replacement.asset_path}`}
                    alt="Replacement"
                    className="w-full h-full object-contain"
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Center: Preview canvas (simplified — shows composited frame) */}
        <div className="flex-1 flex items-center justify-center bg-gray-950">
          <div className="text-gray-600 text-sm">
            Preview sẽ hiển thị ở đây
          </div>
        </div>

        {/* Right: Transform controls */}
        <div className="w-64 bg-gray-900 border-l border-gray-800 p-4 space-y-4 overflow-y-auto">
          <h3 className="text-xs text-gray-500 uppercase">
            Transform
          </h3>

          {/* Anchor */}
          <div>
            <label className="text-xs text-gray-400">Anchor X</label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={replacement.anchor.x}
              onChange={(e) =>
                setReplacement({
                  anchor: { ...replacement.anchor, x: Number(e.target.value) },
                })
              }
              className="w-full"
            />
            <span className="text-xs text-gray-500">
              {replacement.anchor.x.toFixed(2)}
            </span>
          </div>
          <div>
            <label className="text-xs text-gray-400">Anchor Y</label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={replacement.anchor.y}
              onChange={(e) =>
                setReplacement({
                  anchor: { ...replacement.anchor, y: Number(e.target.value) },
                })
              }
              className="w-full"
            />
            <span className="text-xs text-gray-500">
              {replacement.anchor.y.toFixed(2)}
            </span>
          </div>

          {/* Offset */}
          <div>
            <label className="text-xs text-gray-400">Offset X</label>
            <input
              type="range"
              min={-0.5}
              max={0.5}
              step={0.01}
              value={replacement.offset.x}
              onChange={(e) =>
                setReplacement({
                  offset: { ...replacement.offset, x: Number(e.target.value) },
                })
              }
              className="w-full"
            />
            <span className="text-xs text-gray-500">
              {replacement.offset.x.toFixed(2)}
            </span>
          </div>
          <div>
            <label className="text-xs text-gray-400">Offset Y</label>
            <input
              type="range"
              min={-0.5}
              max={0.5}
              step={0.01}
              value={replacement.offset.y}
              onChange={(e) =>
                setReplacement({
                  offset: { ...replacement.offset, y: Number(e.target.value) },
                })
              }
              className="w-full"
            />
            <span className="text-xs text-gray-500">
              {replacement.offset.y.toFixed(2)}
            </span>
          </div>

          {/* Scale */}
          <div>
            <label className="text-xs text-gray-400">Scale</label>
            <input
              type="range"
              min={0.1}
              max={3}
              step={0.05}
              value={replacement.scale}
              onChange={(e) =>
                setReplacement({ scale: Number(e.target.value) })
              }
              className="w-full"
            />
            <span className="text-xs text-gray-500">
              {replacement.scale.toFixed(2)}×
            </span>
          </div>

          {/* Rotation */}
          <div>
            <label className="text-xs text-gray-400">Xoay bổ sung (°)</label>
            <input
              type="range"
              min={-180}
              max={180}
              step={1}
              value={replacement.rotation_offset_deg}
              onChange={(e) =>
                setReplacement({
                  rotation_offset_deg: Number(e.target.value),
                })
              }
              className="w-full"
            />
            <span className="text-xs text-gray-500">
              {replacement.rotation_offset_deg}°
            </span>
          </div>

          {/* Opacity */}
          <div>
            <label className="text-xs text-gray-400">Độ mờ</label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={replacement.opacity}
              onChange={(e) =>
                setReplacement({ opacity: Number(e.target.value) })
              }
              className="w-full"
            />
            <span className="text-xs text-gray-500">
              {(replacement.opacity * 100).toFixed(0)}%
            </span>
          </div>

          {/* Fit mode */}
          <div>
            <label className="text-xs text-gray-400">Fit mode</label>
            <div className="grid grid-cols-3 gap-1 mt-1">
              {(["contain", "cover", "stretch"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setReplacement({ fit_mode: mode })}
                  className={`px-2 py-1 text-xs rounded ${
                    replacement.fit_mode === mode
                      ? "bg-blue-600 text-white"
                      : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                  }`}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>

          {/* Actions */}
          <div className="space-y-1 pt-2">
            <button
              onClick={() => settingsMut.mutate()}
              disabled={settingsMut.isPending}
              className="w-full py-2 text-sm bg-green-700 hover:bg-green-600 disabled:bg-gray-800 rounded"
            >
              {settingsMut.isPending ? "Đang lưu..." : "Áp dụng"}
            </button>
            <button
              onClick={() => {
                resetReplacement();
              }}
              className="w-full py-2 text-sm bg-gray-800 hover:bg-gray-700 rounded"
            >
              Đặt lại
            </button>
            <button
              onClick={() => setScreen("render")}
              className="w-full py-2 text-sm bg-blue-700 hover:bg-blue-600 rounded"
            >
              Tiếp: Render →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
