# S11-T01B — REPORT

**Task:** S11-T01B — Original Audio Remux Engine
**Owning session:** 20260821_160614_40b90e (alpha @ custom, Hermes CLI)
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration — branch codex/s08-integration @ a43b20d
**Status:** **SUBMITTED** — chờ Manager verify / Codex review. KHÔNG tự ghi APPROVED.
**Date:** 2026-08-21 (+07)

---

## 1. Deliverables (đúng Exclusive write ownership)

| File | Loại | Nội dung |
|---|---|---|
| `app/services/original_audio_remux.py` | NEW | Pure/bounded remux engine: canonical first-audio selection, AAC stream-copy / non-AAC→AAC transcode (có fallback record), NO_AUDIO_PRESENT, fail-closed stable codes, bounded subprocess, atomic staging→validate→publish, deterministic checkpoint schema v1. |
| `tests/test_s11_original_audio_remux.py` | NEW | 16 required tests binary (test_01..test_16) + 2 supplementary (container/codec refusal, missing source) = 18 tests. |
| `output/s11-t01b/run-20260821-final/` | Evidence | pytest_verbose.log (full verbose run), evidence.md (lệnh + output thật từng bước). |
| `docs/pm/sessions/S11-T01B-original-audio-engine/TASK.md` | PACKET | Điền Owning session ID. |
| `docs/pm/sessions/S11-T01B-original-audio-engine/LOG.md` | PACKET | Append evidence entries. |

## 2. Required behavior 1-10 → implementation mapping

1. **Resolve canonical first audio stream** — ffprobe `-select_streams` qua full-stream query + `_first_stream(data,"audio")`; map `-map 0:a:0` (first AUDIO specifier); container index ghi vào `checkpoint["audio_stream_index"]` làm selection evidence (contract §2).
2. **AAC → copy; non-AAC → AAC transcode** — `-c:a copy` khi codec == aac; ngược lại `-c:a aac -b:a 192k`. Contract §4.1: nếu copy attempt fail → fallback transcode VÀ ghi `checkpoint["copy_fallback"]="stream_copy_unsafe_transcoded"` (không silent).
3. **No audio → NO_AUDIO_PRESENT** — result status `NO_AUDIO_PRESENT`, error_code None, không publish gì, managed dir rỗng.
4. **Corrupt source fail closed; stable error codes** — 16 stable codes (`CORRUPT_SOURCE`, `UNSUPPORTED_CONTAINER`, `UNSUPPORTED_VIDEO_CODEC`, `PATH_ESCAPE`, `OUTPUT_CAP_EXCEEDED`, `DEADLINE_EXCEEDED`, `CANCELLED`, `VALIDATION_FAILED`, `SOURCE_MUTATED`, …) mỗi code kèm Vietnamese suggested action.
5. **FFmpeg list args; shell=False; bounded stdout/stderr** — single Popen site `subprocess_popen()`: list args, `shell=False`, `stdin=DEVNULL`, ffmpeg thêm `-nostdin` (ffprobe không có flag này — đã verify); stdout+stderr drain concurrent bởi 2 daemon reader threads với combined 1 MiB byte ceiling, vượt → kill tree + `PROBE_OUTPUT_TOO_LARGE`.
6. **Deadline/remaining-budget bounded; cancellation terminates child** — mọi wait/join dùng `remaining_budget(deadline)` tái sử dụng từ `video_probe` (single budget authority); cancel_event poll trong main loop → kill ngay.
7. **Cleanup không vượt remaining budget; no orphan process** — `_kill_tree` dùng psutil children(recursive=True) kill trước rồi parent; reap/join chỉ với remaining budget; test 12/13/14 assert 0 orphan ffmpeg sau sự cố.
8. **Managed path containment; atomic staging; validate trước publish; never expose partial output** — `_resolve_managed_target` chặn absolute/drive/UNC/traversal/subdir/symlink escape; staging file unique `.name.<uuid>.staging.mp4` cùng directory; validate (codec==aac, timebase dương, duration trong tolerance, size ≤ cap) TRƯỚC `os.replace`; partial output không bao giờ xuất hiện ở published path (test 15 observe lúc child start).
9. **Probe output codec; validate duration/timebase; source bytes unchanged** — staged output probe lại bằng ffprobe; source sha256 hash trước + sau remux phải identical (`SOURCE_MUTATED` nếu đổi); duration tolerance max(0.5s, 5%) — đo được AC-3→AAC lệch +20ms, Opus→AAC +13ms (AAC priming noise), truncation thật sẽ vượt xa ngưỡng.
10. **No network/GPU; no Demucs/ASR/TTS/dubbing** — module chỉ import ffmpeg_utils + video_probe.remaining_budget + psutil; không có bất kỳ network/GPU/ML call nào.

