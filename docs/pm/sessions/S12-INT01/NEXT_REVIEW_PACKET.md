# S12 NEXT_REVIEW_PACKET — for Codex reviewer

## 1. Verdict

**SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW.** Do not treat as APPROVED/CLOSED until Codex re-review.

## 2. Integration pointers

- Branch: `codex/s12-integration`; HEAD: (INT01-close SHA, see S12-INT01 REPORT §6).
- Pushed: `ls-remote` == local HEAD (recorded in REPORT §6).
- Evidence root: `C:/Users/Admin/MotionForge2D-evidence/s12/20260907-083200-s12-coding/` (REGISTRY.md append-only + per-task prompt/dispatch/nudge logs + snapshots).
- Pin ranges (full SHA, 21 task commits + merges): `s12-int01/pin_ranges.txt` in evidence root.

## 3. What to review (source diff)

- Production new: `app/schemas/s12_export.py`, `app/services/s12_export/` (preflight, capabilities, profiles, validation, runner/chunks/stitch, publication), `app/persistence` S12 entities + migration `f9a0b1c2d3e4`→`c3d4e5f6a7b8`, `app/workflow/s12_export_jobs.py` + wiring, `app/api/routes/s12_export*.py` + app wiring, `packaging/windows/` + `scripts/s12/`, frontend `export/` (page, components, lib, E2E).
- Tests new: `tests/s12/s12-t01/` (15), `s12-t02/` (28), `s12-t03a/` (30), `s12-t04a/` (26), `s12-t03b/` (19), `s12-t03c/` (15), `s12-t06b/` (12: 11 passed + 1 skipped); T05 real-API Playwright (`frontend/e2e/s12-export.spec.ts`, 15 E2E).
- Session docs: `docs/pm/sessions/S12-{T01,T02,T03A,T03B,T03C,T04A,T05,T06A,T06B,INT01}/LOG.md + REPORT.md`.

## 4. Gates already run (exact numbers)

- `pytest tests/s12/`: **144 passed, 1 skipped / 97.57s**, exit 0, isolated basetemp, `-p no:cacheprovider`.
- `ruff check --select F app/ tests/s12/`: All checks passed. `git diff --check`: 0. Alembic: sole head `c3d4e5f6a7b8`. Porcelain: 0.
- T06B acceptance real: F upscale 1080p→3840x2160 labeled `lanczos-ffmpeg-scale-x4` (30/30 frames, validator PASS, wav bytes); Native 4K control (20/20 frames); G kill owned pid → relaunch reuse 3/3 chunks, 3.00s/30 frames exact, zero `.partial`. Hardware: CPU i5-14600KF + GPU RTX 5070 MEASURED.

## 5. Open items for Codex

1. **Mypy `s12_export` 26 errors / 8 files** (list in REGISTRY + INT01 LOG §6) — please confirm severity / request owner fixes.
2. **F-OBS-01 → T01**: `classify_source_kind` dims-only fallback classifies `native_4k` on dims alone (repro in T06B LOG). Confirm T01 owner fix scope.
3. **Clean-machine NOT_RUN** (no clean VM available) — confirm NOT_RUN (not waive) is acceptable for beta packaging claim.
4. T05 session docs were backfilled by exact owner post-merge (`4a3630a` → merge `e60ec5f`); confirm docs-merge ordering acceptable.

## 6. Do-not-do (reviewer)

- Do not rebase/reset/force-push `codex/s12-integration`. Corrections go to exact task owners, not INT01.
- S11 remains NOT_CLOSED (separate stream); no S13 work in this sprint.
