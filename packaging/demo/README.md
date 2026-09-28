# MotionForge 2D — demo delivery package (MF-END-28)

This directory describes how the demo delivery is PACKAGED, checked and
launched.  It does not replace the frozen S12-T06A contract: the files
under `packaging/windows/`, `scripts/s12/` and `tests/s12/s12-t06a/`
stay byte-identical (their hashes are recorded in
`packaging/demo/inventory.json -> frozen_packaging`).

| File | Role |
|---|---|
| `inventory.json` | measured inventory: backend pins, frontend pins, toolchain versions, Comfy engine + dependency pins, external model section, frozen-packaging hashes, guardrail scans |
| `models.json` | external model manifest (rel path / sha256 / bytes / license / source) — `bundled: false` |
| `build_demo_package_inventory.py` | regenerates both files deterministically |
| `README.md` | this guide |

The launcher lives at the repo root: `scripts/mf_delivery_launcher.ps1`.
The staged package is built by the frozen harness (`Install-MotionForge-
Beta.cmd` / `scripts/s12/s12_t06a_stage.py`) to a path OUTSIDE the
checkout; nothing is copied into this repo.

## 1. Setup (declared external runtimes — probed, never installed)

| Requirement | Check | Missing -> |
|---|---|---|
| Python 3.11 (>=3.11,<3.13) | `python --version` | `TOOL_MISSING` blocker |
| Node.js 20+ (staged frontend runtime) | `node --version` | `TOOL_MISSING` blocker |
| FFmpeg | `ffmpeg -hide_banner -version` | `TOOL_MISSING` blocker |
| Model root (external, read-only) | `-ModelsRoot` or `MF2D_MODELS_ROOT` | `MODELS_ROOT_UNSET` blocker |

Model weights are NEVER bundled: they stay under the external root
declared by `models.json` (`root_env: MF2D_MODELS_ROOT`).  The launcher
falls back to the root declared by `app/media_workflows/
model_profiles.json` (`engine.models_root`) when `-ModelsRoot` is not
given, then `models.json` (`models_root` field when present).

## 2. Checks

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\mf_delivery_launcher.ps1 -Action check `
  -PackageRoot <staged-package-or-checkout> [-ModelsRoot <external-root>]
```

`check` spawns nothing and writes nothing.  It verifies, from ANY current
directory (all paths derive from the script location / parameters):

- package layout: staged `manifest.json` (`s12-t06a-package/2`) + `backend/app`
  + `frontend/`, or the repo checkout (`app/main.py`, `pyproject.toml`);
- ports: backend/frontend must be free on 127.0.0.1 (`PORT_IN_USE`);
- toolchain: python/node/ffmpeg presence + versions (`TOOL_MISSING`);
- models: every entry of `models.json` exists under the models root and is
  non-empty (`MODEL_MISSING`).

Every action prints a final machine-readable line
`LAUNCHER_JSON={...}`.  Exit codes: `0` ok, `3` typed blocker/NOT_RUN,
`2` usage error.

### Missing-model error (exact shape)

```json
{"code":"MODEL_MISSING","level":"blocker",
 "detail":"wan_shot_v1:unet (diffusion_models/wan_animate_2_int8_convrot.safetensors) missing under <root>"}
```

Fix: point `-ModelsRoot` / `MF2D_MODELS_ROOT` at the root that holds the
declared files.  A missing model NEVER degrades into a silent fallback or
an auto-download — the check exits 3 and the action is NOT_RUN.

## 3. Launch / status / stop (hidden helper processes)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\mf_delivery_launcher.ps1 -Action start `
  -PackageRoot C:\stage\mf-demo `
  -RuntimeRoot $env:LOCALAPPDATA\MotionForge2D-demo-runtime

... -Action status ...
... -Action stop ...
```

- `start` re-runs `check` (must pass), then spawns backend
  (`python -m uvicorn app.main:app`, cwd = package/staged backend dir) and
  frontend (`node node_modules/next/dist/bin/next start`, cwd = frontend
  dir) as HIDDEN windows (`Start-Process -WindowStyle Hidden`), waits for
  `/health` and `/`, and writes `launcher_state.json`.
- `status` re-probes each recorded pid's identity (creation time +
  executable) and live HTTP health.
- `stop` stops ONLY the recorded pids after re-verifying their identity;
  a reused/persistent foreign pid is REFUSED (exit 3) and kept in the
  state file — never killed.

The staged package's own frozen lifecycle runner
(`python <stage>\scripts\s12_t06a_run.py setup|serve|diagnose|stop`) stays
available and unchanged; both paths bind the same ports and use the same
runtime-root conventions.

## 4. Outputs (runtime root — outside the package and the checkout)

```
<RuntimeRoot>/
  data/        SQLite DB (created on first boot; never bundled)
  artifacts/   managed artifacts
  output/      exported MP4s
  logs/        backend.log / backend.err.log / frontend.log / frontend.err.log
  launcher_state.json   pids + identity records of the last start
```

## 5. Clean Windows host / human acceptance

The staged package runs on the dev host (observed).  A clean Windows
target (isolated VM or second machine without dev runtimes) is NOT present
for this delivery: the clean-host/human row is **NOT_RUN** and is recorded
as such — never waived, never inferred from a clean venv.

## 6. Licenses, hashes, secrets

Third-party components and license status live in `THIRD_PARTY.md` at the
repo root (ComfyUI engine, mf-comfy dependency, model checkpoints).
Inventory/model records carry artifact hashes and license IDs only —
no keys, tokens or credentials are embedded anywhere in these files.
