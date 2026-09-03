# S11-T06A1 LOG — Deterministic media/QC seed infrastructure (W3)

Task: S11-T06A1 | Branch: `codex/s11/t06a1-0903w3` | Wave: W3 (serial sau W2)
WAVE_BASE: `cd4f7925b9f924e19887ea3e7498c985fa28f454` (canonical HEAD sau T02B)
Authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` (verified: `sha256sum` khớp)
Session: NEW SESSION (worker duy nhất cho T06A1) | ISOLATED WORKTREE `s11-t06a1-0903w3`
Model route: `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback OFF, TTFB 900 (bám S11-SPRINT_CONTRACT §Worker model 2026-09-03)
Runtime: Windows, Python 3.11.9, ffmpeg `8.1.2-full_build-www.gyan.dev` (WinGet Links), pytest 9.1.1

## 0. Baseline (bắt buộc — porcelain 0, đúng branch, đúng HEAD)

```
$ git status --porcelain                                  -> (rỗng)
$ git branch --show-current                               -> codex/s11/t06a1-0903w3
$ git rev-parse HEAD                                      -> cd4f7925b9f924e19887ea3e7498c985fa28f454
$ git rev-parse cd4f7925...                               -> cd4f7925... (khớp WAVE_BASE)
$ ls tests/fixtures/                                      -> legacy_import s08_golden s09_demo s09_renderer s10_full_apply
   (s11_golden KHÔNG tồn tại → không có file cấm để đọc; app/services/qc_checks/ chưa tồn tại)
```

## 1. Probe thực nghiệm trước khi freeze manifest (ground truth)

Dùng ffmpeg/ffprobe local dựng lần lượt từng variant vào `%TEMP%/s11t06a1-probe` (Windows-native path — MSYS `/tmp` path conversion là pitfall đã biết):

```
two_scene:  F: mov,mp4,m4a,3gp,3g2,mj2 dur=4.000000  S: video h264 320x240, audio aac 1ch
multistream: F: mov,mp4,m4a,3gp,3g2,mj2 dur=3.000000  S: video h264 + 4x audio aac 1ch
non_mp4 .mkv: F: matroska,webm dur=2.023000          S: video h264, audio aac 1ch
vp9 .mp4:  F: mov,mp4,m4a,3gp,3g2,mj2 dur=2.000000   S: video vp9, audio aac 1ch
mpeg4 .mp4: F: mov,mp4,m4a,3gp,3g2,mj2 dur=2.000000  S: video mpeg4, audio aac 1ch
no_audio:  F: mov,mp4,m4a,3gp,3g2,mj2 dur=2.000000   S: video h264 (0 audio)
corrupt middle-cut [25%,75%): src 39810 -> 19905 bytes; ffprobe rc=1 "moov atom not found";
                           ffmpeg decode rc=183 "Invalid data found when processing input"
```

Kết luận freeze: corrupt = middle truncate → `probe_must_fail: true`; mkv duration đọc 2.023 → tolerance 0.35 phủ.

## 2. RED trước (TDD — module chưa tồn tại)

Harness `tests/test_s11_t06a1_fixture_harness.py` viết TRƯỚC, chạy lần đầu với đủ cờ isolation:

```
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t06a1_fixture_harness.py \
    -p no:cacheprovider --basetemp "C:/Users/Admin/AppData/Local/Temp/s11t06a1-w3-red-1433-1" -q
  -> ImportError while collecting test_s11_t06a1_fixture_harness.py
  -> ModuleNotFoundError: No module named 's11_qc_media_builders'          (RED đúng lý do)
```

## 3. Implement + GREEN loop (các lần chạy thật, EXIT thật)

