"use client";

import { useCallback, useEffect, useState } from "react";
import {
  exportResult,
  isS12ExportCompleted,
  s12MediaUrl,
  type S12ExportResultPayload,
  type S12ExportRunStatusPayload,
} from "@/lib/s12-export-api";

const HELPER = "text-[11px] leading-snug text-gray-400";

interface ExportEvidenceProps {
  data: S12ExportRunStatusPayload | null;
  /** Only needed for C22 result fetch; the media URL is server-owned. */
  workspaceId?: string;
  projectId?: string;
}

function copyValue(value: string | null): string {
  return value ?? "—";
}

export function ExportEvidence({ data, workspaceId, projectId }: ExportEvidenceProps) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [result, setResult] = useState<S12ExportResultPayload | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);

  // C22-part positive access: fetch the server-owned result metadata only
  // when the run is completed; the media URL is resolved BY THE SERVER and
  // the panel NEVER invents a path/hash/URL of its own.
  const loadResult = useCallback(async () => {
    if (!data || !isS12ExportCompleted(data.status)) return;
    setResultError(null);
    try {
      const payload = await exportResult(data.run_id, workspaceId, projectId);
      setResult(payload);
    } catch (error: unknown) {
      setResult((prev) => (prev ? prev : null));
      setResultError(error instanceof Error ? error.message : "Không tải được kết quả export.");
    }
  }, [data, workspaceId, projectId]);

  useEffect(() => {
    if (data && isS12ExportCompleted(data.status)) {
      void loadResult();
    }
  }, [data, loadResult]);

  if (!data || !isS12ExportCompleted(data.status)) return null;

  const copyServerNote = async () => {
    setCopyError(null);
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(SERVER_OUTPUT_NOTE);
      setCopied(true);
    } catch {
      setCopied(false);
      setCopyError("Không thể sao chép ghi chú server trên trình duyệt này.");
    }
  };

  const mediaHref = result ? s12MediaUrl(result.media_url) : null;

  return (
    <section
      className="min-w-0 w-full rounded border border-emerald-800/60 bg-emerald-950/10 p-3 sm:p-4"
      data-testid="export-evidence"
      aria-label="Bằng chứng export hoàn tất"
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-emerald-200">Bằng chứng export hoàn tất</h2>
          <p className={HELPER}>Chỉ render khi status từ server là completed; không dùng file path để kết luận hoàn tất.</p>
        </div>
        <span className="rounded bg-emerald-900/30 px-2 py-1 text-xs font-medium text-emerald-300">COMPLETED</span>
      </div>

      <dl className="mt-4 grid min-w-0 grid-cols-1 gap-2 text-xs sm:grid-cols-2">
        <div className="min-w-0 rounded bg-gray-900/60 px-3 py-2">
          <dt className="text-gray-400">Identity</dt>
          <dd className="mt-1 break-all font-mono text-gray-200">
            run {data.run_id}<br />
            workspace {data.workspace_id}<br />
            project {data.project_id}<br />
            video {data.video_item_id}
          </dd>
        </div>
        <div className="min-w-0 rounded bg-gray-900/60 px-3 py-2">
          <dt className="text-gray-400">Attempt / revision</dt>
          <dd className="mt-1 break-words text-gray-200">{data.attempt} / {data.revision}</dd>
          <dt className="mt-2 text-gray-400">Job ID / state</dt>
          <dd className="mt-1 break-all font-mono text-gray-200">{copyValue(data.job_id)} / {copyValue(data.job_state)}</dd>
        </div>
      </dl>

      <div className="mt-4 min-w-0">
        <p className="text-xs font-medium text-gray-200">Chunk evidence</p>
        <div className="mt-2 min-w-0 overflow-hidden rounded border border-gray-800">
          <table className="w-full table-fixed text-left text-[11px] text-gray-300">
            <thead className="bg-gray-900/70 text-gray-400">
              <tr>
                <th className="w-[20%] px-2 py-1.5 font-medium">Chunk</th>
                <th className="w-[28%] px-2 py-1.5 font-medium">State</th>
                <th className="w-[24%] px-2 py-1.5 font-medium">Verified</th>
                <th className="w-[28%] px-2 py-1.5 font-medium">Attempt</th>
              </tr>
            </thead>
            <tbody>
              {data.chunks.length === 0 ? (
                <tr>
                  <td colSpan={4} className="break-words px-2 py-2 text-gray-500">Không có chunk record trong response.</td>
                </tr>
              ) : (
                data.chunks.map((chunk) => (
                  <tr key={`${chunk.chunk_index}-${chunk.attempt}`} className="border-t border-gray-800">
                    <td className="break-all px-2 py-1.5 font-mono">{chunk.chunk_index}</td>
                    <td className="break-words px-2 py-1.5">{chunk.state}</td>
                    <td className="break-words px-2 py-1.5">{chunk.verified === 1 ? "Có" : "Chưa"}</td>
                    <td className="break-words px-2 py-1.5">{chunk.attempt}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <p className={HELPER}>Mỗi dòng là chunk identity/state/verified/attempt nhận từ server.</p>
      </div>

      <div className="mt-4 min-w-0 rounded border border-emerald-700/50 bg-emerald-900/10 p-3">
        <p className="text-xs font-medium text-emerald-200">Kết quả export (server-owned)</p>
        {result ? (
          <div className="mt-2 min-w-0 space-y-2">
            <p className="break-all font-mono text-[11px] text-gray-300">
              {result.filename} · {(result.size_bytes / 1024).toFixed(1)} KB · {result.mime}
            </p>
            <video
              controls
              preload="metadata"
              data-testid="export-result-player"
              className="max-h-64 w-full rounded border border-gray-800 bg-black"
              src={mediaHref ?? undefined}
            />
            <div className="flex min-w-0 flex-col items-start gap-1">
              <a
                href={mediaHref ?? undefined}
                download={result.filename}
                className="min-h-9 rounded bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-600"
                data-testid="export-result-download"
              >
                Tải kết quả ({result.filename})
              </a>
              <p className={HELPER}>URL media do backend cấp (result.media_url); panel không tự xây hay suy diễn đường dẫn nào.</p>
            </div>
          </div>
        ) : resultError ? (
          <p className="mt-2 text-[11px] text-red-300" role="alert">
            Không tải được kết quả export: {resultError}
          </p>
        ) : (
          <p className="mt-2 text-[11px] text-gray-400">Đang tải thông tin kết quả từ server…</p>
        )}
      </div>

      <div className="mt-4 min-w-0 rounded border border-gray-700 bg-gray-900/50 p-3">
        <p className="break-words text-xs text-gray-200">{SERVER_OUTPUT_NOTE}</p>
        <div className="mt-2 flex flex-col items-start gap-1">
          <button
            type="button"
            onClick={() => void copyServerNote()}
            className="min-h-9 rounded bg-gray-700 px-3 py-1.5 text-xs font-medium text-gray-100 hover:bg-gray-600"
            data-testid="export-copy-output-note"
          >
            {copied ? "Đã sao chép ghi chú" : "Sao chép ghi chú server"}
          </button>
          <p className={HELPER}>Sao chép nguyên văn ghi chú về output server; media URL chỉ lấy từ server khi có.</p>
          {copyError && <p className="text-[11px] text-red-300" role="alert">{copyError}</p>}
        </div>
      </div>
    </section>
  );
}

const SERVER_OUTPUT_NOTE =
  "Đầu ra được backend ghi và xác nhận ở phía server. Bản ghi này chỉ mô tả output; mọi đường dẫn/URL media phải do server cấp qua result endpoint.";