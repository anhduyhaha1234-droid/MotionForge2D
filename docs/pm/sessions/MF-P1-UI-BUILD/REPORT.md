# MF-P1-UI-BUILD — real frontend build fix + product P1 UI states

**Status:** TASK_SUBMITTED (worker terminal state — never APPROVED/CLOSED)
**Owner session:** `20260923_154033_ea5ccd`
**Model:** EXACT `ocg/deepseek-v4.1-flash`, provider `custom`, thinking ON, fallback OFF
**Wave:** A (CPU) — no GPU, no engine, no live provider, no Comfy
**Tree:** `C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-p1-ui-build`
**Branch:** `codex/mf-tool-20260923-mf-p1-ui-build` · **Base:** `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`
**Evidence root:** `.../mf-core-tool-delivery-20260923/20260923T1535Z/NEW/P1UI/**`

---

## 1. Root cause (measured, not inferred)

`npx next build` on the pristine tree (HEAD `2594de0`) failed:

```
⨯ useSearchParams() should be wrapped in a suspense boundary at page "/apply".
  Read more: https://nextjs.org/docs/messages/missing-suspense-with-csr-bailout
Error occurred prerendering page "/apply".
Export encountered an error on /(app)/apply/page: /apply, exiting the build.
⨯ Next.js build worker exited with code: 1 and signal: null
EXIT=1
```

The reported page is `/apply` only because it is the first `(app)` route the
prerenderer reaches — the failing component is **`AppNav`**, which the SHARED
layout renders (`app/(app)/layout.tsx` → `AppShell` → `AppNav`). A boundary
inside a page cannot cover a component rendered by the layout, which is why
fixing pages alone would not have been enough.

Measurements behind that conclusion:

- `grep -rn useSearchParams frontend/src` → 6 files. The five route pages
  (`apply`, `export`, `object-gallery`, `import-analyze`, `projects/[id]/review`)
  ALL already wrap the hook in `<Suspense>`; **only `AppNav.tsx` called
  `useSearchParams()` with no boundary above it** (recorded per file in
  `raw/preimages.json` — field `has_suspense_boundary`).
- Installed docs read first (packet §0): `frontend/node_modules/next/dist/docs/
  01-app/03-api-reference/04-functions/use-search-params.md` — "@ Behavior /
  Prerendering": calling `useSearchParams` prerenders the client tree up to the
  closest `Suspense` boundary, and "During production builds, a static page that
  calls `useSearchParams` from a Client Component must be wrapped in a `Suspense`
  boundary, otherwise the build fails with the Missing Suspense boundary with
  useSearchParams error." Next.js **16.2.12**.

## 2. Fix shape per file (one file needed a change; five verified already correct)

| File | Pre-fix | Fix shape |
|---|---|---|
| `frontend/src/components/layout/AppNav.tsx` (51 L → 75 L) | `useSearchParams()` called directly in the component the SHARED layout renders ⇒ prerender abort | **Client split + Suspense boundary.** `AppNav` now renders `<Suspense fallback={<AppNavSidebar projectId={null} videoItemId={null} />}><AppNavWithQueryParams/></Suspense>`; the hook lives only in `AppNavWithQueryParams`, which forwards `project`/`video` to a new presentational `AppNavSidebar`. The fallback is the SAME sidebar markup with no deep-link params — the correct prerendered shell, since a static prerender has no query string. `usePathname()`/`useQuery()` stay outside the boundary and keep their server-rendered output. |
| `frontend/src/app/(app)/apply/page.tsx` | already correct: page-level `<Suspense>` around `ApplyRoute` | **unchanged (byte-identical)** |
| `frontend/src/app/(app)/object-gallery/page.tsx` | already correct | **unchanged** |
| `frontend/src/app/(app)/export/page.tsx` | already correct | **unchanged** |
| `frontend/src/app/(app)/import-analyze/page.tsx` | already correct | **unchanged** |
| `frontend/src/app/(app)/projects/[id]/review/page.tsx` | already correct | **unchanged** |

Preserved behaviour (nothing regressed) — `/export` deep links built by the nav
still append `?project=&video=` when both params are present, and fall back to a
bare `/export` otherwise; the active-route highlight, the GPU badge and the
`aria-label="Điều hướng chính"` landmark are byte-for-byte the same JSX, now
rendered by `AppNavSidebar`. `git diff --numstat` = `27 3` on that one file and
`0` on every other tracked file in the tree.

## 3. Gates (each one the real command output; logs under `raw/`)

