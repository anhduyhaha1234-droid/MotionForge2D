"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ImageOff,
  Lock,
  RefreshCw,
  Rocket,
  Search,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  type CharacterData,
  type CharacterStatus,
  type PackVersionData,
  CORE_POSE_SLOTS,
  POSE_SLOT_LABELS,
  CHARACTER_STATUS_LABELS,
  PACK_STATUS_LABELS,
} from "@/lib/api";

const date = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium" }).format(new Date(value));

/* ─── Small presentational helpers ─────────────────────────────────────── */

function StatusBadge({ status }: { status: CharacterStatus }) {
  const palette: Record<CharacterStatus, string> = {
    draft: "bg-[var(--surface-800)] text-[var(--text-secondary)]",
    generating: "bg-[var(--surface-800)] text-[var(--accent-300)]",
    needs_review: "bg-[var(--surface-800)] text-[var(--warning)]",
    ready: "bg-[var(--success-strong)]/20 text-[var(--success)]",
    archived: "bg-[var(--surface-800)] text-[var(--text-faint)]",
  };
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${palette[status]}`}>
      {CHARACTER_STATUS_LABELS[status]}
    </span>
  );
}

function VersionBadge({ version }: { version: PackVersionData }) {
  if (version.status === "published") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-[var(--success-strong)]/20 px-2.5 py-1 text-xs font-medium text-[var(--success)]">
        <Lock aria-hidden="true" size={12} />
        {PACK_STATUS_LABELS[version.status]} · Bất biến
      </span>
    );
  }
  const palette: Record<string, string> = {
    draft: "bg-[var(--surface-800)] text-[var(--text-secondary)]",
    validating: "bg-[var(--surface-800)] text-[var(--accent-300)]",
    ready: "bg-[var(--surface-800)] text-[var(--success)]",
    archived: "bg-[var(--surface-800)] text-[var(--text-faint)]",
  };
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${palette[version.status] ?? ""}`}>
      {PACK_STATUS_LABELS[version.status]}
    </span>
  );
}

/** Honest pose-slot tile. Shows a real preview ONLY when the artifact is
 *  ready AND the image actually loads; otherwise an explicit placeholder —
 *  never a false ready state. */
