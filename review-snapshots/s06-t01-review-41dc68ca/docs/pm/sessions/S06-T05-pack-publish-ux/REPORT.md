# Task S06-T05 Implementation Report (CORRECTED — review worktree)

- **Task ID:** `S06-T05`
- **Status:** `SUBMITTED` (never self-approved)
- **Owner:** Hermes (Review Worktree `s06-t01-review`)
- **Depends On:** `S06-T04` (Codex APPROVED) + `S06-R02` (approved read API)
- **Correction:** S06-T05 WRONG-WORKTREE recovery — see
  `INCIDENT_REPORT_WORKTREE_MAIN.md` and the LOG.md correction section.

## 0. Why this report is a correction

The first S06-T05 run executed in the MAIN repo (INC-2026-08-05-001) and its
artifacts were later copied into this worktree, overwriting 11 approved files
with older main-tree character code. That copy added a weaker NESTED publish
endpoint (`POST /api/v2/characters/{id}/versions/{v}/publish`) and a NESTED
pose-slot image endpoint (`GET /api/v2/characters/{id}/versions/{v}/assets/{pose_slot}/image`)
that replace the approved R02 content/validation contracts. This session:

1. Compared every current file against `output/backup-pre-copy/` (the
   pre-incident approved S06/R02 state).
2. Restored **exactly the 11 overwritten approved files** from the backup:
   `app/api/deps.py`, `app/api/routes/durable_characters.py`,
   `app/persistence/characters.py`, `app/persistence/models.py`,
   `app/schemas/characters.py`, `app/workflow/character_preset_importer.py`,
   `app/workflow/character_validator.py`,
   `frontend/src/app/(app)/characters/page.tsx`, `frontend/src/lib/api.ts`,
   `migrations/versions/d5e6f7a8b9c0_character_library_schema.py`,
   `tests/test_persistence_bootstrap.py` — all verified byte-identical
   (`diff -q` 11/11 SAME).
3. Removed the corrupt T05 backend test
   `tests/test_pack_publish_ux.py` (it targets the forbidden nested
   endpoints) → quarantined at `output/quarantine-t05-corrupt/` for evidence.
4. Verified the **original 90-test R02/character suite passes** on the
   restored state (90/90, twice: before and after the frontend work).
5. Reimplemented S06-T05 **frontend-only** on top of the restored approved
   state: the existing FLAT publish endpoint
   `POST /api/v2/characters/versions/{version_id}/publish` with CAS revision,
   and the typed API/`content_url`/validation contracts from R02. The weaker
   nested image endpoint was removed by the restore and was NOT re-added; no
   R02 route was replaced; no artifact-id attachment/upload controls were
   added.

## 1. Outcome

Users can now review a draft pack's six pose previews, see authoritative
validation state (from `GET /api/v2/characters/versions/{id}/validation`),
explicitly publish an eligible non-published version with a confirmation
dialog and CAS revision, and clearly see that a published version is
immutable. 422 validation failures and 409 stale-revision conflicts are
surfaced honestly; a conflict refreshes current state and is never silently
retried.

## 2. What changed (allowed scope only)

| File | Change |
|---|---|
| `frontend/src/lib/api.ts` | New `ApiError` (status + parsed FastAPI `detail`, unwrapped) thrown by `apiFetch`; new `api.publishCharacterVersion(versionId, revision)` → flat `POST /api/v2/characters/versions/{version_id}/publish` with `{revision}`. |
| `frontend/src/app/(app)/characters/page.tsx` | Pack Review & Publish UX on the approved detail view: publish panel for eligible non-published versions (button disabled with helper text until authoritative validation is complete), explicit confirmation dialog with immutability warning, mutation with CAS revision, success → refetch character/versions/validation + persistent success feedback, 422 → server message + `missing_slots`/`errors` lists, 409 → conflict message + state refresh (no retry), published versions keep the immutable badge/lock note and expose no publish or asset-mutation controls. Feedback renders outside the publish panel so it survives the panel unmount after publish; switching versions clears feedback/dialog. |
| `frontend/e2e/pack-publish-ux.spec.ts` | NEW — 6 focused interaction tests (below). |
| `frontend/e2e/pack-publish-ux-visual.spec.ts` | NEW — desktop + 390px visual QA screenshots. |
| `frontend/playwright.s06t05.config.ts` | NEW — focused config (testMatch, serial, chromium, baseURL :3010). |
| `output/qa-seed-s06-t05.py` | NEW QA seed (uses the approved S06-T02 importer against `output/qa-root`; idempotent; writes a fresh per-run publish target + `output/qa-s06-t05/seed-state.json`). |
| `docs/pm/sessions/S06-T05-pack-publish-ux/LOG.md` | Correction run appended (this report + evidence). |

No backend, schema, migration, validator, importer, `channels.json`, `data/`,
roadmap, or unrelated UI files were changed. The nested publish/image
endpoints exist in NO code path of this worktree anymore.

## 3. Acceptance criteria — evidence

### AC1–AC2. Six-pose review + authoritative validation state
- Pose tiles render ONLY real content-endpoint images (typed `content_url`,
  `artifact_state === "ready"`, honest placeholder otherwise — unchanged
  approved R02 behavior).
