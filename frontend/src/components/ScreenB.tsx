"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type SelectionInput } from "@/lib/api";
import { useProjectStore } from "@/stores/project";
import {
  createViewportTransform,
  canvasToSource,
  sourceToCanvas,
  scaleToCanvas,
} from "@/lib/coordinates";

type Tool = "point" | "negative" | "bbox";

export function ScreenB() {
  const {
    projectId,
    project,
    currentFrame,
    setCurrentFrame,
    selection,
    setSelection,
    maskPreview,
    setMaskPreview,
    setActiveObject,
    setScreen,
  } = useProjectStore();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState<Tool>("point");
  const [points, setPoints] = useState<{ x: number; y: number; label: number }[]>([]);
  const [bbox, setBbox] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const maskImageRef = useRef<HTMLImageElement | null>(null);
  const [autoObjects, setAutoObjects] = useState<Array<{
    object_index: number;
    bbox: { x: number; y: number; width: number; height: number };
    area: number;
  }>>([]);
  const [isAutoSegmenting, setIsAutoSegmenting] = useState(false);

  const meta = project?.video_metadata;
  const frameUrl = projectId
    ? api.getFrameUrl(projectId, currentFrame)
    : null;

  // Load frame image
  useEffect(() => {
    if (!frameUrl) return;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      imageRef.current = img;
      setImageLoaded(true);
    };
    img.src = frameUrl;
  }, [frameUrl]);

  // Load mask preview
  useEffect(() => {
    if (!maskPreview) {
      maskImageRef.current = null;
      return;
    }
    const img = new Image();
    img.onload = () => {
      maskImageRef.current = img;
      drawCanvas();
    };
    img.src = `data:image/png;base64,${maskPreview}`;
  }, [maskPreview]);

  // Draw canvas
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const img = imageRef.current;
    if (!canvas || !container || !img || !meta) return;

    const rect = container.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const vt = createViewportTransform(
      meta.width,
      meta.height,
      canvas.width,
      canvas.height,
    );

    // Clear
    ctx.fillStyle = "#111";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw frame
    const dw = meta.width * vt.scale;
    const dh = meta.height * vt.scale;
    ctx.drawImage(img, vt.offsetX, vt.offsetY, dw, dh);

    // Draw mask overlay
    const maskImg = maskImageRef.current;
    if (maskImg) {
      ctx.globalAlpha = 0.4;
      ctx.drawImage(maskImg, vt.offsetX, vt.offsetY, dw, dh);
      ctx.globalAlpha = 1.0;
    }

    // Draw points
    for (const pt of points) {
      const cp = sourceToCanvas(pt.x, pt.y, vt);
      ctx.beginPath();
      ctx.arc(cp.x, cp.y, 6, 0, Math.PI * 2);
      ctx.fillStyle = pt.label === 1 ? "#22c55e" : "#ef4444";
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Draw bbox
    if (bbox) {
      const tl = sourceToCanvas(bbox.x1, bbox.y1, vt);
      const br = sourceToCanvas(bbox.x2, bbox.y2, vt);
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 3]);
      ctx.strokeRect(tl.x, tl.y, br.x - tl.x, br.y - tl.y);
      ctx.setLineDash([]);
    }
  }, [meta, points, bbox, maskPreview]);

  useEffect(() => {
    drawCanvas();
  }, [drawCanvas, imageLoaded]);

  // Resize observer
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => drawCanvas());
    ro.observe(container);
    return () => ro.disconnect();
  }, [drawCanvas]);

  // Canvas click handler
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas || !meta) return;

      const rect = canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;

      const vt = createViewportTransform(
        meta.width,
        meta.height,
        canvas.width,
        canvas.height,
      );
      const src = canvasToSource(cx, cy, vt);

      if (tool === "point") {
        setPoints((prev) => [...prev, { x: src.x, y: src.y, label: 1 }]);
      } else if (tool === "negative") {
        setPoints((prev) => [...prev, { x: src.x, y: src.y, label: 0 }]);
      }
    },
    [meta, tool],
  );

  // Bbox drag
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (tool !== "bbox") return;
      const canvas = canvasRef.current;
      if (!canvas || !meta) return;
      const rect = canvas.getBoundingClientRect();
      const vt = createViewportTransform(meta.width, meta.height, canvas.width, canvas.height);
      const src = canvasToSource(e.clientX - rect.left, e.clientY - rect.top, vt);
      setBbox({ x1: src.x, y1: src.y, x2: src.x, y2: src.y });
      setIsDragging(true);
    },
    [meta, tool],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!isDragging || tool !== "bbox" || !bbox) return;
      const canvas = canvasRef.current;
      if (!canvas || !meta) return;
      const rect = canvas.getBoundingClientRect();
      const vt = createViewportTransform(meta.width, meta.height, canvas.width, canvas.height);
      const src = canvasToSource(e.clientX - rect.left, e.clientY - rect.top, vt);
      setBbox({ ...bbox, x2: src.x, y2: src.y });
    },
    [isDragging, meta, tool, bbox],
  );

  const handleMouseUp = useCallback(() => setIsDragging(false), []);

  // Preview mask mutation
  const previewMut = useMutation({
    mutationFn: async () => {
      if (!projectId) return;
      const sel = buildSelection();
      if (!sel) return;
      const result = await api.previewMask(projectId, {
        frame_index: currentFrame,
        selection: sel,
        backend: "sam2",
      });
      setMaskPreview(result.mask_png_base64);
    },
  });

  // Accept mask → create object → propagate
  const acceptMut = useMutation({
    mutationFn: async () => {
      if (!projectId) return;
      const sel = buildSelection();
      if (!sel) return;

      // Create object
      const obj = await api.createObject(projectId, {
        name: "Object 1",
        selection: sel,
        scene_id: 0,
      });
      setActiveObject(obj);

      // Propagate
      const { job_id } = await api.propagateObject(projectId, obj.object_id);

      // Poll
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const job = await api.getJob(job_id);
        if (job.status === "completed") {
          const updated = await api.getObject(projectId, obj.object_id);
          setActiveObject(updated);
          setScreen("review");
          return;
        }
        if (job.status === "failed") throw new Error(job.message);
      }
    },
  });

  function buildSelection(): SelectionInput | null {
    if (tool === "bbox" && bbox) {
      return {
        mode: "bounding_box",
        frame_index: currentFrame,
        x: Math.min(bbox.x1, bbox.x2),
        y: Math.min(bbox.y1, bbox.y2),
        width: Math.abs(bbox.x2 - bbox.x1),
        height: Math.abs(bbox.y2 - bbox.y1),
      };
    }
    if (points.length > 0) {
      const lastPos = points.filter((p) => p.label === 1).pop();
      if (lastPos) {
        return {
          mode: "point",
          frame_index: currentFrame,
          x: lastPos.x,
          y: lastPos.y,
        };
      }
    }
    return null;
  }

  const clearPrompts = () => {
    setPoints([]);
    setBbox(null);
    setMaskPreview(null);
  };

  const handleAutoSegment = async () => {
    if (!projectId) return;
    setIsAutoSegmenting(true);
    try {
      const result = await api.autoSegmentObjects(projectId, 0);
      setAutoObjects(result.objects);
    } catch (err) {
      alert(`Lỗi: ${(err as Error).message}`);
    } finally {
      setIsAutoSegmenting(false);
    }
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800">
        <h2 className="text-sm font-medium">Chọn vật thể</h2>
        <div className="flex items-center gap-2 text-sm text-gray-400">
          {meta && (
            <span>
              {meta.width}×{meta.height} • {meta.fps}fps • Frame{" "}
              {currentFrame}/{meta.total_frames - 1}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: Object list (empty for now) */}
        <div className="w-48 bg-gray-900 border-r border-gray-800 p-3">
          <h3 className="text-xs text-gray-500 uppercase mb-2">Vật thể</h3>
          <p className="text-xs text-gray-600">Chưa có vật thể nào</p>
        </div>

        {/* Center: Canvas */}
        <div ref={containerRef} className="flex-1 relative">
          <canvas
            ref={canvasRef}
            className="absolute inset-0 cursor-crosshair"
            onClick={handleCanvasClick}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
          />
        </div>

        {/* Right: Tools */}
        <div className="w-56 bg-gray-900 border-l border-gray-800 p-3 space-y-4">
          <div>
            <h3 className="text-xs text-gray-500 uppercase mb-2">
              Công cụ chọn
            </h3>
            <div className="grid grid-cols-2 gap-1">
              {(["point", "negative", "bbox"] as Tool[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setTool(t)}
                  className={`px-2 py-1.5 text-xs rounded ${
                    tool === t
                      ? "bg-blue-600 text-white"
                      : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                  }`}
                >
                  {t === "point"
                    ? "Điểm +"
                    : t === "negative"
                    ? "Điểm −"
                    : "Hộp"}
                </button>
              ))}
              <button
                onClick={clearPrompts}
                className="px-2 py-1.5 text-xs rounded bg-gray-800 text-gray-300 hover:bg-gray-700"
              >
                Xóa
              </button>
            </div>
          </div>

          <div className="space-y-1">
            <button
              onClick={() => previewMut.mutate()}
              disabled={previewMut.isPending || points.length === 0 && !bbox}
              className="w-full py-2 text-sm bg-gray-800 hover:bg-gray-700 disabled:bg-gray-900 disabled:text-gray-600 rounded"
            >
              {previewMut.isPending ? "Đang tạo mask..." : "Xem mask"}
            </button>

            <button
              onClick={() => acceptMut.mutate()}
              disabled={
                acceptMut.isPending || (!maskPreview && points.length === 0 && !bbox)
              }
              className="w-full py-2 text-sm bg-green-700 hover:bg-green-600 disabled:bg-gray-900 disabled:text-gray-600 rounded"
            >
              {acceptMut.isPending ? "Đang tách object..." : "Chấp nhận & Tách"}
            </button>
          </div>

          {/* Auto-Segment */}
          <div className="space-y-2">
            <button
              onClick={handleAutoSegment}
              disabled={isAutoSegmenting}
              className="w-full px-3 py-2 text-xs bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 rounded transition-colors"
            >
              {isAutoSegmenting ? "Đang quét..." : "🪄 Tự Động Bắt Tất Cả Nhân Vật"}
            </button>
            {autoObjects.length > 0 && (
              <div className="mt-3 space-y-1 max-h-40 overflow-y-auto">
                <p className="text-xs text-gray-400 mb-1">Phát hiện {autoObjects.length} vật thể:</p>
                {autoObjects.map((obj) => (
                  <button
                    key={obj.object_index}
                    onClick={() => {
                      // Set selection to this object's bbox centroid
                      setSelection({
                        mode: "bounding_box",
                        frame_index: currentFrame,
                        x: obj.bbox.x,
                        y: obj.bbox.y,
                        width: obj.bbox.width,
                        height: obj.bbox.height,
                      });
                    }}
                    className="w-full text-left px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded text-xs"
                  >
                    Vật thể #{obj.object_index + 1} — {obj.bbox.width}×{obj.bbox.height}px
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Frame slider */}
          <div>
            <h3 className="text-xs text-gray-500 uppercase mb-2">
              Frame
            </h3>
            <input
              type="range"
              min={0}
              max={(meta?.total_frames ?? 1) - 1}
              value={currentFrame}
              onChange={(e) => setCurrentFrame(Number(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>0</span>
              <span>{(meta?.total_frames ?? 1) - 1}</span>
            </div>
          </div>

          {/* Points list */}
          {points.length > 0 && (
            <div>
              <h3 className="text-xs text-gray-500 uppercase mb-1">
                Điểm đã chọn ({points.length})
              </h3>
              <div className="max-h-32 overflow-y-auto text-xs text-gray-400 space-y-0.5">
                {points.map((p, i) => (
                  <div key={i} className="flex justify-between">
                    <span className={p.label === 1 ? "text-green-400" : "text-red-400"}>
                      {p.label === 1 ? "+" : "−"}({Math.round(p.x)},{Math.round(p.y)})
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
