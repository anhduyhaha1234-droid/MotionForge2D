# S12-LC3-QA R2 command and evidence log

All commands below were run for the QA owner in the contained R2 lane unless
the command envelope says otherwise. Raw stdout/stderr and exit codes are
retained; no failed attempt is replaced by a later result.

## Q1 micro

| Evidence envelope | Exact argv/cwd | Duration / exit | Result |
|---|---|---|---|
| `q1-micro/reproduce-retry-reds-20260910T124714Z.json` (SHA256 `69FB67F169973DEAF5DF4800C8E9EE545C1207B65EC5BEA1BADF0AD9046AFA81`) | `C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/s12/s12-t03c/test_export_jobs_api.py::test_retry_after_cancel_converges tests/s12/s12-t03c/test_s12_t03c_c1_closure.py::test_c15_retry_converges_no_duplicate_successor -vv -p no:cacheprovider`; cwd `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa` | `5.95327877998352s` / `1`; epoch start/end recorded | 2 collected, 2 failed: missing-current-context and stale-checkpoint 409s |
| `q1-micro/rerun-retry-fixed-20260910T125252Z.json` (SHA256 `ACD7269897EEFC2487F5349DE2B0D76D8E172B1832ADBC9A26B44213E5B72E45`) | same two pytest node IDs and flags; same cwd | `6.04057383537292s` / `1`; epoch start/end absent in supplied envelope | isolated fixture reached route but default managed-root lookup failed |
| `q1-micro/rerun-retry-fixed-isolated-20260910T125324Z.json` (SHA256 `E9B99A9E34E2266093A07645C30372EC9ED171FFDAF294DDA977AC17EE1FF4F4`) | same two pytest node IDs and flags; same cwd | `6.55629444122314s` / `1`; epoch start/end absent in supplied envelope | 2 collected, 2 failed on frozen production HTTP 500 unique natural-key conflict / replay found no row |

The third run is the binding Q1 result. The changed fixtures remain red and
assert the intended successor semantics; no 409/500 is treated as success.

## Q2 public graph

Evidence: `q2/public-chain-v2-20260910T125705Z.json` (SHA256
`AE477C28459D9BBD3A904949CC0918F52DD84EC22386849DAAF01BB5A8C36F39`).
Command envelope: `q2/public-chain-v2-command-20260910T125705Z.json` (SHA256
`CBFD4271BCF5CE73346DA8B4DC899D0C3AB024238C5DFD48864CC793BD6DF708`).

Exact argv: `C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe scripts/s12/s12_lc3_probe.py --work-root C:\Users\Admin\mfqa\s12-lc3-r2\20260910T124058Z\QA\Q2-public-chain-v2 --evidence C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r2\20260910T124058Z\q2\public-chain-v2-20260910T125705Z.json`; cwd `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa`; duration `10.7718887329102s`; exit `0`. The supplied envelope did not include epoch start/end. Probe status was `BLOCKED_EXTERNAL_AUTHORITY_FIXTURE`, `manual_sql_used=false`, `worker_started=true`; worker/orchestrator cleanup ran in `finally`.

The probe's exact IDs, OpenAPI operation shapes, request/response bodies,
authority reads, mutation counts, source hash, and all retained raw stderr are
in the JSON evidence. Summary: v2 IDs
`927abd13-58ad-466e-a420-b344870f84df` /
`ff6bba00-062c-480b-8408-538a532588cd`; legacy IDs
`3902d80b8bf1` /
`18585f88-6590-40d2-9acf-7594a7eb7877`; completed legacy job IDs
`59f91218-5a29-4cfd-8910-4a580057683d`,
`29cd7de2-27d6-45cd-a589-b6d80341168f`,
`2053b3f0-504a-4c5b-8019-cdc2befa608d`; artifacts
`0b36ae99-96da-508d-af59-10bb439d047f` /
`2af7f681-55b8-53f0-ae59-9d84a0aadb81`; source SHA256
`bce0018453ff8594a4c1f4bd8287fc5cf84b980b1a713a795fabec5a77096977`.

## Required checks

The checks below are appended as they are run. Full acceptance is not
promoted while the mandatory Q1 micro is red.

## Collection, static, guard, and process checks