- Validation box shows the authoritative `PackVersionValidationData`
  (`complete`, `missing_slots`, `errors`) — unchanged approved behavior.
- **Evidence:** `incomplete pack: publish disabled with authoritative problems
  shown` — `tho_cute` (3/6 assets) shows “Thiếu 3 tư thế bắt buộc.” + the
  missing-slot list and the publish button is disabled with
  “Cần đầy đủ 6 tư thế hợp lệ để xuất bản (đang thiếu 3 tư thế).”

### AC3. Publish with explicit confirmation + CAS revision
- “Xuất bản” (enabled only when validation complete) opens a dialog with an
  immutability warning; confirming POSTs the FLAT endpoint with the current
  `revision`.
- **Evidence:** `confirmation: cancel keeps the draft and sends no publish
  call` — dialog shows “Xuất bản phiên bản v1?” + “bất biến” warning; Hủy
  closes it with **0** publish POSTs and the version stays “Nháp”.

### AC4. Success → refetch → immutable published state
- On success the character, versions, and validation queries are refetched;
  the row becomes “Đã xuất bản · Bất biến”, the lock note appears, and the
  publish control disappears.
- **Evidence:** `success: publish refetches and shows the immutable published
  state` — real publish of a fresh seeded six-pose draft; success feedback +
  “Đã xuất bản · Bất biến” + “Phiên bản đã xuất bản không thể chỉnh sửa” +
  publish button count 0.

### AC5. Honest 422 / 409, no silent retry
- **Evidence:** `422: validation failure is surfaced honestly…` — intercepted
  422 detail `{message, missing_slots: [sitting, walking], errors}` renders
  the server message, “Thiếu: Ngồi, Đi bộ” and both error rows; exactly **1**
  publish POST; version stays draft.
- **Evidence:** `409: stale revision shows conflict, refreshes state, never
  retries` — intercepted 409 renders “Xung đột phiên bản…”, a fresh
  `GET …/versions` fetch happens after the conflict, and exactly **1** publish
  POST after a 1s settle (no retry).

### AC6. Immutable published version — no mutation controls
- **Evidence:** `published version is immutable with no asset mutation
  controls` — `boy_hacker` (published seed): “Đã xuất bản · Bất biến” + lock
  note, publish button count 0, no upload/attach/artifact buttons (0 matches).

## 4. Mandatory regression (restored approved state)

| Suite | Result |
|---|---|
| `tests/test_character_read_api.py` | PASS |
| `tests/test_publish_rejection.py` | PASS |
| `tests/test_character_domain.py` | PASS |
| `tests/test_character_validator.py` | PASS |
| `tests/test_character_preset_importer.py` | PASS |
| **Combined (--cache-clear)** | **90 passed** (31.13s first run; 29.92s final re-run) |

`tests/test_pack_publish_ux.py` (corrupt artifact) is quarantined, not run —
it tests the removed nested endpoints by design of this correction.

## 5. Focused frontend E2E — real QA servers

- Backend :8002 (uvicorn, `MOTIONFORGE_ROOT=output/qa-root`, restored code),
  frontend :3010 (next dev), Playwright `playwright.s06t05.config.ts`.
- Seeded with real characters via the approved importer (`boy_hacker`
  published, `tho_cute` 3/6, `co_gai` complete draft, fresh `co_t05_*` per
  run).
- **8/8 PASS (12.3s):** 2 visual QA + 6 interaction tests (listed above).
- Error paths (422/409) are exercised at the network boundary with route
  interception — the only honest way to verify those UI states without
  corrupting shared QA data; success/confirmation/immutability use real
  backend mutations.

## 6. Visual QA

- Screenshots (desktop 1440×900 + mobile 390×844) in `output/qa-s06-t05/`:
  `desktop|mobile390-{cogai-review,thocute-problems,boyhacker-published}.png`.
- Structural probe (`output/qa-probe-s06-t05.js`): no horizontal overflow at
  390px (scrollWidth 390), pose images load from the content endpoint,
  publish button enabled/disabled states correct, no publish control on
  published versions. (Probe was run because the session model cannot view
  images; PNGs are the pixel evidence for PM review.)

## 7. Quality baseline

- `scripts/quality-baseline.ps1` run fresh in this worktree.
- **Run ID: `20260805-091121`** (summary: `output/quality-baseline/20260805-091121/summary.json`) — **7/7 gates PASS** (exit 0):
  Gate 1 preflight PASS · Gate 2 Python tests PASS (167.53s) · Gate 3 ruff PASS ·
  Gate 4 mypy PASS · Gate 5 tsc PASS · Gate 6 eslint PASS · Gate 7 next build PASS.
  (An earlier run `20260805-090643` caught one lint error in the new publish
  code — `react-hooks/set-state-in-effect` — which was fixed by moving the
  feedback reset into the version-select event handler; the rerun is fully
  green.)

## 8. Exit state

- REPORT = **SUBMITTED**. No commit, no push, no approval granted.
- MAIN repo untouched (per incident decision); `output/backup-pre-copy/` kept
  for PM review; `output/quarantine-t05-corrupt/` holds the removed test.
- Deviations: GPU/SAM2/integration-marked tests excluded by the project's
  quality gate marker (same as previous sessions).
