# Start Prompt — Task S13-T01: Character Identity Profile & Stable Reference-Code Prompt Contract

You are the sole planning/documentation writer for Task **S13-T01** in the isolated worktree
`C:\Users\Admin\MotionForge2D-worktrees\s13-t01` (created when this task is activated).

**Status gate:** This task must NOT start while `E04`/`S06` is unapproved. Activation is
authorized only after the PM review marks this packet's dependency `E04` as `APPROVED` and the
task status changes from `BLOCKED_PENDING_E04` to `READY`. If the gate is not released, stop and
report `BLOCKED` — do not begin.

## Mission

Produce the final, production-quality **Character Identity Contract** for MotionForge 2D's guided
2D character generator (Epic E09). This is a **planning/documentation-only** task: do not implement
runtime code, schemas, migrations, APIs, UI, provider adapters, image generation, or tests. Do not
commit or push. Preserve `channels.json`, `data/`, `presets/` and all user files.

## Read first (required)

1. `docs/pm/sessions/S13-T01-character-identity-contract/TASK.md` — this is your task contract; its
   ten-part specification and binary acceptance criteria are binding.
2. `docs/pm/SESSION_PROTOCOL.md`
3. `docs/pm/ROADMAP.md` (Epic E09, Sprint S13, Sprint S06, activation rules)
4. `docs/PRODUCT_REQUIREMENTS_V2.md` (§5 Character Library, §6 Character Generator)
5. `docs/MASTER_PLAN_V1.md` (§5.1B/5.1C)
6. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
7. `docs/architecture/DURABLE_JOB_CONTRACT.md`
8. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`
9. `app/persistence/models.py` (`CORE_POSE_SLOTS`, `Artifact`, `Character*`)
10. `app/persistence/characters.py`, `app/workflow/character_validator.py`,
    `app/workflow/character_preset_importer.py`, `app/schemas/characters.py`,
    `app/api/routes/durable_characters.py` (S06 domain/repository/validator/importer/API)
11. `docs/pm/sessions/S06-T01-character-library/`, `S06-T02-preset-importer/`,
    `S06-T03-pose-validation/`, `S06-T05-pack-publish-ux/` (approved S06 packets)
12. External reference (read-only): `https://docs.google.com/document/d/1ym5YJonF5Am1v7KibaR2HuVAS1oxi52N8K-0RBCIu44/edit?usp=sharing`
    — tab **"Prompt tham khảo"** (reference-sheet prompt pattern: full-body front/side/back, head
    turnaround, expression panels, signature prop, white/grid presentation, and the consistency rule:
    identical head shape, face, outline weight, colors, proportions; do not redesign between panels;
    simple hand-drawn 2D doodle/stick-figure, flat colors, bold outlines; no 3D/photorealism/extra
    limbs/text/watermarks).

## Deliverables (allowed write scope)

1. `docs/architecture/CHARACTER_IDENTITY_CONTRACT.md` — the full ten-part contract:
   1. Canonical Identity Profile (silhouette, topology/limb count, head/body ratios, facial landmark
      geometry, palette with tolerances, outline width/style, clothing/accessories, signature marks,
      forbidden changes).
   2. Required Output Slots reconciled with the S06 six-slot pack contract
      (`front`, `three_quarter`, `side`, `back`, `sitting`, `walking` required; head turnaround,
      expression panels, signature prop optional-additive; reference sheet a review aid only).
   3. Deterministic generation pipeline proposal (normalization/background removal → canonical
      profile → pose-conditioned generation on same reference/seed/profile → per-slot candidates →
      validation → human review → immutable publish). No provider is approved.
   4. Identity consistency gates stronger than prompts (transparent-pixel validity, image
      integrity/SHA/size/resolution, silhouette overlap, perceptual/embedding similarity, palette
      distance, landmark/proportion checks, topology/extra-limb detection, line-weight/style checks,
      cross-view consistency, uncertainty thresholds). Automated metrics are advisory unless
      calibrated; no claim of zero error.
   5. Fail-closed decision model: `PASS` / `REVIEW_REQUIRED` / `REJECTED` per slot; incomplete or
      uncertain packs cannot publish; regeneration affects only one slot and preserves approved
      slots; explicit user approval required.
   6. Golden dataset and evaluation plan for simple stick/doodle characters (controlled variations,
      negative identity-drift examples, metric thresholds to calibrate, false-accept priority,
      repeatability, regression evidence).
   7. Stable prompt/reference-code template (positive identity invariants, pose-only variables,
      negative constraints, versioning, provider-neutral fields, seed/model provenance,
      reproducibility metadata).
   8. Security/privacy/data policy (managed storage only, containment, no training/reuse without
      authorization, retention, audit).
   9. Dependencies and task split for S13-T01..T08 (do not collapse profile contract, provider
      adapter, generation job, validator, UI, regeneration, publish into one task).
   10. Explicit limitations (exact identity cannot be guaranteed by prompting alone; controls to
       approach production reliability; human approval boundary).
   Each part ends with binary acceptance criteria.
2. `docs/architecture/PROMPT_TEMPLATE_REFERENCE_CODE.md` — canonical template with fixed identity
   block / pose-only variables / negative constraints / template version / provider-neutral fields /
   provenance metadata schema / a complete sample modeled on the reference-sheet structure.
3. `docs/architecture/CHARACTER_GENERATOR_EVALUATION.md` — golden dataset spec, drift negatives,
   calibration procedure, false-accept priority, repeatability, regression evidence format.
4. `docs/pm/sessions/S13-T01-character-identity-contract/REPORT.md` (per template, `SUBMITTED`) and
   `LOG.md` (append-only baseline + actions + evidence).

## Forbidden scope

- `app/`, `migrations/`, `frontend/`, `tests/` (no runtime code, schema, migration, API, UI,
  provider, generation, or tests).
- `channels.json`, `data/`, `presets/`, user files (read-only for evidence; never mutate).
- PRD, Master Plan, ROADMAP and other tasks' contracts.
- Running generation or mutating production data. Commit/push.

## Required validation (static only)

```powershell
git status --short
git diff --check
rg -n "^## " docs/architecture/CHARACTER_IDENTITY_CONTRACT.md
sha256sum channels.json
```

Record every command and its real output in `LOG.md`. Leave `REPORT.md` status `SUBMITTED`, not
`APPROVED`. Do not claim approval.
