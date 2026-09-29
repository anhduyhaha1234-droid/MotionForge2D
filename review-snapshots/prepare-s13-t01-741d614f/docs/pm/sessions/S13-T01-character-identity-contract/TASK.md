# Task S13-T01: Character Identity Profile & Stable Reference-Code Prompt Contract

- **Task ID:** `S13-T01`
- **Epic:** `E09` — Guided 2D Character Generator
- **Sprint:** `S13` — Generator alpha
- **Status:** `BLOCKED_PENDING_E04` (Status: BLOCKED_PENDING_E04)
- **Gate:** Mandatory 7/7 quality baseline before advance (when activated)
- **Depends on:** `E04` (S06 Character Library `APPROVED`) — **NOT yet approved**; this packet is preparation-only and must not be activated until the gate is released.
- **Owner:** Hermes (future session; worktree `s13-t01`)
- **Packet prepared by:** preparation session `20260804_165427_dd8231` (worktree `prepare-s13-t01`), planning/documentation only — no runtime code, schema, migration, API, UI, provider, image generation or tests were implemented.

---

## User outcome

1. The user uploads one clean reference image of a simple 2D character (initially stick-figure / doodle-like, e.g. full-body front or three-quarter, clean background, no occluded head/hands/feet).
2. MotionForge derives a **canonical identity profile** and a **stable reference-code prompt template** so the S13 generator can produce the required multi-view/pose character pack for later compositing into video.
3. Every generated view depicts the **exact same character**. Identity drift — redesign, changed colors, proportions, face, line weight, clothing, accessories, or silhouette — is unacceptable.
4. The system **never silently publishes** an uncertain/incorrect result. Generation may propose candidates, but validation plus **explicit human approval** is mandatory before an immutable Pack Version is published.

## Why now

- The roadmap places `E09` (Generator) after `E04` (Character Library) by default so generator work never blocks the core reskin value (ROADMAP "Task activation rules").
- `S13-T01` depends on `E04`. `E04`/`S06` is **not yet APPROVED** (S06-T05 still `IN_PROGRESS`; roadmap still lists S06-T01..T05 `PLANNED`).
- Per `SESSION_PROTOCOL` §7, a task may only build on approved outputs; unapproved dependencies are treated as non-existent. Preparing the packet now is safe because it is **planning/documentation only** and changes nothing in runtime, schema, or production data.
- The identity contract is the foundation every downstream S13 task (provider adapter, generation job, validator, UI, regeneration, publish) consumes. Freezing it before implementation prevents rework.

## Required reading (before any work in the activated session)

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/ROADMAP.md` (Epic E09, Sprint S13, Sprint S06, activation rules)
3. `docs/PRODUCT_REQUIREMENTS_V2.md` (§5 Character Library, §6 Character Generator)
4. `docs/MASTER_PLAN_V1.md` (§5.1B Character Library, §5.1C Character Generator)
5. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
6. `docs/architecture/DURABLE_JOB_CONTRACT.md`
7. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`
8. `app/persistence/artifacts.py` (ManagedRoot: containment, atomic write, SHA-256, Trash)
9. `app/persistence/models.py` (`CORE_POSE_SLOTS`, `Artifact`, `Character`, `CharacterPackVersion`, `CharacterAsset`)
10. `app/persistence/characters.py` (S06-T01 repository/service: CAS revision, publish gate, immutability)
11. `app/workflow/character_validator.py` (S06-T03 validator: slot completeness, integrity, RGBA/min-resolution/aspect)
12. `app/workflow/character_preset_importer.py` (S06-T02 importer: managed copy, no source mutation)
13. `app/api/schemas/characters.py` + `app/api/routes/durable_characters.py` (S06-T01 API contract)
14. `docs/pm/sessions/S06-T01-character-library/`, `S06-T02-preset-importer/`, `S06-T03-pose-validation/`, `S06-T05-pack-publish-ux/` (approved session packets)
15. External reference (read-only): `https://docs.google.com/document/d/1ym5YJonF5Am1v7KibaR2HuVAS1oxi52N8K-0RBCIu44/edit?usp=sharing` — tab **"Prompt tham khảo"** (reference-sheet prompt pattern; see §2, §7)