## 3. Required tests (binary) — mapping & kết quả

| # | Required test | Test function | Kết quả |
|---|---|---|---|
| 1 | AAC stream-copy path | `test_01_aac_stream_copy_path` | PASSED |
| 2 | MP3→AAC | `test_02_mp3_transcoded_to_aac` | PASSED |
| 3 | AC-3→AAC | `test_03_ac3_transcoded_to_aac` | PASSED |
| 4 | PCM/Opus theo frozen contract | `test_04_pcm_opus_per_frozen_contract` | PASSED |
| 5 | No-audio | `test_05_no_audio_explicit_status` | PASSED |
| 6 | Corrupt source | `test_06_corrupt_source_fails_closed` | PASSED |
| 7 | Multi-stream selects first only | `test_07_multi_stream_selects_first_only` | PASSED |
| 8 | Duration/timebase validation | `test_08_duration_timebase_validation` | PASSED |
| 9 | Validation failure no publish | `test_09_validation_failure_no_publish` | PASSED |
| 10 | Path escape refusal | `test_10_path_escape_refused` | PASSED |
| 11 | Output cap | `test_11_output_cap_enforced` | PASSED |
| 12 | Timeout cleanup | `test_12_timeout_cleanup_no_orphan` | PASSED |
| 13 | Cancellation cleanup | `test_13_cancellation_cleanup_no_orphan` | PASSED |
| 14 | Child cleanup | `test_14_child_cleanup_on_ffmpeg_failure` | PASSED |
| 15 | Atomic publication | `test_15_atomic_publication` | PASSED |
| 16 | Deterministic result/checkpoint | `test_16_deterministic_result_checkpoint` | PASSED |
| + | Container/codec refusal (frozen §2) | `test_supplementary_container_and_codec_refusals` | PASSED |
| + | Missing source | `test_supplementary_missing_source` | PASSED |

## 4. Evidence (lệnh thật + output thật)

### 4.1 Worktree guard (trước mọi write)
```
$ pwd
/c/Users/Admin/MotionForge2D-worktrees/s08-integration
$ git rev-parse --show-toplevel
C:/Users/Admin/MotionForge2D-worktrees/s08-integration
$ git branch --show-current
codex/s08-integration
```

### 4.2 Final required-test run
```
$ python -m pytest tests/test_s11_original_audio_remux.py \
    -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01b_basetemp_final2 -v
...
============================= 18 passed in 19.37s =============================
```
Full log: `output/s11-t01b/run-20260821-final/pytest_verbose.log`

### 4.3 Regression (không phá task khác)
```
$ python -m pytest tests/test_s11_original_audio_contract.py tests/test_video_import.py \
    -q -p no:cacheprovider --basetemp=.../s11t01b_regress
40 passed, 74 warnings in 32.57s

$ python -m pytest tests/test_timebase.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py \
    -q -p no:cacheprovider --basetemp=.../s11t01b_regress2
94 passed, 2 skipped in 2.07s
```

### 4.4 Determinism proof (empirical, trước cả khi viết engine)
```
2 lần transcode ac3->aac với -fflags +bitexact -flags:a +bitexact:
d1 = d2 = a60e09f1c8f49b229a1a1b41669bf5dc1360eb6cd0489b2ac7d49bf27ba76758 → BITEXACT
stream-copy tương tự → BITEXACT_COPY
```
Test 16 chứng minh end-to-end: outputs byte-identical + checkpoints equal cho cả source AAC lẫn MP3.

