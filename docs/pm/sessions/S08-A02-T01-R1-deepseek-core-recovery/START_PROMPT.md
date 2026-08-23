You are the ONLY code writer for MotionForge2D recovery task S08-A02-T01-R1 (DeepSeek Core Recovery).

MANDATORY MODEL CONFIGURATION:
- Provider: custom
- Model: ocg/deepseek-v4-flash
- Reasoning: max
- Do NOT switch model/provider/fallback. If the runtime reports a different model/provider or rejects this model, STOP with REPORT.md = BLOCKED and paste the exact error.
- Record the actual Hermes session ID, the actual displayed model ID/name, provider and reasoning in REPORT.md.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration
HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (do NOT modify, ever)

TASK:
Read FULLY and execute ONLY:
docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/TASK.md

Also read (context only — do not modify):
- docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md (original contract)
- docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/REPORT.md (ABORTED_UNTRUSTED_PARTIAL_OUTPUT incident)

REPORT/LOG:
- Append to docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/LOG.md
- Fill docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/REPORT.md to SUBMITTED

R1 SCOPE (RECOVERY — TRUST NOTHING IN THE DRAFT):
- AUDIT and fix the domain model (app/persistence/models.py A02 block ONLY).
- REWRITE the draft migration migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py to match the corrected contract (down_revision=f7a8b9c0d1e2).
- REWRITE the draft repository app/persistence/structural_evidence.py.
- Write tests: tests/test_s08_a02_structural_evidence_migration.py, tests/test_s08_a02_structural_evidence_domain.py, tests/test_s08_a02_phone_interaction_scenario.py.
- Close EVERY Codex finding F1..F11 with real code + a test that fails on the draft. See TASK.md §4 — normative.
- The current draft code is UNTRUSTED. Do not treat it as submitted. Audit each invariant independently.

STRICT RULES:
- R1 does NOT implement schema/API/router (that is R2). No app/schemas/structural_evidence.py, no app/api/routes/structural_evidence.py, no app/api/app.py changes.
- Do not modify non-A02 code in models.py (S05–A01 sections stay byte-identical).
- Single writer only. Do not spawn another code writer.
- Do not start R2, S08-A02-T02, S07, or S09.
- No commit/push/merge/stash/reset/clean/checkout/restore.
- Do not edit MAIN. Never run alembic against MAIN or a user DB — temp DBs only.
- Do not write outside the R1 allowlist. If needed, STOP BLOCKED with exactly one question.
- No mock/stub/fake data to satisfy tests. Real SQLite/FK/migration paths in isolated temp DBs.
- Validate with MOTIONFORGE_DATABASE_URL UNSET and -p no:cacheprovider, shallow basetemps under C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-*.
- Run the full §7 validation order; paste verbatim commands + real counts into LOG.md/REPORT.md; run the fresh 7/7 quality baseline.

STOP CONDITION:
When TASK.md requirements pass and REPORT.md is SUBMITTED, exit. Manager will independently verify, then stop at MANAGER_VERIFIED_PENDING_CODEX_REVIEW.
