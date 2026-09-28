"use client";

/**
 * MF-END-10 — Bảng view tham chiếu của một phiên bản pack.
 *
 * Hiển thị: từng view (front/three_quarter/side/back/sitting/walking) × role
 * của pack, trạng thái thật (có ảnh / thiếu / chưa khai báo), và cho phép
 * NGAY TẠI UI:
 *  - tải ảnh tham chiếu lên  → POST /versions/{id}/reference-artwork
 *  - tạo ảnh còn thiếu       → POST /versions/{id}/reference-asset-jobs (job bền vững)
 *  - theo dõi / hủy / chạy lại job → GET|cancel|retry reference-asset-jobs
 *
 * Không hiển thị chi tiết nội bộ engine; chỉ trạng thái và lỗi hữu ích.
 * Mọi nút có helper text tiếng Việt ngay dưới (text-gray-400, ≥11px).
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  ImageOff,
  Loader2,
  RotateCcw,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { api, type CharacterAssetData } from "@/lib/api";
import {
  cancelReferenceAssetJob,
  getReferenceAssetJob,
  parseReferenceKey,
  referenceKeyOf,
  REFERENCE_VIEWS,
  retryReferenceAssetJob,
  roleLabel,
  submitReferenceAssetJob,
  uploadReferenceArtwork,
  viewLabel,
} from "./referenceLibraryApi";
import { httpErrorText, isTerminalJobState, jobStateLabel } from "./reasonText";

interface ReferenceViewBoardProps {
  versionId: string;
  versionNumber: number;
  versionStatus: string;
  assets: CharacterAssetData[];
  onChanged?: () => void;
}

interface TileState {
  key: string;
  view: string;
  role: string;
  asset: CharacterAssetData | null;
  /** true khi server báo key này nằm trong missing_slots của phiên bản. */
  missingRequired: boolean;
}

const tone = {
  ok: "text-[var(--success)]",
  warn: "text-[var(--warning)]",
  faint: "text-[var(--text-faint)]",
  error: "text-[var(--danger)]",
};