## Optional evidence

- `frontend/src/app/(app)/characters/page.tsx` + `frontend/src/components/PresetManager.tsx` — only when the S13 UI tasks (T05) raise a question about pack presentation.
- `docs/architecture/UI_UX_DESIGN_STANDARD.md` — only for UI-related acceptance criteria (T05..T07).
- `presets/` directory — only to understand legacy pose asset naming; never as generation input.
- `tests/test_character_validator.py`, `tests/test_character_domain.py`, `tests/test_character_preset_importer.py` — only to confirm S06 validator semantics (do not modify).

## Allowed write scope (activated session)

- `docs/architecture/CHARACTER_IDENTITY_CONTRACT.md` (new — primary deliverable; the full version of §1–§10 below)
- `docs/architecture/PROMPT_TEMPLATE_REFERENCE_CODE.md` (new — canonical template + provenance metadata schema)
- `docs/architecture/CHARACTER_GENERATOR_EVALUATION.md` (new — golden dataset + calibration plan)
- `docs/pm/sessions/S13-T01-character-identity-contract/REPORT.md`
- `docs/pm/sessions/S13-T01-character-identity-contract/LOG.md`

## Forbidden scope (activated session)

- `app/`, `migrations/`, `frontend/`, `tests/` runtime code, schemas, migrations, APIs, UI, provider adapters, image generation.
- `channels.json`, `data/`, `presets/`, user files — never read for mutation, never written.
- PRD, Master Plan, ROADMAP and any other task's contract.
- Running generation or mutating production data.
- Commit/push.

---

# Contract Specification (prepared; to be finalized as `docs/architecture/CHARACTER_IDENTITY_CONTRACT.md`)

Each of the ten parts below carries **binary acceptance criteria (AC)**. In the activated session, every AC must be verifiable by reading the contract document and running static checks — never by invoking a generator.

## 1. Canonical Identity Profile (extracted from the reference)

The contract must define a versioned, machine-readable identity profile derived from the normalized reference image and **confirmed by the user** before generation. It must include, at minimum:

| Field | Extraction rule (proposal) | Tolerance / storage |
|---|---|---|
| `silhouette` | Binary mask + contour signature (normalized radial distance or Hu moments) from the background-removed reference | Store mask artifact + signature vector |
| `topology` | Enumeration of body parts (head, torso, 2 arms, 2 legs, …) and expected limb count; `symmetry` flag (symmetric/asymmetric) | Exact count; no extra/missing limbs allowed |
| `head_body_ratio` | Head height / total body height, head width/height, eye-line height, shoulder/hip width ratios | Ranges with tolerance (±%) |
| `facial_landmarks` | Normalized eye size/position, brow shape, mouth position relative to head box | Geometry set + tolerances |
| `palette` | Dominant color clusters (k=4..6) with hex values; explicit signature color (e.g. `#8B5E3C`) | Per-color ΔE tolerance; forbidden colors |
| `outline` | Stroke width (px relative to canvas), stroke color, sketchiness level | Range + style enum |
| `appearance` | Clothing/accessories enumeration (e.g. tunic, bare feet, wooden hoe, wheat stalk) | Exact list; additions forbidden |
| `signature_marks` | Distinctive marks/props that must survive every view | List; any drift = REJECTED |
| `forbidden_changes` | Negative list: no redesign, no changed colors/proportions/face/line weight/clothing/accessories/silhouette; no extra limbs; no text/watermark | Machine-checkable where possible |