| Gate | Command | Result |
|---|---|---|
| Production build (pre) | `npx next build` @ pristine HEAD | **FAIL** exit 1 — `raw/build_before.txt` |
| Production build (post) | `npx next build` @ fixed tree | **PASS** exit 0 — `✓ Generating static pages (12/12)`, all 12 routes emitted — `raw/build_after.txt` |
| Types | `npx tsc --noEmit` (whole project incl. the new tests) | **PASS** exit 0 — `raw/types_lint.txt` |
| Lint (patch scope, 6 files) | `npx eslint <6 files>` | **PASS** exit 0 |
| Lint (new tests) | `npx eslint src/__tests__/product_p1` | **PASS** exit 0 |
| Lint (whole src — disclosure) | `npx eslint src` | exit 1: **1 pre-existing error** in `src/components/export/ExportEvidence.tsx:48` + 9 warnings. That file is **untouched** (`git status --porcelain` lists only `AppNav.tsx`), so the error is base-line, not introduced here. |
| Affected tests + 3 states | `npx playwright test --config=src/__tests__/product_p1/playwright.p1-ui.config.ts --reporter=list --repeat-each=2` | **6/6 PASS**, exit 0 — `raw/affected_tests.txt` |
| Route sweep (prod server) | real HTTP against `next start` | **9/9 → 200**, including the previously fatal `/apply` — `raw/states.json` |

A flaky green is not proof: the suite passed on the first run and on a
`--repeat-each=2` re-run (6/6). Run 1 of the suite is kept verbatim as
`raw/affected_tests.run1_failed_assertion.txt` with the reason recorded in §5.

## 4. The three UI states (real stack, loopback only)

Stack: this tree's **production build** served by `npx next start -p 3111` +
the **canonical `app.api.app`** via uvicorn on `127.0.0.1:8888` against an
**isolated** root `%TEMP%/mf_p1ui_iso` (per-test DB, seeded by the repo's own
`frontend/e2e/s12-export-seed.py` — repo/domain code + real ffmpeg media).
No fake provider is shipped in `app/` or `frontend/src/`; the user DB/media are
never touched. `MOTIONFORGE_DATABASE_URL` is injected ONLY into those two
test servers and stays unset for ordinary app runtime.

| State | URL | Server truth (read back live) | UI assertions |
|---|---|---|---|
| **blocked** | `/export?project=<blocked>&video=<blocked>` | context `reasons=["S12_EXPORT_FULL_APPLY_MISSING"]`, `checkpoint=null`, `full_apply_run_id=null`; preflight POST → `eligible=false` with 7 refusal codes incl. `S12_EXPORT_SOURCE_MISSING` | `export-context-reasons` visible with the refusal code; `export-preflight` and `export-submit` DISABLED; no `ELIGIBLE` marker; AppNav hydrated; zero `useSearchParams` console errors |
| **success** | `/export?run=<completed>&project=&video=` | run status `completed`; result 200 `media_url=/s12-exports/<run>/media` | `export-evidence` visible + contains `COMPLETED`; `export-run-id` shows the run prefix; `export-progress` visible |
| **reopen** | `/export?run=<pending>&project=&video=` | same run id returned on re-fetch (`same_run_on_reopen=true`), status `pending` | run id survives `page.reload()`; survives `localStorage.clear()` + same URL (pointer-only storage); a run-less deep link restores the SAME persisted selection — never a fork, never an empty panel |

**Positive control** (non-vacuity): the ready project's preflight returns
`eligible=true` with `reason=["S12_EXPORT_OK"]` — so the blocked refusal above is
a real refusal, not a dead endpoint.

## 5. Deviations / disclosures

1. **Test-assertion iteration (not product code).** Suite run 1 had 1 failing
   assertion: I asserted a run-less `/export` deep link shows the server's
   `current_run`. The product instead restores the persisted last selection from
   its localStorage pointer — which is its documented behaviour ("persist last
   run_id ... so reload keeps truth"). I corrected the assertion to the observed
   behaviour; the product source was not touched to make a test pass.
   Run 2 then exposed a second, genuinely racy assertion of mine
   (`export-evidence` count 0 for the blocked project, which legitimately renders
   the seeded `current_run`); replaced by the deterministic fail-closed markers.
   Both runs' logs are kept (`raw/affected_tests.run1_failed_assertion.txt`).
   Final: **6/6 PASS, twice.**
2. **`npx eslint src` is red at base.** 1 error in `ExportEvidence.tsx`
   (`react-hooks/set-state-in-effect`) — a file outside this task's scope and
   untouched by it. Not "fixed", not hidden.
3. **Only 1 of the 6 named files needed a change.** The other five already
   carried correct boundaries; they are listed with their preimage hashes in
   `raw/preimages.json` and were left byte-identical rather than churned.
4. `frontend/.next/` build output and `__pycache__` are git-ignored
   (`git check-ignore` verified) — not strays.

## 6. Artifacts

`raw/build_before.txt`, `raw/build_after.txt`, `raw/types_lint.txt`,
`raw/affected_tests.txt` (+ the run-1 log), `raw/states.json`,
`raw/guard_after.json`, `raw/preimages.json`, and the exact generating scripts
`raw/_preimage_dump.py`, `raw/_fix_appnav.py`, `raw/_states_dump.py`,
`raw/_guard.py`. Session docs: `docs/pm/sessions/MF-P1-UI-BUILD/`.
