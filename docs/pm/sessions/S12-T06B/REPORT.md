# S12-T06B REPORT — C2 W7 (F11 positive acceptance rows C26-C29)

Status: **TASK_SUBMITTED** | Date: 2026-09-09 | Owner session resumed
Branch: `codex/s12/s12-t06b-0907a` | Baseline: `5e6e0fa` | No push/merge.

## Row status

| Row | Status | Evidence |
|---|---|---|
| C26 scenario F normal product | **PARTIAL: native-4K POSITIVE CLOSURE; upscale/letterbox STILL BLOCKED (F11-T06B-02 open, updated)** | native 4K re-encode publishes COMPLETED + GET result/media 200 + playable; upscale 1920x1080->4K and 4:3 letterbox render real 3840x2160 but publish fails frame_order: probe_frame_psnr(candidate4k, reference1080p, 4k) returns 7/30 frames, PSNR ~7.5dB — two concurrent ~12.4MB/frame raw pipes are not robust on Windows (3.1MB/frame works: 30 frames). T04A fit+pad present but insufficient on this host |
| C27 same-job fresh process | **POSITIVE PASS** | ONE normal job; owned stage-1 pid killed (tasklist-proof); production reconciler released expired lease; fresh pid re-claimed (new fence token); verified chunks reused (mtime-identical); handler PUBLISHED; run completed; artifact + no .partial |
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

1. **F11-T06B-01 (P1, owner T03C/T04A)** — REVERIFY on base `9a93475`:
   T03C findfix now builds SourceReference (digests/audio/sha) but
   `_expectation_for` still wires NO `frame_match_mode`: default `exact`
   fails every re-encoded/upscaled candidate at `frame_order`
   ("content order mismatch at frame 0"); `psnr` mode fails closed
   ("psnr mode requires documented frame_psnr_min_db (per profile)");
   and the server-owned `expected_sha256` remains unset in the normal
   submit payload -> provenance FAIL. Positive publish for real
   renders (upscale 1080p->4K, native re-encode, letterbox) is thus
   STILL blocked. Required: publication-side wiring of
   `frame_match_mode="psnr"` + documented `frame_psnr_min_db` (per
   profile) + authority sha source. Repro: any C26 normal job on this
   base (asserted in `test_c26_f11_remaining_blocker_proof`).
2. **C28-F01 (P2, owner T03C/T04A) — CLOSED by T03C findfix on
   `9a93475`**: `_build_source_reference` now attaches
   `AudioReference(mode="transcode"|"absent")` derived from the approved
   artifact; assembly-layer audio contract (mapping/drift/playability)
   verified independently in C28 tests.

## Full-suite gates (REVERIFY, base 9a93475)

- `pytest tests/s12/s12-t06b/ -q -p no:cacheprovider` -> **20 passed,
  1 skipped in 39.07s** (skip = clean-machine NOT_RUN only).
- Regression: T03C **37 passed**, T04A **73 passed** (findfix + psnr
  delta green).
- `ruff check --select F tests/s12/s12-t06b/` -> All checks passed.
- `git diff --check` clean; porcelain allowlist only at commit.

`tests/s12/s12-t06b/` +2 (`test_c26_normal_product.py`,
`test_c27_same_job_fresh_process.py`, `test_c28_audio_mapping.py`,
`c27_stage1_worker.py`), `conftest.py` (builders + db path),
`docs/pm/sessions/S12-T06B/{EXTERNAL_ACCEPTANCE,LOG,REPORT}.md`.
Evidence mirrored to C2 root (see LOG).