function PoseSlotTile({ version, slot }: { version: PackVersionData; slot: string }) {
  const asset = version.assets.find((a) => a.pose_slot === slot);
  const label = POSE_SLOT_LABELS[slot as keyof typeof POSE_SLOT_LABELS] ?? slot;
  const [failed, setFailed] = useState(false);

  const canPreview =
    asset != null && asset.content_url != null && asset.artifact_state === "ready" && !failed;

  const previewUrl = asset ? api.getCharacterAssetContentUrl(asset) : null;

  return (
    <article className="rounded-lg border border-[var(--surface-700)] bg-[var(--surface-850)] p-2">
      <div className="aspect-square overflow-hidden rounded-md border border-[var(--surface-700)] bg-black/40">
        {canPreview && previewUrl ? (
          <img
            src={previewUrl}
            alt={`Tư thế ${label} của phiên bản v${version.version}`}
            className="h-full w-full object-contain"
            loading="lazy"
            onError={() => setFailed(true)}
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-center">
            <ImageOff aria-hidden="true" size={18} className="text-[var(--text-faint)]" />
            <p className="px-1 text-[11px] text-[var(--text-faint)]">
              {asset == null
                ? "Chưa có ảnh"
                : asset.artifact_state !== "ready"
                  ? `Artifact: ${asset.artifact_state}`
                  : "Ảnh không tải được"}
            </p>
          </div>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between gap-1">
        <h4 className="text-xs font-semibold text-[var(--text-primary)]">{label}</h4>
        <span
          className={`flex items-center gap-1 text-[11px] ${
            asset != null && asset.artifact_state === "ready"
              ? "text-[var(--success)]"
              : "text-[var(--text-faint)]"
          }`}
        >
          {asset != null && asset.artifact_state === "ready" ? (
            <CheckCircle2 aria-hidden="true" size={12} />
          ) : (
            <ImageOff aria-hidden="true" size={12} />
          )}
          {asset != null && asset.artifact_state === "ready" ? "Sẵn sàng" : "Thiếu"}
        </span>
      </div>
    </article>
  );
}

/* ─── Detail view ───────────────────────────────────────────────────────── */

function CharacterDetail({
  character,
  versions,
  loading,
}: {
  character: CharacterData;
  versions: PackVersionData[] | undefined;
  loading: boolean;
}) {
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const defaultVersionId = character.default_version_id;

  // Prefer the default (published) version; fall back to the newest draft.
  const effectiveVersionId =
    selectedVersionId ??
    (defaultVersionId && versions?.some((v) => v.id === defaultVersionId)
      ? defaultVersionId
      : versions?.[0]?.id) ??
    null;

  const selectedVersion = versions?.find((v) => v.id === effectiveVersionId) ?? null;

  const validationQuery = useQuery({
    queryKey: ["character-validation", effectiveVersionId],
    queryFn: () => api.getPackVersionValidation(effectiveVersionId!),
    enabled: effectiveVersionId != null,
  });

  // ── S06-T05: Pack Review & Publish UX ─────────────────────────────────

  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  type PublishFeedback = {
    kind: "success" | "validation" | "conflict" | "error";
    message: string;
    missingSlots?: string[];
    errors?: string[];
  };
  const [feedback, setFeedback] = useState<PublishFeedback | null>(null);

  const publishMutation = useMutation({
    mutationFn: ({ versionId, revision }: { versionId: string; revision: number }) =>
      api.publishCharacterVersion(versionId, revision),
    onSuccess: async () => {
      // Refetch character (default version/status may change), the versions
      // list, and the authoritative validation state for this version.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["characters"] }),
        queryClient.invalidateQueries({ queryKey: ["character-versions", character.id] }),
        queryClient.invalidateQueries({ queryKey: ["character-validation", selectedVersion?.id] }),
      ]);
      setFeedback({
        kind: "success",
        message: `Đã xuất bản phiên bản v${selectedVersion?.version}. Phiên bản này giờ là bất biến.`,
      });
    },
    onError: (error: Error) => {
      if (error instanceof ApiError && error.status === 422) {
        const detail = (error.detail ?? {}) as {
          message?: string;
          missing_slots?: string[];
          errors?: string[];
        };
        setFeedback({
          kind: "validation",
          message: detail.message ?? "Không thể xuất bản: phiên bản không hợp lệ.",
          missingSlots: detail.missing_slots ?? [],
          errors: detail.errors ?? [],
        });
        return;
      }
      if (error instanceof ApiError && error.status === 409) {
        // Stale revision: refresh current state, never retry the mutation.
        void queryClient.invalidateQueries({ queryKey: ["character-versions", character.id] });
        void queryClient.invalidateQueries({ queryKey: ["character-validation", selectedVersion?.id] });
        setFeedback({
          kind: "conflict",
          message:
            "Xung đột phiên bản: dữ liệu đã thay đổi ở nơi khác. Đã tải lại trạng thái mới nhất — hãy kiểm tra lại trước khi xuất bản.",
        });
        return;
      }
      setFeedback({ kind: "error", message: "Không thể xuất bản. Vui lòng thử lại." });
    },
  });

  const canOfferPublish =
    selectedVersion != null &&
    selectedVersion.status !== "published" &&
    selectedVersion.status !== "archived";
  const validationComplete = validationQuery.data?.complete === true;
  const missingCount = validationQuery.data?.missing_slots.length ?? 0;

  const handleConfirmPublish = () => {
    if (!selectedVersion) return;
    setFeedback(null);
    publishMutation.mutate({
      versionId: selectedVersion.id,
      revision: selectedVersion.revision,
    });
    setConfirmOpen(false);
  };

  // Switching versions resets publish feedback and any open confirmation
  // (event-driven; avoids setState-in-effect).
  const selectVersion = (versionId: string) => {
    setSelectedVersionId(versionId);
    setFeedback(null);
    setConfirmOpen(false);
  };

  return (
    <section
      aria-label={`Chi tiết nhân vật ${character.name}`}
      className="rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-5"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-lg font-semibold">{character.name}</h3>
          <p className="mt-1 font-mono text-xs text-[var(--text-muted)]">{character.code}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={character.status} />
          {character.default_version_id && (
            <span className="rounded-full bg-[var(--primary-700)]/25 px-2.5 py-1 text-xs font-medium text-[var(--primary-300)]">
              Phiên bản mặc định
            </span>
          )}
        </div>
      </div>

      {character.description && (
        <p className="mb-4 text-sm text-[var(--text-secondary)]">{character.description}</p>
      )}

      <dl className="mb-5 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Loại</dt>
          <dd className="mt-0.5 text-[var(--text-secondary)]">
            {character.character_type === "character"
              ? "Nhân vật"
              : character.character_type === "prop"
                ? "Đạo cụ"
                : "Khác"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Đối xứng</dt>
          <dd className="mt-0.5 text-[var(--text-secondary)]">
            {character.symmetry === "symmetric" ? "Đối xứng" : "Bất đối xứng"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Ngày tạo</dt>
          <dd className="mt-0.5 text-[var(--text-secondary)]">{date(character.created_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">Cập nhật</dt>
          <dd className="mt-0.5 text-[var(--text-secondary)]">{date(character.updated_at)}</dd>
        </div>
      </dl>

      <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        Các phiên bản
      </h4>

      {loading ? (
        <div className="h-16 animate-pulse rounded-lg bg-[var(--surface-850)]" />
      ) : !versions || versions.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--surface-700)] bg-[var(--surface-850)] p-6 text-center text-sm text-[var(--text-muted)]">
          Nhân vật này chưa có phiên bản nào. Hãy tạo phiên bản đầu tiên để bắt đầu.
        </div>
      ) : (
        <div className="mb-5 space-y-2">
          {versions.map((version) => {
            const isDefault = version.id === defaultVersionId;
            const isSelected = version.id === effectiveVersionId;
            return (
              <button
                key={version.id}
                type="button"
                aria-pressed={isSelected}
                onClick={() => selectVersion(version.id)}
                className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                  isSelected
                    ? "border-[var(--primary-400)] bg-[var(--surface-850)]"
                    : "border-[var(--surface-700)] bg-[var(--surface-850)]/60 hover:bg-[var(--surface-850)]"
                }`}
              >
                <span className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                  <span className="font-semibold">Phiên bản v{version.version}</span>
                  {isDefault && (
                    <span className="rounded bg-[var(--primary-700)]/25 px-1.5 py-0.5 text-[11px] text-[var(--primary-300)]">
                      Mặc định
                    </span>
                  )}
                </span>
                <VersionBadge version={version} />
              </button>
            );
          })}
        </div>
      )}

      {selectedVersion && (
        <>
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              6 tư thế bắt buộc · v{selectedVersion.version}
            </h4>
            {selectedVersion.status === "published" && (
              <span className="flex items-center gap-1 text-[11px] text-[var(--text-muted)]">
                <Lock aria-hidden="true" size={12} />
                Phiên bản đã xuất bản không thể chỉnh sửa
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {CORE_POSE_SLOTS.map((slot) => (
              <PoseSlotTile key={slot} version={selectedVersion} slot={slot} />
            ))}
          </div>

          <div className="mt-5 rounded-lg border border-[var(--surface-800)] bg-[var(--surface-850)] p-4">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              Kiểm tra phiên bản
            </h4>
            {validationQuery.isLoading ? (
              <p className="text-sm text-[var(--text-muted)]">Đang kiểm tra...</p>
            ) : validationQuery.isError ? (
              <p className="text-sm text-[var(--danger)]">
                Không thể tải kết quả kiểm tra. Vui lòng thử lại.
              </p>
            ) : validationQuery.data ? (
              validationQuery.data.complete ? (
                <p className="flex items-center gap-2 text-sm text-[var(--success)]">
                  <CheckCircle2 aria-hidden="true" size={16} />
                  Đầy đủ 6 tư thế — sẵn sàng xuất bản.
                </p>
              ) : (
                <div>
                  <p className="text-sm text-[var(--warning)]">
                    Thiếu {validationQuery.data.missing_slots.length} tư thế bắt buộc.
                  </p>
                  {validationQuery.data.missing_slots.length > 0 && (
                    <p className="mt-1 text-xs text-[var(--text-secondary)]">
                      Thiếu:{" "}
                      {validationQuery.data.missing_slots
                        .map((s) => POSE_SLOT_LABELS[s as keyof typeof POSE_SLOT_LABELS] ?? s)
                        .join(", ")}
                    </p>
                  )}
                  {validationQuery.data.errors.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {validationQuery.data.errors.map((error, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-xs text-[var(--text-secondary)]">
                          <AlertCircle aria-hidden="true" size={13} className="mt-0.5 shrink-0 text-[var(--danger)]" />
                          <span>{error}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            ) : null}
          </div>

          {canOfferPublish && (
            <div className="mt-5 rounded-lg border border-[var(--surface-800)] bg-[var(--surface-850)] p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Xuất bản phiên bản v{selectedVersion.version}
                  </h4>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    {validationComplete
                      ? "Xuất bản sẽ chốt phiên bản này — sau khi xuất bản không thể thêm, sửa hoặc xóa tài nguyên."
                      : `Cần đầy đủ 6 tư thế hợp lệ để xuất bản (đang thiếu ${missingCount} tư thế).`}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={!validationComplete || publishMutation.isPending}
                  onClick={() => setConfirmOpen(true)}
                  className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-[var(--primary-600)] px-4 text-sm font-medium text-white transition-colors hover:bg-[var(--primary-500)] disabled:cursor-not-allowed disabled:opacity-45"
                >
                  <Rocket aria-hidden="true" size={16} />
                  {publishMutation.isPending ? "Đang xuất bản..." : "Xuất bản"}
                </button>
              </div>
            </div>
          )}

          {feedback && (
            <div
              role="status"
              className={`mt-3 flex items-start gap-2 rounded-lg border p-3 text-sm ${
                feedback.kind === "success"
                  ? "border-[var(--success-strong)]/40 bg-[var(--success-strong)]/10 text-[var(--success)]"
                  : feedback.kind === "conflict"
                    ? "border-[var(--warning)]/40 bg-[var(--warning)]/10 text-[var(--warning)]"
                    : "border-[var(--danger)]/40 bg-[var(--danger)]/10 text-[var(--danger)]"
              }`}
            >
              {feedback.kind === "success" ? (
                <CheckCircle2 aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
              ) : feedback.kind === "conflict" ? (
                <AlertTriangle aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
              ) : (
                <AlertCircle aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <p>{feedback.message}</p>
                {feedback.kind === "validation" && feedback.missingSlots && feedback.missingSlots.length > 0 && (
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    Thiếu:{" "}
                    {feedback.missingSlots
                      .map((s) => POSE_SLOT_LABELS[s as keyof typeof POSE_SLOT_LABELS] ?? s)
                      .join(", ")}
                  </p>
                )}
                {feedback.kind === "validation" && feedback.errors && feedback.errors.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {feedback.errors.map((error, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs text-[var(--text-secondary)]">
                        <AlertCircle aria-hidden="true" size={13} className="mt-0.5 shrink-0" />
                        <span>{error}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <button
                type="button"
                aria-label="Đóng thông báo"
                onClick={() => setFeedback(null)}
                className="shrink-0 rounded p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                <X aria-hidden="true" size={14} />
              </button>
            </div>
          )}

          {confirmOpen && (
            <div
              role="dialog"
              aria-modal="true"
              aria-label={`Xác nhận xuất bản phiên bản v${selectedVersion.version}`}
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
            >
              <div className="w-full max-w-md rounded-xl border border-[var(--surface-700)] bg-[var(--surface-900)] p-5 shadow-2xl">
                <h3 className="font-display text-lg font-semibold text-[var(--text-primary)]">
                  Xuất bản phiên bản v{selectedVersion.version}?
                </h3>
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  Phiên bản v{selectedVersion.version} của nhân vật “{character.name}” sẽ trở thành
                  phiên bản đã xuất bản. Sau khi xuất bản, phiên bản này là{" "}
                  <span className="font-medium text-[var(--warning)]">bất biến</span> — không thể
                  thêm, sửa hoặc xóa tài nguyên.
                </p>
                <div className="mt-5 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmOpen(false)}
                    disabled={publishMutation.isPending}
                    className="min-h-10 rounded-lg bg-[var(--surface-800)] px-4 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-700)] disabled:opacity-45"
                  >
                    Hủy
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmPublish}
                    disabled={publishMutation.isPending}
                    className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[var(--primary-600)] px-4 text-sm font-medium text-white hover:bg-[var(--primary-500)] disabled:opacity-45"
                  >
                    <Rocket aria-hidden="true" size={16} />
                    {publishMutation.isPending ? "Đang xuất bản..." : "Xác nhận xuất bản"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

/* ─── Main page ─────────────────────────────────────────────────────────── */

export default function CharactersPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<CharacterStatus | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["characters"],
    queryFn: () => api.listCharacters(),
  });

  const filtered = useMemo(() => {
    const chars = query.data?.characters ?? [];
    const term = search.trim().toLowerCase();
    return chars.filter((character) => {
      const matchesSearch =
        term === "" ||
        character.name.toLowerCase().includes(term) ||
        character.code.toLowerCase().includes(term);
      const matchesStatus = statusFilter === "all" || character.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [query.data, search, statusFilter]);

  const selected = filtered.find((c) => c.id === selectedId) ?? null;

  const versionsQuery = useQuery({
    queryKey: ["character-versions", selectedId],
    queryFn: () => api.listCharacterVersions(selectedId!),
    enabled: selectedId != null,
  });

  return (
    <div className="p-6 lg:p-8">
      <div className="mb-6">
        <h2 className="font-display text-2xl font-semibold">Thư viện nhân vật</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Duyệt, tìm kiếm và xem chi tiết bộ nhân vật bền vững từ thư viện sản xuất.
        </p>
      </div>

      {/* Search + filter */}
      <div className="mb-6 grid gap-3 sm:grid-cols-[1fr_12rem]">
        <label className="relative block">
          <span className="sr-only">Tìm kiếm nhân vật</span>
          <Search
            aria-hidden="true"
            size={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-faint)]"
          />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Tìm theo tên hoặc mã nhân vật..."
            className="min-h-10 w-full rounded-lg border border-[var(--surface-700)] bg-[var(--surface-950)] pl-9 pr-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-faint)]"
          />
        </label>
        <label className="block">
          <span className="sr-only">Lọc theo trạng thái</span>
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as CharacterStatus | "all")}
            className="min-h-10 w-full rounded-lg border border-[var(--surface-700)] bg-[var(--surface-950)] px-3 text-sm text-[var(--text-primary)]"
          >
            <option value="all">Tất cả trạng thái</option>
            {(Object.keys(CHARACTER_STATUS_LABELS) as CharacterStatus[]).map((status) => (
              <option key={status} value={status}>
                {CHARACTER_STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {query.isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <div key={n} className="h-40 animate-pulse rounded-xl bg-[var(--surface-850)]" />
          ))}
        </div>
      )}

      {query.isError && (
        <div className="rounded-xl border border-[var(--danger)] bg-[var(--surface-900)] p-6 text-center">
          <AlertCircle className="mx-auto text-[var(--danger)]" />
          <p className="mt-3 text-[var(--text-secondary)]">
            Không thể tải thư viện nhân vật từ máy chủ.
          </p>
          <button
            onClick={() => query.refetch()}
            className="mx-auto mt-4 flex min-h-10 items-center gap-2 rounded-lg bg-[var(--surface-800)] px-4 text-sm"
          >
            <RefreshCw size={16} />
            Thử lại
          </button>
        </div>
      )}

      {query.data && filtered.length === 0 && (
        <div className="rounded-xl border border-dashed border-[var(--surface-700)] bg-[var(--surface-900)] p-10 text-center">
          {search.trim() !== "" || statusFilter !== "all" ? (
            <>
              <Search className="mx-auto text-[var(--primary-300)]" size={28} />
              <h3 className="mt-4 font-display text-lg font-semibold">Không tìm thấy nhân vật</h3>
              <p className="mt-2 text-sm text-[var(--text-muted)]">
                Không có nhân vật khớp với từ khóa hoặc trạng thái đang chọn.
              </p>
            </>
          ) : (
            <>
              <Users className="mx-auto text-[var(--primary-300)]" size={28} />
              <h3 className="mt-4 font-display text-lg font-semibold">Chưa có nhân vật nào</h3>
              <p className="mt-2 text-sm text-[var(--text-muted)]">
                Thư viện hiện chưa có nhân vật. Nhân vật và bộ tư thế sẽ xuất hiện tại đây sau khi
                được tạo.
              </p>
            </>
          )}
        </div>
      )}

      {query.data && filtered.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <div className="grid content-start gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((character) => {
              const active = character.id === selectedId;
              return (
                <button
                  key={character.id}
                  type="button"
                  aria-pressed={active}
                  aria-label={`Xem chi tiết ${character.name} (${character.code})`}
                  onClick={() => setSelectedId(character.id)}
                  className={`min-h-40 rounded-xl border bg-[var(--surface-900)] p-5 text-left transition-colors hover:bg-[var(--surface-850)] ${
                    active ? "border-[var(--primary-400)]" : "border-[var(--surface-800)]"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-[var(--surface-800)] text-[var(--accent-300)]">
                      <Sparkles size={20} />
                    </span>
                    <div className="min-w-0">
                      <h3 className="truncate font-display font-semibold">{character.name}</h3>
                      <p className="truncate font-mono text-xs text-[var(--text-muted)]">
                        {character.code}
                      </p>
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    <StatusBadge status={character.status} />
                    {character.default_version_id && (
                      <span className="rounded-full bg-[var(--primary-700)]/25 px-2.5 py-1 text-xs font-medium text-[var(--primary-300)]">
                        Mặc định
                      </span>
                    )}
                  </div>
                  <p className="mt-3 text-xs text-[var(--text-muted)]">
                    {character.character_type === "character"
                      ? "Nhân vật"
                      : character.character_type === "prop"
                        ? "Đạo cụ"
                        : "Khác"}{" "}
                    · Tạo {date(character.created_at)}
                  </p>
                </button>
              );
            })}
          </div>

          <div className="lg:sticky lg:top-4 lg:self-start">
            {selected ? (
              <CharacterDetail
                character={selected}
                versions={versionsQuery.data}
                loading={versionsQuery.isLoading}
              />
            ) : (
              <div className="rounded-xl border border-dashed border-[var(--surface-700)] bg-[var(--surface-900)] p-10 text-center">
                <Users className="mx-auto text-[var(--text-faint)]" size={24} />
                <p className="mt-3 text-sm text-[var(--text-muted)]">
                  Chọn một nhân vật để xem chi tiết, phiên bản và 6 tư thế bắt buộc.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
