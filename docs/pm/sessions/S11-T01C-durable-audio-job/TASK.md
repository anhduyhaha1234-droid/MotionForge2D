# S11-T01C — Durable ATTACH_ORIGINAL_AUDIO Job Wiring

**Task ID:** S11-T01C
**State:** READY (dispatched khi T01A+B MANAGER_VERIFIED)
**Owning session:** 20260821_214021_cbc36d
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration — branch codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204

## Outcome

Đăng ký và thực thi job type `ATTACH_ORIGINAL_AUDIO` bằng production JobService thật, dùng engine T01B (`app/services/original_audio_remux.py` — đã MANAGER_VERIFIED) làm remux backend.

## Read-only dependencies (đã verified)

- docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md (T01A)
- app/services/original_audio_remux.py (T01B engine — CHỈ import/gọi, KHÔNG sửa)
- app/services/video_probe.py, app/services/ffmpeg_utils.py, app/services/timebase.py
- app/persistence/artifacts.py, app/persistence/jobs.py, app/persistence/models.py
- app/services/video_import.py (tham khảo pattern submit/handler của ANALYZE_MEDIA)

## Exclusive write ownership

| File | Phạm vi |
|---|---|
| app/workflow/job_service.py | CHỈ additive registration cho ATTACH_ORIGINAL_AUDIO; không refactor handlers/lifecycle khác |
| app/workflow/original_audio_handler.py | NEW — adapter mỏng gọi engine T01B (tùy chọn nếu giữ job_service gọn) |
| tests/test_s11_attach_original_audio_job.py | NEW |
| docs/pm/sessions/S11-T01C-durable-audio-job/ | packet/evidence |
| output/s11-t01c/<run-id>/ | logs, test output |

## Required behavior

1. Job type `ATTACH_ORIGINAL_AUDIO`, registered trong default production JobService (KHÔNG chỉ isolated test worker registry).
2. Resolve source từ VideoItem/source Artifact authority — KHÔNG nhận arbitrary filesystem path từ client.
3. Deterministic idempotency key; equivalent submit tái dùng job/effects; conflicting submit fail closed.
4. Retry không duplicate artifact.
5. Restart preserves checkpoint.
6. Cancellation tạo zero publication.
7. Job chỉ complete sau artifact validation/publication.
8. Artifact kind `audio`; ArtifactOwner owner_type `video_item`; purpose `original_audio`.
9. Current ObjectRole/DISCOVER_OBJECTS generation unchanged.
10. Zero schema/migration; zero thay đổi durable worker semantics.
11. Engine defect phát hiện → KHÔNG tự sửa engine; STOP và ghi BLOCKED_ENGINE_DEFECT vào LOG (Manager sẽ resume T01B).

## Forbidden

video_import.py (sửa), original_audio_remux.py (sửa), durable_worker.py, artifacts.py, jobs.py, models.py, migrations, API/frontend, S07 files, file T01A/B/D. Ngoài allowlist → STOP BLOCKED_SCOPE.

## Required tests (binary)

1. Default JobService registers handler. 2. Real handler invocation. 3. Equivalent submit idempotent. 4. Conflicting submit fail closed. 5. Retry no duplicate artifact. 6. Restart/checkpoint. 7. Cancellation zero publication. 8. Validation-before-completion. 9. Correct ArtifactOwner. 10. Analysis generation unchanged. 11. Unknown/missing source stable failure. 12. No process leak.

Dùng temp SQLite DB, temp managed root, basetemp Windows-native riêng, `-p no:cacheprovider`. FFmpeg runtime thật nếu available.

## Worker protocol

- Hard worktree guard trước mọi write; sai tree → BLOCKED WRONG_WORKTREE, exit.
- Cấm reset/clean/stash/restore/checkout/commit/push/merge; MAIN; production DB/data/motionforge.db; git global config.
- Kết thúc: REPORT.md status=SUBMITTED; evidence thật vào LOG.md; điền Owning session ID vào TASK.md.
- Model: alpha @ custom (9Router), reasoning max, fallback disabled. Route chết → BLOCKED_MODEL_ROUTE vào LOG.
