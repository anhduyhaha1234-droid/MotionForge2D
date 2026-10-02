"use client";

/**
 * M1-01 — tạo nhân vật (identity) rồi tạo phiên bản nháp đầu tiên.
 *
 * Hai mutation TÁCH RỜI, đúng contract công khai đã kiểm trên baseline này:
 *  1. `POST /api/v2/characters`            → 201 identity (code trùng = 409)
 *  2. `POST /api/v2/characters/{id}/versions` → 201 draft (KHÔNG idempotency)
 *
 * Vì (2) không idempotent:
 *  - nút bị `disabled` khi đang chạy ⇒ không double submit;
 *  - response bất định (lỗi mạng / huỷ request) KHÔNG auto-retry mù: phải
 *    `listCharacterVersions` để reconcile rồi mới cho người dùng quyết định;
 *  - lỗi ở (2) giữ nguyên character `id` đã tạo và chỉ retry đúng phần (2).
 *
 * UI: mọi nút dark-theme có helper text tiếng Việt ngay dưới
 * (`text-gray-400`, cỡ 11px), dialog có nhãn, focus vào khi mở và trả focus
 * về nút mở khi đóng; Escape đóng.
 */

import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import { ApiError } from "@/lib/api";
import {
  createCharacter,
  createCharacterVersion,
  listCharacterVersions,
  type CharacterIdentity,
  type CharacterTypeInput,
  type CharacterVersionSummary,
  type SymmetryInput,
} from "./referenceLibraryApi";

const NAME_MAX = 200;
const CODE_MAX = 64;
const CODE_PATTERN = /^[a-z0-9_]+$/;

/** Kiểu DTO mà trang cha cần — re-export để import một chỗ. */
export type { CharacterIdentity, CharacterVersionSummary };

const CHARACTER_TYPE_LABELS: Record<CharacterTypeInput, string> = {
  character: "Nhân vật",
  prop: "Đạo cụ",
  other: "Khác",
};

const SYMMETRY_LABELS: Record<SymmetryInput, string> = {
  symmetric: "Đối xứng",
  asymmetric: "Bất đối xứng",
};

export interface CreateCharacterDialogProps {
  /** Nút mở dialog (nhận lại focus khi dialog đóng). */
  returnFocusRef?: React.RefObject<HTMLElement | null>;
  onClose: () => void;
  /** Gọi sau khi có đúng cặp identity+draft (id thật từ server). */
  onCreated: (result: {
    character: CharacterIdentity;
    version: CharacterVersionSummary;
  }) => void;
}

type IdentityState =
  | { kind: "none" }
  | { kind: "creating" }
  | { kind: "failed"; message: string }
  | { kind: "created"; character: CharacterIdentity };

type VersionState =
  | { kind: "idle" }
  | { kind: "creating" }
  | { kind: "failed"; message: string }
  | { kind: "uncertain"; message: string }
  | { kind: "reconciled"; versions: CharacterVersionSummary[] }
  | { kind: "created"; version: CharacterVersionSummary };

function identityErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return "Mã nhân vật này đã tồn tại. Đổi mã khác rồi tạo lại.";
    }
    if (error.status === 422) {
      const detail = error.detailText();
      return detail
        ? `Dữ liệu chưa hợp lệ: ${detail}`
        : "Dữ liệu chưa hợp lệ. Kiểm tra tên (1–200 ký tự) và mã (1–64 ký tự).";
    }
    return `Không tạo được nhân vật (mã lỗi ${error.status}).`;
  }
  return "Không kết nối được máy chủ khi tạo nhân vật.";
}