**ACs (1):**
- [ ] AC1.1 Profile schema is versioned and JSON-serializable; every field has an explicit extraction rule and tolerance.
- [ ] AC1.2 The profile records the normalized reference artifact (SHA-256) and the profile hash it was derived from.
- [ ] AC1.3 A user-confirmation step is defined and recorded (who/when/revision) before the profile is treated as canonical.
- [ ] AC1.4 Forbidden changes are enumerated and mapped to the gates in §4 where mechanically checkable.

## 2. Required Output Slots (reconciled with the pack contract)

The S06 pack contract fixes `CORE_POSE_SLOTS = ("front", "three_quarter", "side", "back", "sitting", "walking")` (`app/persistence/models.py`) and the publish gate requires **all six** (`character_validator.py`, `CharacterRepository.publish_pack_version`). The reference-sheet pattern (Google Doc, "Prompt tham khảo": full-body front/side/back; head turnaround front/three-quarter/side; 4 expression panels; signature prop close-up) adds review aids and optional slots. **No conflicting schema may be invented.**

| Slot | Source | Required? | Pack schema impact |
|---|---|---|---|
| `front` | Core pack | **REQUIRED** | Existing pose_slot |
| `three_quarter` | Core pack | **REQUIRED** | Existing pose_slot |
| `side` | Core pack | **REQUIRED** | Existing pose_slot |
| `back` | Core pack | **REQUIRED** | Existing pose_slot |
| `sitting` | Core pack | **REQUIRED** | Existing pose_slot |
| `walking` | Core pack | **REQUIRED** | Existing pose_slot |
| `head_front`, `head_three_quarter`, `head_side` | Reference sheet (head turnaround) | OPTIONAL extension | Additive `pose_slot` strings; never blocks publish |
| `expression_*` (e.g. tired, strained, anxious, blank) | Reference sheet (expression panels) | OPTIONAL extension | Additive; never blocks publish |
| `signature_prop` | Reference sheet (prop close-up) | OPTIONAL extension | Additive; never blocks publish |
| Reference sheet / contact sheet (multi-panel image) | Reference sheet | REVIEW AID only | Never a pack asset; for design-direction approval (PRD §6.4) |

**ACs (2):**
- [ ] AC2.1 The six core slots remain REQUIRED and unchanged; optional slots are strictly additive `pose_slot` values.
- [ ] AC2.2 The publish gate semantics (all required slots attached, ready artifacts, valid) are preserved; optional slots can never block or alter publish.
- [ ] AC2.3 The reference/contact sheet is explicitly a review artifact, never a required pack asset.
- [ ] AC2.4 Required vs optional is marked per slot with a binary table.

## 3. Deterministic Generation Pipeline Proposal

Contract-only proposal; **no provider is approved in this task** (provider adapter is S13-T02). Stages with I/O contracts:

1. **Reference normalization** — decode → strip EXIF → background removal (SAM/OpenCV-class preprocessing per PRD §6.6) → transparent RGBA canvas → center + normalize scale → record SHA-256 of the normalized reference.
2. **Canonical profile extraction** — compute the §1 profile; require user confirmation.
3. **Pose-conditioned generation** — per slot, generate candidates from the **same normalized reference + same seed + same profile + pose-only variable**; the reference/seed/profile/template-version tuple is the identity anchor.
4. **Per-slot candidate generation** — N candidates per slot (N configurable, default 3–4); each candidate records full provenance (§7).
5. **Validation** — technical + identity gates (§4); verdict per slot (§5).
6. **Human review** — per-slot approve/regenerate (S13-T05/T06); design-direction approval on the contact sheet first (PRD §6.4).
7. **Immutable publish** — S06 publish gate (all required slots pass or explicit human-accepted fallback) → `PackVersion` immutable (S13-T07, S06-T05 semantics).

**ACs (3):**
- [ ] AC3.1 All seven stages are enumerated with input/output artifact types and the owning contract (§4–§7, S01 artifacts, S02 jobs).
- [ ] AC3.2 Determinism is specified: same (reference, seed, profile, template version) ⇒ same candidates; verified in evaluation (§6).
- [ ] AC3.3 No provider is named or required; the adapter boundary owned by S13-T02 is explicit.
- [ ] AC3.4 Generation runs as a durable job (S02 contract) writing only managed artifacts (S01 contract); no synchronous generation inside a request/UI.

