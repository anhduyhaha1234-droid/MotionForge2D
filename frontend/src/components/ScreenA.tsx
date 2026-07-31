"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { useProjectStore } from "@/stores/project";
import { PresetManager } from "@/components/PresetManager";
import {
  Film,
  Upload,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  FolderOpen,
  ArrowRight,
  Layers,
  Wand2,
} from "lucide-react";

export function ScreenA() {
  const { projectId, setProjectId, setProject, setScreen } = useProjectStore();
  const [projectName, setProjectName] = useState("Dự án MotionForge 01");
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progressPercent, setProgressPercent] = useState(0);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  // File Selection
  const handleFileSelect = (file: File | null) => {
    if (!file) return;
    if (!file.name.match(/\.(mp4|mov|avi|mkv)$/i)) {
      setErrorMessage("Vui lòng chọn file video đúng định dạng MP4.");
      return;
    }
    setVideoFile(file);
    setErrorMessage(null);
  };

  // Drag & Drop Handlers
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFileSelect(files[0]);
    }
  };

  // Main Workflow Async Handler (Fixes race condition)
  const handleStartWorkflow = useCallback(async () => {
    if (!videoFile) return;

    setIsProcessing(true);
    setErrorMessage(null);
    setProgressPercent(10);
    setStatusMessage("Đang tạo dự án mới...");

    try {
      // Step 1: Create Project
      const projRes = await api.createProject(projectName);
      const newProjId = projRes.project_id;
      setProjectId(newProjId);
      setProgressPercent(30);

      // Step 2: Upload Video (Sanitized Filename on Backend)
      setStatusMessage("Đang tải video lên hệ thống...");
      await api.uploadVideo(newProjId, videoFile);
      setProgressPercent(50);

      // Step 3: Trigger Ingest & Scene Chunking
      setStatusMessage("Đang khởi chạy AI bóc tách phân cảnh & âm thanh...");
      const ingestRes = await api.triggerIngest(newProjId);
      setProgressPercent(60);

      // Step 4: Poll Job Status until Completion
      const maxAttempts = 300; // 5 minutes for long videos
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const job = await api.getJob(ingestRes.job_id);

        const currentProg = 60 + Math.round((job.progress || 0) * 0.35);
        setProgressPercent(Math.min(currentProg, 95));
        setStatusMessage(job.message || "Đang phân tích video...");

        if (job.status === "completed") {
          setProgressPercent(100);
          setStatusMessage("Phân tích hoàn tất! Đang chuyển sang bước tiếp theo...");
          const updatedProj = await api.getProject(newProjId);
          setProject(updatedProj);
          setTimeout(() => setScreen("selection"), 600);
          return;
        }

        if (job.status === "failed") {
          throw new Error(job.message || "Quá trình phân tích video bị thất bại.");
        }
      }

      throw new Error("Quá trình xử lý bị quá thời gian. Vui lòng thử lại.");
    } catch (err: any) {
      setIsProcessing(false);
      setProgressPercent(0);
      setErrorMessage(
        err.message || "Đã xảy ra lỗi không xác định khi kết nối với server."
      );
    }
  }, [videoFile, projectName, setProjectId, setProject, setScreen]);

  const fileSizeMB = videoFile
    ? (videoFile.size / (1024 * 1024)).toFixed(1)
    : "0";

  return (
    <div className="min-h-screen bg-[#0b0f19] text-slate-100 flex flex-col justify-between p-4 sm:p-8 font-sans selection:bg-blue-500 selection:text-white">
      {/* Background Decorative Glows */}
      <div className="fixed top-0 left-1/4 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="fixed bottom-0 right-1/4 w-96 h-96 bg-purple-600/10 rounded-full blur-3xl pointer-events-none" />

      {/* Header & Stepper */}
      <header className="max-w-5xl w-full mx-auto flex flex-col md:flex-row items-center justify-between gap-4 py-4 border-b border-slate-800/80">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <Film className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
              MotionForge 2D
            </h1>
            <p className="text-xs text-slate-400">
              Nền tảng Re-skin & Localize Video Hoạt Hình AI
            </p>
          </div>
        </div>

        {/* Workflow Step Bar */}
        <div className="flex items-center gap-2 bg-slate-900/80 border border-slate-800 px-4 py-2 rounded-full text-xs font-medium">
          <span className="flex items-center gap-1.5 text-blue-400 font-semibold">
            <span className="w-5 h-5 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-[10px]">
              1
            </span>
            Tải Video
          </span>
          <ArrowRight className="w-3.5 h-3.5 text-slate-600" />
          <span className="text-slate-500">2. Chọn Vật Thể</span>
          <ArrowRight className="w-3.5 h-3.5 text-slate-600" />
          <span className="text-slate-500">3. Duyệt Tách</span>
          <ArrowRight className="w-3.5 h-3.5 text-slate-600" />
          <span className="text-slate-500">4. Thay Thế & Dịch Voice</span>
          <ArrowRight className="w-3.5 h-3.5 text-slate-600" />
          <span className="text-slate-500">5. Ghép MP4</span>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-4xl w-full mx-auto my-8 space-y-6">
        {/* Title Hero Banner */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-medium mb-2">
            <Sparkles className="w-3.5 h-3.5" /> Công nghệ AI SAM 2.1 + Local Inpainting + Dubbing
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
            Nhập Video & Bắt Đầu Dự Án Mới
          </h2>
          <p className="text-sm text-slate-400 max-w-xl mx-auto">
            Tải lên video 2D của đối thủ để tự động chia phân cảnh, bóc tách nhân vật và chuẩn bị lồng tiếng AI sang thị trường quốc tế.
          </p>
        </div>

        {/* Project Form & Drag-and-Drop Card */}
        <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl space-y-6">
          {/* Project Name Input */}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-300 flex items-center justify-between">
              <span>Tên dự án</span>
              <span className="text-[11px] text-slate-500 font-normal">Tự động đặt tên file khi lưu</span>
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="Nhập tên dự án..."
              className="w-full px-4 py-3 bg-slate-950/80 border border-slate-800 rounded-xl text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all text-sm font-medium"
            />
          </div>

          {/* Video Dropzone */}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-300 flex items-center justify-between">
              <span>Video Gốc MP4</span>
              <button
                type="button"
                onClick={() => setShowHelp(!showHelp)}
                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 transition-colors"
              >
                <HelpCircle className="w-3.5 h-3.5" /> Giải thích các nút?
              </button>
            </label>

            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`relative border-2 border-dashed rounded-2xl p-8 text-center transition-all duration-200 cursor-pointer ${
                isDragging
                  ? "border-blue-500 bg-blue-500/10 scale-[1.01]"
                  : videoFile
                  ? "border-emerald-500/50 bg-emerald-500/5"
                  : "border-slate-800 hover:border-slate-700 bg-slate-950/40 hover:bg-slate-950/80"
              }`}
            >
              <input
                type="file"
                accept=".mp4,.mov,.avi,.mkv,video/mp4"
                onChange={(e) => handleFileSelect(e.target.files?.[0] ?? null)}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />

              {videoFile ? (
                <div className="flex flex-col items-center justify-center space-y-3">
                  <div className="w-12 h-12 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                    <CheckCircle2 className="w-6 h-6" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-emerald-300 max-w-md truncate">
                      {videoFile.name}
                    </p>
                    <p className="text-xs text-slate-400 mt-1">
                      Kích thước: <span className="font-semibold text-slate-200">{fileSizeMB} MB</span> • Đã sẵn sàng phân tích
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setVideoFile(null);
                    }}
                    className="text-xs text-slate-400 hover:text-rose-400 underline transition-colors"
                  >
                    Chọn file khác
                  </button>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center space-y-3 py-4">
                  <div className="w-14 h-14 rounded-2xl bg-blue-600/10 text-blue-400 border border-blue-500/20 flex items-center justify-center shadow-inner">
                    <Upload className="w-7 h-7" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-200">
                      Kéo & thả file video MP4 vào đây
                    </p>
                    <p className="text-xs text-slate-400 mt-1">
                      Hoặc <span className="text-blue-400 font-semibold underline">duyệt tìm file</span> từ máy tính của bạn
                    </p>
                  </div>
                  <div className="flex items-center gap-3 text-[11px] text-slate-500">
                    <span>Hỗ trợ: MP4, MOV, AVI</span>
                    <span>•</span>
                    <span>Tốc độ tối ưu trên GPU RTX</span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Help Explanation Card (Collapsible) */}
          {showHelp && (
            <div className="bg-blue-950/40 border border-blue-800/40 rounded-xl p-4 text-xs space-y-2 text-blue-200">
              <h4 className="font-semibold text-blue-300 flex items-center gap-1.5 text-sm">
                <HelpCircle className="w-4 h-4" /> Hướng dẫn chức năng từng nút bấm:
              </h4>
              <ul className="space-y-1.5 list-disc list-inside text-slate-300">
                <li>
                  <strong className="text-blue-400">Nút "Bắt đầu Phân tích" (Start Process)</strong>: Tự động khởi chạy 3 tác vụ ngầm:
                  <ol className="list-decimal list-inside ml-4 text-slate-400 space-y-0.5">
                    <li>Lưu video an toàn vào thư mục dự án.</li>
                    <li>Chạy AI PySceneDetect chia nhỏ video thành từng Cảnh (Scene).</li>
                    <li>Bóc tách dải âm thanh gốc và chuẩn bị khung hình cho AI SAM 2.1.</li>
                  </ol>
                </li>
                <li>
                  <strong className="text-blue-400">Nút "Tải Preset"</strong>: Tự động gán cấu hình nhân vật/giọng đọc từ các video trước của cùng kênh đối thủ.
                </li>
              </ul>
            </div>
          )}

          {/* Error Banner */}
          {errorMessage && (
            <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-4 flex items-start gap-3 text-rose-300 text-xs">
              <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-semibold text-rose-200">Không thể thực hiện:</p>
                <p className="text-slate-300">{errorMessage}</p>
              </div>
            </div>
          )}

          {/* Progress Bar Area */}
          {isProcessing && (
            <div className="space-y-2 bg-slate-950/60 border border-slate-800 p-4 rounded-xl">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-blue-400 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-blue-500 animate-ping" />
                  {statusMessage}
                </span>
                <span className="font-bold text-slate-200">{progressPercent}%</span>
              </div>
              <div className="w-full h-2.5 bg-slate-800 rounded-full overflow-hidden p-0.5">
                <div
                  className="h-full bg-gradient-to-r from-blue-600 via-indigo-500 to-purple-500 rounded-full transition-all duration-300 shadow-sm shadow-blue-500/50"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>
          )}

          {/* Action Button */}
          <button
            type="button"
            onClick={handleStartWorkflow}
            disabled={!videoFile || isProcessing}
            className="w-full py-4 px-6 bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white font-bold rounded-xl shadow-lg shadow-blue-600/25 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none transition-all flex items-center justify-center gap-2 text-sm uppercase tracking-wider"
          >
            {isProcessing ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Đang xử lý phân tích...
              </>
            ) : (
              <>
                <Wand2 className="w-4 h-4" /> Bắt Đầu Phân Tích Video
              </>
            )}
          </button>
        </div>

        {/* Preset Manager Integration */}
        {projectId && (
          <div className="bg-slate-900/40 border border-slate-800/80 rounded-2xl p-6 shadow-lg">
            <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
              <Layers className="w-4 h-4 text-purple-400" /> Quản Lý 1-Click Preset Cấu Hình
            </h3>
            <PresetManager />
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="text-center text-xs text-slate-600 py-4 border-t border-slate-900">
        MotionForge 2D Platform • 100% Local GPU Processing • Local-First Execution
      </footer>
    </div>
  );
}
