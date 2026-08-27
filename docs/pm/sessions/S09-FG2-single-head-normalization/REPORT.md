# S09-FG2 REPORT — stale single-head assertions sau T05A migration

**STATUS: TASK_SUBMITTED**

Session: `20260824_165139_dd1068` (resume sau model-empty EXIT=0 giữa chừng) · Worktree `s08-integration` @ `codex/s08-integration` ee10e55 · `MOTIONFORGE_DATABASE_URL` UNSET suốt phiên · Rules `HERMES_AUTOPILOT_RULES.md` đã nạp toàn bộ (`RULES_LOADED`) · MAIN READ-ONLY, zero git ops.

## Deliverables (đúng write-set)

| File | Thay đổi |
|---|---|
| `tests/test_s07_project_cast_migration.py` | Bỏ constant `HEAD = "b2c3d4e5f6a7b"` → `_live_head()` qua `ScriptDirectory.get_heads()`; revision identity giữ literal; refusal test park tại revision-under-test. **7 passed** |
| `tests/test_s08_a02_structural_evidence_migration.py` | Cùng pattern (`HEAD_REVISION = "a0b1c2d3e4f5"` là identity); assert heads live; refusal park giữ nguyên nghĩa atomic fail-closed. **10 passed** |
| `tests/test_s09_reskin_migration.py` | Xóa `HEAD = "d8e9f0a1b2c3"`; thêm `_live_head()`; single-head assert `heads == [_live_head()]`; roundtrip giữ downgrade target `PRE` (đầy đủ ý nghĩa gốc); park sau refusal giữ literal `d8e9f0a1b2c3` (revision sở hữu guard). **9 passed** |
| `tests/test_s09_t00_structural_lock_migration.py` | Thêm `_live_head()` cạnh `_live_heads()` có sẵn; single-head assert theo `get_heads()` + `len==1` (giữ `mig.revision == "d8e9f0a1b2c3"` đúng theo TASK.md); roundtrip QUA live head — cả 2 snapshot cùng chụp ở head; assert cuối test #5 sang `_live_head()`. **9 passed** |

Evidence artifacts (write-set `output/s09/20260823_sprint_full/tfg2/**`):
- `preserve-baseline-test_s09_reskin_migration.diff` (177 dòng, chụp TRƯỚC khi sửa — bảo toàn +113 insertions từ phiên trước)
- `fixed-test_s09_reskin_migration.diff` (223 dòng), `fixed-test_s09_t00_structural_lock_migration.diff` (61 dòng)
- `LOG.md`, `REPORT.md` trong session dir.

## Verify bắt buộc (lệnh thật + output thật)

1. Pre-fix baseline 4 file (trước mọi patch): **14 failed / 21 passed** → check là THẬT, không phải always-pass.
2. RUN A ×5 file (4 đích + `test_s09_t05_backend_migration.py`), basetemp `%TEMP%/s09fg2-r1a`: **43 passed**.
3. RUN B ngay sau, basetemp `%TEMP%/s09fg2-r1b`: **43 passed** → ×2 PASS liên tiếp.
4. `ruff check` 4 file: **All checks passed!**
5. `git status`: 74 thay đổi working-tree baseline nguyên vẹn; không file nào ngoài write-set bị đụng.

## Self-audit

- KHÔNG hard-code head mới (`b3c4d5e6f7a9` không xuất hiện trong bất kỳ test nào — mọi tham chiếu head qua `get_heads()` live; đã grep xác nhận).
- KHÔNG làm yếu assertion: multi-head vẫn fail (`len==1`/assert một phần tử); roundtrip vẫn full-leg qua PRE (file 3) hoặc qua live head (file 4); refusal tests vẫn chứng minh atomic fail-closed với row/pin.
- Phân biệt đúng identity vs head: literal revision chỉ còn ở vai revision-under-test / điểm park sau refusal (revision sở hữu guard từ chối) — không còn dùng làm snapshot head.
- Sai lầm đã root-cause trong phiên: lần thử đầu park roundtrip file 4 tại `d8e9…` trước khi chụp signature → FAIL thật vì re-upgrade về head có thêm `s09_correction`; sửa theo đúng hướng manager: so sánh like-for-like Ở live head.

## Hạn chế / ghi chú cho Manager

- File 3 & 4 giữ style riêng của chúng (`ScriptDirectory.from_config`) — không thống nhất hóa chéo với file 1 & 2 (trực tiếp `ScriptDirectory(dir)`).
- Không chạy full suite toàn repo (ngoài scope hẹp của TASK.md §Verify); các suite liên quan được yêu cầu đã pass.
