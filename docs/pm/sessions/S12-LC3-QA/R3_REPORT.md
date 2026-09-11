# S12-LC3-R3 QA report

Status: `BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY`

This is the exact-owner QA Goodall R3 report for session
`01a08991-c909-7d03-86ed-ac236d50c87b`. It is not an approval or closure.

## Bounded attempt

The run used the reviewed QA HEAD
`e17f772cf85d388a3c53cd70c11a3b7f60868992`, route
`gpt-5.6-luna/high/fallback-OFF`, a fresh isolated SQLite database and managed
root under `C:\Users\Admin\mfqa\s12-lc3-r3\20260911T034253Z\QA`, and only
public HTTP endpoints. No SQL/ORM row fabrication, private handler, demo
identity, or production/frontend/VAL/RETRY edit was used.

The harness first completed the real legacy public create/upload/analyze chain,
then followed actual returned IDs through deterministic QA extraction, current
roles/occurrences/structural evidence, public character/version/assets,
validation/publish, ProjectCast, and ReskinConfig. The deterministic extractor
is explicitly `FIXTURE_ONLY_ENGINEERING_MECHANISM`; its positive outputs are
not normal-product export evidence.

Raw command envelope/result files:

- [R3 structured result](C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z\public-producer-chain-20260911T035817Z.json)
- [R3 command envelope](C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z\public-producer-chain-20260911T035817Z.command.json)
- [R3 stdout](C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z\public-producer-chain-20260911T035817Z.stdout.txt)
- [R3 stderr](C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z\public-producer-chain-20260911T035817Z.stderr.txt)

Command start/end/duration were `2026-09-11T03:58:17.6701313Z` /
`2026-09-11T03:58:30.2858493Z` / `12.615718s`, exit `0`. Evidence/result and
stdout SHA-256 is
`C97FA33215908D4352BEDB547E1B8E8B3A68141696AEA10FA75E8683497612EA`;
stderr SHA-256 is
`124F2F3866280D26F6F7521251EBD7BE954CA24C07F3C1082D964EACCD181F54`;
command SHA-256 is
`9C38ECC5392E3BC8539B3FE6B719CEC5404CF5F2AE998743CDD563377B056AE9`.

## Exact blocker

After the valid public source and current producer graph existed, the public
Structural Evidence read returned two current segments, but the OpenAPI path
set contained no route that creates/activates a `StructuralLockManifest`.
The only observed storage capability is
`app/persistence/structural_lock.py:495` (`create_manifest`), with route
recording at `:743`; no public producer calls it. ReskinConfig creation
returned `structural_lock_manifest_id=null` and `lock_policy_version=null`.

Public S09 v1 submit and reapprove returned `201`, but the actual v2 authority
was non-executable with this exact reason:

`no structural lock manifest pinned; full apply requires manifest authority
(reapproval after pinning)`

The next valid public calls were:

- S10 Full Apply: `422 {"detail":"v2 authority has no frozen source artifact (incomplete authority)"}`
- S12 context: `200`, with `checkpoint=null`, `lock=null`, `plan=null`, `full_apply_run_id=null`, reasons `S12_EXPORT_FULL_APPLY_MISSING`, `S12_EXPORT_LOCK_MISSING`
- S12 submit: `409 {"detail":"export context not current: ['S12_EXPORT_FULL_APPLY_MISSING', 'S12_EXPORT_LOCK_MISSING']"}`

Mutation counts were `projects=1, video_items=1, jobs=4, artifacts=7,
characters=1, pack_versions=1, character_assets=6, roles=2, occurrences=2,
project_cast_mappings=1, reskin_configs=1, structural_lock_manifests=0,
s09_approvals=2, s12_export_runs=0`; S12 before/after counts were identical.
This proves a genuine missing producer after preceding public producers, not an
empty picker, guessed UUID, role denial, or bad-ID 404.

## Scope and gates

The exact proposed upstream delta is recorded once in
[UPSTREAM_SCOPE_PROPOSAL_R3.md](UPSTREAM_SCOPE_PROPOSAL_R3.md). The full
S01-S10 and C01-C32 maps are in [R3_MATRIX.md](R3_MATRIX.md), with C17/C18/F01/F02
open. Normal-product export, durable S12 worker/publisher/result/media,
playback/download, and real UI interaction are `NOT_DEMONSTRATED` or `NOT_RUN`.
RETRY/VAL terminal and INT candidate-pin prerequisites were not asserted in
this run; RETRY modules and UI checks therefore remain `NOT_RUN` and were not
treated as passes.

The harness stopped its own durable worker/orchestrator and disposed the
isolated database engine. No owned runtime remains active. Only the new
QA-owned harness and R3 session documentation/evidence are in scope.
