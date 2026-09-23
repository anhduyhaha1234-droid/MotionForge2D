import { defineConfig, devices } from "@playwright/test";
import path from "path";

/**
 * MF-P1-UI-BUILD — tests-only Playwright config for the product P1 UI states.
 *
 * Loopback only (packet §2 network rule): the REAL backend (app.api.app, the
 * canonical production-mounted app) on 127.0.0.1:8888 against an ISOLATED temp
 * DB root, and the REAL production build (`next start`) of THIS tree on
 * 127.0.0.1:3111. No Comfy / provider / cloud / model traffic. No fake provider
 * is shipped in app/ or frontend/src/ — the servers below are the repo's own
 * app and this tree's own build.
 *
 * `reuseExistingServer` lets a reviewer either run the stack by hand or let
 * Playwright boot it; nothing in the repo's canonical configs is modified
 * (this file lives in the task's own allowed NEW path).
 */

const ISO = process.env.P1UI_ISO_ROOT ?? "C:/Users/Admin/AppData/Local/Temp/mf_p1ui_iso";
const REPO_ROOT = path.resolve(__dirname, "../../../..");
const FRONTEND_DIR = path.resolve(__dirname, "../../..");

export default defineConfig({
  testDir: __dirname,
  testMatch: /p1_states\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 120_000,
  outputDir: `${ISO}/pw/test-results`,
  use: {
    baseURL: "http://127.0.0.1:3111",
    viewport: { width: 1280, height: 800 },
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [{ name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8888 --log-level warning",
      cwd: REPO_ROOT,
      url: "http://127.0.0.1:8888/docs",
      reuseExistingServer: true,
      timeout: 180_000,
      env: {
        MOTIONFORGE_ROOT: ISO,
        MOTIONFORGE_DATABASE_URL: `sqlite:///${ISO}/data/motionforge.db`,
        MOTIONFORGE_CORS_ORIGINS: "http://localhost:3111,http://127.0.0.1:3111",
      },
    },
    {
      command: "npx next start -p 3111 -H 127.0.0.1",
      cwd: FRONTEND_DIR,
      url: "http://127.0.0.1:3111/",
      reuseExistingServer: true,
      timeout: 180_000,
    },
  ],
});
