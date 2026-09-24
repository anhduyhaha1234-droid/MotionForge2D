# PACK_CAPABILITY_CONTRACT — legacy packs preserved, reference packs versioned

**Task:** MF-TOOL-CONTRACT · **Status:** PROPOSAL (awaiting `C-CONTRACT` Codex review)
**Governing rule:** the existing six-slot / flat-2D character pack **keeps working exactly
as it does today**, and a *distinct, versioned* reference-pack contract is proposed **beside**
it — not on top of it. No universal flat-2D rejection, no mandatory six manual poses for
every new engine.

---

## 1. The legacy pack as it exists today (measured, not assumed)

| Fact | Authority |
|---|---|
| Six canonical pose slots | `app/persistence/models.py:170` — `CORE_POSE_SLOTS = ("front", "three_quarter", "side", "back", "sitting", "walking")` |
| Pack = immutable version with per-slot assets | `app/persistence/models.py` (`PackVersion`, `Asset`), `app/persistence/characters.py` |
| Completeness gate = every core slot present | `app/persistence/characters.py:569` and `:746` — `missing_slots = [slot for slot in CORE_POSE_SLOTS if slot not in present_slots]`, with `complete=not missing_slots` |
| Draft validation without mutation | `app/schemas/characters.py::PackVersionValidationData` (`complete`, `missing_slots`, `errors`) — same validator as publish |
| Publish = CAS on a revision, then immutable | `PublishVersionRequest(revision)`, `SetDefaultVersionRequest(revision)`, `PackVersionData.published_at`/`status`/`revision` |
| Cast pins the immutable version | `app/persistence/project_cast.py` ("Pack must be published and complete (CORE_POSE_SLOTS)"), `app/schemas/project_cast.py::ProjectCastCreateRequest.pack_version_id` |
| Compatibility gate vocabulary | `app/schemas/project_cast.py::CompatibilityReason` — `workspace_mismatch`, `source_overlay_refusal`, `object_kind_mismatch`, `incomplete_pack`, `unpublished_pack`, `missing_required_pose`, `missing_required_capability`, `generation_mismatch`, `stale_revision` |
| Sprint intent | `docs/pm/ROADMAP.md:261` — "one simple 2D reference becomes a human-reviewed six-pose library pack without training" |
| Epic exit | `docs/pm/ROADMAP.md:277` — "generator failure cannot block manual library usage; only complete reviewed packs can be published" |

Nothing above is changed by this contract.

## 2. What is proposed: a versioned reference-pack contract *beside* the legacy one

```
pack_contract_version: "legacy_six_slot_2d" | "reference_pack_v1"
```

A pack declares which contract it satisfies. The two are separate types with separate
gates; migration is opt-in per pack, and a legacy pack is never silently reinterpreted.

### 2.1 `legacy_six_slot_2d` — retained, unchanged

- Required slots: exactly `CORE_POSE_SLOTS`, enforced by the existing validator.
- Required references/views: flat 2D, one image per slot.
- Gate: complete + published + CAS revision → immutable `PackVersion`.
- Cast: usable **as today** by any route whose capability needs no more than a flat 2D
  six-pose pack.

### 2.2 `reference_pack_v1` — proposed for capable engines

- **Required references/views/roles are declared by the pack, not by a universal constant.**
  The contract records, per role and per pack: the required *views* (e.g. front/side/back
  3D-ish views), the required *reference counts*, the *roles* the pack can serve
  (`character`, `prop`, `other`), and — critically — **which engine capabilities the pack
  claims to satisfy**, e.g. `source_video_motion_transfer` needs a motion-capable reference
  set, `image_edit_multi_reference` needs N multi-reference views, a controlled video edit
  needs a view/coverage set a flat 2D sheet may not provide.
- **The requirement set is data, not code.** A new engine capability adds a declared
  requirement profile; it does not add a hard-coded slot list to the domain.
- **Partial packs are legitimate**: a `reference_pack_v1` may be *incomplete for capability X*
  while being *complete for capability Y*. The gate is therefore per capability:
  `assert_compatible(pack, capability)`.

### 2.3 The frozen shape of the declaration (decided this round)

Codex chose **one existing pack/version authority with two versioned branches**, so the
declaration is now concrete and implementable (full storage plan: `S13_P00_DELTA_MATRIX.md` §5):

```
pack_contract_version        VARCHAR(32) NOT NULL DEFAULT 'legacy_six_slot_2d'
                             CHECK (pack_contract_version IN
                                    ('legacy_six_slot_2d','reference_pack_v1'))
requirement_manifest_json    TEXT        NULL   -- required IFF reference_pack_v1
requirement_manifest_sha256  VARCHAR(64) NULL   -- frozen at publish, never re-derived
```

- **One authority, two branches.** The declaration lives on the existing immutable
  `character_pack_version` row. **No second pack table, no second cast table, no second asset
  table**; reference pixels stay in `character_asset`, addressed by `artifact_id` + hash.
- **The manifest is frozen.** It is written once, hashed once and bound to the immutable version;
  the publish snapshot (T07A) records `pack_contract_version` + `requirement_manifest_sha256`. A
  `reference_pack_v1` pack with no manifest cannot exist (CHECK) and cannot be published.
