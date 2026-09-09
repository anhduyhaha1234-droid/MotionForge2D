# S12-T06B EXTERNAL_ACCEPTANCE — C29 (S12-C2 W7)

Split: **MEASURED / SIMULATED / NOT_RUN** — no case removal, no waive.

## MEASURED (this host, real probes, 2026-09-09)

- CPU: `Intel(R) Core(TM) i5-14600KF` — 150 frames 640x360 libx264
  ultrafast, wall 0.08-0.09s (~1.6-1.9k fps) — real encode, exit 0.
- GPU: `NVIDIA GeForce RTX 5070` (12227 total / 9452-9481 free MiB) —
  150 frames 640x360 h264_nvenc, wall 0.19-0.20s — real encode, exit 0,
  nvidia-smi readout; VRAM heuristic for 4K satisfied.
- Scenario F media (real, MEASURED): 1920x1080 -> 3840x2160 render
  (F03 scale+pad), native 3840x2160 control, 4:3 1440x1080 -> letterbox
  pad; frames/timing exact; audio decode + dominant-tone content check
  (440Hz in, 440Hz out; 880Hz control rejected).
- Scenario G (real, MEASURED): owned worker subprocess pid killed
  (tasklist-verified), production reconciler released the expired lease,
  fresh pid re-claimed and REUSED every verified chunk (mtime-identical),
  30/30 frames candidate.

## SIMULATED (method stated, estimate only)

- 4K file-size projection: linear-pixels from measured 1080p bytes/px
  (bpp 0.0013) -> ~624 KB for 60 frames 3840x2160 @10fps. This is an
  estimate, NOT a hardware fact; real 4K encodes were still executed and
  measured for wall-time/dims/frames.

## NOT_RUN (missing environment — recorded, never waived)

- **Clean Windows VM / isolated host**: absent on this machine
  (`S12_T06B_CLEAN_MACHINE` unset; a clean venv on the dev host does NOT
  qualify). Clean-machine acceptance is **NOT_RUN**.
- **Human verdict on a clean Windows target**: no target, no human
  session -> NOT_RUN.
- Consequence (explicit): the Windows portable-BETA (`S12-T06A` harness)
  is **BLOCKED for beta pass** on clean machine until a real clean host
  runs the packaged lifecycle. No auto-waive, no beta pass claim.

## Positive-path blockers found live (verifier findings, owners routed)

- F11-T06B-01 (owner T03C/T04A): `publication._expectation_for` supplies
  no server-owned authority (sha256 / frame digests / cuts / audio ref)
  -> the source-locked validator rejects EVERY real job candidate
  (provenance FAIL + frame_order NOT_MEASURED); runs land `failed`
  (retryable) after producing a real candidate. Positive publish path is
  not closable on base `5e6e0fa`; fail-closed behaviour asserted instead.
- C28-F01 (owner T03C/T04A): `_expectation_for` never attaches
  `SourceReference.audio` -> audio-source jobs are rejected as
  `absent`; assembly-layer audio contract (mapping/drift/playability)
  verified independently in C28 tests.