# S12 LC3-R4 QA owner report

Terminal status: `BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY / NOT_CLOSED / NOT_APPROVED`

Exact owner/session: QA Goodall / `01a08991-c909-7d03-86ed-ac236d50c87b`.
Model route: `gpt-5.6-luna`, reasoning high, fallback OFF. QA branch/worktree:
`codex/s12-lc3-luna-qa` /
`C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa`.
QA checkpoint at start: `ac49c9d4e40e6c3d3a5b3cad49f67d6f12a80cdd`.
Frozen integration candidate at the prior QA packet: `17b33f53b27da58e3330dd4a8270706ac853d37a`.

## Scope

This is the independent QA R08-R10 evidence lane. Only the R4 QA directory
and session documents/evidence are writable. RETRY, VAL, UI, production,
schema, migration, B01 producer, MAIN, canonical S12, demo, S11, and S13 were
read-only or untouched. No reset, clean, stash, rebase, push, migration, or
private-handler substitution was used.

## Micro and audit disposition

The first gate is the new QA-owned packet micro; it asserts exact 62-row
arithmetic, required packet links, and mechanism-versus-normal-product
classification. R3 deterministic extraction remains
`FIXTURE_ONLY_ENGINEERING_MECHANISM`, never normal-product evidence. The next
QA-owned read-only audit hashes the frozen candidate,
inspects the registered OpenAPI routes when import is supported, searches for
production callers of `StructuralLockRepository.create_manifest`, and
reconciles the previously captured public-chain result. Its output is raw JSON;
an import failure is labeled an environment diagnostic, not a product pass.

R01-R08 owner controls were not run from QA before terminal VAL/RETRY owner
transport and candidate pin. Their rows remain `NOT_RUN`/gated. No collected
test count is promoted to executed or passed. The exact command ledger and raw
evidence index record every attempted gate.

## B01 exact public-contract blocker

The valid public R3 chain used server-returned identities: legacy 12-hex
project `27ff27234a0b`, UUID video
`7513a010-767c-4309-aa87-9d47a0ecf860`, completed legacy import/proxy/scene
jobs, extraction job `802bf597-31d6-4331-9e88-e3b160d99a33`, current roles /
occurrences / structural segments, public character/version/assets validation
and publish, ProjectCast `f1e89003-2df8-4fda-a976-9592ea189558`, and
ReskinConfig `d78a4a7e-eda5-4028-b0fe-d33b69f39c1e`. The config lock pin was
null.

The candidate exposes the storage primitive
`app/persistence/structural_lock.py:495` (`create_manifest`) but no public
StructuralLock create/activate route and no production caller. The exact
missing producer is therefore the server-owned operation that validates the
current source/evidence graph, creates/activates the manifest, and returns a
server-generated ID/hash for the supported config CAS pin. This is preserved as
`PROPOSED_ONLY` in `UPSTREAM_SCOPE_PROPOSAL_R3.md`; R4 does not implement it.

Public S09 v1/reapprove returned `201` but the authority was verified and
non-executable with reason `no structural lock manifest pinned; full apply
requires manifest authority (reapproval after pinning)`. S10 returned
`422 {"detail":"v2 authority has no frozen source artifact (incomplete authority)"}`.
S12 context returned `200` with no checkpoint/lock/plan/full_apply_run_id and
S12 submit returned `409` with `S12_EXPORT_FULL_APPLY_MISSING` and
`S12_EXPORT_LOCK_MISSING`.

The R3 before/after consumer counts remained
`projects=1, video_items=1, jobs=4, artifacts=7, characters=1,
pack_versions=1, character_assets=6, roles=2, occurrences=2,
project_cast_mappings=1, reskin_configs=1, structural_lock_manifests=0,
s09_approvals=2, s12_export_runs=0`. This is an external product dependency,
not an empty picker, guessed v2 UUID, or bad-role failure. Normal S12 export,
publisher/result/media, UI, playback, and download remain
`NOT_DEMONSTRATED`/`NOT_RUN`.

## Required next disposition

The next gate is exact-owner terminal transport from VAL and RETRY into a
cleanly pinned INT candidate. Only then may QA rerun the owned RETRY/VAL modules
read-only and UI/contract navigation checks, while preserving all failures and
keeping B01 product rows blocked. No row or sprint is self-approved or closed.

See [R4_MATRIX.md](R4_MATRIX.md), [R4_COMMAND_LEDGER.md](R4_COMMAND_LEDGER.md),
[R4_SESSION_REGISTRY.md](R4_SESSION_REGISTRY.md),
[R4_PACKET_AUDIT.md](R4_PACKET_AUDIT.md), and
[R4_RAW_EVIDENCE_INDEX.md](R4_RAW_EVIDENCE_INDEX.md).

## Final QA gate evidence

