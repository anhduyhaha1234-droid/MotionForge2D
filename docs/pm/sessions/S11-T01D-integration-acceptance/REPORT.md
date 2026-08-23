# S11-T01D — REPORT

**Task:** Real Integration and Acceptance (Original Audio)
**Owning session:** 20260822_003041_b18319
**Worktree guard:** PASS (kiểm tra lại trước MỖI correction) — pwd =
`/c/Users/Admin/MotionForge2D-worktrees/s08-integration`, `git rev-parse --show-toplevel`
khớp, HEAD = a43b20da742996bafcb2f9d1ac57b10d3f1a5204.
**Status:** **SUBMITTED** — re-submitted sau C1 (**TASK_SUBMITTED**), C2
(**TASK_SUBMITTED**), C3 (**TASK_SUBMITTED**), R5 (**TASK_SUBMITTED**),
R6-F4 (**TASK_SUBMITTED**). KHÔNG tự ghi APPROVED.

## Deliverables (đúng allowlist gốc)

1. `tests/test_s11_original_audio_integration.py` (NEW) — 9 test binary cho
   required scenarios 1–8 của TASK.md. REAL production path: default
   `JobService`, temp SQLite alembic-upgrade-head, temp managed root, FFmpeg
   lavfi synthetics thật; chỉ clock/sleeper inject cho determinism.
2. `tests/test_s11_original_audio_acceptance.py` (NEW) — 2 test binary cho
   scenarios 9–10: suite MỘT LỆNH trọn bộ S11 xanh qua subprocess thật;
   ownership-scoped process-leak gate (psutil).
3. Packet evidence: LOG.md + `output/s11-t01d*/` logs chạy thật.

Không sửa bất kỳ file production nào hay file T01A/B/C. Engine T01B hash
8c3a3bb7 nguyên vẹn.

## Required scenario coverage (binary)

| # | Scenario | Test | Kết quả |
|---|----------|------|---------|
| 1 | Happy path MP4 AAC import→attach→completed | `test_s01_happy_path_mp4_aac_import_attach_completed` | PASS |
| 2 | No-audio → NO_AUDIO_PRESENT | `test_s02_no_audio_no_audio_present` | PASS |
| 3 | Corrupt/truncated fail-closed zero publication | `test_s03_corrupt_fail_closed_zero_publication` (truncated-at-import PROBE_NONZERO_EXIT; different-size garbage SOURCE_NOT_READY; same-size mutated source SOURCE_NOT_READY sau R4-P1 — xem C3) | PASS |
| 4 | Non-AAC AC-3/MP3 → warning rồi attach vẫn chạy | `test_s04_non_aac_ac3_mp3_import_warning_then_attach[ac3_source]/[mp3_source]` | PASS |
| 5 | Restart giữa chừng không duplicate artifact | `test_s05_restart_mid_run_no_duplicate_artifact` | PASS |
| 6 | Cancellation giữa remux zero publication staging sạch | `test_s06_cancellation_mid_remux_zero_publication` | PASS |
| 7 | Idempotency reuse/conflict fail-closed | `test_s07_idempotency_reuse_and_conflict_fail_closed` | PASS |
| 8 | Analysis generation unchanged | `test_s08_analysis_generation_unchanged` | PASS |
| 9 | Suite MỘT LỆNH trọn bộ S11 xanh | `test_a01_full_s11_suite_green` + chạy trực tiếp nhiều lần | PASS |
| 10 | Không process leak sau suite | `test_a02_no_process_leak_after_suite` (ownership-scoped) + psutil scan ngoài pytest | PASS |

## Verification gốc (+07)

```
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest \
    tests/test_s11_original_audio_contract.py tests/test_s11_original_audio_remux.py \
    tests/test_s11_attach_original_audio_job.py tests/test_s11_original_audio_integration.py \
    tests/test_s11_original_audio_acceptance.py --ignore=tests/test_integration.py \
    -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01d-suite-final -q
52 passed, 64 warnings in 166.70s (0:02:46)
# re-run: 52 passed in 166.93s; final-gate lần 3: 52 passed in 168.08s
# FFMPEG_LEAKS sau mỗi lần: NONE
```

