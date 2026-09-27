# R27-05 — Public reference ingest delta (authored artwork → managed artifact → pack branch → cast pin → graph reference)

**Task ID:** MF-TOOL-CONTRACT · **Round:** R27-05 (docs only) · **Status:** `TASK_SUBMITTED` — delta PROPOSED, **no dispatch authority, no S13 activation**
**Tree:** `C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-tool-contract` · **Branch:** `codex/mf-tool-20260923-mf-tool-contract` · **HEAD at writing:** `f0b918b`
**Predecessors (DO NOT rework):** NR05 + NR06 are `APPROVED`-level at `f0b918b` (pure contract/DTO + dependency mapping). This document adds ONE new delta and touches no file they own.
**Normative inputs reused, not re-invented:** `PACK_CAPABILITY_CONTRACT.md` §2.2/§2.3 (`reference_pack_v1`, namespaced reference key, one authority/two branches), `S13_P00_DELTA_MATRIX.md` §5.3/§5.4/§5.5 (storage plan, publish snapshot, one compatibility evaluator with two branches), `MEDIA_ENGINE_CONTRACT.md`, `app/schemas/media_engine.py` (NR05 contract DTOs).

---

## 0. Scope, and the four things this delta explicitly does NOT propose

The reviewer's measured product gap: the **real** extraction provider publishes a segmentation `CANDIDATE_MASK` as PNG colour type 0 / mode `L` (correct for segmentation), and there is **no public route that ingests AUTHORED RGB/RGBA artwork** (character/person appearance) and carries it through managed artifact → version/branch requirement manifest → cast pin → graph reference. The demo chain went green only because a fixture published RGBA.

Rejected by the reviewer, and therefore absent from this delta:

| # | Rejected proposal | Why it is absent here |
|---|---|---|
| 1 | Convert the `L` mask → RGBA and attach it to the six legacy pose slots as "artwork" | §6. The mask stays a mask; `L` is the CORRECT mode for segmentation. This delta never converts a mode. |
| 2 | Multiply one mask into six poses | §6. No synthesis of authored pixels is proposed anywhere. |
| 3 | Redefine `complete` / `status` | §5 row D-4. `complete` = enough slots present; `status` = validation result. They may legitimately disagree; this delta keeps both and reads them read-only (measured today at `app/persistence/characters.py:729`, `:143`). |
| 4 | A second library/cast/job store | §4. Reuse: `character_asset` + `character_pack_version` + `project_cast_mapping`. No new table for references, no new store. |
| 5 | All of S13 as a demo precondition | This delta routes its rows onto the ALREADY-EXISTING S13 task IDs and leaves them `BLOCKED_DEPENDENCY`; nothing is activated. |

Also out of scope: code, tests, migrations, API, UI, S13 activation, push. **Write-set of this round is ONE new doc file** plus evidence under the literal evidence root.

---

## 1. Old path/symbol → new exact path/symbol (measured, not guessed)

Every "exists today" cell below is re-derived from the tree by the probe in §9 (`raw/probe_r27.py`), file-by-file and symbol-by-symbol. Rows marked **NEW** are proposals whose *target* file may be new; a proposal never claims to exist.