## 4. Identity Consistency Gates (stronger than prompts alone)

Gates are **binary per check**; automated metrics are **advisory unless calibrated** (see §6). The contract must define, for each gate: input, algorithm family, hard vs advisory, and default threshold:

- **Transparent-pixel validity** — RGBA present; background alpha=0; subject opaque or valid anti-aliased edge (hard).
- **Image integrity / SHA / size / resolution** — SHA-256 matches registered artifact, size matches, min edge ≥ 512px, aspect ≤ 4:1 (hard; matches `character_validator.py` defaults).
- **Silhouette overlap** — IoU/Dice of generated vs reference normalized silhouette (advisory; threshold after calibration).
- **Perceptual / embedding similarity** — feature-embedding cosine (e.g. DINO/CLIP-class) between reference and each panel and **across panels** (advisory).
- **Palette distance** — mean ΔE / histogram distance within profile tolerances; forbidden-color detection (advisory; hard when a forbidden color appears).
- **Landmark / proportion checks** — facial landmarks and head/body ratios inside profile tolerances (advisory; hard when outside hard bounds).
- **Topology / extra-limb detection** — limb count via skeleton/connected-components; extra/missing limb heuristic (hard when count mismatches profile).
- **Line-weight / style checks** — stroke-width distribution, edge density, flat-color check (no gradients/shadows/textures) (advisory).
- **Cross-view consistency** — pairwise similarity of all panels against the same profile (not merely against the reference) (advisory).
- **Uncertainty thresholds** — any near-boundary or low-confidence metric forces `REVIEW_REQUIRED` instead of `PASS` (hard policy).

**ACs (4):**
- [ ] AC4.1 Every gate lists input, algorithm family, hard/advisory classification, and default threshold.
- [ ] AC4.2 The contract states that automated metrics are advisory unless calibrated and **makes no claim of zero error**.
- [ ] AC4.3 Fail-closed default: uncertainty or near-boundary ⇒ `REVIEW_REQUIRED`, never silent `PASS`.
- [ ] AC4.4 Calibration requirements (§6) are referenced, not deferred silently.

## 5. Fail-Closed Decision Model

Per-slot verdicts and pack rules:

| Verdict | Meaning | Publish effect |
|---|---|---|
| `PASS` | All hard gates pass AND no advisory metric below threshold AND user approved | Slot may contribute to a publishable pack |
| `REVIEW_REQUIRED` | Any advisory metric uncertain / near-boundary, or user must decide | Slot is not publishable; must be reviewed/regenerated |
| `REJECTED` | Any hard gate fails (integrity, transparency, topology, missing slot) | Slot is not publishable; must be regenerated |

- A pack is publishable **only** when every required slot is `PASS` (or the user explicitly accepts a documented fallback per PRD §6.5) and the user approves the pack. Incomplete or uncertain packs **cannot publish**.
- **Regeneration affects only one slot** and preserves all approved slots; approved slots are immutable between regeneration rounds; regeneration bumps the candidate/provenance version but never mutates a published `PackVersion`.
- Explicit user approval is recorded with identity/revision/timestamp and is the final authority (PRD §6.7 "approval của user là authority cuối").

**ACs (5):**
- [ ] AC5.1 State machine per slot (candidate → PASS/REVIEW_REQUIRED/REJECTED) and per pack (publishable/not) is defined with exact transitions.
- [ ] AC5.2 Publish is blocked unless every required slot is `PASS` or human-accepted fallback; no silent publish path exists.
- [ ] AC5.3 Regeneration scope is single-slot; approved slots are preserved and immutable during regeneration.
- [ ] AC5.4 Human approval is recorded and required before any immutable publish.