Known pre-existing KHÔNG đụng: `test_no_worker_or_api_cutover_tables` FAILED
(`unexpected tables: ['project_cast_mapping']` — S07 migration guard-test);
`tests/test_integration.py` loại khỏi suite command (SAM2 segfault).

## Process deviation

Không có. Không git reset/clean/stash/restore/checkout/commit/push/merge;
không đụng MAIN, production DB, migrations, models.py, API/frontend, file S07
hay file S11 A/B/C.

---

## CORRECTION C1 — child basetemp long-path Windows (finding P2) — RESOLVED

**Finding (Codex, Manager tái hiện):** nested child basetemp nối tiếp từ
outer `tmp_path` → đường dẫn artifact/media/SQLite quá dài trên Windows
(outer 2 failed / inner 28 failed với basetemp dài; short basetemp → 2
passed). Engine production KHÔNG phải nguyên nhân.

**Fix (chỉ tests/test_s11_original_audio_acceptance.py):** `_child_basetemp(tag)`
— tạo TRỰC TIẾP dưới `tempfile.gettempdir()`, tên ngắn unique
`s11c1-{tag}-{pid}-{seq}`, mkdir(exist_ok=False) + assert trước spawn;
`_cleanup_basetemp()` rmtree(ignore_errors=True) trong finally. Giữ nguyên
recursion guard, frozen command, shell=False, env-strip, timeout 1800.

**Verify:** Gate DÀI (outer basetemp 100 'a') → 2 passed in 115.63s; Gate
NGẮN s11c1-short → 2 passed in 115.30s; ruff sạch; NO s11c1-* leftovers.
Logs: output/s11-t01d-c1/c1-gate-{long,short}.log.

**Status sau C1: TASK_SUBMITTED** — chờ Manager/Codex verify. KHÔNG tự ghi APPROVED.

---

## CORRECTION C2 — diagnostic tail thiếu stderr (finding P2) — RESOLVED

**Finding (Codex vòng 3):** `_run_suite` capture cả stdout lẫn stderr nhưng
tail chẩn đoán chỉ trả stdout → khi child fail ở stderr, assertion message
thiếu thông tin chẩn đoán.

**Cause:** dòng cũ `tail = "\n".join((result.stdout or "").splitlines()[-25:])`.

**Files changed:** chỉ `tests/test_s11_original_audio_acceptance.py`
(integration KHÔNG đổi ở round này).

**Fix:**
- `_bounded_tail(text, 25)` cho từng stream; `_run_suite` trả
  `(code, stdout_tail, stderr_tail)`; assert qua `_diag_message` chứa CẢ HAI
  tail (`--- stdout tail ---` / `--- stderr tail ---`).
- Giữ nguyên: frozen command, S11_ACCEPTANCE_NESTED guard, shell=False,
  timeout=1800, env-strip, `_child_basetemp` + cleanup finally (C1).
- Điểm 4 (leak scan): test_a02 chuyển OWNERSHIP-SCOPED —
  `_run_suite_tracked` (Popen) ghi mọi ffmpeg/ffprobe xuất hiện TRONG cây
  process con đang sống (psutil children recursive); survivor của set đó sau
  khi child exit = leak của run này. Lý do: baseline-diff máy-toàn-phụ sai
  lệch khi chạy song song — gate (c) đã chứng minh ngay vòng đầu. Helper
  máy-quét cũ bị xóa.

**Cross-run interference phát hiện bởi chính fix C2 (minh bạch):** gate (c)
lần đầu A pass / B fail — diagnostic tail mới chỉ thẳng root cause: inner
`test_12_no_process_leak` của file attach T01C (NGOÀI write-set) dùng
pid-diff MÁY-TOÀN-PHỤ nên hai inner suite song song thấy ffmpeg của nhau.
Mitigation trong write-set: `_inner_suite_lock()` — lock file machine-wide
(`%TEMP%/s11-t01d-inner-suite.lock`, msvcrt.locking, retry 0.25s, tự nhả khi
holder chết) serialize phần CHẠY INNER giữa các acceptance invocation.
KHÔNG hạ policy: không assertion nào bị bỏ/sửa. Khuyến nghị dài hạn cho
T01C: chuyển test_12 sang ownership-scoped như T01B đã làm.

