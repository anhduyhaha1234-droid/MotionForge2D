# S12-T01 LOG — Export preflight + frozen contract

Owner session task S12-T01, branch `codex/s12/s12-t01-0907a`, wave-base `1f5936d`.
Evidence dir: `C:/Users/Admin/MotionForge2D-evidence/s12/20260907-083200-s12-coding/s12-t01`.

## 1. Baseline (2026-09-07 UTC)

Commands (worktree `C:/Users/Admin/MotionForge2D-worktrees/s12-s12-t01-0907a`):

- `git status --short --branch` → `## codex/s12/s12-t01-0907a`, clean (no output rows).
- `git log --oneline -1` → `1f5936d docs(s11-int01): C4-R4 no-ff 7c58c37 (TASK_SUBMITTED, pending push)`.
- `sha256sum app/api/app.py` → `ef4c0651d474c07b30bc7ef7d694263d4e036cbc9f06997a9e8737aabee6215e`, 219 lines / 9261 bytes (preimage for bounded patch).
- Allowlist files absent (verified): `app/schemas/s12_export.py`, `app/services/s12_export/`, `app/api/routes/s12_export_preflight.py`, `docs/contracts/s12-export.md`, `tests/s12/`.
- `python -c fastapi/pydantic` → `0.139.2 / 2.13.4`.

Required reading done: HERMES_AUTOPILOT_RULES.md (277 lines, full), packet
S12-CODING-HERMES-PROMPT-20260907.md §5/§6/§7 (162 lines, full), AGENTS.md +
frontend/AGENTS.md, MASTER_PLAN WS-08/WS-09/G5/Scenario F-G, readiness route +
T03G authority + S10 repo + structural-lock repo + QC policy bundle.

## 2. TARGET checklist (Step 1)

1. Frozen schemas `app/schemas/s12_export.py`: request/response strict, reason
   codes enum, manifest/profile/checkpoint/validation/publication contracts.
2. Pure preflight `app/services/s12_export/preflight.py`: native-4K vs upscale
   from provenance, aspect policy, disk/source/readiness/stale-identity checks,
   NO render in evaluation path.
3. Route `POST /api/v2/projects/{id}/export/preflight` + GET OpenAPI surface,
   fail-closed mapping NotFound→404 / Ownership→409 / Params+Stale→422.
4. Contract doc `docs/contracts/s12-export.md` + bounded `app.py` patch
   (import + register only, hash verified after).
5. Tests `tests/s12/s12-t01/`: green matrix incl. missing/corrupt/stale/
   cross-project/unsupported negatives + native/upscale/aspect/disk/ready
   positives + OpenAPI schema test; no real DB/media; no ports 3187/8187/18769.

## 3. Design notes

- Readiness consumed via `compute_project_readiness` (Decision F, no table) —
  upstream implementation untouched.
- S10 checkpoint pin: `ApplyCheckpoint` (revision=1 immutable) + expected
  hash/revision compare; stale → `S12_EXPORT_STALE_CHECKPOINT`.
- StructuralLock: `get_current_manifest(ws, pid, vid, generation)` — missing →
  `S12_EXPORT_LOCK_MISSING`; `source_generation` ties video ↔ manifest.
- Native 4K = source width/height == 3840x2160 AND manifest frame provenance;
  else if target 4K → upscale w/ method label (Scenario F honesty).
- Aspect: target DAR must equal source DAR within epsilon else
  letterbox-required or fail-closed unsupported profile.
- Disk: `shutil.disk_usage` on managed root; estimate = width*h*frames*bpp
  heuristic, frozen constant with basis string (estimate, not fake number).
- Source media: artifact row for `video.source_artifact_id` must exist and be
  `state == 'ready'`; `.partial` in path → rejected.
- QC negative seeding reuses T05A pattern: raw-SQL ws/project/video inserts,
  run via `JobRepository` + completion block helpers.
2026-09-07 09:32 SEAST

## Implementation + verification
- Schemas frozen s12-export-v1 (14 reason codes, 3 profiles, validation/publication contracts).
- Pure preflight: provenance-native, letterbox/fail-closed, disk fail-closed.
- Route verdict-only (no render); disk_usage walk-up robust tmp root.
- app.py bounded +5 (hash 7334f81b, 224 lines/9424 bytes).
- Tests 15/15 pass (basetemp $TEMP/s12t01_i); ruff F clean; regression S10 15 + S11-readiness 9 pass.
- Debug note: QC seed manifest source identity must pair producer-exact (None+empty iff no-source) else coverage-stale not_run.
