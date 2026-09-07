import { defineConfig, devices } from "@playwright/test";

/**
 * S12-T05 Export UI — E2E real-API (own ports/roots, REAL backend).
 *
 * Environment (ports RIÊNG — không đụng 8888/8201/8414/3014):
 *   - Backend  : uvicorn harness (production app + test-only s12_export
 *                router mount) --port 8415
 *                MOTIONFORGE_ROOT=%TEMP%/s12t05_root
 *                MOTIONFORGE_CORS_ORIGINS=http://localhost:3015,http://127.0.0.1:3015
 *                (BẮT BUỘC — frontend :3015 fetch trực tiếp backend :8415;
 *                thiếu origin thì browser bị CORS chặn và page rơi vào
 *                error phase)
 *   - Frontend : npx next dev --webpack -p 3015
 *                (NEXT_PUBLIC_API_URL=http://localhost:8415)
 *   - Seed     : s12t05_seed_export.py (ngoài repo, %TEMP%/s12t05_root) —
 *                workspace/project/videos/artifact/checkpoint/manifest qua
 *                raw SQL + repository, completed FULL RUN_QC_CHECKS run,
 *                pending + completed export runs qua submit_export_job/repo.
 *
 * Tests (s12-export.spec.ts): nav → empty → preflight blocked/eligible →
 * submit → poll → cancel → retry → evidence → helper VN → zero
 * accepted-exception. KHÔNG route mock nào.
 *
 * outputDir + evidence RIÊNG của task — KHÔNG bao giờ ghi
 * frontend/test-results (.last-run.json canonical).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s12-export\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/AppData/Local/Temp/s12t05_pw/test-results",
  use: {
    baseURL: "http://localhost:3015",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390x844",
      use: { ...devices["Pixel 5"], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      command: "python frontend/e2e/s12-export-boot.py",
      cwd: "..",
      env: {
        S12T05_QA_ROOT: "C:/Users/Admin/AppData/Local/Temp/s12t05_root",
        MF_BACKEND_ROOT: "C:/Users/Admin/MotionForge2D-worktrees/s12-s12-t05-0907a",
      },
      url: "http://localhost:8415/docs",
      timeout: 300_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npx next dev --webpack -p 3015",
      url: "http://localhost:3015/",
      timeout: 300_000,
      reuseExistingServer: false,
      env: {
        NEXT_PUBLIC_API_URL: "http://localhost:8415",
      },
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
