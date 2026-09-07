# S12-T02 REPORT — Capability detection + render profiles

- Branch: `codex/s12/s12-s12-t02-0907a`, base `0d04673` (T01 checkpoint).
- Contract consume: `s12-export-v1` (T01) read-only — 4 file T01 untouched
  (verified `git diff --stat HEAD` empty).
- Machine truth (spawn-probe, RTX 5070 / ffmpeg 8.1.2):
  - CPU: libx264 OK, libx265 OK → 3/3 profiles supported qua CPU path.
  - GPU: NVENC/AMF/QSV (H.264+HEVC) liệt kê trong build nhưng spawn-fail thật
    → fail-closed với reason `encoder_failed`, fallback CPU rõ.
  - VRAM free ~7605 MiB → heuristic 4K pass (≥1024 MiB).

## Files changed (allowlist)

NEW: `app/services/s12_export/capabilities.py` (spawn-probe detection +
reason codes + VRAM gate), `app/services/s12_export/profiles.py`
(frozen-profile resolution + measured-basis estimate),
`tests/s12/s12-t02/test_capabilities.py` (11 tests),
`tests/s12/s12-t02/test_profiles.py` (17 tests),
`docs/pm/sessions/S12-T02/{LOG.md,REPORT.md}`.
PATCH: none (T01 files untouched, no app.py change — no new route).

## Policy compliance (contract §6 S12-T02)

- Probe encoder THỰC (spawn testsrc 128x72x5f, exit 0 + non-empty file);
  grep `ffmpeg -encoders` chỉ là pre-filter diagnostic.
- H.264 baseline luôn có đường CPU; HEVC chỉ supported khi probe-pass.
- GPU absent/encoder-failure/VRAM-insufficient/timeout → reason code +
  CPU fallback trong basis (không silent fail).
- Estimate nêu công thức `WxHxf×B/px` với B/px đo từ probe (clamp
  [0.02, 2.0]) hoặc heuristic T01 khi thiếu; frames unknown → fail-closed.
- Aspect/preset không hỗ trợ → fail-closed (`UNSUPPORTED_PROFILE` /
  `ASPECT_MISMATCH`), khớp T01, không stretch/crop.
- Không download/install driver/model; không S11; không ports demo.

## Gates

- `python -m pytest tests/s12/s12-t02/ -q -p no:cacheprovider` → **28 passed
  (1.96s)**.
- `ruff check --select F` (2 service modules + tests) → clean.
- Regression `tests/s12/s12-t01/` → **15 passed (16.73s)**.

## Consumer handoff (T03A/B/C, T04A)

- `detect_capabilities(work_dir)` → `CapabilityReport` (cache mỗi worker run).
- `resolve_all_profiles(report, prefer_gpu=...)` → scheduler T03A.
- `estimate_for_profile(resolved, frames, report)` → `estimate_bytes` +
  `estimate_basis` cho preflight response (T02 refines T01 heuristic).
- `ResolvedProfile.as_export_fields()` khớp strict `ExportProfile` T01.

## TASK_SUBMITTED (transport checkpoint, local branch — không phải APPROVED)

## C1 W2 correction (local, pending review)

- Consume frozen T01-C1 (không redesign): PROFILE_ENCODERS mirror +
  delegate `probe_encoder_support`; proved-native vs labeled-upscale honesty.
- NEW `tests/s12/s12-t02/test_c1_closure.py` — 8 tests chứng minh T01/T03B
  consume được (resolve→estimate→ExportProfile fields).
- Gates: 35 passed + 1 skipped (1 test skip khi T01-C1 chưa merge vào cây);
  ruff F clean; diff-check 0; porcelain = allowlist only.

## TASK_SUBMITTED (transport checkpoint, local branch — không phải APPROVED)
