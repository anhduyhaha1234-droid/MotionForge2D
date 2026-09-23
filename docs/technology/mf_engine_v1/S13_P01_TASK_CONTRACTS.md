# S13_P01_TASK_CONTRACTS — P01A / P01B (contract only, not implemented here)

**Task:** MF-TOOL-CONTRACT · **Status:** PROPOSAL (awaiting `C-CONTRACT` Codex review)
**Explicit non-goal:** this document **contracts** P01. It does **not** implement it. No file
listed below is created or modified by MF-TOOL-CONTRACT. Each P01 task remains gated behind
its own dependencies, its own write allowlist and its own Codex review, exactly like the 22
active S13 IDs in the C5 task map.

**Why P01 exists:** S13 generates packs; before generating, someone must answer *"which
existing published pack (or which starting profile) fits this source role best?"* — and must
never be allowed to silently repoint a role at a different character.

---

## 1. P01A — advisory character-fit recommender (backend, NEW)

**Activation gate.** Only after **T01A, T01C and T02A are APPROVED/frozen** (binding schema,
prompt/version/hash semantics, provider capability probe). Activated by a Codex-approved
packet, not by this proposal.

**Exclusive write allowlist (new files only):**

| Path | Kind |
|---|---|
| `app/services/generation/character_fit.py` | NEW service |
| `app/schemas/character_fit.py` | NEW DTOs |
| `tests/test_character_fit.py` | NEW tests |

**Forbidden:** any migration; any public route; `app/api/app.py`; `app/persistence/models.py`;
any UI/frontend file; any change to `app/persistence/project_cast.py` or
`app/schemas/project_cast.py`; any benchmark/threshold constant.

### 1.1 Required behaviour

1. **Build requirements from approved source-role evidence only.** Inputs are the approved
   source-role evidence records (role kind, views/poses observed, articulation and contact
   evidence, props, scale) — never free-text, never client-supplied.
2. **Candidates are eligible immutable *published* packs.** Unpublished, incomplete, archived
   or workspace-mismatched packs are excluded *before* scoring, using the existing gates
   (`unpublished_pack`, `incomplete_pack`, `workspace_mismatch`, `object_kind_mismatch`,
   `source_overlay_refusal`). When no published pack suffices, the recommender may propose
   **compatible generation starting profiles** instead — clearly typed as *profiles*, never
   represented as if they were packs.
3. **Hard gates precede any AI similarity.** In this order, and each one is a blocker:
   topology/limbs → view/pose coverage → articulation → anchors/contact/props →
   scale/proportion/silhouette. A pack that fails any hard gate is **excluded**, not
   down-ranked: no similarity score may override or "compensate" a blocker.
4. **Explainable Top-K output.** Each ranked entry carries: the candidate identity
   (`character_id` + `pack_version_id`), per-dimension evidence, the hard-gate verdicts, the
   **missing coverage** list, and a **calibrated** confidence. "Calibrated" means derived
   from the measured evidence with a stated scale — an opaque score with no components is a
   contract violation.
5. **A *proposed* pinned series plan.** The output may propose a plan (role → candidate +
   version) for the user to confirm. It is a *proposal object*: it mutates nothing.
6. **Never mutate cast, never publish.** P01A holds no write path to cast mappings, pack
   versions or publication. Structurally: the service module may not import the cast write
   API; a test asserts no cast/publish mutation is reachable.
7. **AI is optional, local and provider-agnostic.** If a similarity model is available it is
   used; if not, the recommender falls back to **deterministic evidence** scoring. It must be
   impossible to emit a confidence that no evidence supports — **never fabricated
   confidence**, never a placeholder score, never a mock recommendation in a shipped path.

### 1.2 Acceptance (binary)

- Ranking of a fixture set returns Top-K with per-dimension evidence and missing coverage;
  every excluded candidate carries its hard-gate reason.
- A candidate failing a hard gate never appears in the Top-K **even when its similarity score
  is the highest** (this is the anti-`opaque-AI-score` control).
- With no model available, the deterministic path returns the same *ordering discipline* with
  confidences derived from evidence; a run with no evidence returns no confidence claim.
- Zero writes: no cast row, no pack version, no publication is created or modified by a run.
- `git status` shows only the three allowlisted files as new.

### 1.3 Required evidence type

Unit tests under `tests/test_character_fit.py` (fixtures only, no network, no GPU) plus a
written matrix mapping each hard gate to the test that proves it excludes rather than
down-ranks.

---

## 2. P01B — fit API + UI with confirmed selection (NEW)

**Activation gate.** After **P01A, T03C and T05B are APPROVED**, and — for the shared UI —
**serialized after T07B**. One packet, one activation, no parallel UI work.

**Exclusive write allowlist:**

