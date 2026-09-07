# S12-T04A — REPORT (independent output validator)

**Status: TASK_SUBMITTED** — branch `codex/s12/s12-s12-t04a-0907a`
(baseline `0d04673`). Không push — Manager/INT01 lo.

## What was built

`app/services/s12_export/validation.py` — pure validator trên frozen
contract `s12-export-v1` (§5 `ValidationContract`, T01 owner):

- `validate(output_path, expectation) -> ValidationVerdict`: pure function,
  KHÔNG publish, KHÔNG update DB (verdict chỉ mang verdict + probes +
  output_path + contract_version, không handle/mutator).
- 10 probes đúng thứ tự `required_probes`: completeness → resolution →
  codec → streams → frame_count → frame_order → timebase → duration →
  av_policy → provenance. Verdict aggregate: any FAIL → FAIL; else any
  NOT_MEASURED → NOT_MEASURED; else PASS.
- ffprobe + decode cần thiết: resolution/codec/streams từ stream inventory;
  frame count/order/timebase từ frame-decode table (`pts` strictly
  increasing — B-frame safe); duration từ container (tolerance 2% + 0.05s);
  provenance = sha256 identity so manifest (không bao giờ dùng file size).
- Insufficient evidence → FAIL hoặc NOT_MEASURED, không PASS giả:
  missing file, unreadable container, `.partial` suffix → FAIL;
  manifest không assert count/duration/audio/sha → NOT_MEASURED.
- Audio policy 3 mode: `required` (phải có audio), `absent` (phải silent),
  `either` (manifest không constrain → NOT_MEASURED); policy lạ → FAIL-closed.
- Binary discovery qua `ffmpeg_utils.find_ffprobe()` (SINGLE authority),
  không hardcode path; không đụng models/migration (T03A lock).

## Tests (26, isolated fixtures + real-media negatives)

`tests/s12/s12-t04a/` — conftest riêng (KHÔNG sửa conftest chung/test cũ);
media thật encode bằng ffmpeg (testsrc 3840x2160 h264 + aac, ultrafast);
fresh isolated roots (`$TEMP/s12t04a_bt` basetemp ngắn):

- `test_validation_pass.py` (6): full PASS với expectation pinned
  (20 frames / 2.0s / sha256 thật); PASS audio-required; absent-audio;
  default unconstrained → NOT_MEASURED-by-design (không PASS giả);
  contract shape khớp `ValidationContract` frozen; purity (không tạo file
  cạnh input, verdict không mang publish handle).
- `test_validation_negatives.py` (14): missing path, truncate 50%,
  corrupt bytes, zero-byte, wrong dimension 1080p, codec mismatch h264-vs-hevc
  (+ hevc-match shape), timing +30s, missing/extra chunk (±frame count),
  audio-required-trên-clip-silent, audio-trên-policy-absent,
  sha256 mismatch, `.partial` suffix — tất cả FAIL (corrupt cho phép
  FAIL/NOT_MEASURED), không PASS giả.
- `test_validation_units.py` (6): probe order/coverage, bad audio_policy
  fail-closed, non-media bytes, directory path, `_parse_rate` branches,
  probe lookup miss.

## Gates (exact commands)

- `python -m pytest tests/s12/s12-t04a/ -q --basetemp="$TEMP/s12t04a_bt" -p no:cacheprovider`
  → **26 passed in 4.11s**
- `ruff check --select F app/services/s12_export/validation.py tests/s12/s12-t04a/`
  → **All checks passed!**
- `python -m pytest tests/s12/s12-t01/ -q --basetemp="$TEMP/s12t04a_t01" -p no:cacheprovider`
  → **15 passed in 18.14s** (T01 regression — frozen files untouched)

## Guards

- Byte-guard: 5 file T01 (contract, schemas, preflight, `__init__`, T01 test)
  `git diff` CLEAN — consume read-only, không drift → không BLOCKED.
- Chỉ 2 path mới: `app/services/s12_export/validation.py` +
  `tests/s12/s12-t04a/` (+ docs session). Không touch S11, ports demo,
  models/migration; không hardcode user path.

## Handoff

Consumer kế: T03C publication (requires validation PASS), T06A/B
acceptance. `ValidationExpectation` nhận facts từ frozen manifest/run
(T01/T03A authorities); `.partial` không bao giờ completed.
