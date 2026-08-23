# S11-T01D — LOG

| Thời gian (+07) | Sự kiện | Evidence | Ghi chú |
|---|---|---|---|
| 2026-08-22T01:05+07:00 | Manager tạo packet sau khi T01A+B+C MANAGER_VERIFIED | S11-SESSION_REGISTRY.md; T01C REPORT | Engine T01B hash 8c3a3bb7; handler T01C ruff/mypy/pytest sạch. Known pre-existing: test_no_worker_or_api_cutover_tables (S07), test_integration.py skip (SAM2). |
| 2026-08-22T00:38+07:00 | Owning session 20260822_003041_b18319 launch. Hard worktree guard PASS trước mọi write | `pwd` = `/c/Users/Admin/MotionForge2D-worktrees/s08-integration`; `git rev-parse --show-toplevel` = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`; HEAD = a43b20da (đúng TASK.md) | Đọc đủ required reading theo thứ tự: TASK → LOG → SPRINT_CONTRACT → 2 architecture contracts → video_import.py / original_audio_remux.py / original_audio_handler.py / job_service.py (read-only) → 3 file test pattern. |
| 2026-08-22T00:45+07:00 | Fixture assumptions verified bằng FFmpeg thật TRƯỚC khi viết test | AC-3 encoder OK (`ffmpeg -c:a ac3` exit 0, ffmpeg 8.1.2 gyan.dev); truncated MP4 → ffprobe exit 1 (stdout rỗng); garbage bytes → exit 1 | FFmpeg resolved qua WinGet Links; conftest.py đã tự thêm PATH fallback. |
| 2026-08-22T01:05+07:00 | Viết tests/test_s11_original_audio_integration.py (NEW, scenarios 1–8, 9 test binary) + tests/test_s11_original_audio_acceptance.py (NEW, scenarios 9–10) | Write-set đúng allowlist; production code KHÔNG bị đụng (git status đối chiếu) | Real path: default JobService (worker tự construct, full registration block), temp SQLite alembic-upgrade head, temp managed root, lavfi synthetics, FakeClock/FakeSleeper chỉ cho determinism. |
| 2026-08-22T01:10→02:00+07:00 | Integration loop RED→GREEN (4 vòng fix test-side, không đụng production) | Vòng 1: 6F/3P — JobStep không có result_json (verdict nằm ở JobEvent.details_json), probe chạy TRONG job ANALYZE_MEDIA chứ không ở submit, `streams` gán nhầm list, cancel-race với clip 2s, produced file consumed khi publish-fail. Fix: đọc verdict từ `JobEvent(to_state=completed).details_json["validation"]`, corrupt-at-import assert qua job failed PROBE_NONZERO_EXIT, thêm nhánh same-size garbage → ENGINE_FAILED, cancel wrapper sleep 1.2s (> watcher tick 0.25s) trước engine entry. Vòng cuối: **9 passed** | Không defect engine/wiring — mọi failure là test-assumption sai so với behavior thật của T01A/B/C (behavior đúng contract). |
| 2026-08-22T01:20+07:00 | Phát hiện + sửa RECURSION trong acceptance file (bởi chính session này) | Thiết kế đầu: inner suite gồm cả file acceptance → mỗi test spawn suite chứa chính nó → nhân bản subprocess vô hạn, 21 phút chưa xong (kill tại proc_43c6d15be90d, exit 1264s). Fix: env sentinel `S11_ACCEPTANCE_NESTED=1` + module-level pytest.skip ở inner run — lệnh suite đóng băng KHÔNG đổi | Sau fix: acceptance file chạy riêng = 2 passed trong 113s. |
| 2026-08-22T02:24+07:00 | ACCEPTANCE SUITE MỘT LỆNH — trọn bộ S11 xanh | Lệnh + output thật bên dưới; log đầy đủ: `output/s11-t01d/run-20260822-acceptance/suite_one_command.log` | 52 passed, 64 warnings, 166.70s |
| 2026-08-22T02:29+07:00 | Suite re-run lần 2 (stability) | Log: `output/s11-t01d/run-20260822-acceptance/suite_one_command_rerun.log` | 52 passed, 166.93s — ổn định 2/2. |
| 2026-08-22T02:30+07:00 | Process-leak scan sau suite bằng psutil | `POST_SUITE_FFMPEG_LEAKS: NONE`; `POST_RERUN_FFMPEG_LEAKS: NONE` | Scenario 10 PASS (test_a02 cũng assert in-suite). |
| 2026-08-22T02:15+07:00 | Known pre-existing verified, KHÔNG đụng | `python -m pytest tests/test_durable_job_persistence.py::test_no_worker_or_api_cutover_tables` → FAILED: `AssertionError: unexpected tables: ['project_cast_mapping']` | Đúng như TASK.md ghi nhận — S07 migration guard-test chưa update, ngoài scope S11. |
| 2026-08-22T02:31+07:00 | Ruff sạch cho 2 file allowlist | `python -m ruff check tests/test_s11_original_audio_integration.py tests/test_s11_original_audio_acceptance.py` → All checks passed! | mypy không bắt buộc cho test files (T01C convention: chỉ app code). |
| 2026-08-22T02:37→02:41+07:00 | Final-gate suite lần 3 + leak scan | `52 passed, 64 warnings in 168.08s` (basetemp s11t01d-suite-gate); `FINAL_GATE_FFMPEG_LEAKS: NONE` | Ổn định 3/3 lần chạy trọn bộ. |
| 2026-08-22T02:34+07:00 | REPORT.md SUBMITTED — chờ Manager verify độc lập | Xem REPORT.md | KHÔNG tự ghi APPROVED/CODEX_APPROVED. |
| 2026-08-22T05:32+07:00 | **CORRECTION C1** (Codex CHANGES_REQUESTED, finding P2 Manager tái hiện): child basetemp nối tiếp từ outer tmp_path → đường dẫn artifact/media/SQLite quá dài trên Windows (outer 2 failed / inner 28 failed với basetemp dài); short basetemp → 2 passed. Engine production KHÔNG phải nguyên nhân | Repro Codex + xác nhận Manager; vị trí cũ: dòng ~128 `tmp_path.parent / f"{tmp_path.name}-suite"` và ~145 `-leak-suite` | Worktree guard PASS lại trước mọi write (pwd + rev-parse khớp, HEAD a43b20da7429). |
| 2026-08-22T05:35+07:00 | Fix harness đúng spec C1, chỉ sửa tests/test_s11_original_audio_acceptance.py | `_child_basetemp(tag)`: tạo TRỰC TIẾP dưới `tempfile.gettempdir()` (không nối tiếp tmp_path), tên ngắn `s11c1-{tag}-{pid}-{seq}` chống collision song song, mkdir(exist_ok=False) + assert tồn tại trước spawn; `_cleanup_basetemp`: `shutil.rmtree(..., ignore_errors=True)` đúng target riêng trong finally. Giữ nguyên: S11_ACCEPTANCE_NESTED guard, frozen five-file command, shell=False, -u MOTIONFORGE_DATABASE_URL khỏi child env, timeout 1800, stdout/stderr tail trong assert | Không đụng app/**, integration/contract/remux/attach tests, S07/S08/S09, MAIN, production DB. |
| 2026-08-22T05:33→05:36+07:00 | VERIFY Gate DÀI (outer basetemp 100+ ký tự 'a' — chính là repro P2, chạy thật) | Lệnh + output: bên dưới; log `output/s11-t01d-c1/c1-gate-long.log` → **2 passed in 115.63s** | Trước fix sẽ fail theo repro Codex; sau fix pass — chứng minh root cause nằm ở prefix độ dài basetemp. |
| 2026-08-22T05:36→05:38+07:00 | VERIFY Gate NGẮN | Log `output/s11-t01d-c1/c1-gate-short.log` → **2 passed in 115.30s** (basetemp s11c1-short) | PASS. |
| 2026-08-22T05:39+07:00 | Ruff sạch file acceptance sau fix + cleanup check + leak scan + scope check | ruff → All checks passed!; `ls Temp/s11c1-*` → NO leftovers (child basetemp đã được dọn); FFMPEG_LEAKS: NONE; `git diff HEAD -- app/` chỉ chứa dirt PRE-EXISTING baseline S07–S10 (29 modified từ trước session, không thay đổi thêm) | Mọi verify C1 xanh. REPORT.md cập nhật TASK_SUBMITTED. |
| 2026-08-22T11:30+07:00 | **CORRECTION C2** (Codex CHANGES_REQUESTED vòng 3): diagnostic tail của `_run_suite` chỉ chứa stdout (dòng 124 cũ) — khi child fail ở stderr thì assertion message thiếu chẩn đoán. Write-set: acceptance file + packet; integration file KHÔNG đổi (mtime xác minh 01:53 giữ nguyên) | Worktree guard PASS lại (pwd + rev-parse khớp, HEAD a43b20da7429) | Evidence run-id: `output/s11-t01d/c2-20260822-diag-tail/`. |
| 2026-08-22T11:33→11:47+07:00 | Fix C2 trong tests/test_s11_original_audio_acceptance.py: `_run_suite` trả `(code, stdout_tail_25, stderr_tail_25)` qua `_bounded_tail`; assert message qua `_diag_message` chứa CẢ HAI tail. Giữ nguyên: frozen five-file command, S11_ACCEPTANCE_NESTED guard, shell=False, timeout=1800, env-strip MOTIONFORGE_DATABASE_URL, `_child_basetemp` ngắn/unique + cleanup finally (C1). Điểm 4: test_a02 chuyển OWNERSHIP-SCOPED — `_run_suite_tracked` ghi mọi ffmpeg/ffprobe xuất hiện TRONG cây process con đang sống (psutil children recursive), survivor sau child exit = leak của run này; helper máy-quét `_ffmpeg_pids` chết bị xóa | ruff All checks passed!; git diff --check sạch | Không đụng production hay file T01A/B/C. |
| 2026-08-22T11:38→11:44+07:00 | Gate (c) lần 1 (2 acceptance SONG SÀNH, basetemp khác nhau): A pass / B FAIL test_a01 — C2 fix hoạt động đúng: tail chẩn đoán mới chỉ thẳng root cause thật = inner `test_12_no_process_leak` (file attach T01C, NGOÀI write-set) false-fail vì dùng pid-diff MÁY-TOÀN-PHỤ (process_iter toàn máy, dòng 424–438): hai inner suite song song thấy ffmpeg của nhau | Log: gate-c-parallel-B.log — `FAILED ...attach_original_audio_job.py::test_12_no_process_leak`, `1 failed, 51 passed, 1 skipped`; stderr tail rỗng đúng như finding C2 mô tả trước fix | Đây là cross-run interference giữa các TEST khác, không phải defect engine hay harness mới. |
| 2026-08-22T11:45→11:47+07:00 | Mitigation isolation trong write-set: `_inner_suite_lock()` — machine-wide lock file (`%TEMP%/s11-t01d-inner-suite.lock`, msvcrt.locking LK_NBLCK, retry 0.25s, tự nhả khi holder chết) serialize PHẦN CHẠY INNER suite giữa các acceptance invocation. KHÔNG hạ policy: không assertion nào bị bỏ/sửa; khuyến nghị dài hạn cho T01C: chuyển test_12 sang ownership-scoped như T01B | ruff All checks passed!; git diff --check = 0 | Wrap cả 2 spawn điểm (a01 `_run_suite`, a02 `_run_suite_tracked`). |
| 2026-08-22T12:05→12:20+07:00 | GATES FINAL trên bản cuối (evidence output/s11-t01d/c2-20260822-diag-tail/): (a) outer basetemp DÀI 100 ký tự 'a' → **2 passed in 142.47s**; (b) basetemp NGẮN s11c2-short → **2 passed in 131.99s**; (c) HAI invocation SONG SÀNH s11c2-par-a/b → **A: 2 passed in 194.75s; B: 2 passed in 260.09s** (B chờ lock ~65s — serialization hoạt động); (d) ruff + `git diff --check` sạch | gate-a-long-final.log, gate-b-short-final.log, gate-c-parallel-A-final.log, gate-c-parallel-B-final.log | Sau gates: NO child basetemp leftovers (s11c1-*/s11c2-*), FFMPEG_LEAKS: NONE. |
| 2026-08-22T11:58+07:00 | REPORT.md cập nhật TASK_SUBMITTED — chờ Manager/Codex verify lại | Xem REPORT.md mục CORRECTION C2 | KHÔNG tự ghi APPROVED/CODEX_APPROVED. |
| 2026-08-22T16:18+07:00 | **CORRECTION C3** (Codex vòng 4 + bằng chứng Manager 15:42): qua `_run_suite_tracked`, INNER child pytest HOÀN TẤT test (py-spy: MainThread idle ở `_pytest/config/__init__.py:254 _console_main`, 0 CPU 8s+) nhưng KHÔNG exit; OUTER poll loop KHÔNG có deadline tổng → cặp treo 80+ phút, Manager kill tay. Write-set lần này gồm cả integration file (3c) | Worktree guard PASS lại (HEAD a43b20da7429); run-id `output/s11-t01d/c3-20260822-hang-fix/` | Nguyên nhân gốc phân tích trong REPORT: OUTER giữ cả 2 PIPE không drain trong lúc poll → stdout pipe đầy block child khi ghi (Windows pipe 64KB); deadline tổng thiếu là nửa còn lại của bệnh. |
| 2026-08-22T16:19→16:24+07:00 | Fix C3: `_run_suite_tracked` — 2 daemon reader threads DRAIN stdout/stderr liên tục (không còn PIPE không đọc); HARD TOTAL DEADLINE `_CHILD_TOTAL_DEADLINE_S=1800s` cho toàn vòng poll — quá hạn `child.kill()` + wait + trả tail kèm marker `[harness] child killed …`; rc tổng hợp `_TIMEOUT_RC=124` nếu kill race ra 0. Giữ nguyên: frozen command, S11_ACCEPTANCE_NESTED, shell=False, env-strip, basetemp ngắn/unique + cleanup finally, `_inner_suite_lock`. Fix 3c integration: expectation `ENGINE_FAILED` → `SOURCE_NOT_READY` (R4-P1 T01C preflight source-phase chặn same-size mutation trước engine); giữ nguyên assert zero-audio-artifact / no-job-files / staging-empty | ruff All checks passed! (sau 2 vòng lint-fix SIM105/E501); git diff --check sạch | Không đụng production/engine/handler/file T01A/B/C. |
| 2026-08-22T16:25+07:00 | GATE (d) integration riêng sau đổi 3c | Log gate-d-integration.log → **9 passed, 18 warnings in 13.73s** | SOURCE_NOT_READY khớp behavior R4-P1 thật trên máy. |
| 2026-08-22T16:26→16:28+07:00 | GATE (a) acceptance outer basetemp DÀI 100 'a' | gate-a-long.log → **2 passed in 130.61s** | test_a02 dùng `_run_suite_tracked` mới — hoàn tất bình thường, không treo. |
| 2026-08-22T16:29→16:30+07:00 | GATE (b) basetemp NGẮN s11c3-short | gate-b-short.log → **2 passed in 130.42s** | PASS. |
| 2026-08-22T16:31→16:34+07:00 | GATE (c) HAI invocation SONG SÀNH s11c3-par-a/b | gate-c-par-A.log → **2 passed in 198.23s**; gate-c-par-B.log → **2 passed in 265.18s** (B chờ lock như thiết kế) | Đối chứng bệnh cũ: cặp tương tự từng treo 80+ phút (Manager kill tay) — giờ cả hai tự kết thúc có bounds. |
| 2026-08-22T16:35+07:00 | GATE (e) process scan + hygiene sau test | `GATE_E_FFMPEG_LEAKS: NONE`; NO child basetemp leftovers; ruff + `git diff --check` sạch; scratch outer `s11c3-intg` đã tự dọn | Máy về baseline. md5: acceptance 28244b02…, integration 69b7a9ae… |
| 2026-08-22T16:36+07:00 | REPORT.md cập nhật TASK_SUBMITTED — chờ Manager/Codex verify lại | Xem REPORT.md mục CORRECTION C3 | KHÔNG tự ghi APPROVED/CODEX_APPROVED. |
| 2026-08-22T16:40→16:50+07:00 | Làm rõ comment 3(c) theo ngữ nghĩa R4-P1 (assertion KHÔNG đổi) + re-verify fresh trên md5 cuối: integration riêng **9 passed in 14.02s**; gate (a) long-basetemp chạy lại **2 passed in 131.19s** (gate-a-long-final.log); ruff cả 2 file sạch; git diff --check OK; FINAL_C3_FFMPEG_LEAKS: NONE; TEMP_CLEAN | md5 cuối: acceptance 28244b02…, integration 7cf56401… | Bổ sung vào REPORT.md mục C3. TASK_SUBMITTED giữ nguyên. |
| 2026-08-22T20:20+07:00 | **R5-T01D** (sau T01A+T01C correction round 5): thêm regression source-artifact authority swap vào integration file — `test_s09_source_artifact_swap_fail_closed_zero_publication`, 2 nhánh fail-closed thật: Leg 1 stale-manifest (submit pins B → pointer về A → run → SOURCE_OWNER_MISMATCH, envelope details khớp manifest/current), Leg 2 bytes-valid-checkpoint replay-still-fails (crash-at-publish hook của s05 + `_force_replay` có sẵn; checkpoint nguồn A → detach sang B → replay bị chặn ở source-phase, engine KHÔNG re-run — engine_runs đếm =1). Acceptance file KHÔNG đụng (md5 giữ 28244b02…) | Guard PASS HEAD a43b20da7429; production đọc-only: authority duy nhất `VideoItem.source_artifact_id` tại original_audio_handler.py:247/458/849 | 2 lần fix giữa chừng theo output thật: (1) scalar() trên ArtifactOwner không order-by trả nhầm row cũ sau re-import → đổi đọc cột VideoItem.source_artifact_id trực tiếp; (2) attach queued + import cùng DB khiến run_once claim nhầm job → tách import trước submit, swap bằng re-point ngoài. |
| 2026-08-22T20:52→21:05+07:00 | GATES R5 (output/s11-t01d/r5-20260822-source-owner-mismatch/): (a) integration riêng → **10 passed in 15.26s** (gate-a-integration.log); (b) acceptance nguyên trạng → **2 passed in 137.09s** (gate-b-acceptance.log); (c) ruff integration All checks passed!; (d) git diff --check OK (warning CRLF pre-existing frontend/fixtures); (e) GATE_E_FFMPEG_LEAKS: NONE + TEMP_CLEAN | md5: acceptance 28244b02… (KHÔNG đổi), integration 772d5166… | REPORT.md cập nhật TASK_SUBMITTED — chờ Manager/Codex verify. KHÔNG tự ghi APPROVED. |
| 2026-08-23T03:58+07:00 | **CORRECTION R6 F4** (Codex finding: coverage cũ chỉ cancel TRƯỚC engine): thêm 2 regression vào integration file — `test_s10_cancel_after_engine_success_zero_residue` (durable flag `cancelling` đặt SAU khi real engine return SUCCESS, seam monkeypatch tầng integration/worker.run_once như test_16 attach-side; job → cancelled, ZERO Artifact/ArtifactOwner/publication, staging job mình purge hết, sentinel cross-job byte-identical, checkpoint KHÔNG còn remux/published evidence) và `test_s11_vertical_multistream_canonical_first_audio` (MP4 H.264+4 AAC thật = 5 streams dựng ffmpeg lavfi 4 tần số; probe R6 nhận; attach SUCCESS qua real pipeline; output probe đúng 1 video + 1 audio AAC — không merge; evidence `remux.checkpoint.audio_stream_index` == index first-audio nguồn) | Guard PASS HEAD a43b20da7429; engine md5 b02b3a09… (`-map 0:a:0`, `audio_stream_index` ghi ở remux.py:1166), handler md5 699e2b34… (`ctx.is_cancelled()` sau engine → `_purge_run_staging` trước raise CANCELLED) | Acceptance file KHÔNG đụng. 2 assertion hiệu chỉnh theo behavior thật đọc từ production: cancel-drain không persist error envelope (accept `None`/`CANCELLED` như test_16); handler bọc engine checkpoint verbatim dưới `remux.checkpoint` nên index nằm ở đó (không top-level). |
| 2026-08-23T04:10→04:25+07:00 | GATES R6-F4 (output/s11-t01d/r6-f4-20260823-postremux-cancel-multistream/): (a) integration run1 **12 passed in 20.64s**, run2 **12 passed in 19.77s**; `-k` regression mới → **2 passed, 10 deselected in 4.95s**; (b) acceptance nguyên trạng **2 passed in 165.58s**; (c) ruff integration All checks passed!; (d) `git diff --check` exit 0, 0 issue thật (chỉ warning CRLF pre-existing); (e) GATE_E_FFMPEG_LEAKS: NONE + TEMP_CLEAN | md5: acceptance 28244b02… (KHÔNG đổi), integration 1e51d86a… | Actual collected count integration file: **12 test** (11 def; s04 parametrize ×2). REPORT.md cập nhật TASK_SUBMITTED — chờ Manager/Codex verify. KHÔNG tự ghi APPROVED. |

## Acceptance suite command (frozen evidence)

```
$ cd C:\Users\Admin\MotionForge2D-worktrees\s08-integration
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest \
    tests/test_s11_original_audio_contract.py \
    tests/test_s11_original_audio_remux.py \
    tests/test_s11_attach_original_audio_job.py \
    tests/test_s11_original_audio_integration.py \
    tests/test_s11_original_audio_acceptance.py \
    --ignore=tests/test_integration.py \
    -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01d-suite-final -q