**Verify (output thật, evidence output/s11-t01d/c2-20260822-diag-tail/):**

```
$ # Gate (a) outer basetemp DÀI (100 ký tự 'a'):
2 passed in 142.47s (0:02:22)          # gate-a-long-final.log
$ # Gate (b) basetemp NGẮN s11c2-short:
2 passed in 131.99s (0:02:11)          # gate-b-short-final.log
$ # Gate (c) HAI invocation ĐỒNG THỜI:
# proc A s11c2-par-a → 2 passed in 194.75s ; proc B s11c2-par-b → 2 passed in 260.09s
# (lần song song đầu TRƯỚC lock: B fail test_12 — gate-c-parallel-B.log giữ làm evidence)
$ # Gate (d): ruff All checks passed! ; git diff --check exit 0
# NO child basetemp leftovers ; FFMPEG_LEAKS: NONE
```

**Status sau C2: TASK_SUBMITTED** — chờ Manager/Codex verify. KHÔNG tự ghi APPROVED.

---

## CORRECTION C3 — inner child không exit + outer treo vô hạn (finding P2) — RESOLVED

**Bằng chứng Manager (15:42+07, py-spy + psutil):** chạy frozen five-file
suite qua OUTER acceptance a02 (`_run_suite_tracked`) → INNER child pytest
(basetemp `s11c1-leak-suite-*`) HOÀN TẤT toàn bộ test (py-spy: MainThread
idle ở `_pytest/config/__init__.py:254 _console_main`, 0 CPU 8s+) nhưng
KHÔNG BAO GIỜ exit; OUTER poll `child.poll()` KHÔNG có deadline tổng →
cặp đôi treo 80+ phút, Manager phải kill tay.

**Root cause (phân tích trong write-set):**
1. Nguyên nhân chính (đúng theo point 2 của yêu cầu): OUTER giữ cả stdout
   lẫn stderr là PIPE và trong suốt vòng poll KHÔNG drain gì. Khi child
   pytest ghi vượt bộ đệm pipe Windows (~64KB) — warnings summary + alembic
   logs của 52 test đủ để đầy — write() của child block vĩnh viễn: MainThread
   đã vào `_console_main` (teardown xong, đang chờ flush cuối/exit) nên
   process không bao giờ kết thúc. Khớp chính xác py-spy: idle, 0 CPU,
   không phải deadlock Python khác.
2. Nửa bệnh còn lại: vòng poll OUTER không có deadline tổng → một khi child
   kẹt, OUTER treo theo vô thời hạn.
(`_inner_suite_lock` loại trừ: handle lock nằm ở OUTER process, không nằm
trên đường exit của child.)

**Files changed (đúng allowlist C3):**
- `tests/test_s11_original_audio_acceptance.py`
  - `_run_suite_tracked`: 2 daemon reader threads DRAIN stdout/stderr liên
    tục (chunks list; stream đóng trong finally) — không còn PIPE không đọc;
  - HARD TOTAL DEADLINE `_CHILD_TOTAL_DEADLINE_S = 1800s` cho toàn vòng
    poll: quá hạn → `child.kill()` → `wait(120)` → join threads → trả tail
    kèm marker `[harness] child killed at 1800s hard total deadline`; rc tổng
    hợp `_TIMEOUT_RC = 124` nếu kill race ra 0 — test FAIL có diagnostic rõ,
    KHÔNG BAO GIỜ treo nữa;
  - defensive kill giữ nguyên trong finally;
  - Giữ nguyên: frozen five-file command, `S11_ACCEPTANCE_NESTED`,
    `shell=False`, env-strip `MOTIONFORGE_DATABASE_URL`, `_child_basetemp`
    ngắn/unique + cleanup finally, `_inner_suite_lock`.