export function ReferenceViewBoard({
  versionId,
  versionNumber,
  versionStatus,
  assets,
  onChanged,
}: ReferenceViewBoardProps) {
  const isDraft = versionStatus === "draft";
  const queryClient = useQueryClient();

  const validationQuery = useQuery({
    queryKey: ["character-validation", versionId],
    queryFn: () => api.getPackVersionValidation(versionId),
  });

  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [prompt, setPrompt] = useState("");
  const [seedText, setSeedText] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobKey, setActiveJobKey] = useState<string | null>(null);

  const tiles = useMemo<TileState[]>(() => {
    const present = new Map<string, CharacterAssetData>();
    const roles = new Set<string>();
    for (const asset of assets) {
      const parsed = parseReferenceKey(asset.pose_slot);
      if (parsed) {
        present.set(asset.pose_slot, asset);
        roles.add(parsed.role);
      }
    }
    const missing = validationQuery.data?.missing_slots ?? [];
    for (const slot of missing) {
      const parsed = parseReferenceKey(slot);
      if (parsed) roles.add(parsed.role);
    }
    if (roles.size === 0) roles.add("character");
    const rows: TileState[] = [];
    for (const role of Array.from(roles).sort()) {
      for (const view of REFERENCE_VIEWS) {
        const key = referenceKeyOf(view, role);
        rows.push({
          key,
          view,
          role,
          asset: present.get(key) ?? null,
          missingRequired: missing.includes(key),
        });
      }
    }
    return rows;
  }, [assets, validationQuery.data]);

  const missingCount = tiles.filter((t) => t.missingRequired || t.asset === null).length;

  const uploadMutation = useMutation({
    mutationFn: (params: { key: string; file: File }) =>
      uploadReferenceArtwork(versionId, {
        reference_key: params.key,
        file: params.file,
      }),
    onSuccess: async (result) => {
      setErrorText(null);
      setNotice(
        `Đã nhập ảnh cho ${viewLabel(result.view)} (${roleLabel(result.role)})` +
          (result.replaced_existing ? " — thay ảnh cũ." : "."),
      );
      setFile(null);
      setExpandedKey(null);
      await queryClient.invalidateQueries({ queryKey: ["character-validation", versionId] });
      onChanged?.();
    },
    onError: (error: unknown) => {
      const message =
        error instanceof Error ? httpErrorText(0, error.message) : String(error);
      setErrorText(
        error instanceof Error && "status" in error
          ? httpErrorText((error as { status: number }).status, (error as Error).message)
          : message,
      );
    },
  });

  const jobMutation = useMutation({
    mutationFn: (params: { key: string }) =>
      submitReferenceAssetJob(versionId, {
        reference_key: params.key,
        view_prompt: prompt.trim(),
        seed: seedText.trim() === "" ? null : Number(seedText.trim()),
        idempotency_key: `${versionId}:${params.key}`,
      }),
    onSuccess: (result) => {
      setErrorText(null);
      setNotice(
        result.duplicate
          ? `Đã có job cho ${result.reference_key} — tiếp tục theo dõi.`
          : `Đã đưa ${result.reference_key} vào hàng đợi tạo ảnh.`,
      );
      setActiveJobId(result.job.job_id);
      setActiveJobKey(result.reference_key);
    },
    onError: (error: unknown) => {
      const withStatus = error as { status?: number };
      setErrorText(
        typeof withStatus.status === "number"
          ? httpErrorText(withStatus.status, (error as Error).message)
          : String(error),
      );
    },
  });

  const jobQuery = useQuery({
    queryKey: ["reference-asset-job", activeJobId],
    queryFn: () => getReferenceAssetJob(activeJobId as string),
    enabled: activeJobId != null,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state && isTerminalJobState(state) ? false : 4000;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelReferenceAssetJob(activeJobId as string),
    onSuccess: () => {
      setNotice("Đã gửi yêu cầu hủy job.");
      void jobQuery.refetch();
    },
    onError: (error: unknown) => {
      setErrorText(String(error));
    },
  });

  const retryMutation = useMutation({
    mutationFn: () =>
      retryReferenceAssetJob(
        activeJobId as string,
        `ui-retry-${Date.now().toString(36)}`,
      ),
    onSuccess: (result) => {
      setNotice(`Đã chạy lại job cho ${result.reference_key}.`);
      setActiveJobId(result.job.job_id);
    },
    onError: (error: unknown) => {
      setErrorText(String(error));
    },
  });

  const openPanel = (tile: TileState) => {
    setExpandedKey(tile.key);
    setFile(null);
    setErrorText(null);
    setNotice(null);
    setPrompt(
      `Ảnh tham chiếu view "${tile.view}" cho ${roleLabel(tile.role)} — ` +
        `giữ nhận dạng, trang phục và tỷ lệ cơ thể từ front@character.`,
    );
    setSeedText("");
  };

  const job = jobQuery.data ?? null;
  const jobRunning =
    job != null && !isTerminalJobState(job.state) && activeJobId != null;

  return (
    <section aria-label={`View tham chiếu pack v${versionNumber}`} className="mt-5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          View tham chiếu · v{versionNumber}
        </h4>
        <span className={`text-[11px] ${missingCount > 0 ? tone.warn : tone.ok}`}>
          {missingCount > 0 ? `Còn thiếu ${missingCount} view` : "Đủ mọi view hiển thị"}
        </span>
      </div>

      {validationQuery.isLoading && (
        <p className="text-[11px] text-gray-400">Đang tải trạng thái view…</p>
      )}
      {validationQuery.isError && (
        <div className="rounded-lg border border-red-700 bg-red-900/20 p-3" data-testid="ref-views-error">
          <p className="text-sm text-red-300">Không tải được trạng thái view của phiên bản.</p>
          <p className="mt-1 text-[11px] text-gray-400">Kiểm tra kết nối máy chủ rồi thử lại.</p>
          <button
            type="button"
            onClick={() => validationQuery.refetch()}
            className="mt-2 min-h-9 rounded bg-gray-700 px-3 text-sm text-gray-100 hover:bg-gray-600"
            data-testid="ref-views-retry"
          >
            Thử lại
          </button>
          <p className="mt-1 text-[11px] text-gray-400">
            Nhấn Thử lại để tải lại trạng thái view tham chiếu.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {tiles.map((tile) => {
          const ready = tile.asset != null && tile.asset.artifact_state === "ready";
          const previewUrl =
            tile.asset && ready ? api.getCharacterAssetContentUrl(tile.asset) : null;
          const isOpen = expandedKey === tile.key;
          return (
            <article
              key={tile.key}
              className="rounded-lg border border-[var(--surface-700)] bg-[var(--surface-850)] p-2"
              data-testid={`ref-tile-${tile.key}`}
            >
              <div className="aspect-square overflow-hidden rounded-md border border-[var(--surface-700)] bg-black/40">
                {previewUrl ? (
                  <img
                    src={previewUrl}
                    alt={`View ${viewLabel(tile.view)} của ${roleLabel(tile.role)}`}
                    className="h-full w-full object-contain"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-center">
                    <ImageOff aria-hidden="true" size={18} className="text-[var(--text-faint)]" />
                    <p className="px-1 text-[11px] text-[var(--text-faint)]">
                      {tile.asset == null
                        ? tile.missingRequired
                          ? "Thiếu (bắt buộc)"
                          : "Chưa có ảnh"
                        : `Artifact: ${tile.asset.artifact_state}`}
                    </p>
                  </div>
                )}
              </div>
              <div className="mt-2 flex items-center justify-between gap-1">
                <h5 className="text-xs font-semibold text-[var(--text-primary)]">
                  {viewLabel(tile.view)}
                </h5>
                <span className={`text-[11px] ${ready ? tone.ok : tone.faint}`}>
                  {roleLabel(tile.role)}
                </span>
              </div>
              <p className="mt-0.5 break-all font-mono text-[10px] text-gray-400">{tile.key}</p>

              <div className="mt-2 flex flex-col gap-1">
                <button
                  type="button"
                  disabled={!isDraft}
                  aria-expanded={isOpen}
                  onClick={() => (isOpen ? setExpandedKey(null) : openPanel(tile))}
                  className="min-h-9 rounded bg-[var(--surface-800)] px-3 text-xs text-[var(--text-primary)] hover:bg-[var(--surface-700)] disabled:cursor-not-allowed disabled:opacity-45"
                  data-testid={`ref-manage-${tile.key}`}
                >
                  {ready ? "Thay ảnh / tạo lại" : "Nhập ảnh hoặc tạo"}
                </button>
                <p className="text-[11px] text-gray-400">
                  {isDraft
                    ? "Mở để tải ảnh lên hoặc tạo bằng engine."
                    : "Phiên bản đã xuất bản — tạo phiên bản mới để sửa."}
                </p>
              </div>

              {isOpen && (
                <div
                  className="mt-2 rounded border border-[var(--surface-700)] bg-[var(--surface-900)] p-2"
                  onKeyDown={(event) => {
                    if (event.key === "Escape") setExpandedKey(null);
                  }}
                >
                  <label className="block text-[11px] text-gray-400" htmlFor={`file-${tile.key}`}>
                    Ảnh tham chiếu (PNG/JPG, không phải mask)
                  </label>
                  <input
                    id={`file-${tile.key}`}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                    className="mt-1 w-full text-[11px] text-[var(--text-secondary)]"
                    data-testid={`ref-file-${tile.key}`}
                  />
                  <button
                    type="button"
                    disabled={file == null || uploadMutation.isPending}
                    onClick={() => file && uploadMutation.mutate({ key: tile.key, file })}
                    className="mt-2 inline-flex min-h-9 w-full items-center justify-center gap-2 rounded bg-[var(--primary-600)] px-3 text-xs font-medium text-white hover:bg-[var(--primary-500)] disabled:cursor-not-allowed disabled:opacity-45"
                    data-testid={`ref-upload-${tile.key}`}
                  >
                    <Upload aria-hidden="true" size={14} />
                    {uploadMutation.isPending ? "Đang tải lên…" : "Tải ảnh lên"}
                  </button>
                  <p className="mt-1 text-[11px] text-gray-400">
                    Ảnh được kiểm tra định dạng ở máy chủ và gắn vào đúng key {tile.key}.
                  </p>

                  <label className="mt-3 block text-[11px] text-gray-400" htmlFor={`prompt-${tile.key}`}>
                    Prompt tạo ảnh (phải nêu rõ view “{tile.view}”, tối thiểu 20 ký tự)
                  </label>
                  <textarea
                    id={`prompt-${tile.key}`}
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    rows={3}
                    className="mt-1 w-full rounded border border-[var(--surface-700)] bg-[var(--surface-950)] p-2 text-xs text-[var(--text-primary)]"
                    data-testid={`ref-prompt-${tile.key}`}
                  />
                  <label className="mt-2 block text-[11px] text-gray-400" htmlFor={`seed-${tile.key}`}>
                    Seed (bỏ trống để máy chủ tự chọn)
                  </label>
                  <input
                    id={`seed-${tile.key}`}
                    type="text"
                    inputMode="numeric"
                    value={seedText}
                    onChange={(event) => setSeedText(event.target.value.replace(/[^0-9]/g, ""))}
                    className="mt-1 w-full rounded border border-[var(--surface-700)] bg-[var(--surface-950)] p-2 text-xs text-[var(--text-primary)]"
                    data-testid={`ref-seed-${tile.key}`}
                  />
                  <button
                    type="button"
                    disabled={
                      jobMutation.isPending ||
                      prompt.trim().length < 20 ||
                      !prompt.toLowerCase().includes(tile.view.toLowerCase())
                    }
                    onClick={() => jobMutation.mutate({ key: tile.key })}
                    className="mt-2 inline-flex min-h-9 w-full items-center justify-center gap-2 rounded bg-[var(--accent-500)] px-3 text-xs font-medium text-[var(--surface-950)] hover:bg-[var(--accent-400)] disabled:cursor-not-allowed disabled:opacity-45"
                    data-testid={`ref-generate-${tile.key}`}
                  >
                    <Sparkles aria-hidden="true" size={14} />
                    {jobMutation.isPending ? "Đang đăng ký…" : "Tạo ảnh còn thiếu"}
                  </button>
                  <p className="mt-1 text-[11px] text-gray-400">
                    Job chạy nền và lưu bền vững — có thể đóng trang rồi mở lại để xem tiếp.
                  </p>
                  <button
                    type="button"
                    onClick={() => setExpandedKey(null)}
                    className="mt-2 min-h-9 w-full rounded bg-[var(--surface-800)] px-3 text-xs text-[var(--text-primary)] hover:bg-[var(--surface-700)]"
                    data-testid={`ref-close-${tile.key}`}
                  >
                    Đóng
                  </button>
                  <p className="mt-1 text-[11px] text-gray-400">Nhấn Escape cũng đóng bảng này.</p>
                </div>
              )}
            </article>
          );
        })}
      </div>

      {activeJobId && (
        <div
          className="mt-3 rounded-lg border border-[var(--surface-700)] bg-[var(--surface-850)] p-3"
          data-testid="ref-job-panel"
        >
          <p className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
            {jobRunning ? (
              <Loader2 aria-hidden="true" size={14} className="animate-spin" />
            ) : (
              <CheckCircle2 aria-hidden="true" size={14} className={tone.ok} />
            )}
            Job {activeJobKey}: {job ? jobStateLabel(job.state) : "đang tải…"}
          </p>
          <p className="mt-1 break-all font-mono text-[10px] text-gray-400">ID: {activeJobId}</p>
          {job && (
            <p className="mt-1 text-[11px] text-gray-400">
              Tiến độ {Math.round((job.progress ?? 0) * 100)}%
              {job.message ? ` — ${job.message}` : ""}
            </p>
          )}
          {jobRunning && (
            <>
              <button
                type="button"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
                className="mt-2 inline-flex min-h-9 items-center gap-2 rounded bg-[var(--surface-800)] px-3 text-xs text-[var(--text-primary)] hover:bg-[var(--surface-700)] disabled:opacity-45"
                data-testid="ref-job-cancel"
              >
                <Ban aria-hidden="true" size={14} />
                Hủy job
              </button>
              <p className="mt-1 text-[11px] text-gray-400">
                Hủy sẽ dừng an toàn; kết quả dở dang không được ghim vào kho.
              </p>
            </>
          )}
          {job && isTerminalJobState(job.state) && job.state !== "completed" && (
            <>
              <button
                type="button"
                onClick={() => retryMutation.mutate()}
                disabled={retryMutation.isPending}
                className="mt-2 inline-flex min-h-9 items-center gap-2 rounded bg-[var(--surface-800)] px-3 text-xs text-[var(--text-primary)] hover:bg-[var(--surface-700)] disabled:opacity-45"
                data-testid="ref-job-retry"
              >
                <RotateCcw aria-hidden="true" size={14} />
                Chạy lại
              </button>
              <p className="mt-1 text-[11px] text-gray-400">
                Chạy lại dùng cùng content key — nếu đã có kết quả hợp lệ thì không tạo thêm.
              </p>
            </>
          )}
          <button
            type="button"
            onClick={() => {
              setActiveJobId(null);
              setActiveJobKey(null);
            }}
            className="mt-2 inline-flex min-h-9 items-center gap-2 rounded bg-[var(--surface-800)] px-3 text-xs text-[var(--text-primary)] hover:bg-[var(--surface-700)]"
            data-testid="ref-job-dismiss"
          >
            <X aria-hidden="true" size={14} />
            Ẩn bảng job
          </button>
          <p className="mt-1 text-[11px] text-gray-400">
            Ẩn chỉ đóng bảng theo dõi; job vẫn tiếp tục trên máy chủ.
          </p>
        </div>
      )}

      {notice && (
        <p role="status" className="mt-3 flex items-center gap-2 text-sm text-[var(--success)]" data-testid="ref-notice">
          <CheckCircle2 aria-hidden="true" size={14} />
          {notice}
        </p>
      )}
      {errorText && (
        <p role="alert" className="mt-2 flex items-start gap-2 text-sm text-[var(--danger)]" data-testid="ref-error">
          <AlertCircle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
          {errorText}
        </p>
      )}

      <p className="mt-3 text-[11px] text-gray-400">
        Điều hướng bàn phím: Tab chuyển focus, Enter/Space mở hoặc kích hoạt, Escape đóng bảng con.
      </p>
    </section>
  );
}
