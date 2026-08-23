You are the ONLY code writer for MotionForge2D correction task S08-A02-T01-C2 (Re-analysis Role Binding, Temporal Dependency, Lineage and Strict API Correction).

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
docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/TASK.md

Also read (context only — do NOT modify, do NOT trust at face value; re-audit current code):
- docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/TASK.md + REPORT.md + LOG.md
- docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/TASK.md + REPORT.md + LOG.md
- docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/REPORT.md
- docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md

REPORT/LOG:
- Append to docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/LOG.md
- Fill docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/REPORT.md to SUBMITTED

C2 SCOPE (close ALL six Codex findings with code + failing-then-passing tests):
- C2-F1 Re-analysis MUST bind a role of the NEW generation: supersede_segment takes target_role_id
  (workflow B), NEVER mutates an existing ObjectRole.source_generation; workflow A keeps prior role;
  target role validated (workspace/project/video/current-generation/kind); target generation ==
  ObjectIntelligenceRepository.current_generation(); producing DISCOVER_OBJECTS job completed + matches.
  TESTS MUST create the new role via ObjectIntelligenceRepository.create_role (or production-equivalent
  API). FORBIDDEN to mutate role.source_generation directly in tests — replace the C1 _advance_generation
  helper accordingly.
- C2-F2 Segment range update must not break child evidence: before CAS update, compute proposed
  frame+ms range, check all bound SegmentMotion / SceneGraphOcclusion(endpoint) /
  SceneGraphContact(endpoint); child range must fit in BOTH dims; violation -> stable SegmentConflictError
  (API 409) + zero mutation (revision/DB byte-identical); cover shrink start/end, frame-only, time-only;
  expansion allowed.
- C2-F3 Explicit manual provenance: workflow A requires confidence_source in {user, manual} AND
  non-empty provenance supplied by caller; never inherit machine provenance when none supplied; old
  source_job_id may remain as extraction source; missing/null/empty provenance -> stable 409/422, zero
  mutation; repo + API tests.
- C2-F4 DB-ENFORCED lineage (not only walker): SQLite+ORM+migration parity for one-predecessor-per-
  successor / one-successor-per-predecessor / no-branch / no-cycle at committed state / one-active-per-
  lineage / concurrent single-winner. UNIQUE(workspace_id, logical_id, lineage_version) alone is NOT
  enough — add real DB-enforced uniqueness for non-null successor relation or an equivalent lifecycle
  design with real SQLite constraints. If the placeholder pattern conflicts, replace with an atomic
  lifecycle; keep active-identity protection; never "walker will detect". Edit migration within the
  SAME revision a0b1c2d3e4f5 (no second head), ORM parity. Raw-SQL corruption tests: two predecessors ->
  DB refuses; duplicate active lineage -> DB refuses; concurrent supersede one winner; rollback no
  orphan/pending row; integrity/FK checks clean.
- C2-F5 Historical API must not mix current: /segments/historical returns ONLY truly historical
  (superseded OR stale generation), never the active current successor; pagination/total after the
  correct filter; logical_id current+history belongs in /segments/{id}/lineage; current-generation
  query sees predecessor as historical but NOT the current successor; current list stays current+active.
- C2-F6 STRICT request DTO + OpenAPI request schemas: ConfigDict(extra="forbid", strict=True) or
  equivalent strict types (JSON "1" must NOT coerce to 1); typed Pydantic request models MUST appear in
  OpenAPI requestBody for EVERY POST/PATCH endpoint (no dict[str, Any] public body); stable 422 for
  NaN/Infinity (never 500) via router-local APIRoute/validation wrapper if needed; OpenAPI tests assert
  concrete schema/$ref per POST/PATCH, not just path existence; tests for unknown fields, NaN/Inf, and
  string->number coercion.

STRICT RULES:
- Allowlist: app/persistence/models.py (A02 block ONLY), app/persistence/structural_evidence.py,
  migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py (same revision, no second head),
  app/schemas/structural_evidence.py, app/api/routes/structural_evidence.py, app/api/app.py (only if
  import/registration needs it), the 5 A02 test files, NEW tests/test_s08_a02_c2_integrity.py,
  packet files, evidence under output/s08-a02-t01-c2/.
- FORBIDDEN: app/persistence/object_intelligence.py production code (unless the manager rules a target
  role cannot be bound via the current API — then STOP BLOCKED with exactly ONE question), frontend,
  A02-T02/S07/S09/renderer/dense flow/video regeneration, other migrations, the 8 head-bump test files,
  MAIN, commit/push/merge/stash/reset/clean/checkout/restore, scripts/quality-baseline.ps1 (run only).
- Single writer only. Do not spawn another code writer. Do not start R2/A02-T02/S07/S09.
- Do NOT weaken/delete old tests; do NOT adjust expected values to pass. If an old test relied on
  coercion C2-F6 forbids, change the test to the correct strict expectation and NOTE it in REPORT.
- No mock/stub/fake data. Real SQLite/FK/migration paths in isolated temp DBs.
- MOTIONFORGE_DATABASE_URL UNSET, -p no:cacheprovider, shallow basetemps under
  C:/Users/Admin/AppData/Local/Temp/s08a02t01c2-*.
- Run the full §9 validation order (18 steps); paste verbatim commands + real counts + raw logs into
  LOG/REPORT/evidence; run the fresh 7/7 quality baseline.
- Timestamps at WRITE TIME, local +07:00 and UTC = local − 7h; never future/estimated.

STOP CONDITION:
When TASK.md requirements pass and REPORT.md is SUBMITTED, exit. Manager then verifies independently
(spot-check C2-F1..F6 incl. no role.source_generation mutation in tests, raw-SQL branch refused,
OpenAPI requestBody $ref, historical no-current-mix). Final C2 manager state =
MANAGER_VERIFIED_PENDING_CODEX_REVIEW; A02-T01 stays NOT APPROVED until Codex. STOP after C2.
