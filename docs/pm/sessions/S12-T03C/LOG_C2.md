# S12-T03C C2 LOG — normal API/worker/recovery/publication (owner 20260907_144542_7d5dbf)

Branch `codex/s12/s12-t03c-0907a` — C2 W4. Baseline: canonical `da7108b` (T01 + T03A CAS/fencing + T04A source-locked + T03B real-media merged). Model: `ocg/deepseek-v4-flash` (custom), fallback OFF. No push/merge.

## Writes (allowlist)

1. `app/workflow/s12_export_jobs.py`
   - `_s12_export_handler` is now the REAL production caller of `publish_export_run` (F01): claim → private candidate → source-locked publication → run `completed`; job completes AFTER the run — states always agree (M13 closed).
   - Any render/publication failure lands the run `failed` (retryable) under the fence and re-raises — never a fake `running` leftover.
   - `submit_export_job` forwards `expected_sha256`, `fps_num`, `fps_den` into the stored manifest (server-owned validation expectations).
   - `reconcile_export_jobs` rewritten to the C2 fencing contract: zero-mutation startup scan that REPORTS expired-lease resumable orphans (fresh claim CAS re-claims); never calls `release_lease` on expired leases and never flips run status (F05).
2. `app/services/s12_export/publication.py` — candidate/publication boundary (F07):
   - NEVER assembles (double-assembly removed); validates the runner's PRIVATE candidate under scratch.
   - ONE atomic `os.replace` candidate → public output only after ready+fence+source-locked PASS; existing output never overwritten; `.partial` never public.
   - Byte-identity sidecar `<output>.sha256` written atomically with the artifact; completed replay re-verifies bytes (tamper fail-closed), never a bare status shortcut.
   - `running → verifying → completed` CAS in the same transaction as the rename.
3. `app/api/routes/s12_export.py` — F02:
   - Submit derives server-owned authority via `resolve_export_authority` (T01 consume) + real readiness aggregate BEFORE any mutation: unresolved authority (409), non-ready (409), unproven/non-media/partial/missing source (422), traversal/spoofed identities (None/422) — zero runs/jobs/outputs (C04/C05).
   - Client filesystem paths are ignored: chunk/scratch/output derived under the server managed root.
   - Returns the REAL durable `JobInfo.job_id` (non-null, F02), never `job.id` of a JobInfo.
   - `S12ExportSubmitRequest` path fields optional (backward compat only).
   - Retry re-submits the EXACT material identity (rebuilds original chunk_config; forwards expected_sha256/fps_num/fps_den) so T03A material-identity replay converges; `IdempotencyConflictError` → 409.
4. `app/lifecycle.py` — bounded S12-only startup recovery: `start()` calls `reconcile_export_jobs` (REAL production caller, F01) after the S02 job reconcile, before the worker polls; never blocks boot.
5. `app/workflow/job_service.py` + `app/api/app.py` — S12 handler registration + router mount (C1 wiring retained; part of F01's normal-app path).

## Tests (tests/s12/s12-t03c/, real components)

- `test_c1_closure.py` (9 tests): C01 normal bootstrap (mounted routes + handler registered + 1 submit → 1 run + 1 Job non-null IDs, server-owned paths); C04-part (real authority stale → 409 zero-mutation; real readiness not_run → 409 zero-mutation); C05 (traversal/non-media/partial reject before mutation, helper + route); C07-part (union replay converges; same-key material drift fail-closed zero extra rows); C14-part (expired lease reported resumable, fresh claim wins, old fence dead); C15 (cancel winner/409, retry converges ≤1 run, states agree); C16 (real ffmpeg render through the normal handler → real validator NOT_MEASURED → run failed retryable, no TypeError, no double assembly, no public partial).
- `test_publication.py` reworked to the candidate-boundary contract (9 tests): PASS publishes exactly once + sidecar; FAIL → failed; fence/not-ready/cross-scope/missing candidate/existing output fail closed; completed replay by bytes; tampered replay fails.
- `test_export_jobs_api.py` reconcile tests updated to zero-mutation report semantics.
- Repro file: R1 documents the historical TypeError (kept), asserts `_load_chunks` removal (no double-assembly); R2 readiness traceback kept.

## Findings fixed (real, from reviewer probes)

- F01: no production caller → handler publishes; lifecycle calls reconcile at startup.
- F02: route null Job ID → real `job_id`; client authority/paths → server-owned; not-ready/invalid → rejected before mutation (M03/M13 boundary).
- F07 (T03C share): candidate/private boundary; replay-by-bytes sidecar; partials never public; no double assembly.
- F05 (consumer share): publication re-checks live fence; reconciled expiry never mutates.

## Known cross-lane dependency (reported, not patched)

C16 positive PASS through the REAL T04A source-locked validator requires frame-digest authority at the FINAL profile raster plus a lossless identity profile — belongs to the T04A/T01 digest contract (F07 remainder); T03C's real path lands `failed` (NOT_MEASURED) truthfully instead of faking PASS.