# S08-P00 — Integration Report (Integrated S05 + S06 Base)

- **Status:** `SUBMITTED` (never APPROVED — Codex performs the PM review)
- **Hermes session:** `20260805_221944_13b889`
- **Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`
- **Branch:** `codex/s08-integration`
- **Base:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
- **Started:** 2026-08-05 22:19 +07:00
- **Submitted:** 2026-08-05 ~23:40 +07:00
- **Quality Run ID (final):** `20260805-232332` — 7/7 PASS
- **Integration evidence Run ID:** `20260805-223518`

## Outcome delivered

One non-destructive integrated working tree containing the exact approved S05 and
corrected S06 product behavior, with semantic reconciliation of the four shared files
and fresh integration evidence. MAIN and both source worktrees (`prepare-s05-t01`,
`s06-t01-review`) remain byte/status unchanged. This preparation task implements no S08
product behavior.

## Source manifests and isolation

- Pre-write guard recorded in LOG.md BEFORE the first write: `pwd`/toplevel =
  `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`, branch `codex/s08-integration`,
  HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`, `git status --short` = exactly the
  S08-P00 packet dir, single-writer confirmed (`process(action='list')` empty).
- Both authoritative manifests recorded VERBATIM in LOG.md via
  `git status --porcelain=v1`: S05 (`prepare-s05-t01`, 55 entries) and S06
  (`s06-t01-review`, 45 entries); both source HEADs verified == integration base.
- Protected baseline recorded: MAIN `channels.json` SHA-256
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; MAIN
  `data/motionforge.db` 311296 bytes / 2026-08-04 18:24:36 (forbidden, never opened);
  MAIN status 45 entries; S05 55 entries; S06 45 entries.
- 88 manifest entries copied FILE-BY-FILE (never a recursive repo copy) from the two
  authoritative worktrees into the integration tree. Exclusions honored:
  `frontend/test-results/.last-run.json` (both trees), `frontend/playwright-report-s05t05/`
  (generated report), S06 launcher scripts/logs, the S06 quarantined corrupt test
  `tests/test_pack_publish_ux.py` (absent from the S06 manifest — quarantined by the S06
  correction) and its obsolete nested API contract (exists in no imported source).
- Byte fidelity after copy: 17/17 S05 sample paths byte-identical; 18/19 S06 sample
  paths byte-identical — the single deviation is the documented whitespace-only EOF
  blank-line trim of `app/persistence/models.py` (+ the same trim on the S06-T05
  `LOG.md`), required for `git diff --check`; content otherwise == S06 bytes.

## Shared-file reconciliation (semantic merge — decisions in LOG.md)

| File | Merge |
|---|---|
| `app/api/app.py` | S05 explicit public lifecycle (JobService.initialize() -> public session_factory -> one Lifecycle; orchestrator ensure_started/stop; NO private attribute reads) + S06 `durable_characters` import + `include_router` after durable_summaries. |
| `app/api/deps.py` | S06 base (get_managed_root / get_db_session / SessionDep) + S05's 4 durable accessors using the public `job_service.session_factory`; S06's private reads converted to the S05 public contract (`svc.managed_root`, `job_service.session_factory`). 0 private reads remain; line count == S06's (279). |
| `frontend/src/lib/api.ts` | S05 superset (ApiError + detail unwrap + detailText, JobInfo with `pending` + optional legacy fields, ChainStep/AnalyzeChainState types, analyzeProject/getAnalyzeChain/retryAnalyzeChain/cancelAnalyzeChain, cancelJob `{status, job_id}`) + S06 Durable Character Library section (all character types, CORE_POSE_SLOTS + 3 label maps, listCharacters/getCharacter/listCharacterVersions/getPackVersionValidation/publishCharacterVersion/getCharacterAssetContentUrl). 1015 lines; tsc clean. |
| `docs/pm/ROADMAP.md` | S05 history preserved (S04-T05 + S05 APPROVED, sprint status lines, S05-C01..C04 notes) + S06 rows APPROVED (T05 per the S06-T05 PM_REVIEW 2026-08-05T09:28) + one S06 sprint-status note; S08 rows untouched (unopened until P00 approval). |

Fixture overlaps (`tests/fixtures/legacy_import/`): 5 files differ S05<->S06 ONLY by
CRLF (verified `diff --strip-trailing-cr`); S06 bytes used for the 5 manifest-listed
files; all other fixtures byte-identical across trees. One layout gap found by the
baseline: the EMPTY dir `corrupt/projects/no_json/` (present in both sources) was
re-created, and 4 base-tracked `importable/**` fixtures were normalized to the exact
LF bytes both source worktrees hold (the integration checkout had CRLF via autocrlf;
the byte-sensitive legacy-import tests hash them). Proof: `git hash-object` == base
blob for all 4, `git diff` empty; residual ` M` status entries are the autocrlf
smudge-comparison artifact only.

## Validation (each run separately from the integrated tree)

