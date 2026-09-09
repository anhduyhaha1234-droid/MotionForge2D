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

## Correction W2 — C1 rows C19 + C12-part (2026-09-08, UTC+7)

Owner resumed exact session/branch @ `c375b87`, porcelain clean.
RULES_LOADED (277 dòng, SHA c9b068b2). W1 checkpoint `0c3ad1a` đã có
locally (fetch remote bị chặn bởi ref rác `turn-diffs/captures`, không
merge/rebase). Contract W1 chỉ đổi §3 provenance + §4 capability —
validation contract §5 T04A consume KHÔNG đổi.

Validator mở rộng (`validation.py`, bounded patch + helper script):
- `ValidationExpectation` thêm `expected_fps`, `reject_vfr=True`,
  `expected_cuts`, `cut_tolerance_frames=1.5`.
- `timebase`: `r_frame_rate != avg_frame_rate` → FAIL (VFR rejected
  pre-work, C12); `expected_fps` mismatch → FAIL (CFR control).
- `_check_cuts` (fold vào `frame_order`): mỗi manifest cut phải land
  trên keyframe trong tolerance, so rational `pts × time_base`
  (Fraction) — không float seconds. Không cuts → không verdict
  (giữ 10-probe shape).
- `streams`: unexpected stream types (subtitle/data/…) → FAIL.
- Inventory bổ sung `r_frame_rate`.

`tests/s12/s12-t04a/test_c1_closure.py` (NEW, 22 tests, C1 MATRIX.md
convention `test_c1_closure.py`, không xóa case cũ):
- C19 control PASS + truncate-half/header-corrupt/non-media FAIL;
  mid-bytes-corrupt → FAIL/NOT_MEASURED (không PASS).
- dims/codec FAIL (+ hevc-match shape); missing/extra chunk FAIL.
- cut mid-GOP (1.0s, GOP chỉ key tại 0) → frame_order FAIL;
  cut tại 0.0 → PASS.
- duration +30s FAIL; fps 25-vs-10 FAIL; audio hai chiều FAIL.
- provenance: wrong-hash FAIL; self-hash sub-clip (hash đúng chính nó
  nhưng count/duration sai manifest) → provenance PASS nhưng overall
  FAIL — circular PASS không bao giờ đủ.
- `.partial` FAIL; swapped-concat B+A (provenance pin chunk A) FAIL.
- C12-part: A+B stitch đúng thứ tự (cuts 0.0/1.0 keyframe-locked,
  CFR exact) → PASS; VFR giả lập (monkeypatch r_frame_rate 15/1 vs
  avg 10/1) → timebase FAIL; CFR control PASS.

Pitfalls: cut 0.05s PASS đúng behavior (tolerance 1.5 frame × 0.1s =
0.15s bao 0.05) → đổi cut test sang 1.0s; self-hash truncate nửa file
→ completeness FAIL early (probe provenance None) → đổi sang sub-clip
`-c copy -t 1.0` decode được; pict IPPPP (ultrafast GOP dài, key duy
nhất pts 0) xác nhận bằng ffprobe thật.

Gate W2: full `tests/s12/s12-t04a/` 48 passed (6.57s) + ruff F clean +
`git diff --check` 0 + T01 regression 15 passed (14.99s).

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

## Correction C2 W2 — source-locked validator (2026-09-09, UTC+7)

Owner resumed @ `0bbb3b3` (canonical post T01-C2), porcelain clean.
RULES_LOADED: C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md,
SHA c9b068b2…, 277 lines. Sources read before coding: REVIEW.md F01–F11
(`.../outputs/s12-c1-review-20260909/`), S12-C2-HERMES-PROMPT.md §4 T04A +
§5 rows C12/C19/C28, docs/contracts/s12-export.md §5/§8 (T01-C2 authority).

F07 validator part closed (app/services/s12_export/validation.py only):
- NEW dataclasses: `SourceReference` (artifact_sha256, frame_count,
  fps_num/den, per-frame `frame_digests`, rational `cuts`, `audio`),
  `AudioReference(mode=remux|transcode|absent, digest, stream_index)`,
  `CutPoint(frame_index, pts_num, pts_den)`; `ValidationExpectation` gains
  `source_locked: bool` + `source_reference`.
- Source-locked mode: candidate self-evidence (monotonic PTS, keyframes,
  audio presence, self-hash) is NOT accepted as proof. Probes are
  recomputed against the independent reference: streams inventory,
  exact frame_count, frame_order via decoded-content digests (rawvideo
  per-frame sha256, presentation order) or rational cut placement,
  timebase exact rational CFR (VFR rejected — no false confidence),
  duration within the one-source-frame bound (1/fps, replacing the old
  2%+50ms gate), av_policy presence/mapping + remux PCM digest +
  A/V start/end drift <= 1 frame, provenance requires server-owned sha.
- Missing reference authority → FAIL; missing content-order evidence
  (no digests, no cuts) → NOT_MEASURED, never fake PASS.
- NEW helpers exported: `probe_frame_digests`, `probe_audio_digest`;
  `_probe_av_bounds` now also reports median packet deltas so end-drift
  compares last-packet-end (a_last+a_delta vs v_last+v_delta).

Tests (NEW tests/s12/s12-t04a/test_c2_source_locked.py, 16): C19 — full
pass w/ reference; equal-length reordered content (B+A) FAIL; changed
audio (remux digest) FAIL; timing drift FAIL; wrong reference FAIL;
missing reference FAIL; combined reorder+audio FAIL; self-hash PASS but
misplaced-cut reference FAILs overall. C12 — rational cut placement
PASS; missing order authority NOT_MEASURED; wrong cut time FAIL; VFR
(monkeypatched r_frame_rate) FAIL; fps mismatch vs rational reference
FAIL. C28 — remux matching audio PASS; transcode explicit not
content-compared PASS; audio start drift (+0.5s itsoffset) FAIL.

Pitfalls: adelay filter silently not applied in multi-input remap (ffmpeg
graph quirk) → drift test uses `-itsoffset` (verified real: a_first 0.476
vs bound 0.1); AAC negative priming pts (-0.0232) is normal and inside
the 1-frame bound; transcode re-encode adds encoder tail so end drift is
measured packet-end-to-packet-end; cuts-only reference is legitimate
authority (PASS), missing both digests AND cuts is NOT_MEASURED.

Gates C2 W2: full tests/s12/s12-t04a/ 64 passed (14.62s) + ruff F clean
+ git diff --check 0 + T01 regression 38 passed (55.51s).
