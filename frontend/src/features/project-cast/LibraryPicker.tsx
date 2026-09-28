"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState, useCallback, useRef } from "react";
import { api, ApiError, type PickerPackItem } from "@/lib/api";

interface LibraryPickerProps {
  pinnedVersionId?: string | null;
  selectedVersionId?: string | null;
  onSelect: (pack: PickerPackItem) => void;
  autoFocus?: boolean;
}

const REASON_VI: Record<string, string> = {
  workspace_mismatch: "Workspace không khớp — pack/role không thuộc workspace hiện tại",
  source_overlay_refusal: "Không thể dùng role source_overlay làm cast thay thế",
  object_kind_mismatch: "Loại đối tượng không khớp với loại nhân vật",
  incomplete_pack: "Pack chưa đủ dữ liệu (thiếu pose)",
  unpublished_pack: "Pack chưa xuất bản — không thể dùng",
  missing_required_pose: "Thiếu pose bắt buộc",
  missing_required_capability: "Thiếu capability bắt buộc",
  generation_mismatch: "Thế hệ dữ liệu (generation) không khớp",
  stale_revision: "Phiên bản mapping đã cũ — cần tải lại",
};

export function LibraryPicker({ pinnedVersionId, selectedVersionId, onSelect, autoFocus }: LibraryPickerProps) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [packs, setPacks] = useState<PickerPackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [phase, setPhase] = useState<"idle" | "loading" | "error" | "empty" | "ready">("idle");
  const [errorText, setErrorText] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(async () => {
    setPhase("loading");
    setErrorText(null);
    try {
      const res = await api.listPickerPacks({ q: debounced || undefined, limit: 50, offset: 0 });
      setPacks(res.packs);
      setTotal(res.total);
      if (res.packs.length === 0) setPhase("empty");
      else setPhase("ready");
    } catch (err) {
      setPhase("error");
      setErrorText(err instanceof ApiError ? err.detailText() || err.message : String(err));
    }
  }, [debounced]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  const handleKeyDown = (e: React.KeyboardEvent, pack: PickerPackItem, index: number) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(pack);
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.min(packs.length - 1, index + 1);
      setFocusedIndex(next);
      document.getElementById(`picker-item-${next}`)?.focus();
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = Math.max(0, index - 1);
      setFocusedIndex(prev);
      document.getElementById(`picker-item-${prev}`)?.focus();
    }
  };

  return (
    <div className="flex flex-col gap-3 p-4 bg-gray-900 rounded-lg border border-gray-700" data-testid="library-picker">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-medium text-gray-200">Thư viện Pack — Chọn phiên bản</h3>
        <p className="text-[11px] text-gray-400">Chỉ hiển thị pack đã xuất bản (published). Tìm theo tên hoặc mã nhân vật. Chọn đúng Pack Version ID.</p>
      </div>

      <div className="flex gap-2">
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Tìm kiếm pack..."
          aria-label="Tìm kiếm pack"
          className="flex-1 px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          data-testid="picker-search-input"
        />
        <button
          onClick={load}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-100 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          data-testid="picker-retry"
        >
          Tìm
        </button>
      </div>
      <p className="text-[11px] text-gray-400">Nhập từ khóa và nhấn Tìm để lọc. Chỉ pack published mới hiện.</p>

      {phase === "loading" && (
        <div className="py-8 text-center text-sm text-gray-400" data-testid="picker-loading">
          Đang tải pack...
        </div>
      )}

      {phase === "error" && (
        <div className="flex flex-col gap-2 p-3 bg-red-900/20 border border-red-700 rounded" data-testid="picker-error">
          <p className="text-sm text-red-300">Lỗi tải pack: {errorText}</p>
          <p className="text-[11px] text-gray-400">Kiểm tra kết nối và thử lại.</p>
          <button
            onClick={load}
            className="self-start px-3 py-1.5 bg-red-700 hover:bg-red-600 text-white rounded text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
            data-testid="picker-error-retry"
          >
            Thử lại
          </button>
          <span className="text-[11px] text-gray-400">Nhấn Thử lại để tải lại danh sách.</span>
        </div>
      )}

      {phase === "empty" && (
        <div className="flex flex-col gap-2 py-8 text-center" data-testid="picker-empty">
          <p className="text-sm text-gray-400">Không có pack nào phù hợp.</p>
          <p className="text-[11px] text-gray-400">Thử đổi từ khóa hoặc tạo pack mới và xuất bản.</p>
          <button
            onClick={() => {
              setQuery("");
              setDebounced("");
            }}
            className="self-center px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-100 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            data-testid="picker-empty-retry"
          >
            Xóa bộ lọc
          </button>
          <span className="text-[11px] text-gray-400">
            Nhấn Xóa bộ lọc để xem lại toàn bộ pack đã xuất bản.
          </span>
        </div>
      )}

      {phase === "ready" && (
        <div className="flex flex-col gap-2">
          <p className="text-[11px] text-gray-400" data-testid="picker-count">
            Tìm thấy {total} pack — chọn đúng Pack Version ID (không chỉ Character).
          </p>
          <div className="flex flex-col gap-2 max-h-96 overflow-y-auto pr-1" role="listbox" aria-label="Danh sách pack" data-testid="picker-list">
            {packs.map((pack, idx) => {
              const isPinned = pinnedVersionId && pack.id === pinnedVersionId;
              const isSelected = selectedVersionId && pack.id === selectedVersionId;
              return (
                <div
                  key={pack.id}
                  id={`picker-item-${idx}`}
                  role="option"
                  tabIndex={0}
                  aria-selected={isSelected ? "true" : "false"}
                  onClick={() => onSelect(pack)}
                  onKeyDown={(e) => handleKeyDown(e, pack, idx)}
                  className={`flex flex-col gap-1 p-3 rounded border cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500 ${isSelected ? "bg-indigo-900/30 border-indigo-600" : "bg-gray-800 border-gray-700 hover:bg-gray-700/80"} ${focusedIndex === idx ? "ring-2 ring-indigo-500" : ""}`}
                  data-testid={`picker-item-${pack.id}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-100">{pack.character_name}</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-gray-700 text-gray-300">{pack.character_code}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    <span>Version {pack.version}</span>
                    <span>•</span>
                    <span className="text-emerald-400">{pack.status}</span>
                    <span>•</span>
                    <span>{pack.asset_count} poses</span>
                  </div>
                  <div className="text-[11px] text-gray-400 font-mono break-all">PackVersion ID: {pack.id}</div>
                  {isPinned && (
                    <span className="self-start text-[11px] px-2 py-0.5 rounded bg-amber-900/30 border border-amber-700 text-amber-300" data-testid={`pinned-${pack.id}`}>
                      Đang ghim (pinned)
                    </span>
                  )}
                  {isSelected && (
                    <span className="self-start text-[11px] px-2 py-0.5 rounded bg-indigo-900/50 border border-indigo-600 text-indigo-300" data-testid={`selected-${pack.id}`}>
                      Đã chọn
                    </span>
                  )}
                  <p className="text-[11px] text-gray-400">Nhấn Enter hoặc click để chọn phiên bản này. Chỉ PackVersion ID mới được ghim.</p>
                </div>
              );
            })}
          </div>
          {/* Desktop + 390px layout hint */}
          <p className="text-[11px] text-gray-400">Giao diện tương thích desktop và 390px. Dùng Tab/Enter để điều hướng bàn phím.</p>
        </div>
      )}
    </div>
  );
}

export { REASON_VI };
