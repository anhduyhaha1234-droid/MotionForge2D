# S11-T01A — Audio Import Policy and Contract

**Task ID:** S11-T01A
**State:** READY
**Owning session:** 20260821_160614_6958a5 (alpha @ custom, Hermes CLI)
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration — branch codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204

## Outcome

Freeze và triển khai chính sách import cho canonical original audio theo frozen decisions (S11-SPRINT_CONTRACT.md):

1. First audio stream là canonical; không trộn nhiều audio streams.
2. Video input vẫn chỉ MP4 + H.264/HEVC.
3. AAC first audio: import bình thường (remux sau này có thể stream-copy).
4. Non-AAC first audio stream: source import VỚI EXPLICIT WARNING — không reject chỉ vì audio non-AAC. S11 remux engine (T01B) chịu trách nhiệm transcode AAC.
5. No-audio: explicit no-audio metadata; không fabricated audio.
6. Video codec/container/HDR policy KHÔNG được nới.
7. Không rewrite lịch sử S05/E03; chỉ supersede duy nhất quyết định B5 non-AAC.

## Exclusive write ownership

| File | Phạm vi |
|---|---|
| docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md | NEW — contract remux (T01B sẽ đọc) |
| docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md | APPEND-ONLY resolution cho B5 (không sửa nội dung cũ) |
| docs/pm/sessions/S11-T01A-audio-import-contract/ | packet/evidence của chính task này |
| output/s11-t01a/<run-id>/ | logs, test output |
| app/services/video_import.py | CHỈ non-AAC acceptance/warning behavior |
| tests/test_video_import.py | CHỈ S11 non-AAC regressions |
| tests/test_s11_original_audio_contract.py | NEW |

## Forbidden

original_audio_remux.py, job_service.py, migration, models.py, API/frontend, mọi file S07/S08 core, test files của T01B/C/D. Nếu cần file ngoài allowlist → STOP BLOCKED_SCOPE, không tự mở rộng.

## Required tests (binary)

1. AAC remains accepted.
2. No-audio remains accepted.
3. MP4 H.264/HEVC với first audio non-AAC → accepted với explicit warning.
4. Unsupported video codec vẫn reject.
5. Unsupported container vẫn reject.
6. HDR/10-bit policy unchanged.
7. First audio stream remains canonical.
8. Multi-stream input không merge streams.
9. Probe/checkpoint retains codec/index/channels/sample rate.
10. Import không transcode/không mutate source bytes.

## Worker protocol

- Hard worktree guard trước mọi write: pwd = worktree, toplevel khớp, nếu sai → BLOCKED WRONG_WORKTREE, exit.
- Cấm: reset/clean/stash/restore/checkout file/commit/push/merge; sửa MAIN; production DB; data/motionforge.db; git global config.
- MOTIONFORGE_DATABASE_URL phải UNSET. Tests dùng temp DB/basetemp riêng (`--basetemp` Windows-native path, `-p no:cacheprovider`).
- FFmpeg binary discovery chỉ qua app/services/ffmpeg_utils.
- Kết thúc: REPORT.md status = SUBMITTED (không tự APPROVED). Ghi evidence thật (lệnh + output) vào LOG.md.
- Model: alpha @ custom (9Router), reasoning max, fallback disabled. Route chết → dừng, ghi BLOCKED_MODEL_ROUTE vào LOG.