| Lần | Lệnh (đủ cờ isolation) | Kết quả thật |
|---|---|---|
| g1 | `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t06a1_fixture_harness.py -p no:cacheprovider --basetemp <w3-g1-1777-1> -v` | 6 failed, 2 passed — `KeyError: 'build_two_scene_source'` (`_BUILDERS` keyed sai: theo scenario thay vì tên builder) |
| g2 | same flags | 6 failed, 2 passed — `ffmpeg: Unable to choose an output format for '1:a'` (expand `-map 0:v 1:a ...` sai: mỗi `-map` phải đứng riêng) |
| g3 | same flags | 3 failed, 5 passed — (a) schema-check corrupt manifest thiếu `format_name_contains`; (b) `probe_error` chứa path+pointer hex → differ cross-run; (c) seed test đếm cumulative sai |
| g4–g5 | same flags | 1 failed, 7 passed — scrub regex chưa bắt pointer không tiền tố `0x` (`@ 0000020...`) |
| g6–g8 | same flags | 1 failed — byte-equality fail ở `unsupported_non_mp4` (Matroska SegmentUID random per mux — không có option tắt; kiến trúc container) |
| g9 | same flags | **8 passed in 10.88s** (GREEN) |
| r1 | `--basetemp <w3-r1-2326-1>` | **8 passed in 10.69s — EXIT 0** (log: evidence/run1.txt) |
| r2 | `--basetemp <w3-r2-2326-2>` | **8 passed in 10.71s — EXIT 0** (log: evidence/run2.txt) |
| final | `--basetemp <w3-final-...>` | **8 passed in 10.61s — EXIT 0** (sau dọn import ruff) |

Sửa chính thức (đều có lý do, không mò): builder-key theo tên manifest builder; `-map` lặp riêng flag; scrub determinism `probe_error` (hex ptr + abs path → `<ABS>`/`0xPTR`); manifest-schema branch corrupt; seed test đếm cumulative 7 (4+3); byte-determinism ngoại lệ mkv (SegmentUID random — probe facts + size vẫn deterministic, 6 MP4 byte-identical thật).

## 4. Evidence scripts (chạy thật, output trong evidence/)

```
$ python %TEMP%/s11t06a1-w3-evidence/ev_probe_facts.py      -> 7 scenario dựng 1 lệnh; facts ffprobe thật (xem probe_facts.json)
   two_scene_source            size= 39810 format=mov,mp4,... dur=4.0   streams=[h264, aac x1]
   multistream_duration_variant size=142022 format=mov,mp4,... dur=3.0   streams=[h264, aac x4]
   unsupported_non_mp4          size= 43598 format=matroska,webm dur=2.023 streams=[h264, aac]
   unsupported_vp9              size= 49262 format=mov,mp4,... dur=2.0   streams=[vp9, aac]
   unsupported_mpeg4            size= 78780 format=mov,mp4,... dur=2.0   streams=[mpeg4, aac]
   corrupt_truncate             size= 13219 probe_ok=False "moov atom not found"
   no_audio_source              size= 26437 format=mov,mp4,... dur=2.0   streams=[h264]

$ python %TEMP%/s11t06a1-w3-evidence/ev_seed_counts.py
   reason_codes_total: 8 | count_after_first_seed: 8 | count_after_reseed: 8 | ids_identical_across_seeds: True
   rows: trajectory_drift/cut_drift/contact_break/z_order/clipping/identity/flicker/audio_timecode
         (status=open severity=warning ewk=two_scene_source:all:<code> — full JSON: evidence/seed_counts.json)
```

## 5. Gates (chạy thật, output thật)

```
$ git diff cd4f7925... -- tests/s11_qc_media_builders.py tests/s11_qc_seed.py \
    tests/test_s11_t06a1_fixture_harness.py tests/fixtures/s11_qc/ \
    | grep -inE "qc_thresholds|thresholds\.py|expected[-_ ]outcome|calibration"
  -> (rỗng)  GREP_EXIT=1 = ZERO tham chiếu (AC2)

$ ruff check --select F tests/s11_qc_media_builders.py tests/s11_qc_seed.py tests/test_s11_t06a1_fixture_harness.py
  -> All checks passed! (RUFF_EXIT=0; sau khi bỏ F401 iter_manifests khỏi s11_qc_seed)

$ python -m py_compile tests/s11_qc_media_builders.py tests/s11_qc_seed.py tests/test_s11_t06a1_fixture_harness.py
  -> py_compile OK

$ python -c "json.load cho 7 manifests" -> 7/7 OK (corrupt_truncate, multistream_duration_variant,
   no_audio_source, two_scene_source, unsupported_mpeg4, unsupported_non_mp4, unsupported_vp9)

$ git diff --stat cd4f7925... -> (rỗng — toàn bộ file mới untracked)
$ git status --porcelain -> ?? tests/fixtures/s11_qc/ | ?? tests/s11_qc_media_builders.py
                            | ?? tests/s11_qc_seed.py | ?? tests/test_s11_t06a1_fixture_harness.py
                            (KHÔNG có file modified nào — scope chỉ allowlist + docs)
```

