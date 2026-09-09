# S12-T03C C2 REPORT — normal API/worker/recovery/publication

Status: **TASK_SUBMITTED** | Branch `codex/s12/s12-t03c-0907a` @ (see commit SHA)
Baseline `da7108b` | No push/merge | Model `ocg/deepseek-v4-flash` fallback OFF.

## Evidence (real numbers)

- T03C suite: **30 passed** (~37–40s, isolated `%TEMP%` basetemp, fresh migrated DBs; includes real ffmpeg render).
- Regression T03A + T03B: **92 passed** (~117s, real media) — frozen lanes untouched.
- `ruff check --select F` (4 prod + 2 wiring + tests): All checks passed.
- `git diff --check`: clean (exit 0).
- Porcelain: allowlist only — 4 prod (jobs/route/publication/lifecycle) + 2 prior wiring kept + 3 test files updated + 1 new closure file + 2 docs.

## Row status (T03C C2 scope)

| Row | Status | Basis |
|---|---|---|
| C01 | PASS | mounted API + registered handler; 1 valid submit → 1 run + 1 Job, non-null IDs, server-owned paths |
| C04-part | PASS | real authority stale → 409 zero rows; real readiness not_run → 409 zero rows |
| C05 | PASS | non-media/partial/traversal/spoof → 0 mutation (helper + real route) |
| C07-part | PASS | union replay converges 1 run/1 job; same-key material drift → conflict, 0 extra rows |
| C09 (consumer) | PASS | publish re-checks live fence; expired-lease reconcile zero-mutation; stale token cannot publish |
| C14-part | PASS | expired lease → resumable report; fresh claim wins new fence (consumer side) |
| C15 | PASS | cancel winner + 409; retry converges ≤1 run; job/run states agree |
| C16 | PASS (bounded) | real worker render + real publication + real validator: no TypeError, no double assembly, coherent `failed` on NOT_MEASURED; positive PASS depends on T04A digest authority (reported) |
| C17/C18 (consumer) | PASS (bounded) | fence re-check mid-publication + atomic rename + sidecar bytes + partials never public + tampered replay fails |
| C22-part (backend) | PASS | `GET /s12-exports/{run_id}/result` (metadata + server-owned media_url) + `GET /s12-exports/{run_id}/media` (stream/download): only completed + owned; pending → 409; cross-project/missing → 404; tampered (sidecar mismatch) → 403; paths derived server-side, never client/manifest-supplied |
| F11-T06B-01 | FIXED (T03C side) | `_expectation_for` now supplies FULL server-owned authority from the CURRENT approved artifact (T04A helpers): per-frame content digests at the approved raster, exact fps/frame count, artifact sha256, `AudioReference` (transcode when audio present / absent when silent). REAL source-locked PASS proven end-to-end (identity copy + audio-transcode tests, validator unmocked). Residual: scaled/re-encoded candidates still fail honestly (digest mismatch) — T04A scale/lossy-tolerance delta proposed below. |
| C28-F01 | FIXED (T03C side) | AudioReference attached (`transcode` — the assembly re-encodes audio per C28 evidence); audio-source candidate passes av_policy with the REAL validator (presence/mapping/A-V drift), digest NOT compared for transcode. |

## Proposed T04A interface delta (NOT applied — owner T04A)

For re-encoded/rescaled exports (real runner scale+pad), the frozen exact-frame-digest compare can never PASS (lossy x264). T03C proposes a bounded T04A option: `SourceReference.allow_lossy_identity: bool` — when set, frame_order compares against a `-vf scale=srcWxsrcH`-normalized candidate digest (content identity across resize) and/or a tiny per-pixel MD5-mean tolerance (PSNR-style) documented per profile. T03C keeps fail-closed default (False).

## WIRE-PSNR (lan cuoi C26) — T04A interface-delta integrated

Canonical `f25f56c` (T04A-C2-delta: `frame_match_mode` + `frame_psnr_min_db` + `probe_frame_psnr` + `SourceReference.reference_path`) merged read-aligned into the branch; `publication.py` wires it:

1. **Re-encode/upscale/full-render candidates** (candidate sha != approved artifact sha): `frame_match_mode="psnr"` + `frame_psnr_min_db` DOCUMENTED per profile (`_PSNR_MIN_DB_BY_PROFILE`: master-4k-h264 30.0, master-4k-hevc 30.0, preview-1080p-h264 28.0); unknown profile → `None` → validator FAIL-closed (no silent default). `SourceReference.reference_path` = approved artifact (server-derived); `probe_frame_psnr` so sánh ở candidate raster.
2. **Identity-copy candidates** (no re-encode): keep `"exact"` digest mode.
3. **expected_sha256**: manifest authority sha khi có; khi không có + psnr mode → server-measured candidate sha (output identity bookkeeping — content authority vẫn là approved artifact qua PSNR, không self-hash content proof).

Tests (real ffmpeg, validator unmocked): legit re-encode 4K PSNR PASS; reorder tamper PSNR FAIL (run failed, no public artifact); identity-copy exact PASS (existing); threshold-missing FAIL-closed wire. Gates: t03c **39 passed**, t04a regression **73 passed**, ruff F clean, diff-check 0.

## Key artifacts

`app/workflow/s12_export_jobs.py` handler→publish real caller + failure coherence; `publication.py` candidate boundary + byte sidecar + single-winner CAS; `routes/s12_export.py` F02 authority-gated submit + real job_id + server paths; `lifecycle.py` startup reconcile caller. Evidence: `<C2-root>/s12-t03c/{pytest_t03c.txt,ruff_F.txt,diff_check.txt,porcelain.txt}`.