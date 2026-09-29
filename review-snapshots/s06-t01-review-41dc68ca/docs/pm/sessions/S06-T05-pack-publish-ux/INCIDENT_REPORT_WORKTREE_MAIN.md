# Incident Report — S06-T05 chạy nhầm vào MAIN repo thay vì Review Worktree

- **Incident ID:** INC-2026-08-05-001
- **Task liên quan:** `S06-T05` (Pack Review, Publish & Immutable Version UX)
- **Thời gian xảy ra:** 2026-08-05 00:11–00:19 (+07:00)
- **Agent:** Hermes session `20260804_235345_9e36e1` (model `ocg/deepseek-v4-flash`, 151 messages, 26m18s, exit 0)
- **Mức độ:** Cao — code được ghi vào sai repository (MAIN thay vì worktree `s06-t01-review`)
- **Trạng thái:** ✅ Đã khắc phục và xác minh (xem phần Xử lý)

---

## 1. Tóm tắt sự cố

Task S06-T05 được chạy bằng script `run-s06-t05-deepseek.ps1` có `Set-Location`
vào worktree `C:\Users\Admin\MotionForge2D-worktrees\s06-t01-review`, nhưng
**agent session thực thi với cwd = MAIN repo** `C:\Users\Admin\MotionForge2D`.
Kết quả: toàn bộ code, test và docs của S06-T05 được ghi vào MAIN repo, còn
worktree vẫn giữ trạng thái cũ (`REPORT.md` = IN_PROGRESS từ 12:23).

## 2. Nguyên nhân gốc

`hermes chat` CLI khởi chạy từ PowerShell script **không kế thừa `Set-Location`**
khi Hermes desktop daemon đang chạy — agent session nhận cwd của daemon
(= MAIN repo), không phải cwd của script. Bằng chứng trong log agent:
lệnh `ls -d /c/Users/Admin/MotionForge2D/docs/pm/sessions/S06-T0*` — agent tự
điều hướng bằng đường dẫn MAIN repo.

## 3. Bằng chứng (đã xác minh trên đĩa)

| Kiểm tra | MAIN repo `C:\Users\Admin\MotionForge2D` | Worktree `s06-t01-review` |
|---|---|---|
| `tests/test_pack_publish_ux.py` (6 test mới) | ✅ Có (mtime 00:12) | ❌ Không có (trước khi copy) |
| `app/api/routes/durable_characters.py` | ✅ Sửa 00:11 | ⚠️ Bản cũ 18:38 |
| `docs/.../S06-T05/REPORT.md` | ✅ SUBMITTED (00:18) | ❌ IN_PROGRESS (12:23) |
| `frontend/src/app/(app)/characters/page.tsx` | ✅ Sửa (659 dòng) | ⚠️ Bản cũ (508 dòng) |

Các file agent ghi vào MAIN repo (cửa sổ 23:50–00:30):
1. `app/api/routes/durable_characters.py`
2. `frontend/src/app/(app)/characters/page.tsx`
3. `tests/test_pack_publish_ux.py`
4. `docs/pm/sessions/S06-T05-pack-publish-ux/LOG.md`
5. `docs/pm/sessions/S06-T05-pack-publish-ux/REPORT.md`

## 4. Xử lý đã thực hiện (2026-08-05 00:20–00:30)

1. **Backup an toàn:** 11 file gốc của worktree → `output/backup-pre-copy/`
   (app/, frontend/, migrations/, tests/) — phòng rollback.
2. **Copy từ MAIN → worktree:** 12 file code/test/docs + fixtures
   `tests/fixtures/legacy_import/*` + `LOG.md`/`REPORT.md`.
3. **Xác minh đồng bộ:** `diff -q` từng file MAIN↔worktree → **0 file còn khác**.
4. **Xác minh chạy được:** `pytest tests/test_pack_publish_ux.py tests/test_character_domain.py --cache-clear`
   → **9 passed, 5.08s** (chạy ngay trong worktree).
5. **Full suite (agent đã chạy trước đó tại MAIN):** 604 passed, 8 skipped,
   7 deselected, 319s, exit 0; tsc/eslint/next build/ruff/mypy đều pass.
6. **Main repo giữ nguyên trạng** (theo quyết định của user) — KHÔNG revert,
   KHÔNG xóa gì ở MAIN.

## 5. Trạng thái hiện tại

- Worktree `s06-t01-review`: `REPORT.md` = **SUBMITTED**, code + test đầy đủ,
  pytest 9 passed tại chỗ.
- MAIN repo: vẫn còn bản sao các file S06-T05 (modified/untracked) — **chủ ý
  giữ nguyên** chờ quyết định của Codex review.
- Bài học đã được ghi vào skill `motionforge-autopilot` (mục "Worktree
  execution pitfall"): phòng ngừa bằng prompt ép cwd tuyệt đối + kiểm tra
  `git status` cả 2 repo sau mỗi run.

## 6. Việc cần Codex review quyết định

1. **MAIN repo còn 44 file thay đổi** (`git status --short` tại
   `C:\Users\Admin\MotionForge2D`), trong đó có bản sao S06-T05 — cần quyết
   định: giữ lại để merge, hay dọn khỏi MAIN (chỉ giữ worktree làm nguồn chính).
2. Xác nhận `output/backup-pre-copy/` trong worktree có thể xóa sau khi review.
3. Xác nhận `S06-T05` = SUBMITTED (không tự approve — theo đúng quy trình).

## 7. Files liên quan

- Script chạy task: `output/run-s06-t05-deepseek.ps1`
- Log đầy đủ: `output/s06-t05-deepseek-hermes.log` (926 KB)
- Backup trước copy: `output/backup-pre-copy/`
- Bản log UTF-8 để đọc nhanh: `C:\Users\Admin\MotionForge2D\output\hermes-task-logs\s06-t05-deepseek-LIVE.txt`
