# S09-FG2 LOG — single-head normalization (final-gate correction)

## Baseline (preflight, trước mọi sửa)
- Rules: `RULES_LOADED` — đọc TOÀN BỘ `C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md` trong lượt này.
- Worktree guard: cwd `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`, branch `codex/s08-integration`, HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`. MAIN READ-ONLY.
- `MOTIONFORGE_DATABASE_URL`: UNSET (đã kiểm `env | grep` → rỗng).
- `git status --short`: 74 thay đổi có sẵn từ các phiên sprint trước — BẢO TOÀN, không đụng gì ngoài write-set.
- Live Alembic heads (ScriptDirectory('migrations').get_heads()): `['b3c4d5e6f7a9']` — khớp finding TASK.md (T05A tạo head mới).
- Pre-existing modification của `tests/test_s09_reskin_migration.py` (+113/−10) đã chụp trước khi sửa: `output/s09/20260823_sprint_full/tfg2/preserve-baseline-test_s09_reskin_migration.diff` (177 dòng). Mọi edit của FG2 nằm LỚP TRÊN trạng thái working-tree hiện tại.
- SESSION_PROTOCOL.md (worktree) đã đọc; pm-session-execution skill đã nạp.

## Plan
1. Pre-fix: chạy 4 file test → ghi bằng chứng FAIL (stale head assertions).
2. Patch file 1 `tests/test_s07_project_cast_migration.py`: bỏ constant HEAD stale, thêm `_live_head()` (ScriptDirectory.get_heads()), assert revision-chain giữ ý nghĩa gốc + single-head discovery.
3. Patch file 2 `tests/test_s08_a02_structural_evidence_migration.py`: tương tự (walk_revisions range giữ nguyên vì là revision identity).
4. Patch file 3 `tests/test_s09_reskin_migration.py`: `HEAD` constant → `ScriptDirectory.from_config(...).get_heads()[0]` qua helper; assertion single-head GIỮ NGUYÊN độ mạnh (multi-head vẫn fail).
5. Patch file 4 `tests/test_s09_t00_structural_lock_migration.py`: giữ revision identity `d8e9f0a1b2c3` (mig.revision, downgrade target, post-downgrade revision); đổi assert heads + `_revision(db)` sau `upgrade head` sang live-head discovery.
6. Verify: 4 file ×2 PASS liên tiếp (basetemp khác nhau) + `tests/test_s09_t05_backend_migration.py` + ruff check 4 files.
7. REPORT.md → SUBMITTED.

## Execution (2026-08-24, resume sau model-empty EXIT)
- File 1 + file 2: HOÀN TẤT trước điểm ngắt (manager đã verify PASS). Pattern: bỏ constant `HEAD` stale → `_live_head()` (ScriptDirectory.get_heads(), assert len==1); revision identity giữ literal (`b2c3d4e5f6a7b` / `a0b1c2d3e4f5`); refusal tests park fixture ĐÚNG tại revision-under-test để leg downgrade test là leg của chính revision đó. File 1: 7 passed; File 2: 10 passed.
- File 3 `test_s09_reskin_migration.py`: xóa constant `HEAD = "d8e9f0a1b2c3"`; thêm `_live_head()`; `test_single_head_via_alembic` assert `heads == [_live_head()]`; roundtrip giữ downgrade target `PRE` (đầy đủ ý nghĩa gốc — qua TẤT CẢ các leg trên empty graph, KHÔNG làm yếu) với `_revision(db)` sau upgrade so với live head; điểm park sau refusal (pinned row) giữ literal `d8e9f0a1b2c3` — revision SỞ HỮU guard từ chối (identity, không phải head). Kết quả: 9 passed.
- File 4 `test_s09_t00_structural_lock_migration.py`: thêm `_live_head()` cạnh `_live_heads()` có sẵn; `test_single_head_and_live_down_revision`: giữ `mig.revision == "d8e9f0a1b2c3"` (đúng), đổi assert heads sang `get_heads()` live + `len==1` (multi-head vẫn fail); roundtrip QUA live head — cả hai schema snapshot cùng chụp Ở live head nên so sánh byte-identical like-for-like (lần thử park tại d8e9 trước khi chụp sig_first bị FAIL thật: re-upgrade về head có thêm `s09_correction` → signature khác; đã root-cause và bỏ walk-back); `test_downgrade_allows_unused_empty_pins_then_roundtrip`: assert cuối `_revision(db) == _live_head()`; các điểm park sau refusal giữ literal revision-under-test. Kết quả: 9 passed.

## Verification evidence
- Pre-fix baseline (4 file): 14 failed / 21 passed — bằng chứng check là THẬT.
- RUN A (`--basetemp=%TEMP%/s09fg2-r1a`): **43 passed** (5 file gồm cả test_s09_t05_backend_migration.py).
- RUN B (`--basetemp=%TEMP%/s09fg2-r1b`, chạy NGAY SAU run A): **43 passed** ×2 liên tiếp.
- `ruff check` 4 file: All checks passed!
- Diff snapshots: `output/s09/20260823_sprint_full/tfg2/fixed-test_s09_reskin_migration.diff` (223 dòng), `fixed-test_s09_t00_structural_lock_migration.diff` (61 dòng).
- Working tree: 74 thay đổi baseline nguyên vẹn; KHÔNG có git op nào (no reset/clean/stash/push); MAIN không đụng.