- `tests/test_s11_original_audio_integration.py` — scenario 3(c) (~dòng 739):
  expectation `ENGINE_FAILED` → `SOURCE_NOT_READY` (R4-P1 T01C: preflight
  source-phase re-verify size/hash chặn same-size mutation TRƯỚC engine —
  vẫn fail-closed, zero publication, staging sạch); các assert
  zero-audio-artifact / no-job-files / staging-empty GIỮ NGUYÊN.

**Gates tự chạy (output thật, evidence output/s11-t01d/c3-20260822-hang-fix/):**

```
$ # Gate (d) — integration riêng sau khi 3c đổi expectation:
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_integration.py \
    -q -p no:cacheprovider --basetemp='C:/Users/Admin/AppData/Local/Temp/s11c3-intg'
9 passed, 18 warnings in 13.73s        # gate-d-integration.log

$ # Gate (a) — acceptance outer basetemp DÀI (100 ký tự 'a'):
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_acceptance.py \
    -q -p no:cacheprovider --basetemp='C:/Users/Admin/AppData/Local/Temp/s11-longpath-fix-aaaa…aaaa'
2 passed in 130.61s (0:02:10)          # gate-a-long.log

$ # Gate (b) — basetemp NGẮN:
$ ... --basetemp='C:/Users/Admin/AppData/Local/Temp/s11c3-short'
2 passed in 130.42s (0:02:10)          # gate-b-short.log

$ # Gate (c) — HAI acceptance SONG SÀNH (basetemp khác nhau):
# proc A: --basetemp='.../s11c3-par-a'  → 2 passed in 198.23s (0:03:18)
# proc B: --basetemp='.../s11c3-par-b'  → 2 passed in 265.18s (0:04:25)
# B chờ lock như thiết kế — ĐỐI CHỨNG bệnh cũ: cặp tương tự từng treo
# 80+ phút phải kill tay; giờ cả hai tự kết thúc có bounds.

$ # Gate (e):
# GATE_E_FFMPEG_LEAKS: NONE (psutil scan máy về baseline, không ffmpeg/ffprobe)
# NO child basetemp leftovers; ruff All checks passed! (cả 2 file); git diff --check sạch
```

md5 sau fix: acceptance `28244b0293b9ba2dd19659b87878045b`, integration
`7cf5640131a541da0a8a0f3f2c557354` (sau khi comment 3(c) được làm rõ theo
ngữ nghĩa R4-P1 — assertion không đổi, re-verify: integration riêng **9
passed in 14.02s**, gate (a) long-basetemp chạy lại **2 passed in 131.19s**
trên md5 cuối này; ruff + git diff --check sạch; FFMPEG_LEAKS: NONE;
TEMP_CLEAN).

**Status sau C3: TASK_SUBMITTED** — chờ Manager/Codex verify. KHÔNG tự
ghi APPROVED.

---

## R5-T01D — regression source-artifact authority swap (R5-P1) — DONE

**Bối cảnh:** T01C R5-P1 biến `VideoItem.source_artifact_id` thành authority
DUY NHẤT (manifest stale ≠ current → `SOURCE_OWNER_MISMATCH` fail-closed ở
resolve (handler ~:255), checkpoint-replay (~:464) và publication (~:853));
T01A đồng bộ warning action text (non-AAC vẫn import, ATTACH sẽ transcode).

**Files changed:** CHỈ `tests/test_s11_original_audio_integration.py`
(acceptance file KHÔNG đụng — md5 giữ `28244b0293b9ba2dd19659b87878045b`,
mtime 16:23 nguyên vẹn). Production chỉ ĐỌC.

**Test mới: `test_s09_source_artifact_swap_fail_closed_zero_publication`**
(10 test trong file, trước Scenario 6):