## 6. Golden Dataset and Evaluation Plan

- **Dataset:** 20–40 simple stick/doodle characters, each with one clean reference (front or three-quarter) and a human-approved ground-truth 6-slot pack (plus optional head/expression variants where available).
- **Controlled variations:** pose variety (sitting/walking), viewpoint (side/back), scale, background cleanliness, line weight (thin/thick), flat palette variants.
- **Negative identity-drift examples:** recolored palette, resized/replaced head, changed outline weight, extra limb, changed/missing prop, anime-style, 3D/photoreal — each labeled `DRIFT`.
- **Metric calibration:** for every advisory metric, compute score distributions over positive and negative sets and select thresholds; the calibration procedure must be recorded in `CHARACTER_GENERATOR_EVALUATION.md`.
- **False-accept priority:** the primary error to minimize is **false-accept** (a drifted panel passes); evaluation must report false-accept rate explicitly and thresholds must be set conservatively until evidence shows otherwise.
- **Repeatability:** same (reference, seed, profile, template version) ⇒ identical output; run as a determinism check in evaluation.
- **Regression evidence:** evaluation runs in a golden job; per-metric table + pass/fail counts recorded; any change to the prompt template or validator gates is gated on regression results.

**ACs (6):**
- [ ] AC6.1 Dataset spec enumerates composition, variation axes, and the negative drift set.
- [ ] AC6.2 Calibration procedure per advisory metric is defined.
- [ ] AC6.3 False-accept priority and explicit false-accept rate reporting are required.
- [ ] AC6.4 Repeatability and regression-evidence procedures are defined.

## 7. Stable Prompt / Reference-Code Template

- **Positive identity invariants:** a fixed identity block (design, palette with hex values, proportions, outline, face, signature marks) that is **byte-identical across all slots** of one pack.
- **Pose-only variables:** the only variable part (pose description, camera, per-panel layout for the contact sheet).
- **Negative constraints:** fixed negative list (no redesign between panels, no photorealism, no 3D, no realistic face, no anime, no extra limbs/fingers, no text/labels/numbers/watermark, no busy background, no gradients/shadows/textures).
- **Versioning:** template schema version field; every candidate records `template_version`.
- **Provider-neutral fields:** fields must not name provider-specific nodes/params; the S13-T02 adapter maps fields to the provider.
- **Seed / model provenance:** seed, model id, adapter version, sampler/settings recorded per candidate.
- **Reproducibility metadata:** full prompt string, profile JSON hash, reference image hash, seed, model, template version stored with each candidate/asset so the output is reproducible from metadata alone.
- **Reference-sheet structure (from the Google Doc pattern):** full-body front/side/back, head turnaround front/three-quarter/side, expression panels, signature prop close-up, on pure white with a thin light-grey grid — used as the design-direction contact sheet and as the skeleton for optional extension slots.

**ACs (7):**
- [ ] AC7.1 Template defines the fixed/variable split explicitly; pose is the only variable across slots.
- [ ] AC7.2 Mandatory provenance metadata schema (reference hash, profile hash, template version, seed, model, full prompt) is defined.
- [ ] AC7.3 Template is provider-neutral; adapter mapping is delegated to S13-T02.
- [ ] AC7.4 A complete sample template (based on the @FARMER reference-sheet structure) is included in `PROMPT_TEMPLATE_REFERENCE_CODE.md`.

## 8. Security / Privacy / Data Policy

- **Managed storage only:** uploaded references and all generated assets live under the managed root (`ManagedRoot`); containment, atomic writes, SHA-256 registration, and Trash semantics follow `MANAGED_ARTIFACT_CONTRACT.md`. Nothing is written outside the managed root.
- **No training / no reuse without authorization:** user references are never sent to training endpoints or reused for other users; provider calls (once a provider is approved in S13-T02) are explicit, logged, and subject to this policy.
- **Retention:** drafts vs published assets have defined lifecycle; user can delete the reference image after profile extraction (explicit choice); deletion uses Trash + restore semantics (S01).
- **Audit:** every candidate records provenance (§7); a user approval log records identity/revision/timestamp.
- **Local-first:** no cloud storage in V1 unless explicitly approved by the user.

