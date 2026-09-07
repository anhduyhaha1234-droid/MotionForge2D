# S12-T02 LOG — Capability detection + render profiles

Owner task S12-T02, branch `codex/s12/s12-s12-t02-0907a`, wave-base `0d04673`
(T01 checkpoint). Worktree `C:/Users/Admin/MotionForge2D-worktrees/s12-s12-t02-0907a`.

## 1. Baseline (2026-09-07 UTC)

- `git rev-parse HEAD` → `0d04673` (T01 transport checkpoint), branch
  `codex/s12/s12-s12-t02-0907a`, tree clean.
- T01 freeze consume read-only: `docs/contracts/s12-export.md`
  (`s12-export-v1`), `app/schemas/s12_export.py`,
  `app/services/s12_export/preflight.py`,
  `app/api/routes/s12_export_preflight.py` — KHÔNG sửa (verified
  `git diff --stat HEAD` empty trên 4 file sau implement).
- ffmpeg 8.1.2 (WinGet links, on PATH) + RTX 5070 (12227 MiB, driver 610.47).
- Required reading: HERMES_AUTOPILOT_RULES.md (277 lines, full), contract
  s12-export.md §1-7, schemas + preflight + route T01 (read-only).

## 2. TARGET checklist (Step 1)

1. NEW `app/services/s12_export/capabilities.py`: probe encoder THỰC (spawn
   encode clip testsrc ngắn, exit 0 + file non-empty) — không grep-only;
   H.264 baseline luôn; HEVC chỉ khi probe-pass; GPU absent/fail/VRAM/timeout
   có reason code + fallback CPU rõ.
2. NEW `app/services/s12_export/profiles.py`: resolve 3 frozen profiles T01
   (dims/codec y nguyên) → supported + support_basis từ CapabilityReport;
   fail-closed aspect/preset không hỗ trợ; estimate WxHxfps×B/px nêu công thức
   (measured probe B/px, clamp [0.02, 2.0], fallback heuristic T01).
3. TESTS `tests/s12/s12-t02/` isolated (fake runner + tmp_path, không sửa
   conftest chung/test cũ) — green + ruff clean.
4. T01 regression green + T01 freeze intact (diff empty).
5. DOCS `docs/pm/sessions/S12-T02/{LOG.md,REPORT.md}` + commit local (không push).

## 3. Design notes

- Probe clip: `testsrc=128x72:rate=5:duration=1s`, `-frames:v 5`,
  `-pix_fmt yuv420p`, timeout 30s/encoder. Unlisted-trong-build →
  `encoder_not_in_build` (không spawn vô ích); spawn fail → `encoder_failed`
  + stderr tail; timeout → `probe_timeout`; ffmpeg vắng → `ffmpeg_missing`.
- `nvidia-smi` best-effort timeout 10s: fail = warning `gpu_absent`, không fatal.
- VRAM heuristic 4K: free ≥ 1024 MiB (`vram_ok` / `vram_insufficient`).
- GPU path chỉ khi GPU-encoder probe-pass CÙNG codec + VRAM ok; mọi nhánh
  GPU-unavailable đều fallback CPU kèm reason trong basis.
- Aspect: mirror epsilon 1% T01; drift + letterbox → ok (detail trong basis);
  drift + passthrough/fail_closed → `S12_EXPORT_ASPECT_MISMATCH`.
- Estimate: measured `probe_bytes/(128*72*5)` khi có probe của chính encoder,
  clamp [0.02, 2.0]; GPU không probe → 0.35B/px; không probe → heuristic T01
  0.5B/px; frames unknown → (None, fail-closed) khớp gate disk T01.
- Không download/install driver/model; không touch S11; không ports demo.

## 4. Implementation + verification

- `capabilities.py` (~230 dòng): EncoderProbe/CapabilityReport dataclasses,
  `probe_encoder`, `detect_capabilities`, `vram_sufficient_for_4k`.
- `profiles.py` (~250 dòng): RENDER_PROFILES mirror frozen T01,
  `resolve_profile`/`resolve_all_profiles`/`estimate_for_profile`,
  `ResolvedProfile.as_export_fields()` validate được dưới `ExportProfile`
  strict schema T01 (có test).
- Bug tự bắt khi smoke: `_listed_encoders` parse sai cột (parts[2] thay vì
  parts[1]) → GPU encoders bị `encoder_not_in_build` giả; fix + verify lại
  thì thấy NVENC/AMF/QSV liệt kê nhưng spawn-fail thật trên máy này
  (NVENC exit 4294967274 "Nothing was written", AMF/QSV tương tự) → đúng
  behavior fail-closed cần chứng minh: grep-list ≠ usable.
- Machine truth (smoke): libx264 OK (3588B/30ms), libx265 OK (4757B/47ms),
  mọi GPU encoder fail-closed, VRAM free 7605 MiB. CPU: 3/3 profiles
  supported; prefer_gpu: 3/3 fallback CPU với reason rõ.
- Gates: `pytest tests/s12/s12-t02/ -q -p no:cacheprovider` → **28 passed
  (1.96s)**; `ruff check --select F` trên 2 modules + tests → clean;
  regression `tests/s12/s12-t01/` → **15 passed (16.73s)**; T01 freeze diff
  empty (4/4 file).
