# S12-T03B REPORT — Chunk render, stitch, checkpoint resume

Status: TASK_SUBMITTED. Baseline `49fe2be1acddafbdd67d4635c61b0084edb0f070`,
branch `codex/s12/s12-t03b-0907a`, local commit only (no push — Manager/INT01
owns transport). Date: 2026-09-07 ~14:22 VN.

## AC mapping (contract §6, verified by real test output)

| AC | Where | Proof |
|---|---|---|
| Validated full-apply output + existing media primitives | `runner.py` renders windows from the validated source via real `find_ffmpeg`; `stitch.py` trims/concats/muxes via real ffmpeg/ffprobe | 19 T03B tests on real-encoded testsrc media |
| Bounded-memory/disk-aware chunking | cores `<= max_frames_per_chunk`; `check_disk_for_run` (T01 B/px basis x1.5 margin) gates before render; ENOSPC → `DiskFullError` | `test_plan_*`, disk-gate + stderr-match paths |
| Exact frame ranges, no dup/drop at seam | `verify_seam_coverage` (first=0, last=N-1, contiguous, sum==N); trim verified decode-exact; stitched count==N asserted twice | `test_plan_covers_exactly_no_seam_dup_drop`, `test_concat_cores_matches_source`, `test_full_run_assembles_exact_frames` |
| Checkpoint = content/config/profile/tool identity | `compute_content_hash` over plan+checkpoint+profile+position+attempt+`TOOL_IDENTITY`; different tool/config → different hash → T03A replay fails closed | `test_plan_content_hash_binds_tool_and_config`, `test_tampered_chunk_hash_replay_fails` |
| Verified chunk reuse | completed+verified+file-decodes-exact → reused with mtime proof; anything else re-rendered or failed closed | `test_resume_reuses_verified_chunks` (mtime-ns equal) |
| Crash/cancel/disk-full/stale lock/tampered chunk | crash → rows+scratch only, resume finishes; cancel flag + `cancelled` status; ENOSPC; foreign/expired lease; tampered file/hash | `test_crash_mid_run_resumes_to_candidate`, `test_cancel_*` (2), `test_stale_lease_*` + `test_expired_lease_*`, `test_resume_rerenders_tampered_chunk_file` |
| Real fresh-process resume without DB repair | every resume test opens a brand-new session+repository; no `UPDATE` outside T03A fenced methods | 11 runner tests, all with fresh `factory()` scopes |
| Audio assembly = exact time mapping, no per-chunk loop/cut | chunks silent; source muxed once with `-t <video duration>`; short audio refused; exactly 1 audio + 1 video stream asserted | `test_audio_mapping_exact_not_looped`, `test_mux_audio_once_maps_timeline` |
| Scratch `.partial` + atomic finalize, never public completed | muxable scratch names during encode; ONE `os.replace` publishes; existing completed refused; `.partial` input refused | `test_stitch_refuses_partial_and_overwrite`, no `.partial` beside any output |

## Files (allowlist only)

- `app/services/s12_export/{chunks,stitch,runner}.py` (NEW, 236+394+490 lines)
- `tests/s12/s12-t03b/` (NEW: `__init__.py`, `conftest.py`, `test_plan_stitch.py`
  8 tests, `test_runner_resume.py` 11 tests)
- `docs/pm/sessions/S12-T03B/{LOG,REPORT}.md` (NEW)

## Numbers

- T03B focused: 19 passed / 18.20s.
- Regression T01+T02+T03A+T04A: 99 passed / 53.14s.
- `ruff check --select F`: All checks passed. `git diff --check`: clean.
- Freeze set: zero drift (porcelain shows only the 6 allowlist NEW paths).

## Notes for T03C / Manager

- Runner never marks the run `completed` and never publishes — candidate path
  returned by `resume()`/`assemble()` awaits T03C publication gate.
- Re-attempt of a terminal (`failed`/`skipped`) chunk needs a NEW attempt row
  (fail-closed `RunnerError` points there); T03B scope renders attempt=1.
- Error codes via `ExportRunner.code_for`: `S12_T03B_STALE_LEASE` /
  `S12_T03B_CANCELLED` / `S12_T03B_DISK_FULL` / `S12_T03B_STALE_IDENTITY` /
  `FENCED_WORKER` / `LEASE_CONFLICT` / `S12_T03B_RUNNER_ERROR`.
