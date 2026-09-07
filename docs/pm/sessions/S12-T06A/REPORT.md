# S12-T06A REPORT — Windows packaging (portable beta / installer harness)

Status: **TASK_SUBMITTED** | Date: 2026-09-07 | Worker: S12-T06A owner
Branch: `codex/s12/s12-t06a-0907a` (worktree `s12-s12-t06a-0907a`)
Baseline: `f2cdf0e` | No merge/fetch/push.

## Acceptance evidence (real numbers)

- Frontend `npm run build` (fresh, no node_modules): **BUILD_EXIT 0**,
  route list includes `/export`; `.next` BUILD_ID `SMMKnaiyQ5jEj09fkhU72`.
- `manifest.json`: **17 backend pins** (exact `==`), **17 frontend
  deps** (range + locked), 45 static files, source commit `f2cdf0e`,
  toolchain probes (ffmpeg 8.1.2-gyan, python 3.11.9, node v26.4.0).
- Preflight: **READY** (5/5 probes).
- `serve` (ports 8423/3123): **SERVE_EXIT 0** — backend `/health` 200,
  frontend `/` 200, `/export` 200, `diagnose` **READY 6/6 checks**.
- `stop`: both processes down, verified. `uninstall`: user data preserved
  by default; unconfirmed removal refused (exit 3).
- Negatives: ffmpeg-missing -> `BLOCKED_FFMPEG_MISSING` exit 3;
  stale manifest -> `BLOCKED_MANIFEST_STALE` exit 3; restore -> READY.
- `ruff check --select F`: **All checks passed**. `git diff --check`: clean.
  Porcelain: allowlist only. User-path hardcode scan: 0 hits.

## Contract compliance (prompt items 5–6)

- Write allowlist respected: only `packaging/windows/` (new), `scripts/s12/`
  (new), `docs/packaging/s12-windows.md` (new) + session LOG/REPORT per item 6.
- Forbidden respected: no hardcoded user path, no system install / PATH /
  firewall / registry writes, no elevation, no model download, no cert, no
  user-data bundling. Missing prerequisites are explicit blockers (exit 3 +
  NOT_RUN), never waived — demonstrated live twice.
- Docs match artifact: build_id, pin counts, ports, and commands in
  `s12-windows.md` are the actually-run values.
- Harness ran real local build artifact + hash (manifest sha256 gate in
  preflight), graceful shutdown ordered, uninstall keeps data by default.

## Known limitations

See LOG.md L1–L3: `stop` falls back to `taskkill /F /T` (logged, ordered,
verified); first boot runs full Alembic head (~40s, covered by 90s wait);
serve verified on CPU path, GPU optional-by-design.

## Files (new)

`packaging/windows/` (6: 4x `.cmd`, `README-BETA.txt`, `manifest.json`),
`scripts/s12/` (3x `.py`), `docs/packaging/s12-windows.md`,
`docs/pm/sessions/S12-T06A/{LOG,REPORT}.md`.
