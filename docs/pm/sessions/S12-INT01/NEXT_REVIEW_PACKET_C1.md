# S12-C1 NEXT_REVIEW_PACKET — for Codex reviewer

**Verdict: SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW** (không phải APPROVED/CLOSED).

## 1. Integration pointers

- Branch: `codex/s12-integration`; HEAD: `60d586417c0eea4d2fa26f4f965a9c53daf16a7a` — local == remote (ls-remote verified), porcelain 0.
- Push range: `0d2e063..60d5864` (non-force).
- Evidence root: `C:/Users/Admin/MotionForge2D-evidence/s12/20260907-182016-C1`.

## 2. C1 merge history (canonical)

| Wave | Lane | Merged commit | Merge commit |
|---|---|---|---|
| W1 | T01-C1 | `0d5bc77` | `0c3ad1a` (pre-existing) |
| W2 | T02-C1 | `7774a3a` | `51d0764` |
| W2 | T03A-C1 | `39442d1` | `45adba0` |
| W2 | T04A-C1 | `d60de45` | `61bff78` |
| W2-fix | T02-C1-fix | `81793a8` | `46feca4` |
| W3 | T03B-C1 | `bd3d9d5` | `0d2e063` |
| W4 | T03C-C1 | `9a91e18` | `a4af4f3` |
| W5 | T05-C1 | `76bd79f` | `09e9a4a` |
| W6 | T06A-C1 | `00d1084` | `5a38e73` |
| W7 | T06B-INT01-fix | `97a54b0` | `60d5864` |

## 3. Final gates (canonical HEAD `60d5864`, all actually run)

- pytest per-dir (basetemp ngắn %TEMP%, `-p no:cacheprovider`):
  - T01 `s12-t01`: **31 passed**
  - T02 `s12-t02`: **36 passed**
  - T03A `s12-t03a`: **44 passed**
  - T03B `s12-t03b`: **32 passed**
  - T03C `s12-t03c`: **19 passed**
  - T04A `s12-t04a`: **48 passed**
  - T06B `s12-t06b`: **11 passed, 1 skipped** (clean-machine NOT_RUN)
  - Tổng backend: **221 passed, 1 skipped** (không tính trùng lặp collection; các dir chạy riêng vì trùng basename `test_c1_closure.py` giữa các package — pre-existing, không phải lỗi code)
- Playwright T05 real-API (no mocks, desktop + mobile 390x844): **23 passed + 1 skipped** (54.7s) — gồm C20 project-export, C21 durable-refresh, C22 result-access.
- `ruff check --select F tests/s12/`: **All checks passed**.
- `git diff --check`: clean.
- Alembic: sole head `c3d4e5f6a7b8`.
- T06A lifecycle live: setup/serve/diagnose READY (backend :8423, frontend :3123), stop ports down, uninstall data kept, manifest rebuild `SMMKnaiyQ5jEj09fkhU72`.

## 4. Findings closed during C1

1. T03C 2 TypeErrors thật (unmocked): `compute_project_readiness` kwargs-only + `ChunkSpec` missing `content_hash`/`attempt` — fixed `9a91e18` (+4 repro tests).
2. T06B `test_f3_provenance_decides_not_filesize` bám behavior CŨ (F-OBS-01 chưa fix); T01-C1 `0d5bc77` đã fix preflight → test fail trên canonical merged. T06B cập nhật test assert behavior mới (bare ≥3840x2160, no provenance → `upscale_4k`), note F-OBS-01 CLOSED bởi T01-C1 — `97a54b0`.

## 5. Open items for Codex

1. **cmc weekly quota exhausted (429)** từ 2026-09-09 ~17:50 +07, reset `2026-09-11T17:23Z`. Worker T06B-fix chạy bằng `ocgfree/muse-spark-1.3-contributor-free` (route user từng cấp phép 2026-09-08). Chỉ thị model mới từ user sau reset là quyết định của user/Codex.
2. `test_c1_closure.py` trùng basename giữa `tests/s12/s12-t0X/` (thiếu `__init__.py` ở t01/t02/t04a) — chạy full-tree `pytest tests/s12/` 1 lệnh sẽ collection-fail; cần chạy per-dir. Không sửa file (giữ ownership); có thể cân nhắc thêm `__init__.py` ở correction sau.
3. Clean-machine T06B: NOT_RUN (không VM sạch) — không waive, beta blocked.
4. S11 vẫn NOT_CLOSED (stream riêng); không mở S13.

## 6. Do-not-do (reviewer)

- Không rebase/reset/force-push `codex/s12-integration`.
- Correction tiếp theo → exact task owner session (đã ghi registry).