52 passed, 64 warnings in 166.70s (0:02:46)
```

Run 2 (stability):

```
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest <same 5 files> \
    --ignore=tests/test_integration.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01d-suite-rerun -q

52 passed, 64 warnings in 166.93s (0:02:46)
```

Focused runs (evidence):

```
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_integration.py \
    -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01d-intg5
9 passed, 18 warnings in 13.32s

$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_acceptance.py \
    -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01d-acc2
2 passed in 113.38s (0:01:53)

$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_contract.py \
    tests/test_s11_original_audio_remux.py tests/test_s11_attach_original_audio_job.py \
    -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01d-abc
41 passed, 46 warnings in 42.97s
```

Known pre-existing (verified lại, không sửa):

```
$ python -m pytest tests/test_durable_job_persistence.py::test_no_worker_or_api_cutover_tables \
    -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t01d-known
1 failed, 2 warnings in 2.22s
E AssertionError: unexpected tables: ['project_cast_mapping']
```

## CORRECTION C1 — acceptance harness long-path Windows (finding P2)

Codex CHANGES_REQUESTED: nested child basetemp nối tiếp từ outer `tmp_path`
→ đường dẫn artifact/media/SQLite quá dài trên Windows (outer 2 failed /
inner 28 failed với outer basetemp dài; short basetemp → 2 passed). Engine
production KHÔNG phải nguyên nhân. Manager đã tái hiện xác nhận.

**Files changed (đúng allowlist C1):** chỉ `tests/test_s11_original_audio_acceptance.py`

- `_child_basetemp(tag)`: child basetemp NGẮN, unique, tạo TRỰC TIẾP dưới
  Windows temp root (`tempfile.gettempdir()`), KHÔNG nối tiếp outer tmp_path;
  tên `s11c1-{tag}-{pid}-{seq}` chống collision chạy song song;
  `mkdir(exist_ok=False)` + assert tồn tại TRƯỚC khi spawn.
- `_cleanup_basetemp()`: `shutil.rmtree(..., ignore_errors=True)` trong
  `finally`, chỉ đúng target riêng của mình (không target rộng).
- Giữ nguyên: `S11_ACCEPTANCE_NESTED` recursion guard, frozen five-file suite
  command, `shell=False`, `-u MOTIONFORGE_DATABASE_URL` khỏi child env,
  timeout 1800, stdout/stderr tail trong assert message.
- KHÔNG sửa production code, không hạ policy, không né defect khác.

**VERIFY (chạy thật 2026-08-22, +07):**

```
$ # Gate DÀI — outer basetemp 100+ ký tự (chính là repro P2 của Codex):
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_acceptance.py \
    -q -p no:cacheprovider \
    --basetemp='C:/Users/Admin/AppData/Local/Temp/s11-longpath-fix-aaaa...aaaa'   # 100 ký tự 'a'
2 passed in 115.63s (0:01:55)
# log đầy đủ: output/s11-t01d-c1/c1-gate-long.log

$ # Gate NGẮN:
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_original_audio_acceptance.py \
    -q -p no:cacheprovider --basetemp='C:/Users/Admin/AppData/Local/Temp/s11c1-short'
2 passed in 115.30s (0:01:55)
# log đầy đủ: output/s11-t01d-c1/c1-gate-short.log

$ python -m ruff check tests/test_s11_original_audio_acceptance.py
All checks passed!

$ ls -d /c/Users/Admin/AppData/Local/Temp/s11c1-* 2>/dev/null || echo "NO leftovers"
NO s11c1-* leftovers (child basetemp đã được dọn sạch sau subprocess)

$ # leak scan sau gates: FFMPEG_LEAKS: NONE
```

**Status sau C1: TASK_SUBMITTED** — chờ Manager/Codex verify lại. KHÔNG tự
ghi APPROVED.
