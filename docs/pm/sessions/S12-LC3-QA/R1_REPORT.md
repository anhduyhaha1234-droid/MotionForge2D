# S12-LC3-QA — R1 terminal report

Terminal status: `BLOCKED_EXTERNAL_AUTHORITY_FIXTURE`.

This is an exact-owner QA report for branch `codex/s12-lc3-luna-qa` at
`91bf577a2706a3351f7a72f9142fbd7b9c5671c3`. No approval, closure, push, reset,
rebase, stash, or clean operation was made. The preserved QA allowlist and
session evidence were recorded in one local checkpoint after the final
review; that commit does not signify green acceptance or closure.

## Scope and changed paths

The only source paths changed in this continuation are the allowlisted QA
paths:

- `scripts/s12/s12_lc3_probe.py` — bounded isolated public-chain probe; added
  explicit managed-root setup, durable worker start/stop, legacy public
  create/upload/analyze traversal, bounded chain reads, OpenAPI inventory,
  and read-only mutation-count assertions.
- `tests/s12/s12-t03a/test_s12_export_c1_closure.py` — typed C08 loser
  evidence; existing winner/loser and lease assertions retained.
- `tests/s12/s12-t06b/test_c28_audio_mapping.py` — stale no-assertion C28
  finding replaced with current explicit audio-authority assertions; existing
  real-media assertions retained.

Session documentation added/updated is under this directory:
`PUBLIC_CHAIN_MAP.md`, `UPSTREAM_SCOPE_PROPOSAL.md`, `R1_MATRIX.md`, this
report, and `evidence/q1-blocked-status.md`. No production, frontend, VAL-
owned, schema, persistence, migration, packaging, or unrelated file was
edited.

## Intake and route policy

The full HERMES rules, session protocol, MAIN/frontend guidance, applicable
architecture and S12 contracts, C3 `NEXT_LUNA_PROMPT.md`, `REVIEW.md`, and
`MATRIX.md`, plus the prior binding C2 prompt, were read before this terminal
assessment. The mandated route remains `gpt-5.6-luna`, reasoning `high`,
fallback `OFF`; no provider/config change was made.

## Fixture versus normal-product classification

The legacy public source chain is valid source/durable-worker evidence only:
public 12-hex project creation, real multipart upload, public analyze submit,
and the durable import/proxy/scene worker completed with real source and proxy
artifacts. It is not a Full Apply authority and is not normal-product S12
acceptance.

The two retry reds are not converted to expected `409` outcomes. Their
existing fixture lineage does not contain a current server-owned Full Apply
authority, so the production route correctly rejects them. The direct-SQL UI
seed that fabricates completed Full Apply rows remains excluded. No S12
worker convergence, completed export, result endpoint, media playback, or UI
click evidence is claimed.

## Commands and raw results

| Envelope | Result |
|---|---|
| `q1-r1-public-legacy-worker-authority-final.*` | exit `0`; `BLOCKED_EXTERNAL_AUTHORITY_FIXTURE`; source chain completed; exact OpenAPI/routes/responses and counts in JSON |
| `q1-r1-retry-current-final.*` | exit `1`; exactly 2 failed retry nodes: `export context is not current` and `S12_EXPORT_STALE_CHECKPOINT` |
| `q1-r1-suite-final.*` | exit `1`; `338 passed, 1 skipped, 2 failed, 313 warnings` in `316.51s` |
| `q1-r1-collect-final.*` | exit `0`; `341 tests collected in 2.32s`; stderr empty |
| `q1-val-correction-t03b.*` | exit `0`; 4 VAL-transported T03B nodes passed |
| `q1-r1-static-final.*` | exit `0`; focused Ruff and `git diff --check` passed |
| `q1-r1-guard-final-pre-allowdocs.*` | exit `0`; supplied pre guard `141` entries, zero failures, with the updated QA status doc explicitly allowlisted |
| `q1-r1-guard-final-protected.*` | exit `0`; supplied protected guard `15` entries, zero failures |
| `q1-r1-process-final.*` | exit `0`; no QA-owned Python, ffmpeg, node, or uvicorn process found |

The exact public route/state/owner/mutation trace and first missing contract
are in [PUBLIC_CHAIN_MAP.md](PUBLIC_CHAIN_MAP.md). The bounded shared-change
request is in [UPSTREAM_SCOPE_PROPOSAL.md](UPSTREAM_SCOPE_PROPOSAL.md). The
complete C01–C32 map is in [R1_MATRIX.md](R1_MATRIX.md).

## Terminal hygiene

The probe stopped its isolated durable worker and analyze orchestrator and
disposed its isolated engine. The final process check is recorded in
`evidence/q1-r1-process-final.*`; it found no QA-owned Python, ffmpeg, node,
or uvicorn process for this worktree/probe. The isolated
runtime used was
`C:\Users\Admin\mfqa\s12-lc3-r1\20260910T103100Z\QA\`; it was not MAIN,
demo data, or the reserved ports.

Because the required current v2 Full Apply authority cannot be created through
the observed supported public contract, the green Q1 commit gate is not met.
The QA source edits and all raw evidence remain classified as blocked evidence;
the user-authorized local checkpoint records them without claiming acceptance.
