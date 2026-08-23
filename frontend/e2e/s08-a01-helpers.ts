/**
 * S08-A01 shared E2E constants/helpers (NOT a spec file — safe to import
 * from both the desktop and the 390px mobile specs).
 */

export const SEVEN_KINDS = [
  "character",
  "prop",
  "background",
  "foreground",
  "graphic",
  "source_overlay",
  "other",
] as const;

export const KIND_VI: Record<string, string> = {
  character: "Nhân vật",
  prop: "Vật phẩm",
  background: "Bối cảnh",
  foreground: "Tiền cảnh",
  graphic: "Nội dung/đồ họa",
  source_overlay: "Lớp nguồn cần loại bỏ",
  other: "Khác",
};
