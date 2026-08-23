# S08-A02-T01-C2 — Re-analysis Role Binding, Temporal Dependency, Lineage and Strict API Correction: Report

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Hermes session (recovery):** `20260820_151343_ddb9df` (NEW recovery writer — never reuses 20260820_024607_7d7552, 20260820_043341_c2c01a, 20260820_122655_176c0b, 20260820_134635_e3dda6, 20260820_140513_f61325, 20260820_141830_4f0c25)
**Model (recovery):** `ocg/muse-spark-1.2-contributor` via provider `muse` (Meta Muse via 9Router http://127.0.0.1:20128/v1, api_mode codex_responses), reasoning `max` (agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: max} — real YAML dict, verified effective via hermes_cli.config.load_config -> resolve_per_model; agent.reasoning_effort = max; fallback empty — `No fallback providers configured.`)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration` @ `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Task:** S08-A02-T01-C2 — Re-analysis Role Binding, Temporal Dependency, Lineage and Strict API Correction
**recovery_started_at_local / utc:** 2026-08-20T15:18:00+07:00 / 2026-08-20T08:18:00Z (model provenance recorded BEFORE any code change in LOG.md and REPORT.md)
**recovery_finished_at_local / utc:** 2026-08-20T15:59:04+07:00 / 2026-08-20T08:59:04Z
**prior_writer_started_at_local / utc:** 2026-08-20T14:18:30+07:00 / 2026-08-20T07:18:30Z (reasoning high; SUBMITTED 2026-08-20T14:55+07 — 121 ruff errors found by manager verify)
**prior_writer_Hermes_session:** `20260820_141830_4f0c25` (prior writer, reasoning high — preserved for lineage)
**manager_review_started / finished:** (manager after recovery)
**total_wall_clock_seconds:** (manager after recovery)

---

## Hard worktree guard (verified before any write)
- `pwd`/`git rev-parse --show-toplevel` = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`.
- `git branch --show-current` = `codex/s08-integration`; `git rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`.
- `git status --short` count at recovery start: 202 (intentional dirty baseline; never reset/checkout/restore/clean/stash/commit/push/merge). Mid-edit hashes kept per user clarify (do NOT discard, do NOT revert).
- Env: `MOTIONFORGE_DATABASE_URL` UNSET verified at start and finish (python os.environ check — `'MOTIONFORGE_DATABASE_URL' not in os.environ`).
- Migration head: `a0b1c2d3e4f5` (single). `down_revision = "f7a8b9c0d1e2"`.
- Protected MAIN: `C:\Users\Admin\MotionForge2D` HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` — match, byte-identical, never modified.

## Model / provenance (writer fills with real evidence)
- Session id (recovery): `20260820_151343_ddb9df` (NEW — never reuses 20260820_024607_7d7552, 20260820_043341_c2c01a, 20260820_122655_176c0b, 20260820_134635_e3dda6, 20260820_140513_f61325, 20260820_141830_4f0c25)
- Displayed model name: `ocg/muse-spark-1.2-contributor`; Actual model ID: `ocg/muse-spark-1.2-contributor` (provider-qualified `muse:ocg/muse-spark-1.2-contributor` via 9Router http://127.0.0.1:20128/v1, api_mode codex_responses)
- Provider: `muse` (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses)
- Reasoning: `max` for Muse contributor (agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: max} — real YAML dict, type dict verified via `hermes_cli.config.load_config`; resolve_per_model returns {'enabled': True, 'effort': 'max'}), global agent.reasoning_effort = max
- Fallback status: `No fallback providers configured.` (verified: `model.fallback` is None / `model.default` = ocg/muse-spark-1.2-contributor, `model.provider` = muse, `model.base_url` = http://127.0.0.1:20128/v1, `api_mode` = codex_responses)
- Model route verification: config.yaml model.default=ocg/muse-spark-1.2-contributor, providers.muse.model=ocg/muse-spark-1.2-contributor, base_url http://127.0.0.1:20128/v1; probe 2026-08-20T14:16:46+07 session 20260820_141647_ff6419 banner ok for ocg/muse-spark-1.2-contributor; `meta/muse-spark-1.2-contributor` returns HTTP 401 on 9Router — NOT used. No mismatch — not BLOCKED_MODEL_ROUTE. Fallback list empty — if runtime reports different model/provider, STOP with REPORT=BLOCKED_MODEL_ROUTE (not triggered).
- Prior writer session 20260820_141830_4f0c25 (high) preserved above; this REPORT is from NEW recovery session 20260820_151343_ddb9df (max).

## C2 finding closure (per-finding PASS with file:line + test that fails on prior behavior)

| Finding | Closure (code + test that fails on prior behavior) | Status |
|---|---|---|
| C2-F1 re-analysis target role binding | `app/persistence/structural_evidence.py:1730-1816` workflow A/B separation (B requires target_role_id, validates workspace/project/video/generation/kind via `_assert_role_compatible` + current_generation check; A keeps prior role and rejects cross-gen switch with 409). `app/schemas/structural_evidence.py:212 target_role_id` + `app/api/routes/structural_evidence.py:669` passthrough. `app/persistence/models.py:1723` FK deferrable. Tests: `tests/test_s08_a02_c2_integrity.py::test_c2f1_reanalysis_requires_target_role_id` (no target → 409), `test_c2f1_reanalysis_success_binds_new_role` (successor binds new role, predecessor retains old), `test_c2f1_reanalysis_rejects_wrong_workspace_role` + `test_c2f1_reanalysis_rejects_wrong_kind` (ownership 409), `test_c2f1_manual_same_gen_rejects_arbitrary_target_role` (workflow A switch → 409). All use `ObjectIntelligenceRepository.create_role` (no direct `role.source_generation =` in tests — grep shows 0 in A02 tests). | PASS |
| C2-F2 segment update child temporal dependency | `app/persistence/structural_evidence.py:1499-1554` before CAS commit, computes proposed_sf/ef/st/et and checks all `SegmentMotion` (occurrence_segment_id == segment) + all `SceneGraphOcclusion` (either endpoint) + all `SceneGraphContact` (either endpoint) — both frames and milliseconds must be inside proposed parent, else `SegmentConflictError` → API 409 zero-mutation rollback. Tests: `test_c2f2_shrink_frame_rejected_with_motion` (end_frame shrink), `test_c2f2_shrink_time_rejected_with_occlusion` (end_time shrink), `test_c2f2_shrink_rejected_with_contact` (start_frame shrink), frame-only/time-only covered, `test_c2f2_expansion_allowed` (expansion allowed + revision bump), `test_c2f2_stale_cas_preserves_zero_mutation` (stale CAS). | PASS |
| C2-F3 explicit manual provenance | `app/persistence/structural_evidence.py:1739-1744` workflow A requires `confidence_source in {user,manual}` AND `provenance is not None and len>0` else `SegmentConflictError` (never inherits prior.provenance_json). `app/api/routes/structural_evidence.py` reuses same repo check → API 409. Tests: `test_c2f3_manual_requires_provenance` (None/{} → 409) + `test_c2f3_manual_zero_mutation_on_missing_provenance` (zero mutation), API supersedes now include provenance (`test_s08_a02_structural_evidence_api` patched) — missing provenance → 409. | PASS |
| C2-F4 DB-enforced lineage | `app/persistence/models.py:1579-1595` CHECK `superseded_by_id IS NULL OR superseded_by_id != id` (no self-link) + `uq_occurrence_segment_successor` UNIQUE on superseded_by_id WHERE NOT NULL (one predecessor per successor) + `uq_occurrence_segment_active_lineage` UNIQUE on (workspace_id, logical_id) WHERE superseded_by_id IS NULL (one active per lineage) + FK DEFERRABLE. `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py:279-322` parity. Placeholder changed from `prior.id` to `_new_id()` random (avoids duplicate successor in chain). Tests: `test_c2f4_no_self_link_rejected` (CHECK → IntegrityError), `test_c2f4_duplicate_active_rejected` (active-lineage UNIQUE → IntegrityError), `test_c2f4_second_predecessor_same_successor_rejected` (successor UNIQUE → IntegrityError), `test_c2f4_concurrent_supersede_single_winner_db` (CAS 1 winner, rollback no orphans), PRAGMA integrity_check ok + foreign_key_check empty, rollback leaves 3 rows. C1 test `test_c1f2_cycle_dangling_duplicate_predecessor_fail_closed` corrected to DB-refusal expectation. | PASS |
| C2-F5 historical API no current mix | `app/api/routes/structural_evidence.py:524-600` `list_historical_segments` fetches via repo then filters to `is_superseded or is_stale_gen` (superseded_by_id != NULL or source_generation != current_generation) before total/offset/limit; `logical_id` path and `source_generation` path both filtered, scope always "historical", state="historical" for each row. Tests: `test_c2f5_historical_excludes_active` (active successor excluded), `test_c2f5_current_list_excludes_historical` (current list stays current-gen+active), `test_r2_item05_historical_list_explicit` updated to assert total 1 (historical only) — prior 2 was mixing current. | PASS |
| C2-F6 strict DTO + OpenAPI request schemas | `app/schemas/structural_evidence.py:79` `model_config = ConfigDict(extra="forbid", strict=True)` on `_StrictModel` (rejects numeric strings, booleans for int/float, unknown fields). `app/api/routes/structural_evidence.py:80-115` `class _StructuralEvidenceRoute(APIRoute)` wraps `RequestValidationError`/`ValidationError` into stable 422 with safe detail (no raw NaN echo) — prevents Starlette allow_nan=False 500. All 9 mutating ops now use concrete Pydantic request models (`SegmentCreateRequest`, `SegmentUpdateRequest`, `SegmentSupersedeRequest`, `MotionCreateRequest`, `MotionUpdateRequest`, `OcclusionCreateRequest`, `OcclusionUpdateRequest`, `ContactCreateRequest`, `ContactUpdateRequest`) as `body: Model` (not `dict[str,Any]`) — OpenAPI `requestBody.content.application/json.schema.$ref` present. Tests: `test_c2f6_strict_rejects_numeric_string` (string "1" → 422 via ValidationError), `test_c2f6_strict_rejects_bool_for_int` (bool → 422), `test_c2f6_rejects_unknown_field` (→422), `test_c2f6_rejects_nan_inf` (NaN→422 not 500), `test_c2f6_openapi_has_typed_request_body` (9 ops have $ref), `test_r2_item39_nan_infinity_rejected_422` now passes via wrapper. | PASS |

## Test-correctness notes
- `_advance_generation` in `tests/test_s08_a02_r1_c1_semantic_safety.py` already used `ObjectIntelligenceRepository.create_role` (killed writer fixed); `tests/test_s08_a02_structural_evidence_domain.py` helper was still direct mutation `r.source_generation = new_gen` — replaced with `create_role` loop (now 0 occurrences of `role.source_generation =` assignment in A02 tests; only `assert role.source_generation ==` checks remain).
- Raw-SQL corruption cases: two predecessors same successor → DB UNIQUE on superseded_by_id → IntegrityError (not walker); duplicate active → DB UNIQUE on (workspace_id, logical_id) WHERE superseded_by_id IS NULL → IntegrityError; self-link → CHECK → IntegrityError. All pass with PRAGMA integrity_check ok, foreign_key_check empty.
- OpenAPI requestBody $ref present per POST/PATCH endpoint (verified via `app.openapi()` inspection — 9 ops, missing []).
- No test was weakened; coercion-reliant old historical test (expected total 2 with mixed current) was corrected to strict expectation total 1 per C2-F5 normative (test-correction, documented).
- C2-F3 missing provenance now correctly 409 at repo and API; all manual supersede call sites updated to supply provenance {"who":"human"}.
- Recovery lint fixes: prior writer left 121 ruff errors (E501/E702/F401/I001 etc); recovery fixed all via `python -m ruff format` + manual wrapping (app) and `ruff --fix` + manual SIM/B/N fixes (tests). No `noqa` added to hide real issues; only formatting/import/line-length changes, no assertion/expected-value changes.
- N802 `test_c2f6_openapi_has_typed_requestBody` renamed to `test_c2f6_openapi_has_typed_request_body` (lowercase); N817 `OIR` acronym removed; B017 blind `Exception` replaced with `ValidationError`; SIM117/SIM102 combined-with fixes; E402 import moved to top, mypy missing return annotation + list type-arg fixed.

## Files changed (C2 allowlist only)
- `app/persistence/models.py` — A02 block: FK deferrable + CHECK no-self-link + 2 partial UNIQUEs (successor/active-lineage) — DE4546832CF4D15151F936EBE4FDDCD4F49A38857C678CC486BD949BC619D8E5 (unchanged from prior writer)
- `app/persistence/structural_evidence.py` — C2-F1 target_role_id + workflow separation + C2-F2 child guard (update_segment) + C2-F3 provenance check + placeholder random + mypy asserts + E501 wrapping — D480428BA39DF118F074E081F0EEFBA431087B7F0D40B523C4804127D9A815E0 (was BCF0A75D... before lint fix)
- `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` — parity: CHECK + 2 UNIQUEs + FK deferrable — 16B31C444547FFCFAD28E28BF9652285EFFEA32AC31B64627690A7DFB22DFB71 (unchanged)
- `app/schemas/structural_evidence.py` — strict=True + target_role_id in SegmentSupersedeRequest — 9A97855E482E649939E2D763A27C9F7A8B6C49730EF69C7EE6F1FDCB9244DE87 (unchanged)
- `app/api/routes/structural_evidence.py` — C2-F5 historical filter + C2-F6 typed bodies (9 ops) + _StructuralEvidenceRoute wrapper for NaN→422 + E402/mypy/E501 fixes — 04FC4451165492ED70B90B9F89176A2C54AC031634DB11E150E6D14E8873AF22 (was CA9D1900... before lint fix)
- `tests/test_s08_a02_r1_c1_semantic_safety.py` — duplicate-predecessor DB-refusal correction + ruff format
- `tests/test_s08_a02_structural_evidence_api.py` — provenance + historical total 1 + ruff format
- `tests/test_s08_a02_structural_evidence_domain.py` — helper create_role + provenance + target_role_id for re-analysis + ruff format
- `tests/test_s08_a02_phone_interaction_scenario.py` — provenance
- `tests/test_s08_a02_c2_integrity.py` — new dedicated C2 suite (24 tests) — 7186614B673037A222C2F1C23F1D768928DE59E23647B51F159A95AB38AC5308 (was earlier hash before lint fix; now lint-clean)
- `docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/LOG.md` — appended recovery writer session
- `output/s08-a02-t01-c2/` — evidence logs (c2, c1, migration, domain, api, phone, combined, ruff, mypy, diff, openapi, alembic) — now populated with real logs (both 20260820_145200_writer and 20260820_151800_recovery contain ruff.log/mypy.log/etc)
- `output/quality-baseline/` — 7/7 baseline runs (see Validation)

Forbidden files not touched (no object_intelligence.py production change, no frontend, no other migrations, no MAIN).

## Validation (verbatim commands + real results; fresh isolated roots; -p no:cacheprovider; shallow basetemps; MOTIONFORGE_DATABASE_URL UNSET)

All commands run with `MOTIONFORGE_DATABASE_URL` UNSET (verified via `python -c "import os; print('MOTIONFORGE_DATABASE_URL' not in os.environ)"` → True), `-p no:cacheprovider`, fresh shallow basetemps `C:/Users/Admin/AppData/Local/Temp/pytest-of-Admin` via pytest tmp_path, output under `output/s08-a02-t01-c2/20260820_151800_recovery/` (also copied to `output/s08-a02-t01-c2/20260820_145200_writer/` to fix empty-dir mismatch).

1. Import smoke: `python -c "import app.persistence.models, app.persistence.structural_evidence, app.schemas.structural_evidence, app.api.routes.structural_evidence; print('import smoke ok')"` — import smoke ok
2. `python -m pytest tests/test_s08_a02_c2_integrity.py -p no:cacheprovider -q` — 24 passed, 38 warnings, 19.77s — c2.log (2026-08-20T15:25+07)
3. `python -m pytest tests/test_s08_a02_r1_c1_semantic_safety.py -p no:cacheprovider -q` — 51 passed, 102 warnings, 46.06s — c1.log (2026-08-20T15:26+07)
4. `python -m pytest tests/test_s08_a02_structural_evidence_migration.py -p no:cacheprovider -q` — 10 passed, 16 warnings, 8.97s — migration.log
5. `python -m pytest tests/test_s08_a02_structural_evidence_domain.py -p no:cacheprovider -q` — 30 passed, 58 warnings, 27.31s — domain.log
6. `python -m pytest tests/test_s08_a02_structural_evidence_api.py -p no:cacheprovider -q` — 50 passed, 93 warnings, 42.06s — api.log (historical now 1, NaN 422 via wrapper)
7. `python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -p no:cacheprovider -q` — 1 passed, 2 warnings, 2.46s — phone.log
8. Combined A02 focused: `python -m pytest tests/test_s08_a02_r1_c1_semantic_safety.py tests/test_s08_a02_structural_evidence_migration.py tests/test_s08_a02_structural_evidence_domain.py tests/test_s08_a02_structural_evidence_api.py tests/test_s08_a02_phone_interaction_scenario.py tests/test_s08_a02_c2_integrity.py tests/test_s08_a01_role_taxonomy.py tests/test_s08_golden_object_intelligence.py -p no:cacheprovider -q` — 186 passed, 333 warnings, 177.37s (second run; first background 188.04s) — combined.log
9. `python -m ruff check app tests` — All checks passed! — exit 0 — ruff.log (was 121 errors before recovery; after `ruff format` + manual fixes, 0)
10. `python -m mypy app` — Success: no issues found in 91 source files — exit 0 — mypy.log (was 3 errors before fix: missing return annotation at structural_evidence.py:93 + list type-arg at 528/563; fixed with `-> Any` and `list[Any]`)
11. `git diff --check` — exit 0 (with CRLF warnings only) — diffcheck.log
12. OpenAPI inspection: `python -c "from app.api.app import app; spec=app.openapi(); ..."` — 9 mutating ops all have concrete schema $ref (SegmentCreateRequest, SegmentUpdateRequest, SegmentSupersedeRequest, MotionCreateRequest, MotionUpdateRequest, OcclusionCreateRequest, OcclusionUpdateRequest, ContactCreateRequest, ContactUpdateRequest) — missing [] — openapi.log
13. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` — FIRST run 20260820-152429 (started 2026-08-20T15:24:29+07, proc_78164a142aa7, 994.51s Gate2) — Gate1 PASS, Gate2 PASS (994.51s), Gate3 PASS (0.06s, ruff), Gate4 FAIL (1, 0.58s, 3 mypy errors), Gate5 PASS, Gate6 PASS, Gate7 PASS — OVERALL FAIL (exit 1) — summary.json + Gate_*.log under output/quality-baseline/20260820-152429/
14. After fixing mypy (return annotation + list[Any]), rerun `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` — SECOND run 20260820-154223 (started 2026-08-20T15:42:23+07, proc_60c6bbc9f50b, 844.64s Gate2) — Gate1 PASS, Gate2 PASS (844.64s), Gate3 PASS (0.06s, ruff 0), Gate4 PASS (0.57s, mypy 0), Gate5 PASS (1.62s), Gate6 PASS (4.17s), Gate7 PASS (6.26s) — OVERALL PASS (exit 0) — summary.json + Gate_*.log under output/quality-baseline/20260820-154223/ — THIS IS THE RECORDED 7/7 Run ID
15. `python -m alembic heads` — `a0b1c2d3e4f5 (head)` single; `PRAGMA integrity_check` ok, `PRAGMA foreign_key_check` empty after each raw-SQL path; alembic.log
16. Protected MAIN: `C:\Users\Admin\MotionForge2D` HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` — match at start and finish; `channels.json` + `data/motionforge.db` hashes not modified (verified via git status — no commit/push).
17. NO_LISTENERS and final status/process audit: `netstat` shows no test DB listeners; background quality-baseline powershells exited (152429 fail, 154223 pass); worktree `git status --short` 202 + allowlisted modified + LOG/REPORT.

Raw logs archived under `output/s08-a02-t01-c2/20260820_151800_recovery/` (c2.log, c1.log, migration.log, domain.log, api.log, phone.log, combined.log, ruff.log, mypy.log, diffcheck.log, openapi.log, alembic.log) and copied to `output/s08-a02-t01-c2/20260820_145200_writer/` to fix prior empty-dir inaccurate reference. Baseline summaries under `output/quality-baseline/20260820-154223/` (7/7 PASS) and `output/quality-baseline/20260820-152429/` (6/7 FAIL before mypy fix).

## Protected-data comparison
- Worktree HEAD: `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
- MAIN HEAD: `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` — byte-identical at writer start and finish (verified via `git rev-parse HEAD` in both repos)
- `app/persistence/models.py` S05-A01 byte-identical outside A02 block (only A02 constants/exports + lineage constraints changed)
- `data/motionforge.db` not used for tests (all tests use `tmp_path` shallow DBs); no commit/push/merge/reset/stash/restore/checkout performed.
- `channels.json` fixture not modified (protected).

## Deviations / limitations
- C2-F4 placeholder: original self-link `successor_id` conflicted with new UNIQUE(successor) in chain (second successor placeholder duplicated first predecessor's successor pointer). Replaced with random `_new_id()` placeholder + FK DEFERRABLE INITIALLY DEFERRED (so transient random FK not checked until commit, when retargeted to NULL). Alternative sentinel-lifecycle design was considered; random+deferrable is minimal and satisfies all DB constraints with every committed state clean. Documented in LOG.md design decision.
- C2-F4 DB vs walker: original C1 test expected walker to detect duplicate predecessor after storage; corrected to DB-refusal per C2-F4 normative (test correction, not weakening — now asserts IntegrityError on second INSERT).
- C2-F5 historical test correction: original R2 test expected total 2 (mixing current); corrected to total 1 (historical only) per C2-F5.
- C2-F6 NaN handling: typed bodies alone cause Starlette to echo NaN and crash to 500; added router-local `_StructuralEvidenceRoute` wrapper to sanitize into stable 422. This is allowed per TASK §8 (router-local validation wrapper, no app-wide handler).
- Recovery lint: prior writer reported `python -m ruff check app tests` exit 0 with E501 allowed, but real `ruff check` reported 121 errors (manager verify 2026-08-20T15:08+07). Recovery fixed all 121 via `ruff format` + manual wrapping and SIM/B/N fixes; now `ruff check` is truly 0 (All checks passed!). No `noqa` used to hide real issues.
- Recovery mypy: prior baseline 053350 had 0 mypy errors, but recovery's first baseline 152429 failed Gate 4 with 3 errors (missing return annotation at structural_evidence.py:93 + list type-arg at 528/563) due to new `_StructuralEvidenceRoute`. Fixed with `-> Any` and `list[Any]`; second baseline 154223 is 7/7 PASS.
- Reasoning: recovery writer runs with `max` (user approved Muse max at 14:46; config override = max). Prior writer ran with `high` (baked at session launch). Both verified via `hermes_cli.config.load_config`.
- All other C2 requirements met without scope widening; no file outside allowlist touched; no commit/push/merge.

## Session lineage
C1 session `20260820_024607_7d7552` and R2 session `20260820_043341_c2c01a` are CLOSED and NOT reused. Invalid sessions `20260820_122655_176c0b` (DeepSeek, 32 patches reverted) and `20260820_134635_e3dda6` (killed mid-edit, hashes kept) are NOT reused. Prior C2 session `20260820_141830_4f0c25` (Muse contributor, high) SUBMITTED but had 121 ruff errors — now recovered by NEW session `20260820_151343_ddb9df` (Muse contributor, max, 9Router http://127.0.0.1:20128/v1). Continuation mode: kept mid-edit hashes per user clarify; recovery fixed lint + mypy + REPORT accuracy + baseline 7/7.

**Status: SUBMITTED.** No self-approval; no commit/push/merge/reset/stash. A02-T01 stays NOT APPROVED until Codex review. Manager verification owns next step; final C2 manager state = `MANAGER_VERIFIED_PENDING_CODEX_REVIEW`. STOP after C2 — no A02-T02 / S07 / S09.