- **The profile engine carries version + hash + NORMATIVE minima.** The capability profile
  (`CAPABILITY_REFERENCE_REQUIREMENTS` in `app/schemas/media_engine.py`) states the minimum
  reference set per capability. A pack declaration may only **select or add** suitable
  requirements for the packs it describes; it may **never lower a minimum to pass**, and the
  evaluator refuses that explicitly rather than accepting a weakened pack.
- **ONE compatibility evaluator with two branches** (`S13_P00_DELTA_MATRIX.md` §5.5), so
  `blocked` / `fallback_allowed` semantics stay single-sourced.
- **`CORE_POSE_SLOTS` and completeness apply to LEGACY ONLY.** `legacy_six_slot_2d` keeps today's
  six-slot completeness gate unchanged; a `reference_pack_v1` pack is **never** forced to carry
  six manual poses, and "missing pose" wording must never appear for one.

## 3. The five anti-regression rules

1. **No universal flat-2D rejection.** A flat-2D six-pose pack remains valid for the
   capabilities it was always valid for. `reference_pack_v1` never invalidates an existing
   pack, and no route may refuse *all* flat-2D packs.
2. **No mandatory six manual poses for every new engine.** `CORE_POSE_SLOTS` is the legacy
   contract's requirement. A `reference_pack_v1` engine declares its own required
   references/views; requiring `front/three_quarter/side/back/sitting/walking` from every
   engine would be a fabricated requirement (and would block engines that need e.g. 3 views
   with a depth-explicit reference instead).
3. **An incomplete legacy pack must not masquerade as an approved new type.** Concretely: a
   pack whose declared `pack_contract_version` is `legacy_six_slot_2d` and whose
   `missing_slots` is non-empty cannot be reported as, offered as, or pinned as a valid
   `reference_pack_v1`. The two verdicts are computed by different gates and are never
   interchangeable; a legacy pack cannot acquire capability it did not declare by being
   "close enough".
4. **Capability absence is explicit.** A pack says which capabilities it satisfies and, for
   each it does not, *why* (`missing_required_pose`, `missing_required_capability`,
   `incomplete_pack`, `generation_mismatch`, …) using the existing `CompatibilityReason`
   vocabulary. Absence is a stated reason code, never an empty list or a silent skip — this
   is the same rule the media-engine schema enforces mechanically
   (`CapabilityOffer.unavailable_reason_code`).
5. **Storing styles is not certifying style quality.** The engine can *store* a style
   reference and *pin* a `style_version`; that is a technical capability. It is **not** a
   statement that the style is good, licensed, on-brand, or approved. Style-quality
   certification remains a human review act recorded by the approval authority
   (`app/services/s09_approval.py`), exactly as pack publication remains a human-reviewed
   act. A `style_version` in a request means "render with this pinned style reference", never
   "this style is approved".

## 4. Gates, preserved

| Gate | Status under this contract |
|---|---|
| Immutable pack versions | **Preserved** — a published `PackVersion` is never mutated; a new version supersedes |
| Approval audit | **Preserved** — `app/services/s09_approval.py` records who approved what, with conflict/integrity errors on replay |
| Fail-closed publication | **Preserved** — only complete + reviewed packs publish; the media engine additionally refuses an empty publish set (`artifact_not_managed`) |
| Manual-library fallback | **Preserved** — `app/workflow/character_preset_importer.py`, `app/services/preset_manager.py` keep working when generation fails (ROADMAP.md:277 epic exit) |
| CAS on publish / repin | **Preserved** — `revision` remains the optimistic token; a stale revision refuses (`stale_revision`) |
| Workspace isolation | **Preserved** — a pack is workspace-scoped; `workspace_mismatch` refuses |
| Source-overlay refusal | **Preserved** — `source_overlay_refusal` still refuses a mapping that would overwrite source-locked content |

## 5. What this changes on disk — decided, no longer deferred

- **This task writes no migration.** The `reference_pack_v1` persistence decision is **TAKEN**
  (Codex R7 direction, §2.3): an additive `pack_contract_version` column plus a frozen
  requirement/reference manifest on the existing immutable `character_pack_version` row. The
  concrete DDL, the affected fields/FK/CHECK, the upgrade/downgrade and the measured
  single-head `down_revision` discovery are in **`S13_P00_DELTA_MATRIX.md` §5**; the migration
  itself is owned by **T01A → T01B → T04A**, serialized, and is *not* implemented here.
- **No change to `CORE_POSE_SLOTS`** and no change to the existing completeness validator: both
  stay legacy-only.
- **No second cast table and no second pack table.** `CastBinding` in the media-engine request is
  a *projection* of the existing project-cast pin.
- **No automatic mapping mutation.** Nothing in this contract lets an engine change which
  `CharacterID`/`PackVersion` a role is mapped to; see `S13_P01_TASK_CONTRACTS.md` §3.

## 6. Decision record (this proposal's questions, answered)

1. **Where does `pack_contract_version` live?** On the existing pack-version table, as one
   additive, NOT NULL, server-defaulted column with a closed CHECK — *not* a new capability-profile
   table. Legacy rows read `legacy_six_slot_2d`; no legacy pack changes behaviour.
2. **Who owns the requirement profile — the capability or the pack?** Both, in a fixed order:
   the capability profile owns the **normative minimum**, and a pack may only select or add
   requirements on top of it. A pack can never lower a minimum to pass.
3. **One evaluator or two?** **ONE evaluator, two branches** (legacy / reference), so
   `blocked` and `fallback_allowed` semantics cannot diverge between two implementations.