- QA packet micro: `qa-packet-micro-terminal-20260911T202300Z.command.json`,
  exit `0`, `3 passed`, 3.172s; stdout SHA
  `ED7BA5BDA32D1147039D4BD04612B0A4C95C7976F71C1483743C6CCEE338F823`.
  Earlier packet-control red attempts are retained as raw evidence and were
  corrected only in QA-owned labels.
- Read-only candidate audit: `qa-readonly-audit-final-20260911T200900Z.*`,
  exit `0`, 4.204s; JSON SHA
  `412CEC09E8B669706F5C39DA8012D6456B70D77A0298E4DA32E80E8412783147`.
  It reports OpenAPI import success, zero public StructuralLock routes, zero
  production `create_manifest` callers, authority `full_apply_executable=false`,
  S10 `422`, S12 `409`, and protected candidate hashes matching the supplied
  baseline.
- QA R4 collection: `qa-collection-r4-final-20260911T201300Z.*`, exit `0`;
  collection-only and not counted as execution/pass.
- Static: compile exit `0`; Ruff exit `0`; `git diff --check` exit `0`.
- Guards: candidate 15-entry guard and QA supplied guard exit `0`; the own
  six-file prewrite snapshot guard exit `0` with zero failures.
- Process cleanup: the earlier `qa-process-terminal-20260911T202200Z.*`
  envelope was exit `0` with zero matches. The latest
  `qa-process-terminal-final-20260911T202600Z.*` envelope is exit `1` because
  the broad audit observed VAL-owned PID `13308` (VAL pytest) and transient
  PID `2924` (VAL worker), both in the separate `s12-lc3-luna-val` lane;
  stdout SHA `B529A36C33F5212B900CF4D4257F224B87E2D089F4A686C7C15F22AF727220AE`.
  No QA-owned runtime was identified and no external process was terminated.
  This is an external environment/control overlap, not B01 or a product pass.

Final packet paths are QA-only. No RETRY/VAL/UI test was rerun from this lane,
and no normal-product S12/video/UI claim was promoted.

## Final candidate transport audit — b6d7187

The exact frozen candidate independently audited after R4 INT transport is
`b6d71873dd1597f191b3ead95cb15e5aff73a722`, clean in
`C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration` on
`codex/s12-lc3-luna-integration`. The captured graph verification proves
ancestors `86630450213f5ed399aa7cbcace0c671999d8b89` (VAL merge),
`0df6cf370d655445953480b56d4797bfddec560f` (RETRY merge), and
`617f7e809f7feb8fda0b69a49c469cc751a2e749` (QA merge); graph envelope
`candidate-merge-graph-verify-20260912T150700Z.command.json` exited `0`.

Read-only candidate gates were run in micro-first order against the merged
VAL/RETRY scopes. In the short contained runtime lane, VAL micro was `2
passed, 3 deselected`, RETRY micro `4 passed, 9 deselected`, VAL finite `3
passed, 2 deselected`, and RETRY finite `9 passed, 4 deselected`; each exited
`0`, with no skips or xfails. Exact envelopes and stdout hashes are indexed in
the fresh candidate lane. Two earlier retained controls failed only from
fixture/temp-path residue (`PublicationError` on an existing output and a
long-path `FileNotFoundError`); they were not promoted to product failures.

Candidate compileall exited `0`; merged-scope `git diff --check` exited `0`.
Changed-scope Ruff exited `1` only on six already-landed VAL findings in
`app/services/s12_export/publication.py` (N818/SIM105/SIM103/SIM102); QA did
not edit production. Corrected duplicate-definition and public-import scans
exited `0` with respectively `[]` over 10 files and five imported modules
with no import errors. The candidate write-set verification exited `0` with
26 entries and zero failures; the final candidate process audit exited `0`
with zero QA-owned matches.

Collection-only verification exited `0` and found 18 VAL/RETRY node IDs with
no collection errors. It remains collection-only and is not a pass or
execution count. The actual VAL worker-kill evidence and RETRY actual-worker/
contested-identity evidence remain owner-submitted artifacts, not normal
public S12 evidence. The read-only b6 audit still reports no public
StructuralLock producer/caller, `structural_lock_manifests=0`, S10 `422`, and
S12 `409` missing Full Apply/lock; B01 remains `PROPOSED_ONLY`,
`BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY`, `NOT_CLOSED`, and
`NOT_APPROVED`. Normal public S12/video/publisher/media/UI/playback remains
`NOT_DEMONSTRATED`/`NOT_RUN`.

Fresh evidence lane:
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r4-owner-submission\20260911T195310Z\qa-candidate-b6d7187-20260912T145123Z`.
The candidate and QA trees were left without QA-owned processes; no external
process was terminated. This transport audit changes no production, VAL, RETRY,
frontend, or candidate bytes.

The QA packet micro was rerun after this addendum: envelope
`qa-packet-micro-candidate-b6-20260912T152700Z.command.json`, exit `0`, `3
passed`, stdout SHA
`CB9CCAE7A25731B47BF196002B487FAD709F7ACC25B8ED060BE59B74A388EE4C`.