- **Leg 1 — stale manifest, resolve path:** import A → authority B →
  submit attach (manifest pins B, assert qua `JobRepository.get_job(
  ...).input_manifest`) → re-point authority về A (mô phỏng producer ngoài
  di chuyển pointer giữa submit và run) → `run_once()` → job failed
  `SOURCE_OWNER_MISMATCH`, envelope details khớp
  (`manifest_source_artifact_id=B`, `current_source_artifact_id=A`);
  zero audio artifact; staging sạch; số file published không đổi.
- **Leg 2 — bytes-valid checkpoint, replay path (hook có sẵn của suite,
  không invent cơ chế):** submit thứ hai pins A → crash-at-publish
  (`_publish_effect` monkeypatch như s05) để checkpoint nguồn tồn tại
  (`cp["source"]["artifact_id"]==A`) → detach sang B → `_force_replay`
  + `run_once()` → vẫn failed `SOURCE_OWNER_MISMATCH` với details
  `checkpointed_artifact_id=A` / `current_source_artifact_id=B`;
  engine KHÔNG re-run (counter `engine_runs==1`); zero audio artifact,
  zero file cho job này, staging sạch.

**Expectation audit (mục 2):** mọi error-code expectation trong file đã khớp
ngữ nghĩa R4/R5 — 3(b)/(c) `SOURCE_NOT_READY` (R4-P1), s05/s09-leg-2
`PUBLICATION_FAILED` cho simulated kill, còn lại là code thật của path.
s04 không pin action text (chỉ code/severity/details codec) → đồng bộ text
T01A không ảnh hưởng assertion nào. Không expectation cũ nào mâu thuẫn.

**Lỗi thiết kế test đã sửa theo output thật (minh bạch):**
1. `s.scalar()` trên ArtifactOwner purpose=source sau re-import trả nhầm row
   cũ (không order-by) → đọc authority TRỰC TIẾP từ cột
   `VideoItem.source_artifact_id`.
2. Submit attach TRƯỚC khi import B khiến `run_once()` claim nhầm job
   (worker một-lần-một-job) → tách: cả hai import chạy trước, swap = UPDATE
   cột authority (đúng state mà R5-P1 xử lý).

**Gates R5 (output thật, evidence output/s11-t01d/r5-20260822-source-owner-mismatch/):**

```
$ # Gate (a) — integration riêng (gồm s09 mới):
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_integration.py \
    -q -p no:cacheprovider --basetemp='C:/Users/Admin/AppData/Local/Temp/s11r5-intg4'
10 passed, 20 warnings in 15.26s       # gate-a-integration.log

$ # Gate (b) — acceptance NGUYÊN TRẠNG (suite tự chạy frozen five-file):
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_acceptance.py \
    -q -p no:cacheprovider --basetemp='C:/Users/Admin/AppData/Local/Temp/s11r5-acc'
2 passed in 137.09s (0:02:17)          # gate-b-acceptance.log

$ # Gates (c)(d)(e):
# ruff integration → All checks passed! ; git diff --check OK
# GATE_E_FFMPEG_LEAKS: NONE ; basetemp scratch dọn sạch (TEMP_CLEAN)
```

md5 sau R5: acceptance `28244b02…` (KHÔNG đổi), integration
`772d5166bc6cde8f72f1582d941eb9bf`.

**Status sau R5: TASK_SUBMITTED** — chờ Manager/Codex verify. KHÔNG tự
ghi APPROVED.

---

## CORRECTION R6 F4 — post-remux cancellation + vertical multi-stream — DONE

**Finding (Codex vòng 6):** coverage cancellation cũ (s06) chỉ chạm cancel
TRƯỚC/khi engine chạy; thiếu leg cancel SAU khi real engine đã tạo output
thật, và thiếu vertical multi-stream thật (≥5 streams).

**Files changed:** CHỈ `tests/test_s11_original_audio_integration.py`
(acceptance file KHÔNG đụng — md5 giữ `28244b0293b9ba2dd19659b87878045b`).
Production chỉ ĐỌC: engine md5 `b02b3a09…` (`-map 0:a:0`,
`audio_stream_index` ghi tại remux.py:1166), handler md5 `699e2b34…`
(`ctx.is_cancelled()` ngay sau engine → `_purge_run_staging` TRƯỚC raise
CANCELLED — fix T01C F2).