| Row | Exists today (measured) | New exact path + symbol (proposed) | Kind |
|---|---|---|---|
| **D-1** | **No public route ingests authored artwork for a character pack.** `app/api/routes/durable_characters.py` (router prefix `/api/v2/characters`, `:45`) exposes only `POST ""` `:49`, `GET ""` `:76`, `GET /{character_id}` `:101`, `PATCH /{character_id}` `:116`, `POST /{character_id}/archive` `:149`, `POST /{character_id}/default-version` `:174`, `POST /{character_id}/versions` `:200`, `GET /{character_id}/versions` `:217`, `POST /versions/{version_id}/assets` `:229`, `POST /versions/{version_id}/publish` `:266`, `GET .../content` `:298`, `GET /versions/{version_id}/validation` `:342`. The only authored-image multipart routes in the whole app are project-scoped: `app/api/routes/projects.py:331` `upload_video` and `app/api/routes/projects.py:1123` `upload_replacement` (`POST /api/projects/{project_id}/objects/{object_id}/replacement`), which stores `objects/<object_id>/replacement.<ext>` under the project workflow and registers **no** `Artifact` row. | **NEW** `app/api/routes/durable_characters.py::ingest_reference_artwork` on **NEW** route `POST /api/v2/characters/versions/{version_id}/reference-artwork` (multipart `file: UploadFile`, form field `reference_key: str`), returning **NEW** `app/schemas/characters.py::ReferenceArtworkData` (`artifact_id`, `sha256`, `size_bytes`, `mime_type`, `width`, `height`, `reference_key`). Handler lives in the EXISTING router — `app/api/app.py` is **not** touched (§2 dependency note). | NEW route on existing file |
| **D-2** | `app/workflow/character_preset_importer.py::CharacterPresetImporter.import_preset` already does the managed-artifact leg: managed write via `ManagedRoot.atomic_write_stream` (`app/persistence/artifacts.py:367`), then `Artifact(kind="image", state="ready", sha256=…, size_bytes=…, mime_type=…)` (`:165`), then `CharacterRepository.attach_asset` (`:180`). It is **not reachable over HTTP** (measured: the only importers of that module are `tests/test_character_preset_importer.py`), it always creates a NEW character + version, and it iterates `CORE_POSE_SLOTS` only. The byte-verification chain that IS public (magic prefilter → FULL Pillow decode → dimension/pixel caps → atomic publish → rollback) lives in `app/api/routes/projects.py::upload_replacement` (`:1123`-…). | **NEW** `app/workflow/character_reference_ingest.py::ingest_reference_artwork(session, storage_root, workspace_id, version_id, reference_key, filename, stream)` — verification chain lifted from `upload_replacement`, managed write + `Artifact` registration lifted from `CharacterPresetImporter.import_preset`, but attaching to an EXISTING draft `CharacterPackVersion` under the namespaced reference key instead of creating a character. Plus **NEW** `app/workflow/character_reference_ingest.py::validate_reference_key`. | NEW file |
| **D-3** | `app/persistence/characters.py::CharacterRepository.attach_asset` (`:496`) accepts ANY `pose_slot` string: `CharacterAsset` (`app/persistence/models.py:1058`) constrains only `length(pose_slot) > 0` and `<= 64` (`ck_character_asset_pose_slot_nonempty`, `ck_character_asset_pose_slot_len`) and uniqueness per version (`uq_character_asset_version_pose_slot`); re-attaching the same key REPLACES the artifact (`:527`-`:534`) and a `published` version is refused (`PackVersionImmutableError`, `:515`). | **Reuse unchanged — zero write.** `PACK_CAPABILITY_CONTRACT.md` §2.3 already fixes the reference key shape (`<view>@<role>`, e.g. `front@character`) inside the EXISTING `character_asset` rows: "no second asset table". Reference pixels therefore ride the already-implemented attach path. | Reuse (no change) |
| **D-4** | The pack branch does not exist yet: `CharacterPackVersion` (`app/persistence/models.py:1017`) has `status`/`validation_json`/`revision` but no `pack_contract_version`, no `requirement_manifest_json`, no `requirement_manifest_sha256`. Publish/validation are single-branch: `CharacterRepository.publish_pack_version` (`app/persistence/characters.py:546`) and `CharacterRepository.validate_pack_version` (`:729`) both call `app/workflow/character_validator.py::validate_character_pack` (`:50`), which hard-codes `CORE_POSE_SLOTS` (`:73`, constant at `app/persistence/models.py:170`) and keeps `complete`/`status` separate (`PackVersionValidationResult`, `:143`). | **Reuse the frozen S13 decision** (`S13_P00_DELTA_MATRIX.md` §5.3): `character_pack_version.pack_contract_version` + `requirement_manifest_json` + `requirement_manifest_sha256` (T01A, MIGRATION OWNER 1 of 3) and the branch-aware validator (T04A/T04C, `app/workflow/character_validator.py`). The ingest route writes the manifest ONCE at ingest-into-draft; the publish path freezes its hash (T01B/T07A). **Exact new symbols are T01A/T01B/T04A/T04C's, as already specified — this delta adds no new persistence symbol.** | Reuse of frozen plan |
| **D-5** | Cast pin ignores any declared branch: `app/persistence/project_cast.py::_evaluate_compatibility_pure` (`:130`) and its `CORE_POSE_SLOTS` completeness check (`:169`); `app/schemas/project_cast.py::CompatibilityEvaluateRequest` (`:153`), `CompatibilityReason` vocabulary. | **Reuse the frozen S13 decision** (`S13_P00_DELTA_MATRIX.md` §5.5): ONE compatibility evaluator, ONE branch point on the pack's declared `pack_contract_version`; `legacy_six_slot_2d` → today's rules incl. `CORE_POSE_SLOTS`; `reference_pack_v1` → the pack's declared/manifest requirements, `CORE_POSE_SLOTS` never required, `incomplete_pack` never emitted for a pose the pack never declared. Pinned by T07A's publish snapshot (`pack_contract_version` + `requirement_manifest_sha256`). | Reuse of frozen plan |
| **D-6** | The graph/engine reference is already id-addressed and path-hostile: `app/schemas/media_engine.py::ReferenceArtifact` (`:578`) = `artifact_id` + 64-hex `sha256`, and a client-supplied `path` raises `CLIENT_ARTIFACT_PATH_REFUSED`; `CastBinding.references: tuple[ReferenceArtifact, ...]` (`:600`, field at `:608`); `independent_references()` (`:252`) counts INDEPENDENT references; `CAPABILITY_REFERENCE_REQUIREMENTS` (`:322`) states the NORMATIVE floor per capability. There is NO authoring route producing such an artifact id for artwork. `app/persistence/models.py::ArtifactOwner.owner_type` (`:632`, CHECK at `:638`) allows only `('channel','project','video_item','scene','artifact')`, and `ObjectRoleArtifact.purpose` (`:1241`, CHECK at `:1263`) allows only `('thumbnail','mask')`. | **No new table, no new purpose, no new owner type.** Authored artwork becomes graph-addressable through (a) `character_asset` (D-3) → `artifact_id` + `sha256`, and (b) the existing `CastBinding.references` tuple built by the cast resolver (T07A/T03C). `ObjectRoleArtifact` keeps `('thumbnail','mask')` exactly as measured — a character reference is **not** a scene role artifact (§6). | Reuse (no change) |
| **D-7** | Mask publication is already real and already separate: `app/services/object_extraction.py::ARTIFACT_PURPOSE_CANDIDATE_MASK = "mask"` (`:200`), artifact rows at `:1926`/`:2026`, purpose check at `:2218`; correction publication writes `Artifact` + `ObjectRoleArtifact` (`app/services/object_correction.py:739`, `:792`, `:800`); content is served by `GET /api/v2/object-intelligence/extraction/{job_id}/artifacts/{artifact_id}/content` (`app/api/routes/object_extraction.py:663`, router prefix measured at `:60`). | **No change proposed.** Documented boundary only (§6): mask purpose/key/colour type stay as measured; the reference branch never consumes a mask as artwork and a mask never satisfies a reference requirement. | Documentation only |

