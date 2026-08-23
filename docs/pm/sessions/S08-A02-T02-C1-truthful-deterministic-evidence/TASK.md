# S08-A02-T02-C1 — Truthful Evidence + Determinism Correction (Codex CHANGES_REQUESTED)

Narrow correction responding to Codex CHANGES_REQUESTED on T02 extraction evidence wiring.  Make
evidence TRUTHFUL (no fabricated synthetic observations outside QA, no silent clamping, no silent
defaults, fail-closed on missing/malformed/invalid input) and DETERMINISTIC across Python processes.

## 1. Mandatory model configuration (BLOCKED_MODEL on mismatch)
- Provider: `muse` (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: `ocg/muse-spark-1.2-contributor` (verified; meta/... 401 — do NOT use).
- Reasoning: `max`. No fallback. Mismatch → STOP REPORT.md = BLOCKED_MODEL_ROUTE.
- Record Hermes session ID / model / provider / reasoning / fallback in LOG.md + REPORT.md BEFORE any change.

## 2. Worktree guard
- ONLY `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`.
- MAIN protected. Intentional dirty (~206). NEVER reset/clean/stash/restore/checkout/commit/push/merge.
- MOTIONFORGE_DATABASE_URL UNSET; temp isolated SQLite only; `-p no:cacheprovider`; shallow unique `--basetemp`.

## 3. Exact write allowlist (do NOT touch any Lane A file)
- `app/services/object_extraction.py`
- `app/schemas/object_extraction.py`
- `app/api/routes/object_extraction.py`
- `tests/test_object_extraction.py`
- `tests/test_object_extraction_api.py`
- `tests/test_object_extraction_production_wiring.py`
- `docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/`
- `output/s08-a02-t02-c1/`

FORBIDDEN: app/persistence/structural_evidence.py, app/persistence/object_intelligence.py,
app/persistence/models.py, tests/test_s08_a02_c3_corrections.py, other persistence files, any
other file, migrations, MAIN, commit/push/merge, data/motionforge.db, deleting/weakening tests.
If a persistence helper change is genuinely required → STOP BLOCKED_SCOPE (file, reason, AC).

## 4. Confirmed blockers (current code, pre-writer)
1. `hash(seg_id)` in motion tx derivation (~app/services/object_extraction.py:2339) — NOT deterministic
   across Python processes (PYTHONHASHSEED randomizes str hash). Fix with stable digest/uuid5.
2. Synthetic camera/object motion created UNCONDITIONALLY (~2320-2366) for ANY provider.
3. Synthetic occlusion/contact created UNCONDITIONALLY (~late 2366-2450, per scene with ≥2 segments).
4. Production path also uses `algorithm="deterministic-layout"` (~2323, 2355, and elsewhere) — must use
   actual provider algorithm in production.
5. Missing bbox fabricated as fixed bbox (defaults to {x,y,w,h} and clamps) — must fail closed / omit
   prompt evidence, NEVER fabricate 10/10/50/50.
6. Confidence out-of-range silently clamped/defaulted to 0.7 (~2264 `cand.get("confidence", 0.7)`) —
   must fail closed; no silent clamp/default.
7. Broad exception + operator-precedence bug: `if isinstance(exc, X) and "already bound" in str(exc) or "already bound" in str(exc)` (~2333, 2364, 2405, 2445) — because `and` binds tighter than `or`,
   ANY exception containing "already bound" is swallowed even if it is the WRONG exception type.
8. "Independent determinism" test actually only replays the same job/process.
9. "Production no-false-evidence" test actually submits provider `deterministic` + QA mode.

## 5. Requirements (normative)
1. Replace Python `hash()` with stable digest / UUID-derived calculation (e.g. `uuid.uuid5` or
   `hashlib.sha256(...).digest()` derived) for all derived ids/transforms.
2. Deterministic evidence byte-identical between processes with DIFFERENT PYTHONHASHSEED.
3. ONLY deterministic QA provider + QA mode may create synthetic motion/contact/occlusion.
4. Production provider:
   - writes contact/occlusion ONLY if the provider truly returns that evidence (presence-based);
   - never infers contact/occlusion merely because two segments exist;
   - never fabricate fake sparse-flow reference;
   - if no estimator/evidence, write NO fake observation (motion only when there is a real transform).
5. QA synthetic records carry explicit provenance: provider=deterministic, qa_mode=true,
   synthetic/test-adapter marker.
6. Production segments use ACTUAL provider algorithm (no deterministic-layout in production).
7. Missing/malformed bbox → fail closed or omit prompt evidence; NEVER fabricate a bbox.
8. NaN/Inf/out-of-range confidence → fail closed; no clamp/default silently.
9. Remove broad exception catches (BLE001 where they swallow real errors).
10. Handle ONLY the typed idempotency conflict (correct exception type) — other exceptions propagate.
11. Parentheses explicit for conditions (`(... and ...) or (...)` correct order); no ambiguous precedence.
12. Keep publication atomic and idempotent (rollback all on failure; replay returns existing row).

## 6. Required tests (in the allowed test files)
- Cross-process determinism: two fresh Python subprocesses with DIFFERENT PYTHONHASHSEED
  (e.g. `PYTHONHASHSEED=1` and `PYTHONHASHSEED=999`) run the deterministic QA full extraction →
  normalized deterministic motion/evidence byte-identical (compare ids, transforms, prompt/seg JSON,
  mask sha256).
- Production-like publication WITHOUT QA mode:
  - segments from real evidence still saved;
  - NO synthetic motion/contact/occlusion;
  - NO `deterministic-layout` algorithm.
- Deterministic QA mode:
  - synthetic graph created;
  - provenance marked QA/synthetic.
- Missing bbox → fail/omit per contract; NOT bbox 10/10/50/50.
- Invalid confidence: NaN, +Inf, -Inf, >1.0, <0.0 → fail closed, zero partial mutation.
- Exception with text "already bound" but WRONG exception type must NOT be swallowed (propagates).
- Existing replay/idempotency/API tests still pass.

## 7. Required reading
- `app/services/object_extraction.py` FULL (deterministic provider ~876+; production provider;
  motion/edges wiring ~2320-2460; confidence ~2264; bbox handling ~700-770, ~890-930; submit ~2424+)
- `app/schemas/object_extraction.py`, `app/api/routes/object_extraction.py`
- `tests/test_object_extraction.py`, `tests/test_object_extraction_api.py`,
  `tests/test_object_extraction_production_wiring.py`
- `docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/TASK.md` + `REPORT.md` (prior T02)
- `docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/REPORT.md` (known-flaky background)

## 8. Validation (separate logs in NEW evidence dir output/s08-a02-t02-c1/<ts>/)
- New C1 tests; existing object_extraction suite; object_extraction API; production wiring;
  structural migration/domain/API/phone regression (read-only expectations — no file edits).
- Cross-process PYTHONHASHSEED repro (two subprocesses).
- Combined focused (extraction + structural A02) at least twice.
- `python -m ruff check app tests` → 0; `python -m mypy app` → Success; `python -m alembic heads`
  → single a0b1c2d3e4f5; OpenAPI typed requestBody intact.

## 9. Stop conditions
- Do NOT open other tasks/sprints. Do NOT commit/push/merge. Do NOT write MAIN. SUBMITTED only.
- If a persistence-helper change is genuinely required → STOP BLOCKED_SCOPE (file, reason, AC).
