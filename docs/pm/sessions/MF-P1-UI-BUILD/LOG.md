# Execution Log — MF-P1-UI-BUILD

Owner session `20260923_154033_ea5ccd` (resumed after an upstream 502 flap; the
Manager measured the prior attempt at `porcelain=0`, HEAD `2594de0`,
`NEW/P1UI/` empty — nothing to reconcile). Terminal state: **TASK_SUBMITTED**.

## Re-orientation

- `pwd` = `/c/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-p1-ui-build` — PASS
- `git rev-parse HEAD` = `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64` — matches base — PASS
- `git status --porcelain | wc -l` = `0` (pristine) — PASS
- Packet read in full: `manager/packets/MF-P1-UI-BUILD.md` (4,224 B).
- Next.js docs read BEFORE writing code (packet §0):
  `frontend/node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-search-params.md`
  (installed version **16.2.12**; `AGENTS.md` explicitly warns this is not the
  Next.js the training data describes).
- Preimages of all six patch-scope files recorded to `NEW/P1UI/raw/preimages.json`
  (bytes, LF line count, CRLF line count, sha256, `has_suspense_boundary`).

## Steps and real outputs

1. **Reproduce (pre-fix).** `npx next build` on the pristine tree →
   `⨯ useSearchParams() should be wrapped in a suspense boundary at page "/apply"`
   → `Error occurred prerendering page "/apply"` → `EXIT=1`.
   Kept whole in `raw/build_before.txt`.
2. **Localise.** `grep -rn useSearchParams frontend/src` → 6 files; five pages
   already wrapped, `AppNav.tsx` (rendered by the SHARED `(app)/layout.tsx` via
   `AppShell`) was not. Boundary scope proved the decisive fact: a page-level
   `<Suspense>` cannot cover a layout-rendered component.
3. **Fix (byte-exact, CRLF preserved).** `raw/_fix_appnav.py` reads `"rb"`,
   asserts the preimage sha256 prefix, asserts the old block appears verbatim,
   rewrites line lists joined with `\r\n`, writes `"wb"`.
   PRE `F22F4255C4AE0F83…` 3,497 B / 51 CRLF →
   POST `E6BB3E17A2D97CA4…` 4,608 B / 75 CRLF.
   `git diff --numstat` = `27 3` (one file); every other scope file `0`.
   This is the CRLF pitfall from `terminal-engineering-discipline` #31 — the
   `patch` tool is deliberately NOT used on these files.
4. **Rebuild (post-fix).** `npx next build` → `✓ Generating static pages (12/12)`,
   `EXIT=0`, 12 routes including `/apply`, `/export`, `/object-gallery`,
   `/import-analyze` — `raw/build_after.txt`. Pre/post pair kept.
5. **Static gates.** `npx tsc --noEmit` exit 0; `npx eslint <6 files>` exit 0;
   `npx eslint src/__tests__/product_p1` exit 0; `npx eslint src` exit 1 with a
   single pre-existing error in the untouched `ExportEvidence.tsx` (disclosed).
   `raw/types_lint.txt`.
6. **Test stack (loopback only, per packet §3 network rule).**
   - isolated root `%TEMP%/mf_p1ui_iso`; the canonical `app.api.app` uvicorn
     `127.0.0.1:8888` with `MOTIONFORGE_ROOT`/`MOTIONFORGE_DATABASE_URL`/
     `MOTIONFORGE_CORS_ORIGINS` injected for the test servers only;
   - seed via the repo's own `frontend/e2e/s12-export-seed.py export`
     (real repository/domain code + real ffmpeg media), exit 0, real ids in
     `%TEMP%/mf_p1ui_iso/seed.json`;
   - this tree's PRODUCTION build served by `npx next start -p 3111`.
   - Route sweep: 9/9 core routes → 200 (the previously fatal `/apply` = 200).
7. **Affected tests + 3 states.** New spec
   `frontend/src/__tests__/product_p1/p1_states.spec.ts` + tests-only config
   `playwright.p1-ui.config.ts` (both inside the packet's allowed NEW path), no
   change to any canonical playwright config.
   - run 1: 2 passed, 1 failed — MY assertion was wrong (see REPORT §5.1). Log
     preserved as `raw/affected_tests.run1_failed_assertion.txt`.
   - run 2: blocked-test assertion racy (also mine) → replaced with
     deterministic fail-closed markers.
   - final: `--repeat-each=2` → **6/6 PASS, exit 0** → `raw/affected_tests.txt`.
8. **Server truth.** `raw/_states_dump.py` re-reads every state's payload over
   live HTTP into `raw/states.json`, including the non-vacuity positive control
   (ready project preflight `eligible=true`, `S12_EXPORT_OK`).
9. **Commit (local only).** Scoped `git add`, never `-A`; no push/merge/reset/
   rebase/stash/restore/clean. Guard result in `raw/guard_after.json`.

## Writeset

- modified: `frontend/src/components/layout/AppNav.tsx`
- new: `frontend/src/__tests__/product_p1/{p1_states.spec.ts,playwright.p1-ui.config.ts,README.md}`
- new: `docs/pm/sessions/MF-P1-UI-BUILD/{REPORT.md,LOG.md}`
- evidence (outside the tree): `NEW/P1UI/**`

No dependency and no lockfile change: `frontend/package.json` and
`frontend/package-lock.json` are byte-identical to HEAD (sha256 compared against
the committed blobs in `raw/guard_after.json`).

## Not done / not claimed

- No APPROVED/CLOSED, no vision/quality verdict, no QA sign-off.
- Nothing pushed; PRODUCT tree, `app/**`, the other lanes' trees and the user
  DB/media were never written.
