# S12-T06A — Windows packaging (portable beta / installer harness)

Status: local harness verified (`TASK_SUBMITTED` scope — no push/merge).
Worktree: `s12-s12-t06a-0907a` | Branch: `codex/s12/s12-t06a-0907a` |
Baseline: `f2cdf0e`.

## What this is

A local-only packaging harness for clean-machine Windows beta installs:

- `packaging/windows/` — portable-beta launchers (`.cmd`), dependency
  manifest (`manifest.json`, generated — pinned backend pins from
  `pyproject.toml`, frontend ranges + lockfile versions, compiled
  `.next` BUILD_ID fingerprint, toolchain probes).
- `scripts/s12/s12_t06a_*.py` — manifest builder, fail-closed preflight,
  lifecycle runner (`setup / serve / diagnose / stop / uninstall`).
- This doc — prerequisites, install, run, uninstall, hardware matrix,
  and the explicit-blocker policy.

What this is NOT: no system install (no PATH/firewall/registry writes),
no elevation, no bundled Python/Node/FFmpeg, no signing cert, no model
download, no user-data bundling.

## Prerequisites (declared, never silently installed)

| Requirement | Minimum | Check |
|---|---|---|
| Python | 3.11.x (>=3.11, <3.13) | `python --version` |
| Node.js | 20+ (provides `npx`, used for `next start`) | `node --version`, `npx --version` |
| FFmpeg | any `ffmpeg -hide_banner -version` exits 0 | `ffmpeg -hide_banner -version` |
| Disk | 2 GiB free under the runtime root | `diagnose` reports free MiB |
| OS | Windows 10/11 x64, localhost bind allowed | preflight `localhost` check |

Verified local matrix (2026-09-07): Python 3.11.9, Node v26.4.0,
npm 11.17.0, FFmpeg 8.1.2-full_build-www.gyan.dev (GPL build,
`--enable-gpl`), Windows 10 x64, CUDA GPU present
(torch 2.11.0+cu128, `cuda.is_available()=True`) — GPU is optional;
CPU render path works without it.

Missing anything = explicit blocker: preflight/serve exit 3 and print
`BLOCKED_*` + `NOT_RUN` with the exact missing env. Blockers are
recorded, never waived.

## Install (portable beta)

```cmd
Install-MotionForge-Beta.cmd CODE_ROOT [RUNTIME_ROOT]
```

- `CODE_ROOT` = repo checkout this beta was staged from (contains
  `scripts/s12/s12_t06a_run.py` + `packaging/windows/manifest.json`).
- `RUNTIME_ROOT` = user-local dir holding `data/ artifacts/ output/
  logs/ RUNTIME.json` (default `%LOCALAPPDATA%\MotionForge2D-beta-runtime`).
- Refuses to use the protected MAIN tree (`%USERPROFILE%\MotionForge2D`)
  as the runtime root.

## Run

```cmd
Start-MotionForge-Beta.cmd CODE_ROOT [RUNTIME_ROOT]
```

Or directly:

```bash
python scripts/s12/s12_t06a_run.py setup --install-root <RT>
python scripts/s12/s12_t06a_run.py serve --install-root <RT> \
  --backend-port 8421 --frontend-port 3121
python scripts/s12/s12_t06a_run.py diagnose --install-root <RT>
```

`serve` spawns backend (`uvicorn app.main:app` on 127.0.0.1) + compiled
frontend (`next start`), waits for backend `/health` and frontend `/`,
then writes pids to `RUNTIME.json`. First backend boot runs the Alembic
`head` upgrade into `<RT>/data/motionforge.db` (fresh file, user-local).

Verified 2026-09-07 (runtime `%LOCALAPPDATA%\s12-t06a-rt1`, ports
8423/3123): backend `/health` 200 `{"status":"ok"}`, frontend `/` 200,
`/export` 200, `diagnose` verdict READY (all 6 checks), `static_file_count`
45, build `SMMKnaiyQ5jEj09fkhU72`.

## Stop / uninstall

```cmd
Stop-MotionForge-Beta.cmd CODE_ROOT [RUNTIME_ROOT]
Uninstall-MotionForge-Beta.cmd CODE_ROOT [RUNTIME_ROOT]
```

`stop` terminates frontend then backend gracefully (whole process tree
via `taskkill /T`; `/F` fallback reported, never silent). `uninstall`
stops, cleans `logs/` + temp files, and KEEPS user data (`data/`,
`artifacts/`, `output/`) by default; `--no-keep-data
--confirm-remove-data` is required to delete them.

## Supported hardware matrix

| Tier | CPU / RAM | GPU | Render path | Status |
|---|---|---|---|---|
| Minimum | x64 4-core / 8 GiB | none (CPU) | CPU preview + FFmpeg encode | supported (preflight-enforced deps only) |
| Recommended | x64 8-core / 16 GiB | NVIDIA GTX 1660+ / CUDA 12.x | GPU-accelerated (torch cu128) | verified present, optional |
| Beta-tested | Win10 x64, 500+ GiB free | CUDA available | CPU serve verified 2026-09-07 | READY |

GPU absence is NOT a blocker (CPU path). Missing Python/Node/FFmpeg,
unwritable roots, or no localhost bind ARE blockers (exit 3 + NOT_RUN).

## Manifest

Regenerate after any dependency or frontend change:

```bash
python scripts/s12/s12_t06a_build_manifest.py
python scripts/s12/s12_t06a_preflight.py --install-root <RT>
```

`manifest.json` schema `s12-t06a-manifest/1`: backend pins (17, exact
`==` from `pyproject.toml`), frontend ranges + locked versions (17),
`.next` BUILD_ID + `required-server-files.json` sha256 + static count,
toolchain probes. Preflight refuses a stale manifest
(`BLOCKED_MANIFEST_STALE` when manifest build_id != `.next/BUILD_ID`).

## Forbidden (never in this harness)

Hardcoded `C:\Users\Admin`, system install / PATH / firewall / registry
writes, elevation, model download, signing certs, bundling source video /
user DB / keys / model weights. No dev checkout, Python, or Node is
assumed without the declaration above; anything missing is a blocker.