## 5. Post-change hashes (sha256)

| File | Hash |
|---|---|
| app/services/original_audio_remux.py | 0175f42d6e131ebbe7c6c069524f7b004a5d86d5b84e80d31e5b0a1dd32c6f32 |
| tests/test_s11_original_audio_remux.py | 60a2ed6efb00748961c1476dcbe43bdb8dc0242e57c971ad8746b2c32572a7aa |

## 5.1 Stability verification (flaky hunt)

40 consecutive full-suite runs sau khi fix test_06: **40/40 × 18 passed**
(~19.4s/run). Flaky gốc đã triệt tiêu: 4096 random bytes hiếm khi
(~0.75%, đo trên 400 mẫu) được ffprobe nhận dạng nhầm thành container
``lrc`` → engine trả ``UNSUPPORTED_CONTAINER`` (đúng — vẫn fail-closed),
test cũ assert cứng ``CORRUPT_SOURCE``. Fix: test chấp nhận cả hai stable
codes (đều là fail-closed), assertion nghiêm là no-publish + no residue.

## 6. Bugs tìm thấy trong phiên (root-cause fix, chi tiết trong evidence.md)

1. `reader.join` trong finally của `_run_bounded` chỉ join err_reader (biến loop cuối) → out_reader leak. Fix: join tuple cả hai.
2. ffprobe KHÔNG có flag `-nostdin` (verify: "Option not found", rc=1) — chỉ ffmpeg có. Fix: bỏ flag khỏi probe cmds; stdin chặn tập trung tại Popen `stdin=DEVNULL`.
3. `os.fsync` trên file handle mở "rb" → Windows Bad file descriptor. Fix: fd O_RDWR riêng, fsync, close, rồi `os.replace`.
4. `-map 0:a:{container_index}` sai ngữ nghĩa — specifier `0:a:N` đếm trong audio streams, không phải container index ("Stream map '' matches no streams"). Fix: luôn `-map 0:a:0` (canonical first audio); container index chỉ là checkpoint evidence.

## 7. Compliance checklist

- [x] Hard worktree guard PASS trước mọi write (pwd + toplevel khớp, branch codex/s08-integration).
- [x] Chỉ ghi file trong Exclusive write ownership; không đụng video_import.py / job_service.py / models.py / migrations / API/frontend / file S07 / packet T01A/C/D.
- [x] Không git reset/clean/stash/restore/checkout-file/commit/push/merge; không MAIN repo; không production DB/data/motionforge.db; không git global config.
- [x] Tests dùng temp media lavfi/anullsrc (FFmpeg available), temp DB (không đụng DB nào), isolated managed root per-test tmp_path, basetemp Windows-native riêng, `-p no:cacheprovider`.
- [x] TASK.md Owning session ID đã điền.
- [x] LOG.md append evidence lệnh + output thật.
- [x] Status = SUBMITTED, KHÔNG tự ghi APPROVED.

## 8. Ghi chú cho reviewer

