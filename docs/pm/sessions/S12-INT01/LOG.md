# S12-INT01 — Session LOG (Git-only integration owner, whole sprint)

- Task ID: S12-INT01 (Manager acts as Git-only owner; no worker dispatch — contract §INT01: Git metadata + docs only, no hand-edit production/test).
- Route: provider `muse` / `cmc/meta/muse-spark-1.3-contributor` / reasoning max / fallback OFF.
- Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s12-integration`, branch `codex/s12-integration`.
- Evidence root: `C:/Users/Admin/MotionForge2D-evidence/s12/20260907-083200-s12-coding/` (REGISTRY.md + per-task packets).

## 1. Pin ranges (exact, full SHA)

Base = parent of T01 feat commit (`0d04673~1`); HEAD evolves bda893a → e60ec5f (T05-docs) → INT01-close (this packet).

| # | Commit | Subject |
|---|---|---|
| 1 | 0d04673 | feat(s12-t01): export preflight frozen contract s12-export-v1 |
| 2 | c375b87 | feat(s12-t04a): independent output validator over s12-export-v1 |
| 3 | 0aedb22 | Merge S12-T04A c375b87 |
| 4 | be1def0 | feat(s12-t02): spawn-probe capability detection + render profiles |
| 5 | 2618e8f | Merge S12-T02 be1def0 |
| 6 | fc6789f | feat(s12-t03a): durable export domain run-chunk-lease + claim-fence |
| 7 | 0ab5765 | docs(s12-t03a): LOG + REPORT SHA record |
| 8 | 584797c | Merge S12-T03A fc6789f |
| 9 | 49fe2be | Merge S12-T03A docs 0ab5765 |
| 10 | 6297869 | S12-T03B: chunk render, stitch, checkpoint resume (19 tests green) |
| 11 | ec45da1 | Merge S12-T03B 6297869 |
| 12 | 8f80fe3 | S12-T03C: durable job/API wiring + validated publication (15 tests) |
| 13 | 16598ea | Merge S12-T03C 8f80fe3 |
| 14 | 030553b | S12-T05: Export UI preflight-submit-status-cancel-retry-evidence real-API + E2E |
| 15 | f2cdf0e | Merge S12-T05 030553b |
| 16 | ddc5d05 | S12-T06A: Windows portable-beta packaging harness |
| 17 | 1c9cd07 | Merge S12-T06A ddc5d05 |
| 18 | 48bf514 | S12-T06B: independent acceptance (F upscale + G resume) + hardware matrix |
| 19 | bda893a | Merge S12-T06B 48bf514 |
| 20 | 4a3630a | S12-T05: docs LOG + REPORT (E2E 15 passed, T03C 15/15, gates green) |
| 21 | e60ec5f | Merge S12-T05 docs 4a3630a |
| 22 | (this) | S12-INT01: sprint-close packet (LOG + REPORT + NEXT_REVIEW_PACKET) |

Full-SHA pin list: `C:/Users/Admin/MotionForge2D-evidence/s12/20260907-083200-s12-coding/s12-int01/pin_ranges.txt` (21 rows pre-INT01).

## 2. Merges (all Manager-executed, --no-ff, zero conflict)

- W1 T01 ff-base; W2 T04A+T02+T03A merges `0aedb22`/`2618e8f`/`584797c`+`49fe2be`; W3 T03B `ec45da1`; W4 T03C `16598ea`; W5 T05 `f2cdf0e`; W6 T06A `1c9cd07`; W7 T06B `bda893a`; T05-docs correction `e60ec5f` (gap backfill, owner T05 — INT01 did not edit lane code).
- Every merge: conflict-free, `git diff --check` 0, porcelain clean post-merge.

## 3. Frozen-HEAD wave gates (exact commands, isolated basetemp, -p no:cacheprovider)

| Gate | Result (real output) |
|---|---|
| W2 gate @ post-T03A HEAD | 99 passed / 52.13s |
| W6 gate @ post-T06A HEAD | 133 passed + ruff clean |
| FINAL @ `bda893a` | **144 passed, 1 skipped / 97.57s**, exit 0 |
| `ruff check --select F app/ tests/s12/` | All checks passed |
| Alembic heads | sole head `c3d4e5f6a7b8` |
| `git diff --check` | 0 |
| `app.main` import | APP_IMPORT_OK |
| T01 re-run (post-close sanity) | 15 passed / 16.26s |
| T06B Manager-independent @ WT | 11 passed, 1 skipped / 10.17s |
| T06B zero-prod-touch | NONALLOW_COUNT 0 |

## 4. Correction history (single-writer §4 respected)

- T01 duplicate `...481996` FROZEN (kept `...186832`); T06A duplicate `...0c1e8a` STOPPED 22:21; T05 docs gap backfill by exact owner `...67a9b5` → `4a3630a`, merged `e60ec5f`. INT01 never edited lane production/test.

## 5. Push / remote

- `bda893a` pushed OK (`1c9cd07..bda893a`); `ls-remote` confirms remote == `bda893a` pre-docs-merge.
- This INT01 commit → push → verify `ls-remote` == local HEAD (record SHA below in REPORT §6).

## 6. Known non-gates (disclosed, not waived)

- Mypy scope `s12_export`: 26 errors / 8 files (type-level only; runtime fully green). NOT an S12 gate; routed to Codex + owners.
- Clean-machine: NOT_RUN (no clean VM; clean venv does not qualify). No beta-pass claim.
- Finding F-OBS-01 → owner T01 (dims-only fallback in `classify_source_kind`; verifier read-only, repro in T06B LOG).

## 7. R6 transport (Hermes owner, 2026-09-15)

- Owner transfer (once): Codex `01a0898b-823a-7053-a1de-27d6fc24fce3` → Hermes session `20260915_201612_9c9e7c`; reason USER_REQUESTED_PLATFORM_MODEL_TRANSFER; route `ocg/deepseek-v4.1-flash` / provider custom / fallback OFF.
- Pre-INT HEAD `83af5167e9dddc931bc8590f547684c0c811784b` clean; serial non-FF merges VAL → RETRY → B01 → QA, zero conflicts:
  1. VAL source `535d7c136e0688bad1dc2905d4889a26869c995e` → merge `0b9ec15c4887422da995ff87cb392b3a7df8ffbb` (delta 6 paths exact).
  2. RETRY source `1d9ed94f7a893967765e7d40a710cdcd99e90601` → merge `46abfba684ad94378be802ed872ac825b0d5e3fb` (delta 5 paths exact).
  3. B01 source tip `c8830b342d678f5defdf17ec66b6c0ad3c6ef1cf` (chain `9caa22329cbb2cb0c0a07ee36e9878778b5a4496` + `c8830b3`) → merge `11e2de8f778783da9a8ce9d45fce7026e38849eb` (delta 8 paths exact).
  4. QA source `69a1280cd7c0130083ed529f425339036c917df3` → merge `b5c62d151c758b6995a7a58ebd8edbb75efa27da` (delta 6 paths exact).
- Union delta `83af5167 → b5c62d1`: 25 paths exact (6+5+8+6, disjoint); 6408 insertions / 144 deletions; `git diff --check` 0; porcelain clean after each merge.
- Static changed-scope: `compileall` app 0; `py_compile` tests 0; `ruff check --select F` 0 (`All checks passed!`); informational full-ruleset 52 style diagnostics (4 inherited publication.py: N818/SIM103/SIM102/SIM105).
- No broad pytest (Manager final gate after freeze); no push; no production/test hand edits by INT. Detail: R6_REPORT.md + evidence dir under `Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/20260915T131158Z/INT`.

## 8. R6 round 2 — QA follow-up transport (Hermes INT, 2026-09-15)

- Input QA2 `c5954d2ea465b1619f2c2613ae89ec456bee14ca` (parent `0c18d2d19fdb40c7c62d88da9ac4d39a72e48385` — QA build trực tiếp trên candidate đã tích hợp); merge `dd51f1f3a34e1a56510eb478a1c2a6a9e3085051` (parents `0c18d2d…` + `c5954d2…`), zero conflict, delta đúng 7 path (+1201/−68), diff-check 0, porcelain trống.
- Static: `compileall` app 0; `py_compile` 4 file QA-r6 0; `ruff check --select F` 0; full-ruleset trên 4 file đó 0 (`All checks passed!`).
- Evidence: R6_INT_RAW_PROVENANCE_R2.txt + COMMAND_LEDGER.jsonl (append, phase `r2_*`); không push; không sửa tay production/test.

## 9. R7 round 1 transport — 5 lanes (Hermes INT, 2026-09-16)

- Wave-base `35f6cb2`; serial non-FF merges zero conflict, đúng thứ tự Manager B: VAL `86b1a2a`→`0ea57b5` (8 files); RETRY `4ce3b136c8c9d7bd7c1aeace590dfb6a8c2d15ab`→`2942efb` (3 files; literal 41-char typo trong prompt/handoff đã ghi rõ trong R7_REPORT.md); B01 `a027c59`→`4cd2966` (8 files); BRIDGE `dae7632`→`761414a` (13 files); QA `958d021`→`8704ec0` (6 files).
- Transport tip `8704ec020960e67205cfeb93f4e54bda019205ae`; union delta 38 paths exact (+7573/−249); diff-check 0; porcelain trống sau từng merge.
- Static: `compileall` app 0; `py_compile` 24 file 0; `ruff check --select F` 0 (`All checks passed!`); full-ruleset informational 136 style-class diagnostics (chi tiết trong R7_REPORT.md).
- Evidence: `outputs/s12-r7-two-managers/20260916T0351Z/B/INT/` (COMMAND_LEDGER.jsonl + R7_INT_RAW_PROVENANCE.txt + manifests). Không push; không sửa source/test.

## 10. R7 round 2 — B01 CR2 transport (Hermes INT, 2026-09-16)

- Input CR2 `396a3c81589ea19b6c5b119e446b1bd4c7f4b754` (parent `c3cf0955…` = HEAD round 1; branch `codex/s09-lock-producer-b01-r6` tip; worktree B01 porcelain trống). 1 commit, delta đúng 4 paths: `tests/test_s09_structural_lock_producer.py` + S09 `{CONTRACT,LOG,REPORT}.md` (test+docs only, +148/−7).
- Merge `a30f71bf4eef8fe34f2acc20875346d62ac1e24a` (parents `c3cf095…` + `396a3c8…`), zero conflict; diff-check 0; porcelain trống.
- Static: `compileall` app 0; `py_compile` test file 0; `ruff check --select F` 0 (`All checks passed!`); full-ruleset informational 14×N802 style-class (không F-class).
- Evidence: COMMAND_LEDGER.jsonl (append, phase `r7r2_*`) + R7_INT_RAW_PROVENANCE_R2.txt; không push; không sửa source/test.

## 11. R7 round 3 — QA chain + R5 sync (Hermes INT, 2026-09-16)

- Input `393e1bfad7328c349cc81202cdf54c9df9b7274d` (parent `c3cf095…`): 5 files (+537/−56) — QA LOG/R6_INVENTORY/R7_PREP + `test_r6_b01i_public_chain.py` chain-rewrite + `test_r7_prep_inventory.py` → merge `159b61d295d1a608b20023b0424910ade504d0e7`.
- Input `3444a498c0f865070d4e2c24af0dd9a506b6628c` (parent `393e1bf…`): 3 files (+35/−10) — QA LOG + `R5_MATRIX.md` + `test_r5_matrix_packet.py` (R7-B2 bounded exception) → merge `05eed0f269f8578cc777e39234e752e7a59e40ae`.
- Zero conflict cả 2 merge; diff-check 0; porcelain trống sau từng merge.
- Static: `compileall` app 0; `py_compile` 3 test file 0; `ruff check --select F` 0 (`All checks passed!`); full-ruleset informational 3×E501 style-class (dòng tên dài trong r5 matrix packet).
- Transport tip `05eed0f269f8578cc777e39234e752e7a59e40ae`; delta tổng vs wave-base `35f6cb2` = 43 paths (thêm `R5_MATRIX.md` + `test_r5_matrix_packet.py` + `test_r6_b01i_public_chain.py` so với 40 trước đó).
- Evidence: COMMAND_LEDGER.jsonl (append, phase `r7r3_*`) + R7_INT_RAW_PROVENANCE_R3.txt; không push; không sửa source/test.

## 12. R7 round 4 — QA pin re-freeze (Hermes INT, 2026-09-16)

- Input `5947088e4145d71bee6863bfb2619c8e45c2f1d4` (parent `3444a49…`; branch `codex/s12-lc3-luna-qa` tip; worktree porcelain trống): 3 files (+20/−2) — QA LOG +18, `R6_INVENTORY.md` ±1, `test_r6_finite_inventory.py` ±1 (pin re-freeze, R7-B2 addendum) → merge `f44600453a596b3f5d9324618b1bcca35222b33c`.
- Zero conflict; diff-check 0; porcelain trống.
- Static: `compileall` app 0; `py_compile` finite_inventory 0; `ruff check --select F` 0 (`All checks passed!`); full-ruleset 0 (`All checks passed!`).
- Transport tip `f44600453a596b3f5d9324618b1bcca35222b33c`; delta tổng vs `35f6cb2` = 44 paths (+1: `tests/s12/s12-lc3-qa-r6/test_r6_finite_inventory.py`).
- Evidence: COMMAND_LEDGER.jsonl (append, phase `r7r4_*`) + R7_INT_RAW_PROVENANCE_R4.txt; không push; không sửa source/test.

## 13. S12-LC3-INT — transport wave-base `2594de06` (QC-EVIDENCE + UI-BUILD + QA), Hermes INT, 2026-09-24

- Candidate `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`. Session thực thi `20260924_214735_cd0f35` (suy từ first-user-message trong `state.db`, msg id 224302; `parent_session_id` NULL nên không chứng minh được lineage resume — ghi nhận, không suy đoán). Route `ocg/deepseek-v4.1-flash` / custom / thinking ON / fallback OFF.
- Pre-INT HEAD `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`, porcelain 0 (đo lại, khớp Manager). Ba `git merge --no-ff` nối tiếp, zero conflict, zero hand-edit: QC-EVIDENCE `2809f9c8dd5cca5a2be86e80a2f190a11a0fff11` → `76f50bee` (14 files +5997/−3); UI-BUILD `bd16c6db2c6f93d5f2cb704638b29bd71393b787` → `6871745d` (6 files +496/−3); QA `22815ed47b4169cc53961240547d0536c7180027` → `f991e243` (11 files +2270/−7). Range QA KHÔNG phải descendant của wave-base (merge-base `5947088e4145d71bee6863bfb2619c8e45c2f1d4`) nên là merge 3-way thật; đo trước khi merge: 2 file dùng chung có blob id giống hệt ở `5947088e` và `2594de06`, và không commit nào trong `5947088e..2594de06` chạm `tests/product_p1/**`, `tests/s12/s12-lc3-qa-r6/**`, `tests/test_s09_t06_backend_authority.py`.
- Chọn merge thay vì cherry-pick cho range QA (packet cho phép "cherry-pick hoặc replay Git-only tương đương"): merge giữ chính sha Manager-verified làm ancestor của candidate, mạnh hơn replay-đổi-sha; đồng thời delta đưa vào được chứng minh trùng byte với delta gốc (`git diff --binary` sha256 bằng nhau: QC `f02c6ea6…`, UI `9568591c…`, QA `80417aa1…`). Ancestry `git merge-base --is-ancestor` = YES cho cả ba sha.
- Frozen integrated HEAD `f991e243f5dfa7e42a04948504af0863cc92fa43` (HEAD^ `6871745dfed1f6c113cb5daeb095ba3342c4a338`); union delta vs `2594de06` = 31 paths (+8763/−13); `git diff --check` 0; porcelain trống sau từng merge và lúc freeze.
- Static trên candidate: `import app` / `app.services.qc_evidence` / `app.workflow.qc_checks_handler` / `app.main` rc 0; `compileall` app scope rc 0; `ruff check --select F` app/services/qc_evidence + app/workflow/qc_checks_handler.py + tests/product_p1 → `All checks passed!`; `pytest tests/product_p1/qc_evidence -q -p no:cacheprovider` → **68 passed, 125 warnings in 184.61 s** (tái lập đúng số 68 của Manager tại `2809f9c`). Suite QA public_chain và S09 authority KHÔNG chạy ở INT (thuộc chain của QA sau freeze).
- QA-tree advance (writer đã quiescent, đo chứ không tin lời): receipt `S12-LC3-QA-resume-after-502.json` exit 0 ended `2026-09-24T14:46:19Z`, pid 34664 đã mất khỏi process table, worktree QA porcelain 0, chỉ còn `.ruff_cache/**` (git-ignored) mới hơn commit cuối. `git merge --ff-only f991e243…` → `Updating 22815ed..f991e24` / `Fast-forward`, rc 0, porcelain 0 ⇒ QA HEAD `22815ed47b…` → `f991e243f5dfa7e42a04948504af0863cc92fa43` (trùng candidate). Blocker QA2 nay đã thoả trên đĩa; chạy chain vẫn là việc của QA owner.
- Commit docs-only (write set DAG `docs/pm/sessions/S12-INT01/**`, 9 files) ghi `S12INT_TRANSPORT_LEDGER.md` + `S12INT_REPORT.md` + `FROZEN_CANDIDATE.md` + mục LOG này; không đụng code/test/đường dẫn khác. KHÔNG push; KHÔNG merge MAIN; không rebase/reset/stash/restore/clean/force. CONTRACT `5f5fd67..542570d` vẫn `BLOCKED_DEPENDENCY` (S13 path) — không thuộc round này.
- Disclosure: mọi merge in `fatal: bad object refs/codex/turn-diffs/…` + `error: failed to perform geometric repack` nhưng vẫn thành công (maintenance `gc --auto` gặp broken ref có sẵn của tool khác); lần chạy pytest đầu bị cắt ở 180 s tại 66 dots — đó là timeout chứ không phải fail (lệnh này mất 185.25 s theo đo của Manager); bản nháp ledger đầu tiên chứa 1 sha 40-hex "đúng định dạng nhưng không tồn tại" vì `git rev-parse <40hex>` chỉ echo lại tham số chứ không kiểm tồn tại — `git log -1 <sha>` báo `fatal: bad object`, sha thật `de5435b9a29d7e47812f5c76ef0db27cd10bfca2` đã được đọc lại từ commit chain và sửa trước khi chốt.
- Evidence: `outputs/mf-core-tool-delivery-20260924/20260924T1055Z/S12INT/` (S12INT_REPORT.md + ledger + FROZEN_CANDIDATE.md + raw/S12INT_TRANSPORT_RAW.txt + raw/pytest_qc_evidence.txt + raw/commands_ledger.jsonl + raw/frozen_candidate.json). Terminal `TASK_SUBMITTED`; không APPROVED/CLOSED.

## 14. S12-LC3-INT — transport round D (QC-EVIDENCE `5ea5928` + QA `bf40b76`), Hermes INT, 2026-09-25

- Candidate `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`; route `ocg/deepseek-v4.1-flash` / custom / thinking ON / fallback OFF (không fallback). Pre-INT HEAD `0ccbee343ed48a18737863427793f46fb9694411`, porcelain 0 (đo lại, khớp Manager).
- Hai `git merge --no-ff` nối tiếp, ZERO conflict, ZERO hand-edit: MF-P1-QC-EVIDENCE `2809f9c8dd5cca5a2be86e80a2f190a11a0fff11..5ea5928a216ec33f8598bab9669d873ad9d37e53` (1 commit) → `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e` (5 files +2123/−199); S12-LC3-QA `f991e243f5dfa7e42a04948504af0863cc92fa43..bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` (1 commit) → `04541443ff6dada4fe464e315888ac58a0dbfcd9` (1 file +1619/−353). Đo trước khi merge: merge-base của mỗi range tip với HEAD trước merge ĐÚNG BẰNG range start (`2809f9c8`, `f991e243` — cả hai đã là ancestor từ round C), nên mỗi merge chỉ đưa vào đúng delta của tip. Delta merge khớp chính xác scope check của Manager (5 files +2123/−199 và 1 file +1619/−353).
- Frozen integrated HEAD MỚI: `04541443ff6dada4fe464e315888ac58a0dbfcd9` (HEAD^ `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e`), tạo lúc `2026-09-24T19:21:36Z`, ghi nhận freeze `19:27:22Z`; union delta vs `0ccbee34` = 6 paths +3742/−552; `git log --oneline 0ccbee34..HEAD` = 4 dòng; `git diff --check` 0; porcelain trống sau từng merge, sau checks và lúc freeze. Candidate cũ `f991e243` bị supersede nhưng KHÔNG mất: nó vẫn là ancestor của candidate mới, và record round C được giữ ở mục History của transport ledger (§8) — ledger round C (158 dòng) còn nguyên byte (đã chứng minh `p_body in cur` so với blob gốc đọc từ git).
- Provenance: `git merge-base --is-ancestor` = YES cho cả `5ea5928a` và `bf40b76e`; cả hai tip verify bằng `git rev-parse --verify <sha>^{commit}`. Delta equivalence (sha256 của `git diff --no-color --binary`): QC nguồn == QC merge `44b41776b6a9ecf351ba094cd17554533b2a56546699b6d5876ec1131484342e` (128.188 B cả hai); QA nguồn == QA merge `8c88b36d28a34fe67b7b77715afc384fb95091461e584e8e89dd4a1889825288` (102.648 B cả hai). Per-path equality so với CHÍNH source tree của mỗi lane: 0 khác biệt cho cả hai lane; 6/6 blob IDENTICAL (so blob id, KHÔNG so byte worktree — `core.autocrlf=true` làm cùng blob checkout ra số byte khác nhau, đó là false-difference đã biết).
- Checks tại candidate: import smoke (`app`, `app.services.qc_evidence.{compose,observe,sources}`, `app.workflow.qc_checks_handler`, `app.main`) rc 0; `compileall` phạm vi touched rc 0; `pytest tests/product_p1/qc_evidence -q` → **82 passed, 153 warnings in 244.30 s** (rc 0, wall 247 s — tăng từ 68 vì QC round D thêm `test_correction_round_d.py` 1.146 dòng); `pytest tests/product_p1/public_chain -q` → **29 passed, 2 skipped in 12.03 s** (rc 0, wall 13 s); porcelain 0 sau cả hai suite. Chạy suite ở background với cửa sổ đủ lớn — suite qc_evidence mất ~250 s, cửa sổ ngắn sẽ CẮT chứ không fail.
- QA-tree advance (chỉ sau khi writer quiescent, ĐO chứ không tin lời): receipt `manager/receipts/S12-LC3-QA-roundD-finish.json` exit_code=0 ended `2026-09-24T19:18:15.394504Z` pid 25928 (receipt round-D chính: rc 0 ended `18:49:26Z` pid 33108); cả hai pid đã mất khỏi process table; worktree QA porcelain 0; hai snapshot cách nhau 43 s (`19:23:23Z` / `19:24:06Z`) trùng nhau về HEAD/porcelain/mtime file mới nhất, và file mới nhất trong tree (`19:15:54Z`) cũ hơn thời điểm receipt kết thúc. `git merge --ff-only 04541443…` → `Updating bf40b76..0454144` / `Fast-forward`, rc 0, porcelain 0 ⇒ QA HEAD `bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` → `04541443ff6dada4fe464e315888ac58a0dbfcd9`, và `git merge-base --is-ancestor bf40b76… HEAD` = YES (range QA vẫn là ancestor). Chạy chain vẫn là việc của QA owner — INT không chạy.
- KHÔNG transport (theo scope): `MF-TOOL-CONTRACT 542570d..f0b918b` (đường C-CONTRACT, giữ `BLOCKED_DEPENDENCY`, không được vào PRODUCT), các tree CORE (COMFY `a1dd05c` / VIDEO14B / BENCH), UI (round này không có commit UI mới).
- KHÔNG sửa, theo chỉ thị: finding cấp SẢN PHẨM mà QA đo — S12 export readiness không đạt được qua public API (readiness cần một QC run full ĐÚNG SCOPE HIỆN TẠI hoàn tất, trong khi full run bị từ chối với fixture chỉ có một segment). Đây là gap sản phẩm để nhánh code / Codex route; QA đã ghi nó thành control asserted `BLOCKED_EXACT`. INT chỉ transport + freeze.
- Docs (write set `docs/pm/sessions/S12-INT01/**`): `FROZEN_CANDIDATE.md` (overwrite cho round này), `S12INT_TRANSPORT_LEDGER.md` (§8 history + §9 rows round D, phần round C giữ nguyên byte), `S12INT_REPORT.md` (§10), mục LOG này. KHÔNG push (`git branch -r --contains HEAD` = 0), KHÔNG merge MAIN, không rebase/reset/stash/restore/clean/amend, không sửa code/test bằng tay.
- Disclosure: cả hai merge in `fatal: bad object refs/codex/turn-diffs/…` + `error: failed to perform geometric repack` nhưng vẫn thành công (maintenance `gc --auto` gặp broken ref có sẵn của tool khác — không "sửa" vì không thuộc task). Bộ verify ledger tự phát hiện 1 lỗi ở CHÍNH script kiểm (đếm dòng bảng trùng prefix với bảng round C) — đã scope lại theo full row string, không sửa số liệu cho khớp.
- Evidence: `outputs/mf-core-tool-delivery-20260924/20260924T1557Z/S12INT/` (REPORT.md, TRANSPORT_LEDGER.md, raw/proofs_transport.txt, raw/check_candidate.log, raw/pytest_*.txt, raw/frozen_candidate.json, raw/commands_ledger.jsonl, raw/sha256_manifest.txt). Terminal `TASK_SUBMITTED`; không APPROVED/CLOSED.

## 15. S12-LC3-INT - transport round D2 (S12-LC3-QA `641b83d`), Hermes INT, 2026-09-26

- Base `b077da0` (round-D docs commit), porcelain 0. ONE range transported by ONE `git merge --no-ff`, ZERO conflicts,
  ZERO hand edits: S12-LC3-QA `04541443..641b83d` (1 commit) -> `09489bab2c5513b731d92ade492a6017780f9373`
  (1 file +157/-17, byte-equal to the Manager scope check). `merge-base b077da0 641b83d` = `04541443` = range start.
- NEW FROZEN CANDIDATE #2 `09489bab2c5513b731d92ade492a6017780f9373` (`HEAD^` b077da0, `HEAD^2` 641b83d). Round C and round D
  candidates kept in the history (FROZEN_CANDIDATE.md SS7 + ledger SS8/SS9; round-D freeze JSON kept as
  `raw/frozen_candidate_roundD.json`).
- Proofs: ancestry YES (both SHAs); delta sha256 `6e9ab1ae...` identical on source and merge deltas (11,597 B both);
  scoped per-path diff 0; blob `f67e8227` identical source/HEAD. Checks at the candidate: import smoke rc 0, compileall rc 0,
  pytest `tests/product_p1/qc_evidence` 82 passed rc 0 251.37 s, pytest `tests/product_p1/public_chain` 30 passed 2 skipped
  rc 0 12.18 s, porcelain 0. QA tree advance after MEASURED quiescence (receipt S12-LC3-QA-roundD2 rc 0 ended
  2026-09-26T10:59:37Z pid 6136 absent + two snapshots 60 s apart identical): `git merge --ff-only 09489bab` ->
  Fast-forward `641b83d..09489ba`, QA HEAD -> `09489bab...`, ancestry of `641b83d` in QA HEAD YES, porcelain 0.
- Evidence root `20260924T1557Z/S12INT` refreshed: `raw/proofs_transport_d2.{sh,txt}`, `raw/delta_qa_d2_{source,merged}.patch`,
  `raw/check_candidate_d2.{sh,log}`, `raw/pytest_{qc_evidence,public_chain}_d2.txt`, `raw/qa_quiescence_d2.{py,txt}`,
  `raw/qa_advance_d2.txt`, `raw/frozen_candidate.json` (+ round-D snapshot), ledger/report copies and the sha256 manifest.
- NOT fixed (by instruction): the product gap QA measured (3 of 8 visual detectors have no producer; S12 readiness stays
  `BLOCKED_EXACT`) - routed as delta A -> S08-T02, delta B/chain leg -> S08-T05. Nothing pushed; MAIN `a40e368` untouched.
  TASK_SUBMITTED; khong APPROVED/CLOSED.