| # | Gate | Result |
|---|---|---|
| 1 | S05 final suite (7 files: orchestrator_binding, atomic_cancel, production_wiring, lifecycle, chain_progression, orchestration, golden_integration) | **41 passed** (81.37s) — matches Codex 41/41 |
| 2 | S06 corrected suite (5 files: character_read_api, publish_rejection, character_domain, character_validator, character_preset_importer) | **90 passed** (29.05s) — matches S06 90/90 |
| 3 | Focused shared-file proof | suites 1+2 exercise app.py/deps.py both sides; api.ts both sides proven by the e2e suites below + tsc; ROADMAP verified by grep (S00–S06 complete, S08 unopened) |
| 4 | `python -m ruff check app tests` | All checks passed |
| 5 | `python -m mypy app` | Success: no issues in 72 source files |
| 6 | `npx tsc --noEmit` | exit 0 |
| 7 | `npm run lint` | 0 errors, 9 warnings (== S06 known-warning set) |
| 8 | `npm run build` (production) | exit 0; /characters + /import-analyze generated |
| 9 | `git diff --check` | exit 0 (after the EOF trims; CRLF advisory warnings only) |
| 10 | Integration UI smoke DESKTOP (Playwright, isolated root `20260805-223518`) | **20/20 passed** (53.2s) |
| 11 | Integration UI smoke 390px MOBILE (Playwright, same isolated root) | **12/12 passed** (29.3s) |
| 12 | Quality baseline `scripts/quality-baseline.ps1` | **Run ID `20260805-232332`: 7/7 PASS, OVERALL PASS (exit 0)** — Gate 2 `825 passed, 19 skipped, 7 deselected` in 291.09s |

Baseline note: the first baseline run `20260805-231404` failed Gate 2 on exactly the 2
legacy-import tests described above; root cause fixed (empty `no_json/` dir + LF
fixture normalization, both fidelity-to-source) and the final fresh run is fully green.
The failed run is preserved as evidence.

## Integration smoke details (run ID `20260805-223518`)

- Backend: bare production entrypoint `uvicorn app.main:app` on :8003, cwd +
  MOTIONFORGE_ROOT/OUTPUT/MODELS = NEW `output/s08-p00-integration/20260805-223518/backend-root`;
  the real lifespan Alembic-bootstrapped the NEW DB (incl. S06 character schema
  d5e6f7a8b9c0) and started the durable worker + chain orchestrator (health 200).
- Seed: P00 seed copy -> 5 REAL characters (co_gai 6/6, co_hai 6/6, tho_cute 3/6,
  boy_hacker published, fresh per-run success target) with real managed PNG artifacts.
- Frontend :3011 (NEXT_PUBLIC_API_URL=:8003). NOTE: an old S05 dev server still owned
  :3011 and served the S05 tree's pages (first Playwright attempts hung on it); it was
  killed (PID 74428) and the frontend restarted from the integration tree — verified the
  served /characters HTML before re-running. Machine-state incident, not a code issue.
- Desktop 20/20: Import/Analyze interaction 6/6 (empty state, real T02→T03→T04
  completion, atomic chain cancel, successor retry, resume no-duplicate, retry honesty)
  + visual 6/6 (setup/file-selected/progress/completed/preflight-error × desktop/390px
  with full-bar + 100% assertions); Character Library interaction 6/6 (incomplete
  disabled, confirmation-cancel 0 POSTs, honest 422, 409 no-retry + refresh, publish
  success → immutable, published-no-controls) + visual 2/2 (desktop + 390px
  review/problems/published).
- Mobile 390px 12/12: both interaction suites at mobile width (one re-seed was needed
  for the per-run publish target — the documented S06 harness precondition).
- Evidence: `output/s08-p00-integration/20260805-223518/` = seed-state.json, seed
  script, backend-root/ (isolated DB + 57 MB artifacts), screenshots/ (16 PNGs),
  test-results/ (`.last-run.json`: passed, no failed tests).

## Protected-state comparison (final)

- MAIN `channels.json` SHA-256 unchanged; MAIN DB stat unchanged; MAIN status 45
  entries (unchanged); S05 55 entries (unchanged); S06 45 entries (unchanged).
- No commits, pushes, merges, branch/worktree operations, stash, reset, checkout,
  restore, clean, or deletions anywhere.

## Changed files (integration tree only)

- Imported: 88 manifest entries (S05 + S06 source/test/architecture/session-packet
  paths — full list in LOG.md).
- Semantic merges: `app/api/app.py`, `app/api/deps.py`, `frontend/src/lib/api.ts`,
  `docs/pm/ROADMAP.md`.
- Fidelity fixes: EOF blank-line trims (2), empty `no_json/` dir, 4 `importable/`
  fixtures normalized to source bytes.
- P00 evidence tooling (NEW, same pattern as S05-C04-R3): `frontend/playwright.s08-p00.config.ts`,
  `frontend/e2e/s08-p00-import-analyze.spec.ts`, `frontend/e2e/s08-p00-import-analyze-visual.spec.ts`,
  `frontend/e2e/s08-p00-pack-publish-ux.spec.ts`, `frontend/e2e/s08-p00-pack-publish-ux-visual.spec.ts`,
  `output/s08-p00-integration/20260805-223518/qa-seed-s06-t05-p00.py`.
- Packet: `docs/pm/sessions/S08-P00-integrated-base/LOG.md` (append-only, status
  SUBMITTED), this `REPORT.md` (SUBMITTED). `TASK.md` untouched; `PM_REVIEW.md` untouched
  (PENDING — Codex owns it).

## Remaining risks / notes for Codex

- The integration tree is intentionally uncommitted (packet forbids commit/merge); the
  full S08 product sprint must build on this tree's working state.
- The 4 `importable/` ` M` status entries are the autocrlf artifact described above
  (bytes == base blobs; `git diff` empty) — no content deviation from either source.
- The P00 e2e tooling copies are needed to reproduce the isolated smoke; if the PM
  prefers them elsewhere they can be moved without touching product code.
- `output/` trees and `frontend/node_modules` are gitignored; both baseline runs
  (failed + final) are preserved under `output/quality-baseline/`.

## Recommended decision

`PENDING` — awaiting Codex PM review. Status `SUBMITTED` only. S08-T01 is not released
until this packet is APPROVED.
