# S12-LC3-QA R2 report

Status: `BLOCKED_Q1_RETRY_IDENTITY_AND_EXTERNAL_AUTHORITY`.
This is an evidence checkpoint, not APPROVED/CLOSED. Exact route used:
`gpt-5.6-luna`, reasoning `high`, fallback `OFF`.

## Scope and head

Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa`

Branch: `codex/s12-lc3-luna-qa`

Candidate/head: `7dfbca84456501c3a995490e98741604d149aabf`

Runtime lane: `C:\Users\Admin\mfqa\s12-lc3-r2\20260910T124058Z\QA\`
Evidence root: `C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r2\20260910T124058Z\`

Only QA test/probe/session-document paths were changed. No production,
frontend, VAL-owned, shared S09/S10, MAIN, canonical, demo, S11, or S13 file
was changed. No reset, stash, clean, rebase, push, manual SQL, private
handler substitute, or fabricated authority/completion was used.

## Q1 correction loop

The two required nodes were first reproduced against the original fixture and
then repaired only within the allowlisted QA fixtures. The repaired fixtures
are explicitly `FIXTURE_ONLY` mechanism tests: they seed a current S10
Full Apply authority through the existing isolated test factory, use current
plan/hash/frame pins from the server row, use an isolated managed root, and
retain current/stale/missing/tamper controls. The assertions still require a
real usable successor, a new job, no cancelled replay/409 substitution, and
exactly one winner under two live callers.

| Attempt | Result |
|---|---|
| `q1-micro/reproduce-retry-reds-20260910T124714Z.json` | exit `1`; `test_retry_after_cancel_converges` got `409 export context is not current`; C15 got `409 S12_EXPORT_STALE_CHECKPOINT` |
| `q1-micro/rerun-retry-fixed-20260910T125252Z.json` | exit `1`; fixture reached the route but used the default managed root, exposing unsafe runtime isolation before successor assertions |
| `q1-micro/rerun-retry-fixed-isolated-20260910T125324Z.json` | exit `1`; both nodes reached current authority and failed with HTTP `500`: `UNIQUE constraint failed: s12_export_run.workspace_id, ... plan_hash, ... checkpoint_hash`, followed by `export run creation conflict resolved to no row` |

Raw envelope hashes are recorded in `R2_LOG.md`. The final isolated failure
is a frozen production defect, not a fixture-authority failure. The retry
route resubmits the same plan/checkpoint natural identity, the database
unique constraint rejects a second run, and `_replay_after_conflict` cannot
find the custom retry idempotency/natural key. QA therefore did not weaken the
assertions, accept 409/500, skip/xfail/ignore, or patch production. The exact
upstream owner and minimal identity correction are in
`UPSTREAM_SCOPE_PROPOSAL.md`.

Because the mandatory Q1 micro is red, no focused or broad acceptance suite
was promoted as green. The raw failures remain retained for correction.

## Q2 public graph

The fresh isolated probe used real public IDs and a fresh managed database.
`POST /api/v2/projects/` returned project
`927abd13-58ad-466e-a420-b344870f84df`; `POST
/api/v2/projects/{project_id}/videos` returned video
`ff6bba00-062c-480b-8408-538a532588cd` with `status=imported` and no source
artifact. The separate legacy public chain returned 12-hex project
`3902d80b8bf1` and durable UUID video
`18585f88-6590-40d2-9acf-7594a7eb7877`.

Legacy `POST /api/projects` → multipart `POST
/api/projects/{project_id}/video` → `POST
/api/projects/{project_id}/analyze` completed through the durable worker:
source artifact `0b36ae99-96da-508d-af59-10bb439d047f`, proxy artifact
`2af7f681-55b8-53f0-ae59-9d84a0aadb81`, three completed jobs
`59f91218-5a29-4cfd-8910-4a580057683d`,
`29cd7de2-27d6-45cd-a589-b6d80341168f`, and
`2053b3f0-504a-4c5b-8019-cdc2befa608d`, `scenes_count=1`, and source SHA256
`bce0018453ff8594a4c1f4bd8287fc5cf84b980b1a713a795fabec5a77096977`.
Counts before S12 submit were `projects=2, video_items=2, artifacts=2,
jobs=3, s12_export_runs=0`.

Actual-ID scoped reads were HTTP `200` but empty/not-ready: reskin configs
`0`, object roles `0`, project-cast mappings `0`, S09 approvals `0`, and
readiness `not_run`/`never_run`. The v2 export context was HTTP `200` with no
Full Apply run, checkpoint, lock, or plan and reasons
`S12_EXPORT_FULL_APPLY_MISSING` and `S12_EXPORT_LOCK_MISSING`. Public S12
submit returned HTTP `409` with the same reasons and left jobs at `3` and
S12 export runs at `0`.

The OpenAPI snapshot contains the actual v2 create/video/context,
ReskinConfig, role/cast, S09 reapprove/full-apply-authority, S10 Full Apply,
legacy upload/analyze, and S12 submit routes. It contains no v2 durable import
operation and no StructuralLock create/activate operation. The first valid
missing prerequisite is a server-owned current lock/source-generation and
owned role/pack/config graph; without those, there is no valid reapprove or
Full Apply body. The empty v2 identity and completed legacy chain are not
silently merged. `PUBLIC_CHAIN_MAP.md` and `UPSTREAM_SCOPE_PROPOSAL.md`
contain the exact route ownership and minimal shared delta.

Normal-product S12 submit → durable worker → publisher → result/media, real
UI clicks/reload/recovery, playback, cancel/retry/restart, and download were
not demonstrated. Positive legacy worker/artifact rows are classified as
partial source-ingest evidence only. Direct-SQL seeded E2E remains fixture
only and is not counted.

## Matrix and terminal checks

`R2_MATRIX.md` maps all C01–C32 with exact current or carry-forward
classification. `C17`, `C18`, `F01`, and `F02` remain open. The required
static/collection/guard/process command results are appended to `R2_LOG.md`.
There is no approval or closure claim.
