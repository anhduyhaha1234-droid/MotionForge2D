# S12-T06A LOG — C2 (F09 closure: staged package + process-identity safety)

Task: S12-T06A (C2) | Worktree: `s12-s12-t06a-0907a` | Branch:
`codex/s12/s12-t06a-0907a` | Baseline: `6fc6aef` (clean, verified before
code) | Date: 2026-09-09

RULES_LOADED: `C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md`
SHA-256 c9b068b2195461b1f867a5ec95714cea3ab09881757f5607094574d15dda428f,
277 lines, read in full (sections 1–12). Review read in full:
`.../outputs/s12-c1-review-20260909/REVIEW.md` (F01–F11) +
`S12-C2-HERMES-PROMPT.md` (§4 T06A + §5 C23/C24/C25).

## Writes (allowlist only: packaging/windows/**, scripts/s12/**, docs/packaging/s12-windows.md, tests/s12/s12-t06a/**, docs/pm/sessions/S12-T06A/**)

1. `scripts/s12/s12_t06a_stage.py` (NEW, 190 lines) — relocatable staged
   package builder: validates stage root (absolute, outside checkout,
   outside protected MAIN, never overwrite), rebuilds frontend with
   NEXT_PUBLIC_API_URL baked at BUILD boundary, copies backend artifact
   (app/, alembic.ini, migrations/) + frontend artifact (.next,
   package.json/lock, runtime node_modules minus dev-only pkgs) +
   scripts/launchers, writes manifest.json (schema s12-t06a-package/2).
   Missing node/npm -> exact BLOCKER exit 3.
2. `scripts/s12/s12_t06a_run.py` (REWRITE, 500 lines) — package-root
   based (PACKAGE_ROOT from __file__, never repo hardcode); backend
   cwd=package/backend; frontend via `node node_modules/next/dist/bin/
   next start -p` (NO npx); process identity record {pid, creation_time,
   executable, command, expected_executable, command_marker, token};
   stop re-probes live identity and REFUSES reused/wrong PIDs (keeps
   evidence/stop_evidence.json, exit 1, pids retained); uninstall keeps
   data by default, removal needs --confirm-remove-data; install-root
   guard rejects protected MAIN and package tree.
3. `scripts/s12/s12_t06a_preflight.py` (REWRITE, ~250 lines) — package
   aware (manifest in package root); probes ffmpeg/python/node/roots/
   localhost/package; package check: BUILD_ID parity, required-server-
   files presence, backend entry, endpoint baked at build boundary
   (`_baked_api_search` over .next manifests/server chunks); tamper/
   wrong-endpoint/missing-runtime -> BLOCKED_* exit 3.
4. `scripts/s12/s12_t06a_build_manifest.py` (REWRITE, ~200 lines) —
   manifest with REAL locked frontend versions (scoped-aware, no null
   locks), toolchain VERSIONS only (F09: no Admin tool paths), endpoint
   + artifact hashes (BUILD_ID sha256, required-server-files sha256,
   backend tree digest).
5. `packaging/windows/*.cmd` (REWRITE ×4) + README-BETA.txt — staged
   launchers taking PACKAGE_ROOT [+RUNTIME_ROOT], honest wording
   (staged package + declared external runtimes, not "portable").
6. `docs/packaging/s12-windows.md` (REWRITE) — prereqs, stage build,
   lifecycle, manifest integrity, forbidden list, clean-machine NOT_RUN.
7. `tests/s12/s12-t06a/` (NEW ×2, 17 tests) — process identity
   (identity_ok match/refuse wrong creation/exe/cmd; stop refuses
   foreign pid keeps evidence; stop clears gone pids), uninstall data
   retention (keep/refuse/confirm), install-root guard (MAIN + package
   tree rejected), manifest integrity (exact pins, real locks, scoped
   present, no user paths in toolchain, localhost endpoint).

## Live verification (real outputs, ports 8426/3126, C2 root
`C:/Users/Admin/MotionForge2D-evidence/s12/20260909-211318-C2`)

- `s12_t06a_stage.py --stage-root <C2>/s12-t06a/stage`: STAGE_EXIT 0;
  npm run build with NEXT_PUBLIC_API_URL=http://127.0.0.1:8426 ->
  BUILD_ID ilMFXRHX0rRYMrBt7RD0E (first attempt failed: next
  transpile-config cannot find typescript after node_modules prune ->
  kept typescript, rebuilt clean).
- Preflight (staged scripts, cwd=C2 root): 6/6 READY — manifest+build
  agree, endpoint 8426 baked, backend entry present.
- setup: exit 0. serve: backend pid 11748 (created
  2026-09-09T21:21:08.344+00:00) /health 200; frontend pid 14832
  (created 2026-09-09T21:21:13.575+00:00) / 200, /export 200.
- diagnose: READY 6/6, processes identity verified both.
- stop: exit 0, ports 8426/3126 down, pids cleared.
- uninstall: exit 0, data/ (motionforge.db + sentinel) preserved;
  --no-keep-data without confirm -> exit 3 BLOCKED, data still there.
- C24 negatives (tamper clone): build_id tamper -> BLOCKED_MANIFEST_STALE;
  endpoint 9999 -> BLOCKED_WRONG_ENDPOINT; PATH without node/ffmpeg ->
  BLOCKED_NODE_MISSING + BLOCKED_FFMPEG_MISSING; Admin-path grep 0 hits.
- pytest tests/s12/s12-t06a/: 17 passed (~41s) ×2 runs.
- Gates: ruff --select F scripts/s12/ tests/s12/s12-t06a/ All checks
  passed; git diff --check 0; py_compile OK; porcelain allowlist only.
- Known pre-existing (NOT mine): tests/s12 collection shows 5 duplicate
  test_c1_closure.py errors in s12-t02/t03b/t03c/t04a dirs — owned by
  those task owners (C2), T06A dir collects clean.

## Notes / pitfalls found

- Node_modules prune must keep `typescript` (next.config.ts transpile).
- WMI CreationDate is `/Date(ms)/` — normalized to ISO in
  `_normalize_wmi_date`; identity compare in seconds (±2s).
- CRLF/LF mixing in .cmd files trips `git diff --check` — normalized to
  LF before gate.
- Clean-machine row: local staged-outside-checkout lifecycle verified;
  external clean Windows VM remains NOT_RUN (recorded, never waived;
  beta/release blocked on it per C29/C23).