| Check | Exact command / cwd | Raw result |
|---|---|---|
| Full-tree collection | `C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/s12 --collect-only -q -p no:cacheprovider`; cwd `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa`; start `2026-09-10T13:09:25.9468665+00:00`, end `2026-09-10T13:09:29.8766383+00:00`, duration `3.9297718s` | `checks/collection-full-tree-20260910T130000Z.json`, SHA256 `26510085A300B0AA6313208A589494B71403DD2448316E9B53B6E7F35F4D7637`, exit `0`, `351` node IDs, `0` duplicate node IDs, `0` collection errors, stderr empty |
| Ruff focused reader/import check | `ruff check --select F,I tests/s12/s12-t03c/test_export_jobs_api.py tests/s12/s12-t03c/test_s12_t03c_c1_closure.py scripts/s12/s12_lc3_probe.py`; same cwd; duration `0.0286897s` | `checks/static-ruff-fi-final.json`, SHA256 `F8CF201379EB3284AEB21B4976A513D3C296878B60BCD3788FE5A805BD8C0AF4`, exit `0`, stdout `All checks passed!` |
| Git whitespace check | `git diff --check`; same cwd; duration `0.0361368s` | `checks/static-git-diff-check-final.json`, SHA256 `B5075DEF2C6C699A5D2213FE2AF9E96A43FA0066E6BF0032CE69BFCFE051CC1F`, exit `0`; stderr contains only Git's LF→CRLF working-copy warnings for the five modified tracked files, no diff error |
| Earlier successful static raw records | same commands | `checks/static-ruff-fi.json` SHA256 `65DF87F804D41848E8E2CE98CDFC307DA5B69DCF1D30339B5687AB3CC4FF7C04`; `checks/static-git-diff-check.json` SHA256 `03D1618AAEF93F93144910C6CCB41682A10CDB53E6E351563B291EC273832757`; both exit `0` and retained |
| Initial invalid static invocations (retained) | `ruff` with no subcommand; `git` with no subcommand; same cwd | `checks/static-ruff-initial-invalid-argv.json` SHA256 `CA3352EDFEB7F1968FCEC6741D817BE32B19A0C4B9A6B2CF6E72EB9A3F6D6360` exit `2`; `checks/static-git-initial-invalid-argv.json` SHA256 `E9E6A9BE16FCF3796604BF4B9152C63CEE56D3A17ABB6EE4B0F9E5A26F36A675` exit `1`; CLI usage only, no source effect |
| R2 QA write-set guard | same full `write_set_guard.py verify` command with baseline `baseline-qa-r2.json` and the five tracked QA allow-changes; same cwd; start/end captured in envelope; duration `0.0791063s` | `checks/write-set-qa-r2-final-command.json`, SHA256 `13E315FA466AE79F7FF4C68A26689230DC86C691EAFF224EEE28AF2BCC750BBC`, exit `0`, stdout `{"status":"VERIFIED","failures":0,"entries":8}`; report SHA256 `2DBC05D57F04EE922EBF38EB17A26B483EA000FA4E1345F91DFCF4D44A79EAC1` |
| Earlier guard raw record | same guard command; retained | `checks/write-set-qa-r2-command.json`, SHA256 `07FE17CBB12E69AAE8C75C19BBE4D6BC0D945CEA088BF962539ECD3F5023C519`, exit `0` |
| Frozen candidate guard | `write_set_guard.py verify` against supplied `baseline-candidate-r2.json`; cwd `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration`; no allow-changes | `checks/write-set-candidate-r2-command.json`, SHA256 `680BE15658E34C668F7CC5D36B53220124873350A1C33017DE120B8B2E9E6CC8`, exit `0`, `{"status":"VERIFIED","failures":0,"entries":13}`; report SHA256 `7372E1FB872803392A1979140DF51BB17872F92F66A6FC22343F320BD8E29E4A` |
| Process cleanup initial probe | QA identifier scan accidentally matched its own PowerShell command; retained as `checks/process-cleanup-r2.json`, SHA256 `F8416EF45967039A0E9E7E1427EAFAF8BD1B2C4804C0C59B6DF3B0616C55A6C4` | superseded only as a self-match; no process was terminated |
| Process cleanup final | `Get-CimInstance Win32_Process` filtered for `s12-lc3-r2`, `s12-lc3-luna-qa`, `Q2-public-chain-v2`, excluding the checker PID; cwd QA worktree; duration `0.2074286s` | `checks/process-cleanup-r2-final.json`, SHA256 `9D4EA8F8F55E4D18850002290535E1D5EC65000D84AC2B879CB329FA1308B058`, exit `0`, `0` matches |

No QA-owned writer, server, worker, ffmpeg, node, or orchestrator process was
left active at the final check. The full suite was not run because the
mandatory Q1 micro remained red on the frozen production retry contract.