**ACs (8):**
- [ ] AC8.1 All asset writes are specified to go through `ManagedRoot` (containment enforced).
- [ ] AC8.2 A no-training/no-reuse-without-authorization clause is explicit and covers provider calls.
- [ ] AC8.3 Retention/deletion rules and the audit fields are defined.
- [ ] AC8.4 Local-first default is stated.

## 9. Dependencies and Task Split (S13-T01..T08)

| Task | Outcome | Depends on | Owns |
|---|---|---|---|
| S13-T01 | Character Profile and stable reference-code prompt contract | E04 | `CHARACTER_IDENTITY_CONTRACT.md` + template + evaluation plan (this task) |
| S13-T02 | ComfyUI/provider adapter with capability and failure contracts | S13-T01 | Adapter code, capability/failure contract |
| S13-T03 | Pose-conditioned six-panel generation job | S13-T02, E01 | Generation job (durable) |
| S13-T04 | Identity/style/pose validation and panel status | S13-T03 | Validator implementation + panel status API |
| S13-T05 | Guided upload→profile→generate→review UI | S13-T04 | UI flow |
| S13-T06 | Regenerate one panel and preserve approved panels | S13-T05 | Regeneration scope + preservation |
| S13-T07 | Publish complete approved output as immutable Pack Version | S13-T06 | Publish UX + immutability |
| S13-T08 | Scenario J quality/performance benchmark report | S13-T07 | Benchmark evidence |

The contract, provider adapter, generation job, validator, UI, regeneration and publish are **separate tasks**; none may be collapsed into another. Downstream tasks reference the approved upstream contract only (SESSION_PROTOCOL §7).

**ACs (9):**
- [ ] AC9.1 The split table mirrors the ROADMAP S13 rows and dependency edges.
- [ ] AC9.2 No single task combines contract + adapter + generation + validator + UI + regeneration + publish.
- [ ] AC9.3 Each downstream task points to the approved upstream contract it inherits.
- [ ] AC9.4 Epic exit is preserved: generator failure cannot block manual library usage; only complete reviewed packs publish.

## 10. Explicit Limitations

- **Exact identity cannot be guaranteed solely by generative prompting.** Generative models can drift even with strong prompts.
- Controls needed to approach production reliability: profile conditioning on the same reference + seed + profile, multi-gate validation (§4), calibrated thresholds (§6), fail-closed decision model (§5), single-slot regeneration (§5), and the mandatory human approval boundary (§5).
- The human approval boundary is explicit: the user is the final authority; the system never silently publishes.
- The contract claims no zero-error guarantee; automated metrics are advisory until calibrated.

**ACs (10):**
- [ ] AC10.1 The limitations section states that exact identity cannot be guaranteed by prompting alone.
- [ ] AC10.2 The controls needed to approach production reliability are enumerated.
- [ ] AC10.3 The human approval boundary and no-silent-publish rule are explicit.
- [ ] AC10.4 No language overclaims zero error or calibrated accuracy without evidence.

---

## In scope

- The ten-part contract above, finalizable as `docs/architecture/CHARACTER_IDENTITY_CONTRACT.md`.
- `docs/architecture/PROMPT_TEMPLATE_REFERENCE_CODE.md` (template + provenance metadata schema + sample).
- `docs/architecture/CHARACTER_GENERATOR_EVALUATION.md` (golden dataset + calibration plan).
- Static documentation checks only (file existence, schema presence, cross-references, `git diff --check`).

## Out of scope

- Any provider integration, generation, background removal, image I/O, or runtime execution.
- Character schema changes beyond documenting additive optional `pose_slot` values.
- S13-T02..T08 implementation work.

## Implementation constraints