0d. **CORRECTION round 6 / R6 F1+F3 (2026-08-23T02:30+07, Codex
   CHANGES_REQUESTED — probe stream-cap + no-audio terminal invariant):**

   **F1 (P1) — probe từ chối nguồn hợp lệ ≥5 streams:** `_probe_streams`
   cũ fetch TOÀN BỘ streams (không `-select_streams`) rồi từ chối khi
   TỔNG vượt `_MAX_STREAMS=4` → MP4 H.264 + 4 AAC hoàn toàn hợp lệ bị
   `CORRUPT_SOURCE "source declares 5 streams"`. Repro thật TRƯỚC fix:
   engine raise đúng message đó trên fixture 5-stream. FIX engine:
   tách thành 3 probe bounded-select CHIA SẺ MỘT deadline (mỗi call
   `_run_bounded` nhận cùng monotonic deadline ⇒ chỉ tiêu remaining
   budget, không fresh window):
   - `_probe_one_stream(select="v:0")` — bounded như video_probe;
   - `_probe_one_stream(select="a:0")` — canonical first audio;
   - `_probe_format(format=format_name,duration)` — container section.
   Ceiling check GIỮ nguyên `_MAX_STREAMS=4` nhưng đổi vai trò: giờ là
   guard ffprobe-contract per-query (một specifier v:0/a:0 phải trả
   ≤1 stream), KHÔNG còn là rule từ chối nguồn theo tổng stream.
   Empirical xác minh trước khi sửa: `-select_streams a:0` trên file
   no-audio → rc=0 `"streams": []`; file corrupt (moov thiếu) → rc≠0
   bất kể select ⇒ phát hiện CORRUPT_SOURCE không bị yếu đi.

   **F3 (P2) — no-audio terminal bỏ qua drift pre/post hash:** nhánh cũ
   hash source TRƯỚC probe rồi post NGAY TRƯỚC return SUCCESS; repro
   monkeypatch deterministic cho thấy engine trả NO_AUDIO_PRESENT với
   `source_sha256=b9bdb6e3… ≠ post_remux_source_sha256=752d41e8…`.
   FIX engine — terminal boundary no-audio giờ theo thứ tự:
   1. cancel_event set → CANCELLED (zero target);
   2. re-hash vs pre-hash mismatch → SOURCE_MUTATED (zero target);
   3. re-check cancel SAU integrity gate — cancel thắng success result.

   **Regressions thêm (deterministic, monkeypatch hook, không sleep):**
   `test_r6_f1_five_stream_source_accepted` (fixture 1v+4a, assert
   precondition 5 streams, engine accept + publish đúng 2 streams
   h264+aac); `test_r6_f3_no_audio_mutation_raises_source_mutated`;
   `test_r6_f3_no_audio_terminal_cancel_wins`.

   **Gates tự chạy (lệnh + output thật):**
   - Serial ×2: **23 passed in 26.82s** và **23 passed in 26.70s**
     (`env -u MOTIONFORGE_DATABASE_URL … --basetemp=` riêng từng run,
     `-p no:cacheprovider`)
   - Repro explicit post-fix: 5-stream → STREAM_COPY, out audio
     `[{'index': 1, 'codec_name': 'aac'}]`; mutation-repro → SOURCE_MUTATED
   - ruff (engine+tests) exit 0; mypy exit 0; `git diff --check` sạch;
     process scan ffmpeg/ffprobe về baseline NONE

   Evidence: `output/s11-t01b/20260822_1500_r6-f1-f3/` (gate_a_serial_
   run1/2.log, gate_b_repros.log, gate_c_lint_mypy_process.log,
   gate_d_write_set.log, evidence.md).
   Hash sau R6 — engine:
   `19e5fc015c54dba20f3f18496e5dbfeb7493fd1ba86acecb4f4d133357c3f27b`;
   tests:
   `d435cc8302147c77b2cf6234edf1da8481aa5a6deb043f45c2918c1d65af3b83`.
   Write-set đúng giới hạn (triage trong gate_d: các file cấm mang mtime
   PRE-R6 từ session khác đang in-flight trên cùng worktree).
   **Status: TASK_SUBMITTED — chờ Codex re-review; KHÔNG tự ghi APPROVED.**

