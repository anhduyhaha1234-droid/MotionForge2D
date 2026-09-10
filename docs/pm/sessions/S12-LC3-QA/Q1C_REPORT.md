# S12-LC3-QA — Q1c final acceptance report

Terminal status: `BLOCKED_EXTERNAL_AUTHORITY_FIXTURE`.

This is a bounded Q1c attempt from the frozen integration candidate, not an
approval or closure decision. Production, frontend, VAL-owned tests, retry
tests, and branch transport were not modified. The QA checkpoint branch
was based at prior checkpoint `5fc8bdbc5ff5dcc799ce4427a5f0b3ceae4dbd1e` and
the Q1c evidence is recorded in one subsequent local QA checkpoint; the
frozen candidate tested here is `codex/s12-lc3-luna-integration` at
`9f8e9fd0ffd318682313808b177bf711ad162739`.

## Route and scope

The mandated route remains `gpt-5.6-luna`, reasoning `high`, fallback `OFF`.
No provider, router, or configuration change was made. The Q1c commands were
read-only against the frozen candidate; only this QA session's new evidence
and report files were written.

The full C3 prompt/review/matrix, HERMES rules, applicable protocol/AGENTS and
S12 contract, and current R1 QA report/matrix/public map were read before the
attempt. The retained `UPSTREAM_SCOPE_PROPOSAL.md` remains the only upstream
proposal; no upstream implementation was opened.

## Fresh public-chain attempt

Runtime and database were isolated under:

`C:\Users\Admin\mfqa\s12-lc3-r1\20260910T111607Z\Q1C\`

The candidate-bound probe forced `app` imports to the frozen integration tree.
Its complete structured stdout/result is
`evidence/q1c-public-chain-final.json` (exit `0`, SHA-256
`920FCAB5EE57925F21690ADC4ECC12EB81D5A9D3A6CDEC767C7B20D30F0D04D2`).
`manual_sql_used` is `false`.

Observed public identities and positive source-chain evidence:

- v2 project `418e2971-2561-45dc-bdbb-332515233c3c`, v2 video
  `1c88a0c7-5f5b-46ca-9f1b-2c4313aa2fb5`: both created by public API.
- legacy project `76355ad9187e`, legacy durable video
  `189b4183-6827-41e2-9e87-91c10290df88`: public create/upload/analyze path.
- source artifact `41d3f265-97d3-5628-81be-90bb3dd04604`, proxy artifact
  `3183e375-152f-56fa-a9c7-3f181c85e200`, source SHA
  `bce0018453ff8594a4c1f4bd8287fc5cf84b980b1a713a795fabec5a77096977`.
- import/proxy/scene jobs returned by public analyze completed; final counts
  were `projects=2`, `video_items=2`, `artifacts=2`, `jobs=3`,
  `s12_export_runs=0`.

The server-owned export context returned `200` for the actual legacy IDs but
had reasons `S12_EXPORT_FULL_APPLY_MISSING` and `S12_EXPORT_LOCK_MISSING`.
Public submit returned `409`:

`export context not current: ['S12_EXPORT_FULL_APPLY_MISSING', 'S12_EXPORT_LOCK_MISSING']`

Pre-submit and post-submit counts were unchanged; no S12 run, publisher,
result, or media output was created. The exact authority attempts remain in
the JSON: v2 import `404 Not Found`, config creation `404 object role
ownership mismatch`, empty pack picker, S09 reapprove `404 ReskinConfig ...
not found`, and S10 Full Apply `404 ApplyCheckpoint ... not found`. The first
missing contract remains a public/service-owned path to create and pin a valid
current StructuralLockManifest and its Full Apply authority/prerequisites.

This is source/durable-worker evidence only. It is not normal-product S12
acceptance. No direct handler, SQL/ORM authority fabrication, seeded completed
row, user/demo asset, playback, download, or media inspection was used.

## UI boundary

The frozen candidate has `frontend/package.json` and the S12 Playwright config,
but no `frontend/node_modules`. Node/npm are present, yet installing
dependencies would expand this bounded task and alter the frozen runtime. The
real Export UI was therefore not launched; no clicks, reload, project/video
switch, retry, playback, download, or UI defect is claimed. The existing
direct-SQL seed remains fixture-only and was not used.

Raw availability envelope: `evidence/q1c-ui-availability.*`.

## Candidate verification

Collection was run once on the frozen candidate:

`python -m pytest tests/s12 --collect-only -q -p no:cacheprovider`

It exited `0` with `351 tests collected in 2.83s`; complete stdout/stderr/exit
are `evidence/q1c-collection-final.*`. The affected retry suite was run once:

`python -m pytest tests/s12/s12-t03c/test_export_jobs_api.py::test_retry_after_cancel_converges tests/s12/s12-t03c/test_s12_t03c_c1_closure.py::test_c15_retry_converges_no_duplicate_successor -vv -p no:cacheprovider`

It exited `1`: exactly `2 failed, 5 warnings in 5.08s`. The failures remain:

- `tests/s12/s12-t03c/test_export_jobs_api.py::test_retry_after_cancel_converges`
  — `app/api/routes/s12_export.py:494`, `409 export context is not current;
  retry rejected`.
- `tests/s12/s12-t03c/test_s12_t03c_c1_closure.py::test_c15_retry_converges_no_duplicate_successor`
  — `app/api/routes/s12_export.py:508`, `409 S12_EXPORT_STALE_CHECKPOINT:
  retry context changed`.

No retry assertion was weakened and neither retry test was edited. Existing
R1 full-suite results remain historical; Q1c did not rerun the full suite.

## Hygiene and evidence

The probe stopped its isolated worker/orchestrator and disposed its isolated
engine. The final scoped process check found no QA-owned Python, ffmpeg, node,
or uvicorn process; raw evidence is `evidence/q1c-process-final.*`. The
supplied pre/protected guards passed with `141/0` and `15/0`; raw evidence is
`evidence/q1c-guard-final.*`.

The complete current-head 32-row map is [Q1C_MATRIX.md](Q1C_MATRIX.md).
The retained route map and upstream proposal are [PUBLIC_CHAIN_MAP.md](PUBLIC_CHAIN_MAP.md)
and [UPSTREAM_SCOPE_PROPOSAL.md](UPSTREAM_SCOPE_PROPOSAL.md). This Q1c result
does not promote any row to approval or closure.