---

## 2. Task/owner + dependency + write-set per row (existing vocabulary only)

Task IDs, dependencies and "current owner" come from the existing S13 P00 task map (`S13_P00_DELTA_MATRIX.md` §2b) and from the existing session registry (`docs/pm/sessions/`, measured to contain the owner directories named below). **No new manager layer, no wildcard write-set, no new sprint vocabulary.**

| Row | Task ID (existing) | Current code owner (measured session dir) | Dependency (C5 edge) | Exclusive write-set (exact paths) |
|---|---|---|---|---|
| D-1 | **S13-T05A** (guided upload → profile flow; row 13 in §2b.1) — write-set **EXTENSION**, see note | `S06-T01-character-library` (`app/api/routes/durable_characters.py`, `app/schemas/characters.py`) | `T01D + T03C + T04A` (unchanged); **does not open before T04A** | `app/api/routes/durable_characters.py`, `app/schemas/characters.py` |
| D-2 | **S13-T05A** (same ID; the workflow half of the ingest) | `S06-T02-preset-importer` (`app/workflow/character_preset_importer.py`) | as D-1 | `app/workflow/character_reference_ingest.py` (**new file**) |
| D-3 | **S13-T01A/T01B** (persistence reused, no change) | `S06-T01-character-library` (`app/persistence/characters.py`, `app/persistence/models.py`) | `T01A -> T01B` | **none — zero-write row** (proves the reuse claim) |
| D-4 | **S13-T01A** (migration owner 1 of 3) + **T01B** (manifest freeze) + **T04A/T04C** (branch-aware validator) | `S06-T01` (`models.py`, `characters.py`) + `S06-T03-pose-validation` (`app/workflow/character_validator.py`) | `T01A -> T01B -> T04A -> T04C` | `app/persistence/models.py`, `app/persistence/characters.py`, `app/workflow/character_validator.py`, `migrations/versions/<live-head-child>_s13_t01a_identity_profile.py` |
| D-5 | **S13-T07A** (pin/ snapshot) with `T07B` consuming it | `S07-T01-project-cast-domain-api` (`app/persistence/project_cast.py`, `app/schemas/project_cast.py`) | `T06A + T04B + T04C` | `app/persistence/project_cast.py`, `app/schemas/project_cast.py` |
| D-6 | **S13-T03C** (request-construction enforcement of `CAPABILITY_REFERENCE_REQUIREMENTS`) + **T07A** | `MF-TOOL-CONTRACT` owns `app/schemas/media_engine.py` (this lane, NR05) | `T01D + T02A + T03B + T04A` | **none in this round — zero-write row** (DTOs already exist and are reused as-is) |
| D-7 | **S13-T04C** (capability-aware validators) + **S13-T05C** (UI must show only the declared requirement) | as D-4 / UI lane | `T04A -> T04C`, `T05B -> T05C` | **none in this round — documentation-only row** |

