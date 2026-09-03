import { defineConfig, devices } from "@playwright/test";

/**
 * S11-T05B Readiness UI — E2E + a11y (own ports/roots, REAL backend).
 *
 * Environment (started separately, ports RIÊNG — không đụng 8888/8201/8212/8025/8026/8413/3013):
 *   - Backend  : uvicorn app.main:app --port 8414
 *                MOTIONFORGE_QA_MODE=1 MOTIONFORGE_ROOT=%TEMP%/s11t05b_root
 *                MOTIONFORGE_EXTRACTION_QA_MODE=1 MOTIONFORGE_EXTRACTION_PROVIDER=deterministic
 *                MOTIONFORGE_CORS_ORIGINS=http://localhost:3014,http://127.0.0.1:3014
 *                (BẮT BUỘC — frontend :3014 fetch trực tiếp backend :8414; thiếu
 *                origin thì browser bị CORS chặn và page rơi vào error phase)
 *   - Frontend : npx next dev -p 3014 (NEXT_PUBLIC_API_URL=http://localhost:8414)
 *   - Seed     : e2e seed script (ngoài repo, %TEMP%/s11t05b_root) — project/video/run/QC-item
 *                rows qua repository/raw SQL (Decision A: không có POST công khai cho QC items;
 *                check-run completion evidence qua JobRepository — đúng path T03F orchestrator).
 *
 * Tests (s11-t05-readiness.spec.ts):
 *   - reflect payload T05A cho ready/blocked/not_run (Playwright từng case)
 *   - blocked → fix qua correction → auto-ready (WS-07 recheck evidence), KHÔNG nút tay
 *   - long-job "Đang xử lý lại…" không chặn điều hướng
 *   - error "Chưa tính được readiness — Thử lại"
 *   - zero accepted-exception (Decision G DOM scan) + helper text VI dưới mọi button
 *
 * outputDir + evidence RIÊNG của task — KHÔNG bao giờ ghi frontend/test-results
 * (.last-run.json canonical).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s11-t05-readiness\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/AppData/Local/Temp/s11t05b_pw/test-results",
  use: {
    baseURL: "http://localhost:3014",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});