- No runtime code, schema, migration, API, UI, provider, image generation, or tests (this task is contract-only).
- No commit/push; preserve `channels.json`, `data/`, `presets/` and all user files byte-for-byte.
- Automated metrics are advisory unless calibrated; the contract must not claim zero error.
- All documentation follows the SESSION_PROTOCOL write-scope rules.

## Mandatory downstream implementation invariants

- Identity and pack are separate aggregates: identity invariants cannot be silently
  rewritten by regenerating or publishing a pose pack; projects pin an immutable pack
  version.
- Candidate lifecycle is explicit per slot: `GENERATING`, `REVIEW_REQUIRED`, `REJECTED`,
  `APPROVED`, `SUPERSEDED`. Single-slot regeneration preserves all other approved slots.
- Only pose/camera fields vary across generation calls; reference hash, profile hash,
  fixed identity prompt block and template version remain identical.
- Compositing readiness is part of acceptance: consistent canvas, scale, bounding box,
  facing direction and ground/contact anchor; no crop or unexplained cross-slot jump.
- The review UI must support reference-vs-candidate zoom and overlay/blink/wipe,
  actionable validation reasons, candidate history and explicit approval.
- V1 support is restricted to simple flat-color stick/doodle characters with clear
  outlines and standard two-arm/two-leg topology until golden evidence approves more
  complex styles.
- Golden evaluation uses 20-40 human-approved characters and reports false-accept rate,
  manual-review rate, regenerations per accepted pack, deterministic repeatability,
  latency and cost. False accepts have the highest severity.
- Provider/model/adapter version, seed, final prompt/settings, reference/profile hashes,
  template version and approval audit fields are mandatory provenance; missing
  provenance blocks publish.

## Acceptance criteria (binary — verified by static checks)

- [ ] AC-A TASK/START_PROMPT/LOG/REPORT/PM_REVIEW packet exists under `docs/pm/sessions/S13-T01-character-identity-contract/` with correct statuses (BLOCKED_PENDING_E04 / NOT_STARTED / PENDING).
- [ ] AC-B `docs/architecture/CHARACTER_IDENTITY_CONTRACT.md` contains all ten sections with binary ACs 1–10 above.
- [ ] AC-C `docs/architecture/PROMPT_TEMPLATE_REFERENCE_CODE.md` contains fixed/variable split, negative constraints, versioning, provider-neutral fields, provenance metadata and a complete sample.
- [ ] AC-D `docs/architecture/CHARACTER_GENERATOR_EVALUATION.md` contains dataset spec, drift negatives, calibration procedure, false-accept priority, repeatability and regression evidence format.
- [ ] AC-E No runtime/schema/migration/API/UI/provider/test files changed; `git status` delta is documentation-only; `channels.json` and `data/` untouched (SHA-256 unchanged).
- [ ] AC-F Static checks pass (`git diff --check`, markdown presence, cross-reference grep).

## Required validation

```powershell
# static documentation checks only — no generation, no runtime
git status --short
git diff --check
rg -n "Status: BLOCKED_PENDING_E04|Status: NOT_STARTED|Decision: PENDING" docs/pm/sessions/S13-T01-character-identity-contract/
rg -n "^## [1-9]|^## 10\." docs/architecture/CHARACTER_IDENTITY_CONTRACT.md
sha256sum channels.json
```

## Required evidence

- Test/validation commands and their real output (LOG.md).
- List of files changed (documentation only).
- `channels.json` SHA-256 before/after identical.
- The preparation report `output/S13_T01_PREPARATION_REPORT.md` (Status: SUBMITTED).

## Stop conditions

- E04/S06 not approved — **current state; the task stays BLOCKED_PENDING_E04 and must not start**.
- Need to change the pack schema (core slots) or the publish gate — stop and ask PM.
- Need to run generation or touch production data — stop.
- Requirement conflict or acceptance criteria not verifiable — stop and report `BLOCKED`.
