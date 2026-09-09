# S12-T06A — Windows packaging (staged beta package, C2)

Status: C2 correction in progress (F09 closure: relocatable staged
package + process-identity safety). Worktree: `s12-s12-t06a-0907a` |
Branch: `codex/s12/s12-t06a-0907a` | Baseline: `6fc6aef`.

## What this is

A relocatable STAGED beta package for Windows:

- `packaging/windows/` — launchers (`Install/Start/Stop/Uninstall`),
  dependency/build manifest (`manifest.json`, generated), README.
- `scripts/s12/` — stage builder, package manifest builder, fail-closed
  preflight, lifecycle runner (`setup / serve / diagnose / stop /
  uninstall`).
- `tests/s12/s12-t06a/` — process-identity / manifest-integrity /
  data-retention tests.
- This doc — prerequisites, install, run, uninstall, and the exact
  blocker policy.

The package is a **staged build**, not a fully self-contained portable
bundle: it bundles the built frontend (`frontend/.next`, baked at build
time with the packaged backend port) and the backend artifact (app
tree), and DECLARES the external runtimes it needs. It never installs
anything, never downloads, never elevates, and never edits
PATH/registry/firewall/ACL.

## Declared external prerequisites (probed — never installed)

| Requirement | Check | Missing ->
|---|---|---|
| Python 3.11.x (>=3.11,<3.13) | `python --version` | `BLOCKED_PYTHON_VERSION` |
| Node.js 20+ (`node`; `npm` only needed at stage/build) | `node --version` | `BLOCKED_NODE_MISSING` |
| FFmpeg (exits 0 on `-hide_banner -version`) | ffmpeg probe | `BLOCKED_FFMPEG_MISSING` |
| Localhost bind on 127.0.0.1 | preflight bind probe | `BLOCKED_LOCALHOST_BIND` |
| Writable runtime roots | probe-write data/artifacts/output/logs | `BLOCKED_RUNTIME_ROOTS_NOT_WRITABLE` |

Missing prerequisite = exact blocker (exit 3 + `NOT_RUN`, never waived).

## Build the stage (C2: relocatable package)

```cmd
Install-MotionForge-Beta.cmd STAGE_ROOT [BACKEND_PORT] [FRONTEND_PORT]
```

or directly:

```bash
python scripts/s12/s12_t06a_stage.py --stage-root <ABS> \
    --backend-port 8426 --frontend-port 3126
```

What the stage does (real build/runtime boundary):

1. **Rebuilds the frontend** with `NEXT_PUBLIC_API_URL` set to the
   packaged backend (`http://127.0.0.1:<backend-port>`), so
   `next.config` rewrites are baked at BUILD time — never the dev
   default port.
2. Copies backend artifact (`app/`, `alembic.ini`, `migrations/`) to
   `stage/backend/`, frontend build + lockfile + runtime node_modules
   (dev-only packages excluded) to `stage/frontend/`.
3. Copies lifecycle scripts + launchers + README.
4. Writes `manifest.json` (schema `s12-t06a-package/2`): backend exact
   pins from `pyproject.toml`, frontend ranges + REAL locked versions
   (scoped packages included — no null locks), artifact hashes
   (BUILD_ID + sha256, required-server-files sha256, backend tree
   digest), baked endpoint, and toolchain VERSIONS ONLY (no absolute
   user paths).

Refusals: stage root inside the repo checkout, inside protected MAIN
tree, existing stage (never overwrite), node/npm missing.

## Run the lifecycle from the staged root (C23)

With the stage on an owned path OUTSIDE the repo checkout and only the
declared runtimes on PATH:

```bash
python <stage>/scripts/s12_t06a_run.py setup --install-root <RT>
python <stage>/scripts/s12_t06a_run.py serve --install-root <RT>
python <stage>/scripts/s12_t06a_run.py diagnose --install-root <RT>
python <stage>/scripts/s12_t06a_run.py stop --install-root <RT>
python <stage>/scripts/s12_t06a_run.py uninstall --install-root <RT>
```

- `serve` spawns backend (`uvicorn app.main:app` from `<stage>/backend`)
  + frontend (`node <stage>/frontend/node_modules/next/dist/bin/next
  start` — never `npx`), waits `/health` + `/`, writes RUNTIME.json.
- Every spawned process records **identity**: PID + creation time +
  executable + command line + ownership token. `stop` re-probes live
  identity; a reused/wrong PID (creation-time/exe/cmd mismatch) is
  REFUSED — never killed — evidence written (`evidence/stop_evidence.
  json`) and exit nonzero with pids retained.
- `uninstall` keeps user data (`data/ artifacts/ output/`) by default;
  deletion requires explicit `--no-keep-data --confirm-remove-data`.

Runtime root `<RT>` must be a user-local OWNED dir — the protected MAIN
tree and the package tree itself are rejected (C25-part qa-root guard).

## Manifest integrity (C24)

- backend pins exact `==` (17), frontend pins with locked versions.
- Artifact hashes in manifest; preflight re-checks BUILD_ID parity and
  required-server-files presence; tamper/missing/wrong-endpoint all
  fail closed (`BLOCKED_MANIFEST_STALE`, `BLOCKED_WRONG_ENDPOINT`, ...).
- Endpoint correctness at build boundary: preflight scans the staged
  `.next` build manifests/server chunks for the manifest
  `api_base_url`; a build baked for the wrong port (dev default) is
  rejected.
- No secrets, no absolute Admin tool paths in manifest/scripts
  (toolchain = versions only); repo-wide hardcode scan in gates.

## Forbidden (never in this package)

Hardcoded `C:\Users\Admin`, system install / PATH / firewall / registry
writes, elevation, model/cert downloads, bundling user DB/keys/media,
labeling the developer launcher as portable/bundled. Missing approved
bundler/runtime/license prerequisite = exact blocker; no silent
workaround, no waiver.

## Clean-machine row (C23 external)

This machine is not a clean Windows VM with dev runtimes stripped. The
local row runs the staged package from a path outside the checkout with
only the declared tool dirs on a scrubbed PATH; the external clean-VM
counterpart remains `NOT_RUN` and is recorded, never waived.