0c. **CORRECTION round 4 / R4-P2 (2026-08-22T14:05+07, Codex
   CHANGES_REQUESTED — orphan-test coverage re-parent):**

   **P2 — descendants-scan tại một thời điểm:** `_owned_ffmpeg_pids()`
   chỉ thấy process còn NẰM TRONG cây tại lúc gọi. Process ffmpeg/ffprobe
   bị re-parent sau khi parent chết (Windows đóng parent handle) rơi khỏi
   `descendants` ⇒ orphan thật bị leak-gate bỏ sót. Fix thuần test-side;
   engine KHÔNG đụng (hash giữ nguyên `47833d53…`) và KHÔNG có production
   defect ⇒ không ghi BLOCKED_ENGINE_DEFECT:
   - `_OwnedPidRecorder`: wrap `engine.subprocess_popen` — mỗi spawn
     ffmpeg/ffprobe được ghi PID NGAY LÚC TẠO (trước mọi khả năng
     re-parent) + sampler nền (50 ms) union thêm tree∧marker scan vào
     cùng pid-set trong suốt lúc engine chạy. Cross-run isolation giữ
     nguyên: suite khác mang marker khác, không bao giờ lọt vào set.
   - `_assert_no_orphans(marker, known_pids=…)`: phase mới poll CHÍNH
     NHỮNG PID đã snapshot (`psutil.Process(pid).is_running()` + name
     check chống Windows PID-reuse false-positive) tới khi hết hoặc hết
     deadline bounded 5 s — KHÔNG phụ thuộc descendants hiện hành ⇒
     re-parent-proof. Fallback không known_pids = tree∧marker scan như
     cũ (during-run). Không fixed sleep.
   - Wire vào test_12 (timeout), test_13 (cancel), test_14 (child-fail).
   - `test_concurrent_invocations_no_cross_blame` NÂNG CẤP: worker tự
     record pid-set lúc spawn, assert non-empty (snapshot không vacuous),
     post-run poll fixed PIDs; parent assert `WORKER_<tag>_PIDS ≥ 1` +
     `DEADLINE_EXCEEDED CLEAN` cho cả hai worker chạy đồng thời. Template
     render được `ast.parse` xác nhận compile OK.

   **Gates tự chạy (lệnh + output thật):**
   - a) Serial ×2: **20 passed in 23.87s** (run 1) và **20 passed in 23.91s** (run 2)
   - b) Concurrent 2 invocation basetemp+managed-root riêng: A exit=0 "**20 passed in 24.88s**", B exit=0 "**20 passed in 24.91s**" (wall 25.8s) — CONCURRENT_GATE: PASS
   - c) ruff → All checks passed (exit 0); `git diff --check` sạch; process scan sau test → máy về baseline NONE

   Evidence: `output/s11-t01b/20260822_1335_r4-reparent-proof/` (4 log gate + evidence.md).
   Hash sau R4-P2 — tests: `e8cac81711fdbf3d2900c9be422751db790f404eebd77e97dde3a180b99226fa`;
   engine KHÔNG đổi: `47833d53e3f59bc13a93cc6b071fed5b82e0af20723c723d32cf7e043100dd08`.
   Files changed đúng write-set: tests/test_s11_original_audio_remux.py +
   packet + evidence run-id mới. Temp đã dọn.
   **Status: TASK_SUBMITTED — chờ Codex re-review; KHÔNG tự ghi APPROVED.**