| Path | Kind |
|---|---|
| `app/api/routes/character_fit.py` | NEW router |
| `tests/test_character_fit_api.py` | NEW API tests |
| `frontend/src/app/(app)/characters/generation/fit/**` | NEW UI |
| `frontend/e2e/s13-p01-fit.spec.ts` | NEW E2E |
| `app/api/app.py` | **EXT — exactly ONE router include hunk** |
| `frontend/src/app/(app)/characters/page.tsx` | **EXT — fit hunks only** |
| `frontend/src/lib/api.ts` | **EXT — fit hunks only** |

**Forbidden:** any migration; any second cast table; `app/config.py`;
`app/persistence/models.py`; any other route file; any hunk in `app.py` beyond the single
include.

### 2.1 Required behaviour

1. **Browsing/fit endpoints are read-only.** They expose P01A's advisory output; they never
   write.
2. **Only explicit, user-confirmed choices persist.** Persistence goes through the **existing
   project-cast APIs** with the **current `revision` (CAS)** — never a new write path, never a
   second table. A stale revision **refuses** (`stale_revision`); missing evidence **refuses**.
3. **AI never changes a mapping.** A recommendation is advisory: a mapping changes only when a
   human confirms it. There is no code path where a higher-scoring candidate rewrites an
   existing cast pin, and no "auto-apply" affordance in the UI.
4. **Confirmed selection survives context changes.** Across **two videos and a reopen**, the
   chosen `CharacterID`/`PackVersion` must persist and be the one used; nothing re-derives or
   re-picks silently on load.
5. **The client cannot choose the provider** (inherited from T03C), and the fit UI cannot
   request generation of a provider the server did not resolve.

### 2.2 Frozen truth it must respect

- **Deterministic fallback**: with no AI model, the fit UI shows evidence-based ordering, not
  an error and not a fake score.
- **Hard compatibility gates** (P01A §1.1.3) are visible in the UI as blockers with reasons —
  a blocked candidate can never be confirmed into a cast pin.
- **Frozen benchmark truth**: P01B may not introduce or tune any threshold used by
  `T08A/T08B`; benchmark truth is Codex-signed (`C13-GOLDEN-TRUTH-SIGNOFF`) and P01 does not
  touch it.

### 2.3 Acceptance (binary)

- `app/api/app.py` diff contains **exactly one** additional router include versus its
  predecessor baseline (the same one-hunk discipline T01D/T03C already carry).
- An API test proves a stale revision refuses and a missing-evidence request refuses.
- An E2E test proves: choose a candidate in video A → open video B → reopen video A → the
  chosen `CharacterID`/`PackVersion` is the same and no silent re-pick occurred.
- A test proves no request body can cause a cast mutation without an explicit confirm action.
- `git status` shows only the seven allowlisted paths.

### 2.4 Required evidence type

API tests (`tests/test_character_fit_api.py`) + Playwright E2E
(`frontend/e2e/s13-p01-fit.spec.ts`) + the two-video/reopen persistence proof recorded as
raw output.

---

## 3. Cross-cutting rules binding both P01 tasks

| Rule | Statement |
|---|---|
| No opaque AI score | Every score is decomposable into named dimensions with evidence. A number with no components is a defect. |
| No automatic mapping mutation | Cast pins change only by explicit human confirmation through existing CAS APIs. |
| No second cast table, no migration | P01 adds no persistence layer of its own. |
| Deterministic fallback | With no model available, evidence-based ordering is returned — never a fabricated confidence, never a stub. |
| Refusal over silence | Every exclusion/refusal names one of the existing closed reason codes. |
| Provider-agnostic | P01 does not name, require or download a model; a model is optional and local. |
| Benchmark immutability | P01 cannot alter thresholds, datasets or expected verdicts. |

## 4. Dependency graph (unchanged from C5 where they overlap)

```
T01A ─┬─ T01B ─┬─ T03A ─┐
      │        └─ T04A ─┼─ T03C ─┐
T01C ─┘                │        ├─ T05A/B/C ─┬─ T06A ─ T06B ─┐
T02A ──────────────────┘                    └─ T07A ─ T07B ─┴─ P01B
                                                             
P01A  ← needs T01A + T01C + T02A
P01B  ← needs P01A + T03C + T05B, serialized after T07B
```

## 5. Open questions this proposal puts to Codex

1. Does P01A's deterministic fallback need to be a **separate named component** (so T08
   can benchmark it) or a branch inside `character_fit.py`? This proposal prefers a named
   component with its own evidence output.
2. Is the "proposed pinned series plan" allowed to be persisted as a *draft* record, or must
   it stay ephemeral until confirmed? This proposal prefers **ephemeral until confirmed** —
   persistence arrives only through the existing CAS cast API.
3. Does `reference_pack_v1` (see `PACK_CAPABILITY_CONTRACT.md`) change P01A's candidate set
   shape, or are both pack types simply two candidate kinds in one ranked list? This proposal
   prefers **one ranked list, candidate kind as a field**.
