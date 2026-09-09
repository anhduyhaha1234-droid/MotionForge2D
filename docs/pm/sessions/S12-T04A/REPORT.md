# S12-T04A — REPORT (independent output validator)

**Status: TASK_SUBMITTED (W2 correction)** — branch
`codex/s12/s12-s12-t04a-0907a` (baseline `0d04673`, W1 checkpoint `0c3ad1a`
có locally). Không push — Manager/INT01 lo.

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

## W2 correction — C1 rows C19 + C12-part

- `ValidationExpectation`: `expected_fps` (CFR control), `reject_vfr=True`
  (VFR rejected pre-work), `expected_cuts` + `cut_tolerance_frames=1.5`
  (source-locked seams, rational `pts × time_base` qua Fraction).
- `timebase` FAIL khi `r_frame_rate != avg_frame_rate` (VFR) hoặc fps sai
  manifest; `_check_cuts` fold vào `frame_order` — mỗi cut phải land trên
  keyframe; `streams` FAIL với unexpected stream types.
- `test_c1_closure.py` (22 tests): C19 full matrix (corrupt/truncate/dims/
  codec/streams/count/order/cut/timing/audio/provenance, missing-extra
  chunk, `.partial` → FAIL/NOT_MEASURED; self-hash circular → overall FAIL)
  + C12-part (A+B stitch PASS với cuts keyframe-locked + CFR exact; VFR
  giả lập FAIL; CFR control PASS). Không xóa case cũ.

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

- `python -m pytest tests/s12/s12-t04a/ -q --basetemp="$TEMP/s12t04a_all" -p no:cacheprovider`
  → **48 passed in 6.64s** (W2: 26 cũ + 22 `test_c1_closure.py` C19/C12-part)
- `python -m pytest tests/s12/s12-t04a/test_c1_closure.py -q --basetemp="$TEMP/s12t04a_c1" -p no:cacheprovider`
  → **22 passed in 4.92s**
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

## C2 W2 — source-locked validator (F07 validator part; C12/C19/C28 consumers)

Production: only `app/services/s12_export/validation.py` changed (scope
C2 W2 T04A). SourceReference/AudioReference/CutPoint + `source_locked`
mode as described in LOG. Independent immutable reference evidence
(frame digests / rational cuts / fps_num-den / approved-audio digest)
now establishes exact frame count/order/cuts, rational timebase,
inventory, audio content/mapping and start/end drift within the
one-source-frame bound (1/fps). Monotonic PTS, codec keyframes, audio
presence and candidate self-hash alone never PASS source-locked
validation. T01/T02/T03A/T03B files untouched (FORBIDDEN list respected).

## Gates C2 W2 (exact commands)

- `python -m pytest tests/s12/s12-t04a/ -q --basetemp="$TEMP/s12t04a_full" -p no:cacheprovider`
  → **64 passed in 14.62s** (48 prior + 16 test_c2_source_locked.py)
- `python -m pytest tests/s12/s12-t04a/test_c2_source_locked.py -q --basetemp="$TEMP/s12t04a_c2" -p no:cacheprovider`
  → **16 passed in 6.81s**
- `ruff check --select F app/services/s12_export/validation.py tests/s12/s12-t04a/`
  → **All checks passed!**
- `git diff --check` → 0
- `python -m pytest tests/s12/s12-t01/ -q --basetemp="$TEMP/s12t04a_t01c2" -p no:cacheprovider`
  → **38 passed in 55.51s** (T01-C2 regression)

Write-set C2 W2 (allowlist): app/services/s12_export/validation.py (M),
tests/s12/s12-t04a/test_c2_source_locked.py (NEW), LOG.md/REPORT.md (M).
