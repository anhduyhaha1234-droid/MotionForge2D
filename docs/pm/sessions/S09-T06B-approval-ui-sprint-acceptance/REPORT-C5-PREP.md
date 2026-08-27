# REPORT — S09-T06B-C5-PREP (portable launcher + content-addressed different-evidence)

- Task: S09-T06B-C5-PREP | Owner session: 20260824_131423_423e42 | provider custom @ 9Router | model meta | reasoning max | TTFB 900 | fallback OFF
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration | branch codex/s08-integration | HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- Authority: Codex C4 REVIEW CHANGES_REQUESTED 2026-08-27 | F3/F4 (C5-R2) | RULES_LOADED 180 lines SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25
- Preflight: MOTIONFORGE_DATABASE_URL=UNSET | J1-v4 ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 13/13 (drift above is pre-existing sprint M files, not this PREP write-set; our write-set is untracked new FE files) | ports 8201/3115 have stray prior-run listeners (node+python) | PREP does NOT start production, B1 will quiesce before J1/J2.
- Workspace dirty: 32 M (all sprint code landed before this PREP) | this PREP touched ZERO app/**.

## Write-set (exclusive, verified on disk)

- frontend/e2e/s09-t06bc4-targeted-regeneration.spec.ts (1106 lines, 48647 B, mtime 12:25 +07) | portable launcher + F3 different-evidence corrected, affected-only proof preserved
- frontend/e2e/s09-t06bc4-helpers.ts (NEW, 6772 B) | launchIsolatedBackend / waitForBackendReady / stopLaunched (explicit python -m uvicorn, isolated MOTIONFORGE_ROOT/DB/output/ports, stdout/stderr captured, readiness asserted, finally cleanup; never spawn bash)
- frontend/playwright.s09t06bc4.config.ts (existing, not modified in C5)
- output/s09/20260823_sprint_full/t06b-c5/ (staging; README.md)
- docs/pm/sessions/S09-T06B-approval-ui-sprint-acceptance/{LOG.md, REPORT.md, REPORT-C5-PREP.md} (own docs)

Tuyet doi khong sua: app/**, backend tests/fixtures, T03/T04, J1-v4, MAIN/docs, S10/S11/S13.

## Required fixes (review C4) | how each is satisfied

### 1) F4 P1 launcher | deterministic Windows-compatible launcher
- Removed every spawn(bash) occurrence from runtime code (verified: runtime spawn(bash)=0, naive spawn.*bash=0 in spec).
- Alternate instance launch is via launchIsolatedBackend() -> spawn python -m uvicorn with cwd=runtimeRoot, env:{PYTHONPATH, MOTIONFORGE_ROOT=runtimeRoot, ...}, stdio via logFd | explicit Node spawn, no shell word, C:/ paths visible (cwd = runtimeRoot, no WSL translation). fs.openSync log capture, never stdio ignore.
- Primary restart also via same helper (no bash).

### 2) F4 P1 isolation | separate runtime root/DB/output/ports, logs+exit captured, cleanup in finally
- Alternate root: altRoot = path.join(RUN_ROOT, alt-backend-${runTag}) (unique per run). MOTIONFORGE_ROOT = altRoot -> lifespan creates isolated altRoot/data/motionforge.db + altRoot/artifacts + altRoot/output.
- Different port: ALT_PORT = 8212 (primary stays 8201 | no collision). Env MOTIONFORGE_S09_DECISION_DIR = altDir/frozen-c5-alt isolated per instance.
- Capture: logFile = path.join(runtimeRoot, prod-backend-${port}.log), logFd = fs.openSync(logFile,a), stdio [ignore, logFd, logFd]; waitForBackendReady(page.request, ALT_PORT) polls GET /api/v2/projects and asserts fs.existsSync(logFile) + log non-empty.
- Cleanup: try { ... } finally { stopLaunched(altLaunched); await page.waitForTimeout(1500); } | SIGTERM->SIGKILL grace, owned children only.

### 3) F3 P1 different-evidence | genuinely different verified content + same-bytes-different-path same-identity
- Same bytes, different path -> same identity (explicitly asserted): stage byte-identical copy via stage_frozen_copy.py into frozen-copy-same-${runTag}, verify copySha === DECISION_SHA256, then _c5_identity_check.py calls resolve_frozen_evidence_sha256(bench, decPrimary) vs resolve_frozen_evidence_sha256(bench, decCopy) and asserts sha_a == sha_b == genEv.frozen_evidence_sha256 + prints IDENTITY_SAME_BYTES_SAME_ID_OK.
- Genuinely different verified content -> different identity (real different-evidence case): _c5_stage_different_evidence.py flips independent_verification.i03_run_B.content_sha256 last hex char deterministically (still 64-hex, schema-valid) into altRoot/frozen-c5-alt/route_decisions json; resolve_frozen_evidence_sha256(altBench, altDec) is resolved and asserted expectedAltFrozen !== genEv.frozen_evidence_sha256 (content-driven, not path-driven). Backend canonical already is content-addressed (decision_sha256 + benchmark_content_sha256 + run_b_content_sha256), so path carries no authority.
- Stale/tampered never reaches mutation | covered by existing stale-confirm 409 + verifyFrozenChain + _pinned_evidence fail-closed (not re-added).
- The byte-identical-copy/different-path case is now explicitly the non-difference proof, not the difference proof. Zero frozen-byte mutation still asserted (verifyFrozenChain post-identity).

### 4) Preserve affected-only proof | unchanged
- d4 regenerates: regenerated=true, render_ms number, artifact_id + sha256 MUST change, frame_count preserved, real compositing delta via overlap fixture d4_group_1.
- d1/d2/d3 reused: regenerated=false, render_ms ?? null === null, base_publication verbatim (artifact_id/sha256/size_bytes/frame_count exact), DB attempt rendered_loop_count==1, affected_loop_ids==[d4_group_occlusion], single demo_loop_regen attempt.
- All other phases (A/B/B2/C/I/E/R/P6/F5/G) preserved verbatim; only R phase different-evidence mock + launcher/restart portability changed.

## Static checks (PREP boundary: TSC + scoped ESLint only, isolated cache/output, NO shared production start)

- npx tsc --noEmit (cwd frontend/) -> EXIT=0 (helpers stdios cast + distinct deduped + waitForBackendReady typed via page.request).
- npx eslint --max-warnings 0 e2e/s09-t06bc4-targeted-regeneration.spec.ts e2e/s09-t06bc4-helpers.ts e2e/s09-t06bc4-global-setup.ts -> EXIT=0.
- Config playwright.s09t06bc4.config.ts not modified; npx eslint on it also 0 via broad check.
- No next build, no backend start, no Chromium run in PREP (per prompt boundary).

## Self-audit (discipline 5 | soft proof here; Manager re-audits at B1/J2)

- MOTIONFORGE_DATABASE_URL=UNSET verified; J1-v4 manifest SHA ae92247b direct file match (drifted 7 renderer files are pre-existing sprint M, not this PREP write-set | our write-set is untracked new FE files, 0 app/** edits).
- No app/** write by this PREP (git diff --name-only -- app/ drifts are pre-existing; git status --porcelain -- app/workflow/s09_demo_jobs.py untracked snapshot = no edit, just C4 file still untracked).
- Ports 8201/3115 show prior-run stray listeners (node 27452 + python 1112) | PREP did not start/collide; B1 quiescence will attribute + stop task-owned ones only.
- Helper s09-t06bc4-helpers.ts is T06B-owned under authorized frontend E2E scope (frontend/e2e/*).

## STATUS: TASK_SUBMITTED | PREP / AWAITING_B1_JOIN

Launcher portable (explicit python -m uvicorn, isolated root/DB/output/ports, logs+readiness, finally cleanup) + corrected F3 assertions (same-bytes->same-identity + genuinely-different verified content->different identity) authored; TSC+scoped ESLint PASS; KHONG chay Chromium production acceptance truoc J2-C5. Cho Manager B1 quiescence -> J1 backend mutex (T03+T04 focused x2 long basetemp) -> J2 re-hash + audit T06B scope -> resume same owner (20260824_131423_423e42) cho final Chromium x2 sequential voi isolated fresh state.