export function CreateCharacterDialog({
  returnFocusRef,
  onClose,
  onCreated,
}: CreateCharacterDialogProps) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [characterType, setCharacterType] = useState<CharacterTypeInput>("character");
  const [symmetry, setSymmetry] = useState<SymmetryInput>("symmetric");
  const [description, setDescription] = useState("");

  const [identity, setIdentity] = useState<IdentityState>({ kind: "none" });
  const [version, setVersion] = useState<VersionState>({ kind: "idle" });
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; code?: string }>({});

  const nameRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  /* Focus vào dialog khi mở; trả focus về nút mở khi đóng. */
  useEffect(() => {
    const returnTarget = returnFocusRef?.current ?? null;
    nameRef.current?.focus();
    return () => {
      returnTarget?.focus();
    };
  }, [returnFocusRef]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const validate = (): boolean => {
    const errors: { name?: string; code?: string } = {};
    const trimmedName = name.trim();
    const trimmedCode = code.trim();
    if (trimmedName.length < 1 || trimmedName.length > NAME_MAX) {
      errors.name = `Tên nhân vật phải từ 1 đến ${NAME_MAX} ký tự.`;
    }
    if (trimmedCode.length < 1 || trimmedCode.length > CODE_MAX) {
      errors.code = `Mã nhân vật phải từ 1 đến ${CODE_MAX} ký tự.`;
    } else if (!CODE_PATTERN.test(trimmedCode)) {
      errors.code = "Mã chỉ gồm chữ thường, số và dấu gạch dưới (ví dụ: hero_01).";
    }
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const identityBusy = identity.kind === "creating";
  const versionBusy = version.kind === "creating";
  const identityDone = identity.kind === "created";
  const hasResult = identityDone && version.kind === "created";

  const handleCreateIdentity = async () => {
    if (identityBusy || identityDone) return;
    if (!validate()) return;
    setIdentity({ kind: "creating" });
    try {
      const created = await createCharacter({
        name: name.trim(),
        code: code.trim(),
        character_type: characterType,
        symmetry,
        description: description.trim() === "" ? null : description.trim(),
      });
      setIdentity({ kind: "created", character: created });
      setVersion({ kind: "idle" });
    } catch (error) {
      setIdentity({ kind: "failed", message: identityErrorMessage(error) });
    }
  };

  /**
   * Tạo draft. Không idempotent ⇒ nếu lỗi KHÔNG phải ApiError có status rõ
   * ràng (tức request có thể đã tới server) thì chuyển sang trạng thái
   * "uncertain" và KHÔNG tự chạy lại; người dùng đọc lại versions để quyết định.
   */
  const handleCreateVersion = async () => {
    if (identity.kind !== "created" || versionBusy) return;
    setVersion({ kind: "creating" });
    try {
      const created = await createCharacterVersion(identity.character.id);
      setVersion({ kind: "created", version: created });
      onCreated({ character: identity.character, version: created });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setVersion({ kind: "failed", message: "Không tìm thấy nhân vật vừa tạo trên máy chủ." });
        return;
      }
      setVersion({
        kind: "uncertain",
        message:
          "Chưa xác nhận được kết quả tạo phiên bản. Nhấn “Đọc lại phiên bản” để kiểm tra trước khi thử lại.",
      });
    }
  };

  const handleReconcile = async () => {
    if (identity.kind !== "created") return;
    setVersion({ kind: "creating" });
    try {
      const versions = await listCharacterVersions(identity.character.id);
      setVersion({ kind: "reconciled", versions });
    } catch {
      setVersion({
        kind: "uncertain",
        message: "Vẫn chưa đọc lại được danh sách phiên bản. Kiểm tra kết nối rồi thử lại.",
      });
    }
  };

  const identityStatusLine = (() => {
    if (identity.kind === "created") {
      return `Đã tạo nhân vật — ID: ${identity.character.id}`;
    }
    return null;
  })();

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-character-title"
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:items-center"
      data-testid="create-character-dialog"
    >
      <div
        ref={panelRef}
        className="w-full max-w-xl rounded-xl border border-[var(--surface-700)] bg-[var(--surface-900)] p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <h3
            id="create-character-title"
            className="font-display text-lg font-semibold text-[var(--text-primary)]"
          >
            Tạo nhân vật mới
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng hộp thoại tạo nhân vật"
            className="shrink-0 rounded p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            data-testid="create-character-close"
          >
            <X aria-hidden="true" size={18} />
          </button>
        </div>

        {/* ── 1. Identity ─────────────────────────────────────────────── */}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-xs text-[var(--text-secondary)]">Tên nhân vật (bắt buộc)</span>
            <input
              ref={nameRef}
              value={name}
              disabled={identityDone}
              onChange={(event) => setName(event.target.value)}
              aria-invalid={fieldErrors.name != null}
              placeholder="Ví dụ: Cô gái tóc đỏ"
              className="mt-1 min-h-10 w-full rounded-lg border border-[var(--surface-700)] bg-[var(--surface-950)] px-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-faint)]"
              data-testid="create-character-name"
            />
            <span className="mt-1 block text-[11px] text-gray-400">
              1–{NAME_MAX} ký tự. Tên hiển thị trong thư viện.
            </span>
            {fieldErrors.name && (
              <span className="mt-1 block text-[11px] text-[var(--danger)]" data-testid="name-error">
                {fieldErrors.name}
              </span>
            )}
          </label>

          <label className="block">
            <span className="text-xs text-[var(--text-secondary)]">Mã nhân vật (bắt buộc)</span>
            <input
              value={code}
              disabled={identityDone}
              onChange={(event) => setCode(event.target.value)}
              aria-invalid={fieldErrors.code != null}
              placeholder="Ví dụ: red_hair_girl"
              className="mt-1 min-h-10 w-full rounded-lg border border-[var(--surface-700)] bg-[var(--surface-950)] px-3 font-mono text-sm text-[var(--text-primary)] placeholder:text-[var(--text-faint)]"
              data-testid="create-character-code"
            />
            <span className="mt-1 block text-[11px] text-gray-400">
              1–{CODE_MAX} ký tự, chỉ chữ thường/số/gạch dưới. Mã phải là duy nhất.
            </span>
            {fieldErrors.code && (
              <span className="mt-1 block text-[11px] text-[var(--danger)]" data-testid="code-error">
                {fieldErrors.code}
              </span>
            )}
          </label>

          <label className="block">
            <span className="text-xs text-[var(--text-secondary)]">Loại</span>
            <select
              value={characterType}
              disabled={identityDone}
              onChange={(event) => setCharacterType(event.target.value as CharacterTypeInput)}
              className="mt-1 min-h-10 w-full rounded-lg border border-[var(--surface-700)] bg-[var(--surface-950)] px-3 text-sm text-[var(--text-primary)]"
              data-testid="create-character-type"
            >
              {(Object.keys(CHARACTER_TYPE_LABELS) as CharacterTypeInput[]).map((value) => (
                <option key={value} value={value}>
                  {CHARACTER_TYPE_LABELS[value]}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-[11px] text-gray-400">
              Nhân vật hoặc đạo cụ. Mặc định là Nhân vật.
            </span>
          </label>

          <label className="block">
            <span className="text-xs text-[var(--text-secondary)]">Đối xứng</span>
            <select
              value={symmetry}
              disabled={identityDone}
              onChange={(event) => setSymmetry(event.target.value as SymmetryInput)}
              className="mt-1 min-h-10 w-full rounded-lg border border-[var(--surface-700)] bg-[var(--surface-950)] px-3 text-sm text-[var(--text-primary)]"
              data-testid="create-character-symmetry"
            >
              {(Object.keys(SYMMETRY_LABELS) as SymmetryInput[]).map((value) => (
                <option key={value} value={value}>
                  {SYMMETRY_LABELS[value]}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-[11px] text-gray-400">
              Mô tả cơ thể đối xứng hay không — dùng khi tạo tư thế.
            </span>
          </label>
        </div>

        <label className="mt-3 block">
          <span className="text-xs text-[var(--text-secondary)]">Mô tả (không bắt buộc)</span>
          <textarea
            value={description}
            disabled={identityDone}
            onChange={(event) => setDescription(event.target.value)}
            rows={2}
            className="mt-1 w-full rounded-lg border border-[var(--surface-700)] bg-[var(--surface-950)] p-2 text-sm text-[var(--text-primary)]"
            data-testid="create-character-description"
          />
          <span className="mt-1 block text-[11px] text-gray-400">
            Ghi chú ngắn giúp phân biệt nhân vật trong thư viện.
          </span>
        </label>

        {/* ── Bước 1: tạo identity ────────────────────────────────────── */}
        <div className="mt-4 flex flex-col gap-1">
          <button
            type="button"
            onClick={handleCreateIdentity}
            disabled={identityBusy || identityDone}
            aria-disabled={identityBusy || identityDone}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[var(--primary-600)] px-4 text-sm font-medium text-white transition-colors hover:bg-[var(--primary-500)] disabled:cursor-not-allowed disabled:opacity-45"
            data-testid="create-character-submit"
          >
            {identityBusy && <Loader2 aria-hidden="true" size={16} className="animate-spin" />}
            {identityBusy
              ? "Đang tạo nhân vật…"
              : identityDone
                ? "Đã tạo nhân vật"
                : "Tạo nhân vật"}
          </button>
          <span className="text-[11px] text-gray-400">
            {identityDone
              ? "Bước 1 xong. Nút bị khoá để không tạo trùng — làm tiếp bước 2."
              : "Bước 1/2: tạo hồ sơ nhân vật. Chưa tạo phiên bản."}
          </span>
        </div>

        {identityStatusLine && (
          <p
            className="mt-3 flex items-start gap-2 break-all text-sm text-[var(--success)]"
            data-testid="create-character-identity-id"
          >
            <CheckCircle2 aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
            {identityStatusLine}
          </p>
        )}

        {identity.kind === "failed" && (
          <p
            role="alert"
            className="mt-3 flex items-start gap-2 text-sm text-[var(--danger)]"
            data-testid="create-character-identity-error"
          >
            <AlertCircle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
            {identity.message}
          </p>
        )}

        {/* ── Bước 2: tạo phiên bản nháp ──────────────────────────────── */}
        {identityDone && (
          <div className="mt-5 rounded-lg border border-[var(--surface-700)] bg-[var(--surface-850)] p-3">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              Bước 2/2 · phiên bản nháp
            </h4>
            <p className="mt-1 text-[11px] text-gray-400">
              Nhân vật cần một phiên bản nháp để bắt đầu thêm tư thế/asset. Bước này độc lập với
              bước 1: nhân vật đã tạo sẽ không bị mất nếu bước này lỗi.
            </p>

            {version.kind === "created" ? (
              <p
                className="mt-3 flex items-start gap-2 break-all text-sm text-[var(--success)]"
                data-testid="create-version-id"
              >
                <CheckCircle2 aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
                Đã tạo phiên bản nháp — ID: {version.version.id}
              </p>
            ) : (
              <>
                <button
                  type="button"
                  onClick={handleCreateVersion}
                  disabled={versionBusy}
                  aria-disabled={versionBusy}
                  className="mt-3 inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[var(--accent-500)] px-4 text-sm font-medium text-[var(--surface-950)] transition-colors hover:bg-[var(--accent-400)] disabled:cursor-not-allowed disabled:opacity-45"
                  data-testid="create-version-submit"
                >
                  {versionBusy && <Loader2 aria-hidden="true" size={16} className="animate-spin" />}
                  {versionBusy ? "Đang tạo phiên bản…" : "Tạo phiên bản nháp"}
                </button>
                <span className="mt-1 block text-[11px] text-gray-400">
                  Nhấn để tạo phiên bản nháp đầu tiên (hợp đồng 6 tư thế legacy, chưa xuất bản).
                </span>
              </>
            )}

            {version.kind === "failed" && (
              <p
                role="alert"
                className="mt-3 flex items-start gap-2 text-sm text-[var(--danger)]"
                data-testid="create-version-error"
              >
                <AlertCircle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
                {version.message}
              </p>
            )}

            {version.kind === "uncertain" && (
              <div
                role="alert"
                className="mt-3 rounded border border-[var(--warning)]/40 bg-[var(--warning)]/10 p-3"
                data-testid="create-version-uncertain"
              >
                <p className="text-sm text-[var(--warning)]">{version.message}</p>
                <button
                  type="button"
                  onClick={handleReconcile}
                  disabled={versionBusy}
                  className="mt-2 inline-flex min-h-10 items-center gap-2 rounded-lg bg-[var(--surface-800)] px-4 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-700)] disabled:opacity-45"
                  data-testid="create-version-reconcile"
                >
                  Đọc lại phiên bản
                </button>
                <span className="mt-1 block text-[11px] text-gray-400">
                  Đọc lại trạng thái thật trên máy chủ trước khi tạo thêm — tránh phiên bản trùng.
                </span>
              </div>
            )}

            {version.kind === "reconciled" && (
              <div className="mt-3" data-testid="create-version-reconciled">
                <p className="text-sm text-[var(--text-secondary)]">
                  Máy chủ hiện có {version.versions.length} phiên bản cho nhân vật này.
                </p>
                <ul className="mt-1 space-y-0.5">
                  {version.versions.map((item) => (
                    <li key={item.id} className="break-all font-mono text-[11px] text-gray-400">
                      v{item.version} · {item.status} · {item.id}
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={handleCreateVersion}
                  className="mt-2 inline-flex min-h-10 items-center gap-2 rounded-lg bg-[var(--accent-500)] px-4 text-sm font-medium text-[var(--surface-950)] hover:bg-[var(--accent-400)]"
                  data-testid="create-version-submit-after-reconcile"
                >
                  Tạo phiên bản nháp
                </button>
                <span className="mt-1 block text-[11px] text-gray-400">
                  Nếu danh sách trên đã có phiên bản nháp đúng ý, đóng hộp thoại thay vì tạo thêm.
                </span>
              </div>
            )}
          </div>
        )}

        {/* ── Đóng ───────────────────────────────────────────────────── */}
        <div className="mt-5 flex flex-col gap-1">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[var(--surface-800)] px-4 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-700)]"
            data-testid="create-character-done"
          >
            {hasResult ? "Xong — xem nhân vật vừa tạo" : "Đóng"}
          </button>
          <span className="text-[11px] text-gray-400">
            {hasResult
              ? "Đóng hộp thoại và xem chi tiết nhân vật vừa tạo trong thư viện."
              : "Đóng hộp thoại. Nhân vật đã tạo (nếu có) vẫn được giữ nguyên."}
          </span>
        </div>
      </div>
    </div>
  );
}