**Test mới 1 — `test_s10_cancel_after_engine_success_zero_residue`:**
durable flag `cancelling` được đặt SAU khi `remux_original_audio` return
SUCCESS (seam monkeypatch tầng integration/worker.run_once, cùng pattern
test_16 attach-side; assert `engine_out.is_file()` trước khi flag để chứng
minh real output đã tồn tại). Job → `cancelled`; ZERO audio Artifact +
ArtifactOwner + publication (artifacts/ bất biến); staging job MÌNH purge
sạch (kể cả directory shell); sentinel cross-job byte-identical; checkpoint
chỉ còn source evidence (`remux`/`published` KHÔNG được ghi cho run bị
hủy). Envelope error: cancel-drain của worker không persist failure
envelope — chấp nhận `None`/`CANCELLED` như test_16 attach-side.

**Test mới 2 — `test_s11_vertical_multistream_canonical_first_audio`:**
MP4 H.264 + 4 AAC streams thật (ffmpeg lavfi, 4 tần số 440/880/1320/1760 Hz
= 5 streams tổng) → probe R6 bounded NHẬN → attach chạy real pipeline đến
`completed`. Assert: nguồn đúng 1 video + 4 audio (tất cả AAC); output probe
đúng **1 video + 1 audio AAC** (streams KHÔNG bao giờ bị merge);
`remux.checkpoint.audio_stream_index` == container index của first-audio
nguồn (selection evidence); STREAM_COPY; sha256 artifact khớp file;
source bytes unchanged end-to-end. Lưu ý shape evidence: handler bọc engine
checkpoint VERBATIM dưới `cp["remux"]["checkpoint"]` (đường dẫn tuyệt đối
bị strip ở top-level) nên index đọc từ đó.

**Giữ nguyên (yêu cầu mục 3):** s06 in-flight cancel, 3(b)/(c)
`SOURCE_NOT_READY`, s09 authority-swap `SOURCE_OWNER_MISMATCH` (2 nhánh),
s05 restart, toàn bộ scenario 1–8.

**Gates R6-F4 (output thật, evidence output/s11-t01d/r6-f4-20260823-postremux-cancel-multistream/):**

```
$ # Gate (a) run 1 — integration file riêng:
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_integration.py \
    -q -p no:cacheprovider --basetemp='C:/Users/Admin/AppData/Local/Temp/s11r6-intg2'
12 passed, 24 warnings in 20.64s       # gate-a-integration-run1.log

$ # Gate (a) — gọi regression MỚI theo -k (chứng minh chạy thật):
$ ... -k "s10_cancel_after_engine_success_zero_residue or s11_vertical_multistream_canonical_first_audio"
2 passed, 10 deselected, 4 warnings in 4.95s   # gate-a-new-regressions-k.log

$ # Gate (a) run 2:
12 passed, 24 warnings in 19.77s       # gate-a-integration-run2.log

$ # Gate (b) — acceptance NGUYÊN TRẠNG (frozen five-file qua child subprocess):
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_acceptance.py \
    -q -p no:cacheprovider --basetemp='C:/Users/Admin/AppData/Local/Temp/s11r6-acc'
2 passed in 165.58s (0:02:45)          # gate-b-acceptance.log

$ # Gates (c)(d)(e):
# ruff integration → All checks passed!
# git diff --check → exit 0, 0 issue thật (chỉ warning CRLF pre-existing)
# GATE_E_FFMPEG_LEAKS: NONE ; basetemp scratch dọn sạch (TEMP_CLEAN)
```

**Actual test count:** integration file thu thập **12 test** (11 def;
s04 parametrize ×2 [ac3_source/mp3_source]) — không hard-code count cũ.
md5 sau F4: acceptance `28244b02…` (KHÔNG đổi), integration
`1e51d86a1a3329da045feadde9ab4361`.

**Status sau R6-F4: TASK_SUBMITTED** — chờ Manager/Codex verify. KHÔNG tự
ghi APPROVED.