## 6. Commit

```
$ git add tests/s11_qc_media_builders.py tests/s11_qc_seed.py \
      tests/test_s11_t06a1_fixture_harness.py tests/fixtures/s11_qc/media_manifests/ \
      docs/pm/sessions/S11-T06A1/
$ git commit -m "S11-T06A1 (W3): deterministic media/QC seed infrastructure"
$ git log -1 --format="%H %s"   -> <xem REPORT/terminal>
```
Commit LOCAL trên task branch — KHÔNG push/merge/rebase/reset/clean/stash/force.

## 7. Status

`TASK_SUBMITTED` — toàn bộ acceptance criteria 1–4 đạt (bảng đối chiếu trong REPORT.md). EXIT.
---

## 8. CORRECTION C1 (resume exact session — finding P1 contract violation)

Resume: session `20260903_122658_633b7e`, branch fast-forward tới canonical
`746b129a35783b132ff7e29f6a35389288a67ac1` (T02A-C1 fix enum: 10 reason codes).
Finding: manifests dùng reason-code cũ → seed fail DB CHECK (28 fail gate cumulative; diagnosis 2/2 fail harness).

### Fix (2 manifest — seed_plan)

```
two_scene_source.json:            ["trajectory_drift","cut_drift","identity","flicker"]
                                  -> ["trajectory_drift","cut_drift","identity_drift","temporal_flicker"]
multistream_duration_variant.json:["audio_timecode","cut_drift","clipping"]
                                  -> ["audio_missing","av_sync_drift","cut_drift"]
```

`tests/s11_qc_seed.py` + `tests/test_s11_t06a1_fixture_harness.py`: KHÔNG cần sửa —
seed/harness derive từ `QC_REASON_CODES` (10 codes binding) nên kỳ vọng tự đúng; scan xác nhận
zero token cũ trong cả 3 file + 7 manifests.

### Verify (chạy thật sau sửa)

```
$ grep -rnE 'z_order"|"clipping"|"identity"|"flicker"|"audio_timecode"' \
      tests/fixtures/s11_qc/media_manifests/ tests/s11_qc_media_builders.py \
      tests/s11_qc_seed.py tests/test_s11_t06a1_fixture_harness.py
  -> (rỗng) RESCAN_EXIT=1 = zero token cũ (PASS)

$ python -m pytest tests/test_s11_t06a1_fixture_harness.py \
      -p no:cacheprovider --basetemp "C:/Users/Admin/AppData/Local/Temp/s11t06a1-c1-463-1" \
      (env -u MOTIONFORGE_DATABASE_URL)
  -> 8 passed in 10.77s — PYTEST_EXIT=0
     (test_seed_every_reason_code giờ seed FULL 10 codes qua repository)

$ python %TEMP%/s11t06a1-w3-evidence/ev_seed_counts.py
  -> reason_codes_total: 10 | count_after_first_seed: 10 | count_after_reseed: 10
     ids_identical_across_seeds: True
  -> rows: trajectory_drift, cut_drift, contact_break, z_order_error,
     silhouette_clipping, identity_drift, edge_halo, temporal_flicker,
     audio_missing, av_sync_drift  (evidence/seed_counts.json đã cập nhật)

$ ruff check --select F tests/s11_qc_media_builders.py tests/s11_qc_seed.py \
      tests/test_s11_t06a1_fixture_harness.py
  -> All checks passed!
$ python -m py_compile ... -> py_compile OK
```

### Commit C1

`git add` CHỈ 2 manifest + docs/S11-T06A1 (LOG/REPORT + evidence/seed_counts.json); commit local 1 commit.