0b. **CORRECTION round 3 (2026-08-22T11:21+07, Codex CHANGES_REQUESTED —
   process-ownership trong leak/orphan check):**

   **P1 — name-only machine scan (tests):** `_ffmpeg_pids()` cũ quét toàn bộ
   process ffmpeg/ffprobe CỦA MÁY theo tên (`psutil.process_iter(["name"])`)
   → hai acceptance/remux suite chạy ĐỒNG THỜI với basetemp/managed root
   riêng đã nhận nhầm process của nhau là orphan và cùng fail. Fix thuần
   test-side (engine KHÔNG đụng — hash giữ nguyên `47833d53…`, không cần
   expose ownership info):
   - `_owned_ffmpeg_pids(marker)`: pid chỉ là "của run này" khi thỏa ĐỒNG
     THỜI 2 tín hiệu độc lập: (1) **process-tree** — descendant đệ quy của
     pytest process hiện hành (`psutil.Process(os.getpid()).children(
     recursive=True)`); (2) **cmdline marker** — đường managed_root riêng
     per-test (tmp_path) xuất hiện trong cmdline của process. Suite lạ
     không share tree lẫn marker ⇒ không thể cross-blame.
   - `_assert_no_orphans(marker)`: thay 3 chỗ `time.sleep(0.3)` cố định
     (che race) bằng bounded poll deadline 5s / poll mỗi 50ms; assert trên
     ownership-scoped set (invariant timeout/cancel dọn sạch orphan do RUN
     ĐÓ tạo ra — giữ nguyên).
   - Áp cho cả 3 test cleanup: test_12 (timeout), test_13 (cancel),
     test_14 (child-fail). SOURCE_MUTATED fix + atomic publish + mọi
     behavior hiện có giữ nguyên.

   **Concurrency regression control:** thêm
   `test_concurrent_invocations_no_cross_blame` — spawn 2 worker pytest-
   process ĐỒNG THỜI (`suite_alpha`, `suite_beta`: managed root + basetemp
   riêng), mỗi worker chạy engine THẬT breach deadline 1.5s rồi self-check
   ownership scope theo marker MÌNH; parent parse `WORKER_<tag>_RESULT`
   bắt buộc cả hai = `DEADLINE_EXCEEDED CLEAN` (chứng minh không cross-blame
   khi sibling đang chạy thật).

   **Gates tự chạy (lệnh + output thật):**
   - a) Serial ×2: `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_remux.py -q -p no:cacheprovider --basetemp=...` → **20 passed in 27.04s** (run 1) và **20 passed in 27.00s** (run 2)
   - b) Concurrent: 2 invocation song song basetemp riêng (+`MOTIONFORGE_MANAGED_ROOT` khác nhau ở B) → A exit=0 "**20 passed in 28.56s**", B exit=0 "**20 passed in 28.47s**" (wall 29.5s) — CONCURRENT_GATE: PASS
   - c) ruff 2 file → All checks passed (exit 0); mypy engine → Success no issues (exit 0); `git diff --check` sạch; process scan sau test → máy KHÔNG còn ffmpeg/ffprobe nào (về baseline)

   Evidence: `output/s11-t01b/20260822_1125_r3-ownership/` (4 log gate).
   Hash sau r3 — tests:
   `5621d5b102f05a3706282bda0b5f551895bc6cb67489c02997b512473f4ed50f`;
   engine KHÔNG đổi: `47833d53e3f59bc13a93cc6b071fed5b82e0af20723c723d32cf7e043100dd08`.
   Files changed đúng write-set: tests/test_s11_original_audio_remux.py +
   packet + evidence. Temp basetemp đã dọn.
   **Status: TASK_SUBMITTED — chờ Codex re-review; KHÔNG tự ghi APPROVED.**

0a. **CORRECTION round 2 (2026-08-22T04:20+07, Codex CHANGES_REQUESTED):**

   **P1 — fail-closed ordering (engine):** `os.replace(staging, target)` trước
   đây chạy TRƯỚC re-hash source; nếu source mutate sát publication thì raise
   `SOURCE_MUTATED` nhưng target đã tồn tại. Fix: chuyển khối Phase 5
   (re-hash + so sánh) lên NGAY SAU fsync staging và TRƯỚC `os.replace`;
   mismatch → `staging.unlink(missing_ok=True)` (suppress OSError) rồi raise
   `CODE_SOURCE_MUTATED` (stable code giữ nguyên) ⇒ invariant
   **"SOURCE_MUTATED ⇒ không có target"** đúng ở mọi path raise, không cần
   post-check. Atomic publication/fsync/validation/cancellation/timeout/
   output-cap/path-containment không đổi; copy/transcode behavior không đổi.
   Race window giữa pre-publish hash và `os.replace` được đánh giá chấp nhận
   được theo contract (TOCTOU thu hẹp về tối thiểu: chỉ còn khoảng giữa hash
   xong và rename — không thể loại trừ tuyệt đối khi không khóa source), và
   invariant bắt buộc của reviewer đã đảm bảo bằng thứ tự mới.

   **P2 — tautology (tests):** xóa dead check
   `assert probe_all_streams(...)[1:] == [] or True` tại :255; invariant
   "đúng 1 audio stream" đã assert chặt bởi `len(audio)==1 and
   audio[0]["codec_name"]=="aac"` ngay sau.

   **Regression test bắt buộc:** thêm
   `test_source_mutation_detected_before_publication` — mutate source
   DETERMINISTIC qua monkeypatch hook `_sha256_file` của engine (call đầu =
   pre-hash thật; mọi call hash SOURCE sau đó trả `"0"*64` ⇒ đúng lúc re-hash
   pre-publication phát hiện mismatch); KHÔNG sleep, KHÔNG race. Assert:
   (a) raise đúng stable code `SOURCE_MUTATED`; (b) `_published(...)` KHÔNG
   tồn tại sau call; (c) managed dir rỗng (staging/temp residue sạch).

   **Gates sau fix (lệnh + output thật):**
   - `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_remux.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01b-corr2` → **19 passed in 19.67s**
   - solo regression test → **1 passed in 1.96s**
   - `python -m ruff check app/services/original_audio_remux.py tests/test_s11_original_audio_remux.py` → **All checks passed!** (exit 0)
   - `python -m mypy app/services/original_audio_remux.py` → **Success: no issues found in 1 source file** (exit 0)

   Hash sau correction #2 — engine:
   `47833d53e3f59bc13a93cc6b071fed5b82e0af20723c723d32cf7e043100dd08`;
   tests: `be72f1b96678e1073143eb5c0771796a1b28d8f2703f8e8ac5b4fec6525fcca3`.
   Files changed đúng write-set T01B: engine + test remux + packet (LOG/REPORT).
   **Status: TASK_SUBMITTED — chờ Codex re-review; KHÔNG tự ghi APPROVED.**

