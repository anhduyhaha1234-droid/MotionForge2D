You are the ONLY code writer for MotionForge2D correction task S08-A02-T01-R1-C1 (Generation, Idempotency and Temporal Integrity Correction).

MANDATORY MODEL CONFIGURATION:
- Provider: custom
- Model: ocg/deepseek-v4-flash
- Reasoning: max
- Do NOT switch model/provider/fallback. If the runtime reports a different model/provider or rejects this model, STOP with REPORT.md = BLOCKED and paste the exact error.
- Record actual Hermes session ID, actual displayed model ID/name, provider and reasoning in REPORT.md.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration
HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (do NOT modify, ever)

TASK:
Read FULLY and execute ONLY:
docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/TASK.md

Also read (context only):
- docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/TASK.md + REPORT.md + LOG.md
  (R1 = Codex CHANGES_REQUESTED; do NOT trust the R1 report at face value — re-audit current code)
- docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md (original A02 contract)

REPORT/LOG:
- Append to docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/LOG.md
- Fill docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/REPORT.md to SUBMITTED

C1 SCOPE (SEMANTIC CORRECTION — re-audit everything, R1 is NOT trusted):
Close all 7 Codex C1 findings with real code + tests that fail on current behavior:
- C1-F1 Generation semantics: two workflows (A) manual same-generation correction and (B) re-analysis transition to ObjectIntelligenceRepository.current_generation(); no arbitrary future/stale generation; fail closed; provenance/confidence_source honest for manual.
- C1-F2 Logical identity + branch safety: repository-owned logical_id, guaranteed uniqueness/scope, lineage_version with UNIQUE(workspace_id, logical_id, lineage_version), no branching, concurrent supersede single-winner, cycle/dangling/branch fail-closed.
- C1-F3 Complete idempotency: motion/occlusion/contact equivalence MUST include identity fields; same key + any differing field = stable conflict; zero mutation.
- C1-F4 Frame AND time containment (child range within segment; contact/occlusion within BOTH endpoints).
- C1-F5 Ownership/artifact: mask = same workspace + kind=image + state=ready; model/detector requires completed DISCOVER_OBJECTS job matching SHA/generation; manual evidence uses user/manual confidence_source; segment kind compatible with role taxonomy.
- C1-F6 Domain validation before flush (lengths, shapes, NaN/Infinity, malformed JSON fail-closed; only translate true unique/idempotency conflicts, never blanket IntegrityError catch).
- C1-F7 Durable delete policy: change CASCADE → RESTRICT on object_role→occurrence_segment and occurrence_segment→segment_motion (or prove an equivalent history-preserving design).

Add ALL required tests to the NEW tests/test_s08_a02_r1_c1_semantic_safety.py, and extend the migration/domain/phone test files as needed.

STRICT RULES:
- Only modify: app/persistence/models.py (A02 block ONLY), app/persistence/structural_evidence.py,
  migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py, and the 3 existing A02 test files.
- Create: tests/test_s08_a02_r1_c1_semantic_safety.py + packet LOG/REPORT + evidence under output/s08-a02-t01-r1-c1/.
- Do NOT touch: app/schemas, app/api, app/api/app.py, app/api/deps.py, frontend,
  extraction/grouping/correction production code, S07/S09, the 8 pre-existing head-bump test files, MAIN.
- Do NOT use "best judgement" to widen the write scope. If you need a file outside the allowlist,
  STOP with REPORT.md = BLOCKED and exactly ONE question.
- Single writer only. Do not spawn another code writer. Do not start R2 / S08-A02-T02 / S07 / S09.
- No commit/push/merge/stash/reset/clean/checkout/restore. Do not edit MAIN.
- Migration a0b1c2d3e4f5 (down_revision f7a8b9c0d1e2) may be rewritten — ONLY on fresh temp DBs, never MAIN/user DB, no second head.
- No mock/stub/fake data to satisfy tests. Real SQLite/FK/migration paths in isolated temp DBs.
- MOTIONFORGE_DATABASE_URL UNSET, -p no:cacheprovider, shallow basetemps under C:/Users/Admin/AppData/Local/Temp/s08a02t01r1c1-*.
- Run the full §10 validation order (20 steps); paste verbatim commands + real counts; run the fresh 7/7 quality baseline.
- Do NOT weaken/delete old tests; do NOT adjust expected results to match wrong code.

STOP CONDITION:
When TASK.md requirements pass and REPORT.md is SUBMITTED, exit. Manager then verifies independently;
final C1 manager state is MANAGER_VERIFIED_FOR_OVERNIGHT_CONTINUATION_PENDING_CODEX_REVIEW (or BLOCKED after ≤2 correction cycles).
