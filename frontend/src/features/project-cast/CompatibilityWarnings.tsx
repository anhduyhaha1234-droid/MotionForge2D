"use client";

import type { CompatibilityEvaluateResponse, CompatibilityReason } from "@/lib/api";

interface Props {
  result: CompatibilityEvaluateResponse | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

const VI_LABEL: Record<CompatibilityReason, string> = {
  workspace_mismatch: "Workspace không khớp",
  source_overlay_refusal: "Không thể dùng source_overlay",
  object_kind_mismatch: "Loại đối tượng không khớp",
  incomplete_pack: "Pack chưa hoàn chỉnh",
  unpublished_pack: "Pack chưa xuất bản",
  missing_required_pose: "Thiếu pose bắt buộc",
  missing_required_capability: "Thiếu capability bắt buộc",
  generation_mismatch: "Thế hệ dữ liệu không khớp",
  stale_revision: "Phiên bản đã cũ (stale revision)",
};

const VI_HELP: Record<CompatibilityReason, string> = {
  workspace_mismatch: "Pack và role phải cùng workspace. Kiểm tra lại workspace.",
  source_overlay_refusal: "Role source_overlay là lớp xóa, không thể thay thế bằng character.",
  object_kind_mismatch: "Role kind và character_type không tương thích — chọn pack đúng loại.",
  incomplete_pack: "Pack thiếu asset — cần bổ sung pose trước khi dùng.",
  unpublished_pack: "Chỉ pack đã published mới được ghim. Hãy xuất bản pack.",
  missing_required_pose: "Pack thiếu pose cần cho role này.",
  missing_required_capability: "Pack thiếu capability (ví dụ symmetry) cho role.",
  generation_mismatch: "Generation của role và pack không khớp — cần re-analysis hoặc pack mới.",
  stale_revision: "Mapping đã thay đổi ở nơi khác. Tải lại và thử lại.",
};

export function CompatibilityWarnings({ result, loading, error, onRetry }: Props) {
  if (loading) {
    return (
      <div className="p-3 bg-gray-800 border border-gray-700 rounded text-sm text-gray-400" data-testid="compat-loading">
        Đang kiểm tra tương thích...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col gap-2 p-3 bg-red-900/20 border border-red-700 rounded" data-testid="compat-error">
        <p className="text-sm text-red-300">Lỗi kiểm tra: {error}</p>
        <p className="text-[11px] text-gray-400">Thử lại kiểm tra tương thích.</p>
        {onRetry && (
          <button onClick={onRetry} className="self-start px-3 py-1.5 bg-red-700 hover:bg-red-600 text-white rounded text-sm focus:outline-none focus:ring-2 focus:ring-red-400" data-testid="compat-retry">
            Thử lại
          </button>
        )}
      </div>
    );
  }

  if (!result) {
    return (
      <div className="p-3 bg-gray-800 border border-gray-700 rounded" data-testid="compat-empty">
        <p className="text-sm text-gray-400">Chưa chọn pack — chọn một phiên bản để xem cảnh báo tương thích.</p>
        <p className="text-[11px] text-gray-400">Thông báo sẽ hiện sau khi chọn Pack Version ID.</p>
      </div>
    );
  }

  if (result.compatible) {
    return (
      <div className="p-3 bg-emerald-900/20 border border-emerald-700 rounded" data-testid="compat-compatible">
        <p className="text-sm text-emerald-300">✓ Tương thích — có thể ghim pack này.</p>
        <p className="text-[11px] text-gray-400">Không có cảnh báo. Nhấn Ghim để tạo mapping.</p>
        {result.pinned_version_id && <p className="text-[11px] text-gray-400">Pinned hiện tại: {result.pinned_version_id}</p>}
      </div>
    );
  }

  const isBlocked = result.blocked;
  const fallback = result.fallback_allowed;

  return (
    <div className={`flex flex-col gap-3 p-3 rounded border ${isBlocked && !fallback ? "bg-red-900/20 border-red-700" : "bg-amber-900/20 border-amber-700"}`} data-testid="compat-warnings">
      <div className="flex items-center gap-2">
        <span className={`text-sm font-medium ${isBlocked && !fallback ? "text-red-300" : "text-amber-300"}`}>
          {isBlocked && !fallback ? "✗ Không tương thích — bị chặn" : "⚠ Cảnh báo tương thích"}
        </span>
        {fallback && <span className="text-[11px] px-2 py-0.5 rounded bg-amber-800 text-amber-200" data-testid="compat-fallback-badge">Có fallback</span>}
      </div>

      <ul className="flex flex-col gap-1.5" data-testid="compat-reason-list">
        {result.reasons.map((r) => (
          <li key={r} className="flex flex-col gap-0.5 p-2 bg-gray-800 rounded border border-gray-700" data-testid={`compat-reason-${r}`}>
            <span className="text-sm text-gray-200">{VI_LABEL[r] ?? r}</span>
            <span className="text-[11px] text-gray-400">{VI_HELP[r] ?? ""}</span>
            <span className="text-[10px] text-gray-500 font-mono">{r}</span>
          </li>
        ))}
      </ul>

      {fallback && result.fallback_description && (
        <div className="p-2 bg-gray-800 border border-gray-600 rounded" data-testid="compat-fallback">
          <p className="text-sm text-gray-200">Fallback cho phép: {result.fallback_description}</p>
          <p className="text-[11px] text-gray-400">Pack thiếu một phần nhưng có thể dùng tư thế mặc định. Xác nhận để tiếp tục.</p>
        </div>
      )}

      {isBlocked && !fallback && (
        <div className="p-2 bg-red-900/30 border border-red-600 rounded" data-testid="compat-blocked">
          <p className="text-sm text-red-300">Không thể ghim — fallback không hỗ trợ, hệ thống fail closed.</p>
          <p className="text-[11px] text-gray-400">Chọn pack khác tương thích để tiếp tục. Không có nearest-match tự động.</p>
        </div>
      )}

      {!isBlocked && fallback && (
        <p className="text-[11px] text-gray-400">Có thể ghim với fallback hiển thị ở trên — hành động sẽ lưu fallback rõ ràng.</p>
      )}

      {result.pinned_version_id && (
        <p className="text-[11px] text-gray-400" data-testid="compat-pinned">
          Phiên bản đang ghim: {result.pinned_version_id}
        </p>
      )}
      {onRetry && (
        <button onClick={onRetry} className="self-start px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-100 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" data-testid="compat-warnings-retry">
          Kiểm tra lại
        </button>
      )}
    </div>
  );
}

export { VI_LABEL, VI_HELP };
