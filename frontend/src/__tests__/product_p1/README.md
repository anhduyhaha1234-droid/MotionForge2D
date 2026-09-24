# product_p1 — MF-P1-UI-BUILD UI-state tests (tests-only)

Three REAL-stack UI states for the product P1 pages: **blocked / success /
reopen**. Nothing here is a mock: the frontend under test is this tree's
**production build** (`next start`), the API is the repo's **canonical
`app.api.app`**, and the data comes from the repo's own seed script.

## What these tests exist for

`npx next build` on the base commit fails with
`useSearchParams() should be wrapped in a suspense boundary at page "/apply"`
because `frontend/src/components/layout/AppNav.tsx` called `useSearchParams()`
while being rendered by the SHARED `(app)/layout.tsx`. `AppNav` now owns a
`Suspense` boundary; this spec is the executable proof that the pages actually
render in the browser afterwards (and that the bailout never reappears in the
console).

## Run it

Prereqs: an isolated root with a seeded DB (the repo's own seed), the canonical
backend, and the production build already made.

```bash
# 1. isolated root + DB + seed (real repo/domain code, real ffmpeg media)
export ISO="C:/Users/Admin/AppData/Local/Temp/mf_p1ui_iso"      # any temp dir
# boot the canonical app once so migrations create $ISO/data/motionforge.db, then:
MF_BACKEND_ROOT="$PWD" MF_DB_PATH="$ISO/data/motionforge.db" \
  S12T05_QA_ROOT="$ISO" python frontend/e2e/s12-export-seed.py export > "$ISO/seed.json"

# 2. production build of THIS tree
cd frontend && npx next build

# 3. run the states (the config boots/reuses both loopback servers)
npx playwright test --config=src/__tests__/product_p1/playwright.p1-ui.config.ts --reporter=list
```

The config's `webServer` entries start the backend (`127.0.0.1:8888`) and
`next start` (`127.0.0.1:3111`) with `reuseExistingServer: true`, so it works
either way. Loopback only — no Comfy / provider / cloud / model traffic, and no
fake provider is shipped in `app/` or `frontend/src/`.

Env overrides: `P1UI_ISO_ROOT`, `P1UI_FE_BASE`, `P1UI_API_BASE`.
