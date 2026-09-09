# S12-T06B REPORT — C2 W7 (F11 positive acceptance rows C26-C29)

Status: **TASK_SUBMITTED** | Date: 2026-09-09 | Owner session resumed
Branch: `codex/s12/s12-t06b-0907a` | Baseline: `5e6e0fa` | No push/merge.

## Row status

| Row | Status | Evidence |
|---|---|---|
| C26 scenario F normal product | **RENDERED/PASS (fail-closed publish, finding F11-T06B-01 open)** | 3 tests MEASURED: 1920x1080->3840x2160 real chunks (F03 scale+pad), native 4K control, 4:3 letterbox; exact dims 3840x2160 / frames / timing; candidate never `.partial`; publication rejects due to missing authority (asserted) |
| C27 same-job fresh process | **VERIFIED-REUSE/PASS (fail-closed publish, F11-T06B-01 open)** | ONE normal job; owned stage-1 pid killed (tasklist-proof); production reconciler released expired lease; fresh pid re-claimed with NEW fence token; all verified chunks reused (mtime-identical); candidate 30/30 frames; run failed retryable; no forged repair |
| C28 audio mapping + drift | **PASS** | 3 tests MEASURED: content mapping (440Hz source in -> 440Hz out, 880Hz control rejected); remux-vs-transcode explicit (`-c:v copy` + `-c:a aac`); start/end drift pin 3.00s; short audio fails closed (StitchError); artifacts playable (ffprobe + wav decode). Finding C28-F01 routed (publication audio-ref gap) |
| C29 external acceptance | **MEASURED CPU/GPU + SIMULATED + NOT_RUN clean machine** | `EXTERNAL_ACCEPTANCE.md`: CPU i5-14600KF ~1.6-1.9k fps 640x360 libx264 wall 0.08-0.09s; GPU RTX 5070 h264_nvenc wall 0.19-0.20s; 4K projection SIMULATED (bpp 0.0013, method stated); clean Windows VM/human NOT_RUN -> beta BLOCKED, never waived |

## Full-suite gates (real output)

- `pytest tests/s12/s12-t06b/ -q -p no:cacheprovider` -> **18 passed,
  1 skipped in 30.02s** (skip = clean-machine NOT_RUN only).
- `ruff check --select F tests/s12/s12-t06b/` -> All checks passed.
- `py_compile` all suite files OK; `git diff --check` -> clean.
- Porcelain at commit: allowlist only (`tests/s12/s12-t06b/**`,
  `docs/pm/sessions/S12-T06B/**`).

## Findings routed to owners (no product edits by verifier)

1. **F11-T06B-01 (P1, owner T03C/T04A)** — `publication._expectation_for`
   does not supply server-owned authority to the source-locked validator
   (`expected_sha256` unset -> provenance FAIL; `frame_digests`/`cuts`
   empty -> frame_order NOT_MEASURED), so NO real job can publish
   positive on base `5e6e0fa`. Repro: run `submit_export_job` + real
   handler; publication raises `export validation FAIL on
   ['frame_order','provenance']`; run lands `failed` (retryable) after a
   real candidate exists. Required: wire sha256 (+ digests/cuts) from
   the server-owned authority into `_expectation_for`.
2. **C28-F01 (P2, owner T03C/T04A)** — `_expectation_for` builds
   `SourceReference(..., audio=None)`; a job candidate carrying audio is
   rejected as `absent`. Required: attach `AudioReference` (mode
   explicit) when the manifest supplies `audio_source`.

## Files this correction

`tests/s12/s12-t06b/` +2 (`test_c26_normal_product.py`,
`test_c27_same_job_fresh_process.py`, `test_c28_audio_mapping.py`,
`c27_stage1_worker.py`), `conftest.py` (builders + db path),
`docs/pm/sessions/S12-T06B/{EXTERNAL_ACCEPTANCE,LOG,REPORT}.md`.
Evidence mirrored to C2 root (see LOG).