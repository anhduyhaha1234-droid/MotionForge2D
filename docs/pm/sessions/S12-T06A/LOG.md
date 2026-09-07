# S12-T06A LOG — Windows packaging (portable beta / installer harness)

Task: S12-T06A | Worktree: `s12-s12-t06a-0907a` | Branch: `codex/s12/s12-t06a-0907a`
Baseline: `f2cdf0e` (clean, porcelain 0 — verified before code) | Date: 2026-09-07

RULES_LOADED: `C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md`
SHA-256 `c9b068b2195461b1f867a5ec95714cea3ab09881757f5607094574d15dda428f`,
277 lines, read in full (sections 1–12) before any action.

## Writes (allowlist only: packaging/windows/ + scripts/s12/ + docs/packaging/s12-windows.md)

1. `scripts/s12/s12_t06a_build_manifest.py` (164 lines)
   - Real local state only: backend pins from `pyproject.toml` (17 exact `==`),
     frontend ranges + lockfile versions from `package.json`/`package-lock.json`
     (17), `.next/BUILD_ID` + `required-server-files.json` sha256 + static
     count, backend source sha256 (`app/main.py`, `app/api/app.py`,
     `app/config.py`, `app/lifecycle.py`, `alembic.ini`), toolchain probes.
   - Missing `.next` build -> exit 2 NOT_RUN (never faked).
2. `scripts/s12/s12_t06a_preflight.py` (170 lines, read-only)
   - 5 fail-closed probes: FFmpeg (`-hide_banner -version` rc 0, mirrors
     `ffmpeg_binary.py` contract), Python >=3.11,<3.13, writable runtime
     roots (probe-write+delete), 127.0.0.1 ephemeral bind, manifest<->`.next`
     BUILD_ID agreement + backend entry present.
   - Exit 0 READY (one JSON object on stdout); exit 3 BLOCKED_* + NOT_RUN,
     never waived.
3. `scripts/s12/s12_t06a_run.py` (411 lines)
   - `setup / serve / diagnose / stop / uninstall`. Code root derived from
     `__file__` (never hardcoded); runtime root `--install-root` (user-local,
     refuses protected MAIN tree). Backend env: `MOTIONFORGE_ROOT=<RT>`,
     `MOTIONFORGE_DATABASE_URL=sqlite:///<RT>/data/motionforge.db`,
     `MOTIONFORGE_QA_MODE=1`, CORS scoped to the served frontend port.
   - `serve` waits backend `/health` (90s) + frontend `/` (120s) before
     writing pids. `stop` = frontend-first graceful, `taskkill /T` whole
     tree + `/F` fallback (reported). `uninstall` keeps user data by default;
     `--no-keep-data` without `--confirm-remove-data` -> exit 3 BLOCKED.
   - Windows fixes found live: `os.kill(pid, 0)` raises `SystemError`
     (WinError 87) on CPython 3.11 -> `tasklist` lookup; `taskkill` without
     `/T` kills only the npx/cmd wrapper, orphaning `next-server` -> `/T`
     whole-tree kill.
4. `packaging/windows/` — `Install/Start/Stop/Uninstall-MotionForge-Beta.cmd`
   (CODE_ROOT + optional RUNTIME_ROOT args, no elevation/PATH/registry),
   `README-BETA.txt`, `manifest.json` (generated, build
   `SMMKnaiyQ5jEj09fkhU72`, 45 static files).
5. `docs/packaging/s12-windows.md` (126 lines) — prerequisites table,
   install/run/stop/uninstall, hardware matrix, manifest regen, forbidden
   list. Numbers are the real verified ones (see evidence).

## Live verification (real output, ports 8423/3123, runtime %LOCALAPPDATA%\s12-t06a-rt1)

- `npm run build` (fresh checkout, no node_modules): BUILD_EXIT 0
  (route list includes `/export`).
- Manifest: 17 backend pins, 17 frontend deps, build_id `SMMKnaiyQ5jEj09fkhU72`.
- Preflight: READY (ffmpeg 8.1.2-full_build-gyan GPL, python 3.11.9,
  writable data/artifacts/output/logs, ephemeral bind ok, manifest agree).
- `setup` + `serve`: SERVE_EXIT 0, backend pid 11352, frontend pid 11920.
- Post-serve (+20s): backend `/health` 200 `{"status":"ok"}`, frontend `/`
  200, `/export` 200, `diagnose` verdict READY (all 6 checks incl. pids
  alive, free 519351 MiB).
- `stop`: both down (connection refused, expected), data kept.
- `uninstall`: logs/temp cleaned, `data/` (`motionforge.db` + sentinel)
  PRESERVED; `--no-keep-data` w/o confirm -> exit 3 BLOCKED (as designed).
- Negative probes: PATH without ffmpeg dir -> `BLOCKED_FFMPEG_MISSING`
  exit 3; tampered manifest build_id -> `BLOCKED_MANIFEST_STALE` exit 3;
  restore -> READY again.
- Gates: `ruff check --select F scripts/s12/` All checks passed (fixed one
  live F401 unused `re` import), `py_compile` OK, `git diff --check` 0,
  porcelain = allowlist only (3 new dirs), hardcode-user-path scan 0 hits.

## Known limitations (not waived, recorded)

- L1: Windows console processes (uvicorn via Popen, npx/next-server) do not
  honor graceful SIGTERM; `stop` always falls to `taskkill /F /T` and logs
  `killed (/F fallback)`. Shutdown is still ordered (frontend first) and
  verified (ports down). No data-loss path: DB writes go through the app's
  own lifecycle, not the harness.
- L2: first backend boot runs full Alembic `head` upgrade (~40s on this
  machine, 21 revisions ending `c3d4e5f6a7b8` = current head); `serve`
  health-wait covers it (90s budget).
- L3: GPU present (torch cu128) but serve verified on CPU path only; GPU
  absence is not a blocker by design.
- Earlier cycle note: first serve (ports 8421/3121) reported READY then the
  backend subprocess vanished silently (log ends mid-migration, no error —
  infra-level kill, not app error; relaunched 8422 backend served
  `/health` + `/api/v1/health` + `/api/channels` fine). Final cycle
  (8423/3123) stayed up through all checks. Pids in evidence are final-cycle.
