# S11-T01B — Original Audio Remux Engine

**Task ID:** S11-T01B
**State:** READY
**Owning session:** 20260821_160614_40b90e (điền bởi owning writer session khi launch)
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration — branch codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204

## Outcome

Pure/bounded original-audio remux engine cho canonical first audio stream. Engine là module thuần: nhận source path đã resolve + managed output dir, trả về result/checkpoint deterministic. KHÔNG đụng import policy, KHÔNG đụng job wiring.

## Exclusive write ownership

| File | Phạm vi |
|---|---|
| app/services/original_audio_remux.py | NEW |
| tests/test_s11_original_audio_remux.py | NEW |
| docs/pm/sessions/S11-T01B-original-audio-engine/ | packet/evidence |
| output/s11-t01b/<run-id>/ | logs, test output |

## Read-only dependencies

docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md (nếu T01A chưa land: dùng frozen decisions trong S11-SPRINT_CONTRACT.md), app/services/video_probe.py, app/services/ffmpeg_utils.py, app/services/timebase.py, app/persistence/artifacts.py, app/persistence/jobs.py, app/persistence/models.py.

## Required behavior

1. Resolve canonical first audio stream.
2. AAC → stream-copy; non-AAC → AAC transcode.
3. No audio → explicit NO_AUDIO_PRESENT.
4. Corrupt source fail closed; stable error codes.
5. FFmpeg list args; shell=False; bounded stdout/stderr.
6. Deadline/remaining-budget bounded; cancellation terminates child.
7. Cleanup không vượt remaining budget; no orphan process.
8. Managed path containment; atomic staging; validate trước publish; never expose partial output.
9. Probe output codec; validate duration/timebase; source bytes unchanged.
10. No network/GPU; no Demucs/ASR/TTS/dubbing.

## Forbidden

video_import.py, job_service.py, migration, models.py, shared-service signature changes, API/frontend, file S07, file T01A/C/D. Ngoài allowlist → STOP BLOCKED_SCOPE.

## Required tests (binary)

1. AAC stream-copy path. 2. MP3→AAC. 3. AC-3→AAC. 4. PCM/Opus theo frozen contract hoặc stable refusal. 5. No-audio. 6. Corrupt source. 7. Multi-stream selects first only. 8. Duration/timebase validation. 9. Validation failure no publish. 10. Path escape refusal. 11. Output cap. 12. Timeout cleanup. 13. Cancellation cleanup. 14. Child cleanup. 15. Atomic publication. 16. Deterministic result/checkpoint.

Tests dùng temp media (lavfi/anullsrc nếu FFmpeg available), temp DB, isolated managed root, basetemp riêng Windows-native, `-p no:cacheprovider`.

## Worker protocol

- Hard worktree guard trước mọi write; sai tree → BLOCKED WRONG_WORKTREE, exit.
- Cấm reset/clean/stash/restore/checkout/commit/push/merge; MAIN; production DB; git global config.
- Kết thúc: REPORT.md status = SUBMITTED. Evidence thật vào LOG.md.
- Model: alpha @ custom (9Router), reasoning max, fallback disabled. Route chết → BLOCKED_MODEL_ROUTE vào LOG.
