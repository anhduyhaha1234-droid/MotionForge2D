# S12-T04A — LOG (independent output validator)

- Task: S12-T04A — output validator độc lập (new owner, KHÔNG publish/KHÔNG DB).
- Manager: 20260905_162953_5a5cda. Worktree:
  `C:\Users\Admin\MotionForge2D-worktrees\s12-s12-t04a-0907a`,
  branch `codex/s12/s12-s12-t04a-0907a`, baseline `0d04673` (T01 checkpoint).
- Contract: `docs/contracts/s12-export.md` §5 ValidationContract
  (s12-export-v1) — consume read-only, KHÔNG sửa file T01.

## Timeline (2026-09-07, UTC+7)

1. Đọc toàn bộ `HERMES_AUTOPILOT_RULES.md` (277 dòng) + frozen contract
   + `app/schemas/s12_export.py` (`ValidationContract`) +
   `app/services/s12_export/preflight.py` + T01 test conventions.
2. Preflight: pytest 9.1.1 / pydantic 2.13.4; libx264 + libx265 + aac OK;
   4K ultrafast encode ~0.3s/clip → dùng real-media 4K cho mọi test.
   ffprobe frame keys: presentation order dùng `pts` (strictly
   increasing; B-frame safe), `pkt_duration` absent → bỏ qua, không assert.
3. Viết `app/services/s12_export/validation.py` (NEW):
   `validate()` pure → `ValidationVerdict` (verdict + 10 probes theo đúng
   `REQUIRED_PROBES` order); binary qua `ffmpeg_utils.find_ffprobe()`
   (không hardcode path); `ValidationExpectation` frozen-manifest facts;
   `None` = manifest không assert → NOT_MEASURED, không PASS giả.
4. Viết `tests/s12/s12-t04a/`: `conftest.py` (real ffmpeg builders +
   session fixtures `good_4k`, `good_4k_audio`, `small_1080`,
   `tiny_hevc`), `test_validation_pass.py` (6), `test_validation_negatives.py`
   (14), `test_validation_units.py` (6).
5. Gate run 1: 25 passed + 1 failed — `test_pass_pinned_4k` dùng default
   `audio_policy="either"` (NOT_MEASURED by design) nhưng assert full PASS.
   Fix: test dùng `audio_policy="absent"` cho clip silent (đúng semantic;
   production code không đổi).
   Collect error xen giữa: `@pytest.mark.parametrize("codec", ...)` thừa
   trên `test_parse_rate_branches` (không có arg) → bỏ decorator.
6. Gate run cuối: 26 passed (4.11s) + `ruff check --select F` clean +
   T01 regression 15 passed (18.14s). Guard: 5 file T01 CLEAN (git diff),
   chỉ 2 path mới (validation.py + tests/s12/s12-t04a/).

## Gate outputs

- `python -m pytest tests/s12/s12-t04a/ -q --basetemp="$TEMP/s12t04a_bt" -p no:cacheprovider`
  → `26 passed in 4.11s`.
- `ruff check --select F app/services/s12_export/validation.py tests/s12/s12-t04a/`
  → `All checks passed!`
- `python -m pytest tests/s12/s12-t01/ -q --basetemp="$TEMP/s12t04a_t01" -p no:cacheprovider`
  → `15 passed in 18.14s` (T01 regression, frozen files untouched).

## Write-set (task worktree relative)

- NEW: `app/services/s12_export/validation.py`
- NEW: `tests/s12/s12-t04a/conftest.py`, `test_validation_pass.py`,
  `test_validation_negatives.py`, `test_validation_units.py`
- NEW: `docs/pm/sessions/S12-T04A/LOG.md`, `REPORT.md`

Không sửa conftest chung/test cũ, không đụng models/migration (T03A lock),
không touch S11 files, không đụng ports demo, không hardcode user path.
