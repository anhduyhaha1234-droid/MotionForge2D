# S12-LC3-R3 QA log

Owner/session: QA Goodall / `01a08991-c909-7d03-86ed-ac236d50c87b`

Route: `gpt-5.6-luna`, reasoning `high`, fallback `OFF`.

Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa`

Branch: `codex/s12-lc3-luna-qa`

Starting reviewed HEAD: `e17f772cf85d388a3c53cd70c11a3b7f60868992`

Evidence root:
`C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z`

Runtime root:
`C:\Users\Admin\mfqa\s12-lc3-r3\20260911T034253Z\QA`

## Command ledger

| Start UTC | End UTC | Duration | CWD | Command | Exit |
|---|---|---:|---|---|---:|
| 2026-09-11T03:58:17.6701313Z | 2026-09-11T03:58:30.2858493Z | 12.615718s | `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa` | `python tests/s12/s12-lc3-qa-r3/r3_public_producer_chain_harness.py --work-root C:\Users\Admin\mfqa\s12-lc3-r3\20260911T034253Z\QA\public-producer-r3-capture-20260911T035817Z --evidence C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z\public-producer-chain-20260911T035817Z.json` | 0 |

Raw command envelope, stdout, stderr, structured result, and SHA-256 values
are retained as `public-producer-chain-20260911T035817Z.command.json`,
`.stdout.txt`, `.stderr.txt`, and `.json` in the evidence root. The structured
result and stdout SHA are
`C97FA33215908D4352BEDB547E1B8E8B3A68141696AEA10FA75E8683497612EA`;
stderr SHA is
`124F2F3866280D26F6F7521251EBD7BE954CA24C07F3C1082D964EACCD181F54`;
command SHA is
`9C38ECC5392E3BC8539B3FE6B719CEC5404CF5F2AE998743CDD563377B056AE9`.

## Result

The public graph reached a completed legacy upload/analyze/import/proxy/scene
chain, durable object extraction, current roles/occurrences/segments,
published character/version/assets, project cast, and ReskinConfig. Public S09
v1 submit and reapprove each returned `201`, but the returned v2 authority was
verified and non-executable because no StructuralLockManifest was pinned. S10
then returned `422 {"detail":"v2 authority has no frozen source artifact
(incomplete authority)"}`. S12 context returned `200` with no checkpoint/lock/
plan/full_apply_run_id and S12 submit returned `409` with
`S12_EXPORT_FULL_APPLY_MISSING` and `S12_EXPORT_LOCK_MISSING`.

Mutation counts after the failed consumers were:
`projects=1, video_items=1, jobs=4, artifacts=7, characters=1,
pack_versions=1, character_assets=6, roles=2, occurrences=2,
project_cast_mappings=1, reskin_configs=1, structural_lock_manifests=0,
s09_approvals=2, s12_export_runs=0`. Counts before/after S12 were identical.

Status: `BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY`. Normal-product S12
worker/publisher/result/media and real UI/video playback are
`NOT_DEMONSTRATED`/`NOT_RUN`; the deterministic extraction runtime is
`FIXTURE_ONLY_ENGINEERING_MECHANISM`. No SQL/ORM fabrication, private handler,
demo data, or frontend/production/VAL/RETRY edit was used. The harness stopped
its worker/orchestrator and disposed the isolated engine; no owned runtime was
left active.

Rerunning RETRY-owned modules, UI acceptance, and broad acceptance remains
gated until RETRY/VAL terminal and INT pins a candidate, per the binding R3
prompt. Those gates are recorded as `NOT_RUN`, not as passes.

## Final QA-only checks

| Check | Exact command/result |
|---|---|
| Compile | `python -m compileall -q tests/s12/s12-lc3-qa-r3/r3_public_producer_chain_harness.py`; exit `0`. |
| Ruff correction loop | Initial `ruff check tests/s12/s12-lc3-qa-r3/r3_public_producer_chain_harness.py` exited `1` with 14 import/line-length findings; only the new harness was corrected. Final same command exited `0`, stdout `All checks passed!`. |
| Whitespace | `git diff --check`; exit `0`; only Git's LF-to-CRLF warning for the tracked QA map was emitted. |
| Protected write-set guard | `python C:\Users\Admin\MotionForge2D\docs\pm\tools\write_set_guard.py verify --root C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa --manifest C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z\baseline-qa-r3.json --allow-change docs/pm/sessions/S12-LC3-QA/PUBLIC_CHAIN_MAP.md --report C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa\docs\pm\sessions\S12-LC3-QA\evidence\r3-write-set-final.json`; exit `0`, stdout `{"status": "VERIFIED", "failures": 0, "entries": 233}`. |
| Process cleanup | `Get-CimInstance Win32_Process` filtered to Python/ffmpeg/node/uvicorn and `s12-lc3-r3`, `r3_public_producer_chain_harness`, or `s12-lc3-luna-qa`; stdout `NO_QA_OWNED_RUNTIME_PROCESSES`; exit `0`. |

The final diff path review contained only the tracked QA map plus the new
QA-owned R3 harness, R3 log/matrix/report/proposal, and guard report. No
production, frontend, VAL-owned, RETRY-owned, or unrelated path was changed.