**Write-set extension note (both rows):** `S13-T05A`'s frozen write-set in `S13_P00_DELTA_MATRIX.md` §2b row 13 names `app/workflow/character_preset_importer.py` and `app/services/preset_manager.py`. D-1/D-2 add two exact paths + one new file to that task's write-set. `S13_P00_DELTA_MATRIX.md` §6 requires an explicit Codex-approved delta before a path outside the P00 write-sets is touched — **this document is that delta request; it is not an authorization.** Deliberately avoided: `app/api/app.py` (kept out of the write-set by putting the route on the existing router, so T01D's single include hunk stays exactly one hunk).

---

## 3. Migration requirement per row + `down_revision` discovery

| Row | Migration required? | Discovery / serialization |
|---|---|---|
| D-1 | **No** — route + DTO only; reads/writes columns owned by D-4. | — |
| D-2 | **No** — service file only. Managed bytes + `artifact` rows need no schema change. | — |
| D-3 | **No, and this is measured, not assumed.** `character_asset.pose_slot` carries only length/uniqueness constraints (`app/persistence/models.py:1058`-`:1081`), so the namespaced reference key `front@character` fits the existing column with zero schema change. | — |
| D-4 | **Yes** — exactly ONE migration, and it is the ALREADY-FROZEN T01A migration (1 of 3): `add_column` × 3 (`pack_contract_version` with `server_default 'legacy_six_slot_2d'`, `requirement_manifest_json`, `requirement_manifest_sha256`) then 2 `create_check_constraint`. No data migration; every pre-existing row becomes legacy. | `down_revision` = **the live single head at activation**, discovered (never hard-coded) by parsing `revision` + `down_revision` from every `migrations/versions/*.py`, computing `heads = revisions never referenced as a down_revision`, and **aborting if `len(heads) != 1`**. Measured this round: **21 files / 21 revisions / single head `d4e5f6a7b8c9`** (`migrations/versions/d4e5f6a7b8c9_s12_retry_lineage.py`). Serialization: `T01A -> T01B -> T04A`, one head at a time. **Not executed by this round.** |
| D-5 | **No** — reads the branch column written by D-4. | — |
| D-6 | **No** — DTO reuse; `app/schemas/media_engine.py` is already landed at `f0b918b`. | — |
| D-7 | **No** — documentation only. | — |

---

## 4. Reuse-vs-additive analysis (why the minimum is ONE route + ONE service file)

**What the existing public importer/upload already does for authored artwork (measured):**

1. `app/api/routes/projects.py::upload_replacement` (`:1123`) — PUBLIC, multipart, the strongest byte-verification chain in the codebase (magic prefilter → FULL Pillow decode → dimension/total-pixel caps → atomic publish → rollback on failure). But it is **project-scoped**: it writes `objects/<object_id>/replacement.<ext>` through the project workflow and registers **no managed `Artifact` row**, so its output cannot be named by `artifact_id`, cannot be referenced by `ReferenceArtifact`, and dies at the pack boundary. Reuse its *verification logic*; its destination is wrong for a pack reference.
2. `app/workflow/character_preset_importer.py::CharacterPresetImporter.import_preset` — does the **whole managed-artifact leg correctly** (managed write + `Artifact(state="ready")` with sha256/size/mime + attach to a version). But it is **not a public path** (no route imports it; measured callers are tests only), it **creates a new character + version**, and it **iterates `CORE_POSE_SLOTS`**, so it cannot carry a reference to an existing version and cannot express a reference key.
3. `POST /api/v2/characters/versions/{version_id}/assets` (`app/api/routes/durable_characters.py:229`) — attaches an EXISTING ready artifact to a slot, replacing on repeat. Correct and reusable, but **no public route creates the authored artwork artifact**, so this route is unreachable for authored pixels today. This is the measured root of the reviewer's finding.

**Alternatives and why they lose:**

| Alternative | Verdict |
|---|---|
| Extend `upload_replacement` (project lane) to also register a managed artifact and attach it to a pack version | **Rejected.** Crosses two owners (`S08-H02` project workflow vs `S06-T01` character library), makes a project-scoped route write character-pack state, and still needs a reference key. More surface, not less. |
| Expose `CharacterPresetImporter` behind a route and extend it | **Rejected as the minimum.** It must first stop forcing character creation + `CORE_POSE_SLOTS` iteration — a rewrite of a task another owner holds (`S06-T02`), for no gain over a new small service. |
| A second reference/asset store (e.g. `character_reference` table) | **Rejected by the reviewer** and unnecessary: `character_asset` + namespaced key already fits (D-3, measured). |
| Any conversion of the segmentation mask into artwork | **Rejected by the reviewer** and by §6. |

**The minimum, justified:** ONE new route on the EXISTING `durable_characters` router (so `app/api/app.py` stays untouched and T01D's include stays one hunk) + ONE new service file that reuses `ManagedRoot` (`app/persistence/artifacts.py:206`/`:367`), the existing `Artifact` model (`app/persistence/models.py:589`) and the existing `CharacterRepository.attach_asset` (`app/persistence/characters.py:496`). Zero new tables, zero new columns for the ingest itself, zero changes to the two existing semantics, and the branch/manifest/cast work stays exactly where S13 already put it (D-4/D-5 reuse). Net new code surface: one handler + one service function pair.

---

## 5. Proving tests + public API acceptance per row

Existing test files are named as measured on disk; proposed files are labelled **NEW (proposed)** — the S13-named ones come from `S13_P00_DELTA_MATRIX.md` §2b.

| Row | Proving tests | Public API acceptance |
|---|---|---|
| D-1 / D-2 | **NEW (proposed)** `tests/test_s13_t05a_reference_ingest.py` — REAL authored RGBA PNG (min alpha < 255) → `201` with `artifact_id` + 64-hex `sha256`; artifact row `kind="image"`, `state="ready"`, size matches bytes on disk; re-upload of the same `reference_key` replaces (not duplicates); a mode-`L` mask PNG is REFUSED as artwork; truncated payload with valid magic → `415`; published version → `409`; unsafe `reference_key` → `422`. Existing gates kept green: `tests/test_character_validator.py`, `tests/test_publish_rejection.py`, `tests/test_character_read_api.py`, `tests/test_character_domain.py`, `tests/test_character_preset_importer.py`. | `POST /api/v2/characters/versions/{version_id}/reference-artwork` → `201 {artifact_id, sha256, size_bytes, mime_type, width, height, reference_key}`; `404` unknown version; `409` published version; `415` non-image/corrupt/truncated; `422` unsafe key. |
| D-3 | Covered by the D-1/D-2 suite (attach asserted through `GET /versions/{version_id}/validation` + asset list) | `POST /api/v2/characters/versions/{version_id}/assets` behaviour unchanged (`:229`), including replace-on-repeat and `409` on a published version. |
| D-4 | **NEW (proposed, S13-named)** `tests/test_s13_t01a_pack_contract.py`, `tests/test_s13_t01b_manifest_freeze.py`, `tests/test_s13_t04a_validation_branch.py`; existing `tests/test_publish_rejection.py` + `tests/test_character_validator.py` unchanged-green. | `POST /versions/{version_id}/publish` → legacy: `422` `{message, missing_slots, errors}` exactly as today; reference: refusal naming the manifest key, **never** "missing pose". `GET /versions/{version_id}/validation` → `complete` = enough required entries present, `status` = validation result, **unchanged and independent**. |
| D-5 | `tests/test_s07_cast_compatibility.py` (existing) + **NEW (proposed)** `tests/test_s13_t07a_publish_snapshot.py` | `POST /api/v2/project-cast/evaluate` → `blocked` with a `CompatibilityReason` code (never an empty list / silent skip); a legacy pack that is incomplete can never be reported/pinned as a reference pack. |
| D-6 | `tests/technology/test_media_engine_contract.py` (existing, this lane) — `ReferenceArtifact` path refusal, `independent_references` non-duplication | Engine request acceptance is unchanged: references are addressed by managed `artifact_id` + `sha256`; a client path is refused with `CLIENT_ARTIFACT_PATH_REFUSED`. |
| D-7 | `tests/test_object_extraction.py`, `tests/test_object_correction.py`, `tests/technology/test_media_engine_contract.py` (all existing; read-only rows) | Mask content stays at `GET /api/v2/objects/extractions/{job_id}/artifacts/{artifact_id}/content`; no reference route accepts a mask as artwork. |

---

## 6. Mask ≠ artwork boundary (frozen)

- **Segmentation stays segmentation.** `ARTIFACT_PURPOSE_CANDIDATE_MASK = "mask"` (`app/services/object_extraction.py:200`), published with `purpose="mask"` and associated through `ObjectRoleArtifact` whose CHECK is exactly `('thumbnail','mask')` (`app/persistence/models.py:1263`). PNG colour type 0 / mode `L` is the CORRECT representation of a segmentation mask and is **not** changed, not converted, and never multiplied into poses.
- **Artwork keeps its own requirement.** Authored appearance survives today's rules unchanged: the publish validator requires REAL transparency — at least one effective alpha pixel below 255 — via `REQUIRE_ALPHA_CHANNEL` (`app/workflow/character_validator.py:47`) and `_has_real_transparency` (`:177`), plus `128x128` minimum resolution (`MIN_POSE_WIDTH`/`MIN_POSE_HEIGHT`, `:37`/`:40`). An authored RGBA cutout satisfies this; an `L` mask does not, and that is the intended verdict — the fix is a real public artwork ingest (D-1/D-2), not a mask conversion.
- **The reference video path uses `reference_pack_v1` branch semantics** (`PACK_CAPABILITY_CONTRACT.md` §2.2/§2.3): the pack declares its required views/counts/roles as data; the NORMATIVE floor is `CAPABILITY_REFERENCE_REQUIREMENTS` (`app/schemas/media_engine.py:322`) and a declaration may only select or add, never lower, a minimum. `ReferenceRequirement` is the per-capability shape (`:273`).
- **Legacy six-slot validation is not bypassed.** `legacy_six_slot_2d` keeps `CORE_POSE_SLOTS` completeness and the alpha/resolution gate exactly as measured; the reference branch has its OWN requirements (manifest keys + per-capability floor). Neither branch can borrow the other's verdict: "an incomplete legacy pack must not masquerade as an approved new type" (`PACK_CAPABILITY_CONTRACT.md` §3 rule 3) and a reference pack is never forced to carry six manual poses (rule 2).
- **Graph addressability without new schema.** A reference is `artifact_id` + `sha256` (`ReferenceArtifact`, `app/schemas/media_engine.py:578`); paths are refused (`CLIENT_ARTIFACT_PATH_REFUSED`). No new `owner_type`, no new `purpose`, no second store.

---

## 7. S08 producer gap list (minimum, no fabricated measurements) — PROPOSED ONLY

Both gaps are measured on the tree plus the S12-LC3-QA product run (`S12QA/REPORT_D2.md`, detector matrix: 5/8 visual detectors COMPOSE, 3 missing). **No dispatch authority is claimed here; these are proposals for Codex to open or refuse.**

### 7.1 S08-T02 — contact / occlusion evidence (owner: `docs/pm/sessions/S08-T02-candidate-extraction`)

**Facts that come from the model/segmentation today (measured, this tree):**

| Fact | Where measured | State |
|---|---|---|
| Segmentation masks per candidate (`purpose="mask"`, colour type 0 / mode `L`) | `app/services/object_extraction.py:200`, `:1926`, `:2026`, `:2218` | REAL |
| Object roles / occurrences / bbox / per-segment frames+times | `app/services/object_extraction.py` (role + segment writes inside `discover_objects_handler`, `:1276`) | REAL |
| Scene graph EDGES (`scene_graph_occlusion` `models.py:1931`, `scene_graph_contact` `models.py:2044`) | `app/services/object_extraction.py:2417`-`:2480` | **QA-SYNTHETIC ONLY**: gated by `_is_qa_synthetic` (`:2361`), `algorithm="deterministic-layout"`, provenance `qa_mode/synthetic/test_adapter` |

**Facts missing (the gap):** for the deterministic adapter to produce even its synthetic edges, a scene must hold **at least two segments** — measured guard `if len(seg_ids) < 2: continue` (`app/services/object_extraction.py:2420`). The real/deterministic adapter publishes ONE segment per scene, so `scene_graph_contact` = 0 rows and `scene_graph_occlusion` = 0 rows on the product run; the `contact_break` and `z_order_error` detectors then have no `contacts`/segments input and report evidence-missing. `detect_contact_break` requires `analysis_window`, `segments` and `contacts` (`app/services/qc_checks/contact_break.py:178`, `:79`, `:93`, `:184`).

**Minimum proposed delta (SEPARATE write-set, PROPOSED ONLY):** add ONE second segment whose `start_frame != scene.start_frame` inside the same scene of the deterministic adapter, so the existing `:2417`-`:2480` block emits 1 occlusion + 1 contact row without touching the `len(seg_ids) < 2` rule (the cut_drift sub-range contract is preserved by the same block's existing sub-range arithmetic).
- Write-set: `app/services/object_extraction.py` (only).
- Owner activation: resume `S08-T02-candidate-extraction` — **PROPOSED**, requires Codex's own activation sentence; dependency `S08-T02` re-open must not collide with the D-4/D-5 character work (disjoint paths, so it may share a wave).
- Type: `BLOCKED_DEPENDENCY` until that sentence exists. No measurements are asserted here for the post-change row counts.

### 7.2 S08-T05 — rendered-side mask (owner: `docs/pm/sessions/S08-T05-targeted-correction`)

**Facts that come from the model/segmentation today (measured, this tree):**

| Fact | Where measured | State |
|---|---|---|
| SOURCE-side candidate mask publication (`purpose="mask"`) | `app/services/object_correction.py:739` (`Artifact`), `:792` (`ARTIFACT_PURPOSE_CANDIDATE_MASK`), `:800` (`ObjectRoleArtifact`) | REAL |
| Corrected-artifact publication + `ObjectRoleArtifact` purpose CHECK `('thumbnail','mask')` | `app/persistence/models.py:1241`, `:1263`; `app/services/object_correction.py:617`-`:690` | REAL |
| Rendered-side mask | — | **MISSING** |

**Facts missing (the gap):** `edge_halo` measures the halo of the RENDERED mask against the EXPECTED mask and records both artifact hashes (`app/services/qc_checks/edge_halo.py:59` `measure_halo_width(rendered, expected, …)`, module docstring "rendered mask against the EXPECTED mask"). Only source-side mask artifacts exist, so the detector has no rendered side on this candidate and reports an evidence dependency rather than a measured value.

**Minimum proposed delta (SEPARATE write-set, PROPOSED ONLY):** publish ONE rendered-side mask artifact through the existing correction publication path (`app/services/object_correction.py:617`-`:690`, `Artifact` + `ObjectRoleArtifact`) so `edge_halo` receives both sides — **no new model, no new table, no new route**.
- Write-set: `app/services/object_correction.py` (only).
- Owner activation: resume `S08-T05-targeted-correction` — **PROPOSED**, requires Codex's own activation sentence.
- Type: `BLOCKED_DEPENDENCY` until that sentence exists. The post-change detector status is NOT asserted here.

**Unauthorized in this round (both gaps):** dispatch, new owner sessions, queue mutation, threshold change, any edit to `app/services/object_extraction.py` or `app/services/object_correction.py`.

---

## 8. Status after this round

- `TASK_SUBMITTED` (docs-only delta). `QUALITY_ACCEPTED` = 0 — Codex owns that verdict.
- `S13-INT01`, the 22 S13 production task IDs and `P01A`/`P01B` stay **`BLOCKED_DEPENDENCY`** — this document activates nothing.
- No migration executed. No app/test/persistence/API/UI file changed. No push.
- Explicitly NOT claimed: that the ingest route exists (it does not — it is proposed), that the manifest columns exist (they do not — T01A), or that any post-change test/row count is known.

## 9. Probe and gates

- `raw/probe_r27.py` re-derives every "exists today" cell of §1 and every producer fact of §7 from the tree (existence, symbol, route, constant, CHECK text, line anchors, absence claims) and prints `PASS/FAIL` per row; a row that cannot be re-derived is marked a proposal rather than existing. `raw/probe_r27_out.txt` is its verbatim output; `results.json` is its machine record.
- micro gate: all probe rows PASS.
- focused gate: `git status --porcelain` shows ONLY this new doc; `git diff --stat HEAD` empty.
- retained doc probe: `d16_nr06_doc_check.py` re-run (HEAD-independent doc integrity) with its counts recorded in `REPORT.md`.