0. **CORRECTION round 1 (2026-08-21T21:31+07, Manager verification):** fix hẹp
   đúng 4 lỗi quality gates trong engine, không refactor gì khác:
   - (1) ruff UP035 `Callable` tại :63 → import từ `collections.abc`
     (kèm sắp lại khối import theo isort để qua I001).
   - (2) ruff F841 biến chết `source_audio_time_base` tại :855 → xóa
     (không side-effect, không nơi nào dùng).
   - (3) mypy unused-ignore tại :71 (`psutil = None  # type: ignore[assignment]`)
     → bỏ comment; psutil là declared dependency nên nhánh except không chạy,
     và gán None cho module object được mypy chấp nhận.
   - (4) mypy unused-ignore tại :451 (`except subprocess_timeout() as exc  #
     type: ignore[misc]`) → bỏ comment; helper trả `type[Exception]` nên
     except clause hợp lệ sẵn.
   Kết quả gates (lệnh thật):
   - `python -m ruff check app/services/original_audio_remux.py tests/test_s11_original_audio_remux.py` → **All checks passed!** (exit 0)
   - `python -m mypy app/services/original_audio_remux.py` → **Success: no issues found in 1 source file** (exit 0)
   - `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_remux.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01b_corr1` → **18 passed in 19.42s**
   Hash sau correction — engine: `8c3a3bb7c9ac7d71a063f276eb14fa64bf1b178cd8b7a03496205432219775d3`;
   test file KHÔNG đổi: `60a2ed6efb00748961c1476dcbe43bdb8dc0242e57c971ad8746b2c32572a7aa`.

1. Engine đọc THÊM contract đã land của T01A (`docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md`) ngoài frozen decisions: §2 selection evidence (`audio_stream_index` trong checkpoint) và §4.1 copy-fallback-record đã implement + test được bổ sung sau khi phát hiện contract tồn tại giữa phiên.
2. Output cap do ENGINE tự monitor (poll size staging trong main loop) chứ không delegate `-fs` cho ffmpeg — verify trực tiếp: `-fs 1000` vẫn rc=0 và ghi 277KB (ffmpeg không fail khi vượt cap).
3. Timeout/cancel test dùng clip 300s (mp3→aac ~8.3s measured) với deadline 3s/cancel@2s — deterministic breach, không flaky sleep-guessing.
4. Determinism nhờ `-fflags +bitexact -flags:a +bitexact` — loại encoder/muxer version tags khỏi output bytes; đã verify BITEXACT trên cả hai path trước khi viết engine.
